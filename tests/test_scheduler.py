"""
Regression tests for v12 scheduler layer.

Tests:
  - Job model (state transitions, priority, readiness)
  - Queue Manager (submission, ordering, cancellation, persistence)
  - Worker Pool (dispatch, stats)
  - Scheduler (submit, schedule, recurring, stats)

Run:  python -m pytest tests/ -v
"""

import os
import sys
import time
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# JOB MODEL TESTS
# ============================================================

class TestJob:
    """Test the Job state machine and properties."""

    def test_job_creation(self):
        from core.jobs import Job, JobState, JobPriority
        job = Job(task="test task")
        assert job.status == JobState.QUEUED
        assert job.priority == JobPriority.NORMAL
        assert job.max_retries == 2

    def test_job_priority_from_string(self):
        from core.jobs import JobPriority
        assert JobPriority.from_string("urgent") == 0
        assert JobPriority.from_string("high") == 1
        assert JobPriority.from_string("normal") == 2
        assert JobPriority.from_string("background") == 3
        assert JobPriority.from_string("unknown") == 2  # default

    def test_job_happy_path(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        job.transition(JobState.RUNNING)
        job.transition(JobState.COMPLETED)
        assert job.is_terminal

    def test_job_failure_path(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        job.transition(JobState.RUNNING)
        job.transition(JobState.FAILED)
        assert job.is_terminal

    def test_job_retry_path(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        job.transition(JobState.RUNNING)
        job.transition(JobState.WAITING_RETRY)
        job.transition(JobState.RUNNING)
        job.transition(JobState.COMPLETED)
        assert job.is_terminal

    def test_job_illegal_transition(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        try:
            job.transition(JobState.COMPLETED)  # can't go queued -> completed
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_job_cancel_from_queued(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        job.transition(JobState.CANCELLED)
        assert job.status == JobState.CANCELLED
        assert job.is_terminal

    def test_job_cancel_from_running(self):
        from core.jobs import Job, JobState
        job = Job(task="fix bug")
        job.transition(JobState.RUNNING)
        job.transition(JobState.CANCELLED)
        assert job.is_terminal

    def test_job_is_ready_immediate(self):
        from core.jobs import Job
        job = Job(task="now")
        assert job.is_ready

    def test_job_is_ready_deferred(self):
        from core.jobs import Job
        job = Job(task="later", schedule_at=time.time() + 3600)
        assert not job.is_ready

    def test_job_is_ready_deferred_past(self):
        from core.jobs import Job
        job = Job(task="past", schedule_at=time.time() - 1)
        assert job.is_ready

    def test_job_duration(self):
        from core.jobs import Job
        job = Job(task="timed")
        job.started_at = time.time()
        job.finished_at = job.started_at + 1.5
        assert job.duration_ms is not None
        assert 1400 < job.duration_ms < 1600

    def test_job_to_dict(self):
        from core.jobs import Job
        job = Job(task="serialize")
        d = job.to_dict()
        assert "id" in d
        assert d["task"] == "serialize"
        assert d["status"] == "queued"

    def test_job_lt_priority_ordering(self):
        from core.jobs import Job, JobPriority
        urgent = Job(task="urgent", priority=JobPriority.URGENT)
        normal = Job(task="normal", priority=JobPriority.NORMAL)
        assert urgent < normal


# ============================================================
# QUEUE MANAGER TESTS
# ============================================================

class TestQueueManager:
    """Test the priority queue."""

    def setup_method(self):
        # Use a temp file for queue persistence
        self.tmpdir = tempfile.mkdtemp(prefix="q_test_")
        from core.queue_manager import QueueManager, QUEUE_PATH
        # Monkey-patch the queue path
        self._orig_path = QUEUE_PATH
        import core.queue_manager as qm
        qm.QUEUE_PATH = os.path.join(self.tmpdir, "test_queue.json")
        self.queue = QueueManager()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        import core.queue_manager as qm
        qm.QUEUE_PATH = self._orig_path

    def test_submit_job(self):
        from core.jobs import Job
        job = Job(task="test submit")
        job_id = self.queue.submit(job)
        assert job_id is not None
        assert self.queue.pending_count() == 1

    def test_next_job_fifo(self):
        from core.jobs import Job
        j1 = Job(task="first")
        j2 = Job(task="second")
        self.queue.submit(j1)
        self.queue.submit(j2)
        next_job = self.queue.next_job()
        assert next_job.task == "first"

    def test_priority_ordering(self):
        from core.jobs import Job, JobPriority
        normal = Job(task="normal", priority=JobPriority.NORMAL)
        urgent = Job(task="urgent", priority=JobPriority.URGENT)
        background = Job(task="bg", priority=JobPriority.BACKGROUND)
        self.queue.submit(normal)
        self.queue.submit(urgent)
        self.queue.submit(background)
        next_job = self.queue.next_job()
        assert next_job.task == "urgent"

    def test_cancel_job(self):
        from core.jobs import Job
        job = Job(task="cancel me")
        job_id = self.queue.submit(job)
        result = self.queue.cancel_job(job_id)
        assert result["status"] == "cancelled"

    def test_requeue_failed(self):
        from core.jobs import Job, JobState
        job = Job(task="retry me")
        job_id = self.queue.submit(job)
        # Manually fail it
        job.transition(JobState.RUNNING)
        job.transition(JobState.FAILED)
        result = self.queue.requeue_failed(job_id)
        assert result["status"] == "requeued"

    def test_stats(self):
        from core.jobs import Job
        self.queue.submit(Job(task="a"))
        self.queue.submit(Job(task="b"))
        stats = self.queue.stats()
        assert stats["total_jobs"] == 2

    def test_persistence(self):
        from core.jobs import Job
        from core.queue_manager import QueueManager
        self.queue.submit(Job(task="persistent"))
        # Create a new queue manager pointing to same file
        q2 = QueueManager()
        assert q2.stats()["total_jobs"] == 1


# ============================================================
# WORKER POOL TESTS
# ============================================================

class TestWorkerPool:
    """Test the worker pool."""

    def test_pool_creation(self):
        from core.workers import WorkerPool
        pool = WorkerPool(size=2)
        assert pool.size == 2
        assert pool.idle_workers() == 2

    def test_worker_stats(self):
        from core.workers import WorkerPool
        pool = WorkerPool(size=4)
        stats = pool.stats()
        assert stats["size"] == 4
        assert stats["idle_workers"] == 4
        assert stats["active_jobs"] == 0

    def test_pool_no_jobs_to_dispatch(self):
        from core.workers import WorkerPool
        pool = WorkerPool(size=2)
        dispatched = pool.maybe_dispatch()
        assert dispatched == 0


# ============================================================
# SCHEDULER TESTS
# ============================================================

class TestScheduler:
    """Test the scheduler."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sched_test_")
        import core.queue_manager as qm
        from pathlib import Path
        self._orig_path = qm.QUEUE_PATH
        qm.QUEUE_PATH = os.path.join(self.tmpdir, "test_queue.json")
        # Reset the global queue
        from core.queue_manager import QueueManager
        qm.queue = QueueManager()
        from core.scheduler import Scheduler
        self.scheduler = Scheduler(pool_size=2)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        import core.queue_manager as qm
        qm.QUEUE_PATH = self._orig_path

    def test_submit_job(self):
        job_id = self.scheduler.submit("test task")
        assert job_id is not None
        stats = self.scheduler.stats()
        assert stats["queue"]["total_jobs"] >= 1

    def test_schedule_deferred(self):
        job_id = self.scheduler.schedule("deferred task", run_at=time.time() + 3600)
        assert job_id is not None

    def test_recurring_job(self):
        job_id = self.scheduler.recurring("check tests", interval="5m")
        assert job_id is not None

    def test_cancel_job(self):
        job_id = self.scheduler.submit("cancel me")
        result = self.scheduler.cancel_job(job_id)
        assert result["status"] == "cancelled"

    def test_scheduler_stats(self):
        self.scheduler.submit("task 1")
        stats = self.scheduler.stats()
        assert "pool" in stats
        assert "queue" in stats

    def test_list_jobs(self):
        self.scheduler.submit("task A")
        self.scheduler.submit("task B")
        jobs = self.scheduler.list_jobs()
        assert len(jobs) >= 2

    def test_event_trigger_registration(self):
        trigger_id = self.scheduler.on_event("test.failure", "fix the test")
        assert trigger_id is not None
        stats = self.scheduler.stats()
        assert "test.failure" in stats["event_triggers"]


if __name__ == "__main__":
    import traceback
    test_classes = [TestJob, TestQueueManager, TestWorkerPool, TestScheduler]

    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            try:
                if hasattr(instance, "setup_method"):
                    instance.setup_method()
                getattr(instance, method_name)()
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method()
                print(f"  PASS  {cls.__name__}.{method_name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {cls.__name__}.{method_name}: {e}")
                failed += 1

    print(f"\n{'='*50}")
    print(f"  Scheduler tests: {passed} passed, {failed} failed")
    print(f"{'='*50}")