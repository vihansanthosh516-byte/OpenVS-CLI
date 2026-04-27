"""
Worker Pool — parallel agent execution workers.

Each worker runs one job at a time through the v11 orchestrator.
The pool manages worker lifecycle and dispatches jobs from the queue.
"""

import threading
import time
from typing import Optional

from core.jobs import Job, JobState
from core.event_bus import bus


class Worker:
    """A single agent worker that executes jobs.

    Each worker has its own orchestrator instance so jobs
    run in complete isolation from each other.
    """

    def __init__(self, worker_id: str):
        self.id = worker_id
        self.busy = False
        self.current_job: Optional[Job] = None
        self.jobs_completed = 0
        self.jobs_failed = 0
        self._lock = threading.Lock()

    def run_job(self, job: Job) -> dict:
        """Execute a job through the orchestrator."""
        with self._lock:
            self.busy = True
            self.current_job = job

        job.transition(JobState.RUNNING)
        job.started_at = time.time()
        job.worker_id = self.id

        bus.emit("job.started", {"job_id": job.id, "worker_id": self.id})

        try:
            from core.orchestrator import Orchestrator
            orchestrator = Orchestrator()
            result = orchestrator.run(job.task)

            job.result = result
            job.finished_at = time.time()

            if result.get("status") == "completed":
                job.transition(JobState.COMPLETED)
                self.jobs_completed += 1
                bus.emit("job.completed", {
                    "job_id": job.id,
                    "worker_id": self.id,
                    "duration_ms": job.duration_ms,
                })
            else:
                self._handle_failure(job, result.get("error", "unknown"))

        except Exception as e:
            job.finished_at = time.time()
            self._handle_failure(job, str(e))

        finally:
            with self._lock:
                self.busy = False
                self.current_job = None

        return job.to_dict()

    def _handle_failure(self, job: Job, error: str):
        """Handle a job failure — retry or mark as failed."""
        job.retries += 1
        if job.retries <= job.max_retries:
            job.transition(JobState.WAITING_RETRY)
            bus.emit("job.retry", {
                "job_id": job.id,
                "retries": job.retries,
                "max_retries": job.max_retries,
                "error": error[:200],
            })
        else:
            job.transition(JobState.FAILED)
            self.jobs_failed += 1
            bus.emit("job.failed", {
                "job_id": job.id,
                "worker_id": self.id,
                "retries": job.retries,
                "error": error[:200],
            })

    def to_dict(self) -> dict:
        """Worker status as dict."""
        return {
            "id": self.id,
            "busy": self.busy,
            "current_job": self.current_job.id if self.current_job else None,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
        }


class WorkerPool:
    """Pool of agent workers that drains the job queue.

    The scheduler calls pool.maybe_dispatch() to assign
    queued jobs to idle workers. Workers run in separate threads.
    """

    def __init__(self, size: int = 4):
        self.size = size
        self.workers: list[Worker] = []
        self._threads: dict[str, threading.Thread] = {}
        self._running = False

        # Create workers
        for i in range(size):
            self.workers.append(Worker(f"worker_{i+1}"))

    def start(self):
        """Start the worker pool loop."""
        self._running = True
        bus.emit("pool.started", {"size": self.size})

    def stop(self):
        """Stop the worker pool."""
        self._running = False
        bus.emit("pool.stopped", {})

    def maybe_dispatch(self) -> int:
        """Dispatch queued jobs to idle workers.

        Returns the number of jobs dispatched this tick.
        """
        if not self._running:
            return 0

        dispatched = 0

        for worker in self.workers:
            if worker.busy:
                continue

            # Get next job from queue
            from core.queue_manager import queue
            job = queue.next_job()
            if job is None:
                break

            # Dispatch job to worker in a thread
            t = threading.Thread(
                target=worker.run_job,
                args=(job,),
                daemon=True,
                name=f"{worker.id}-{job.id}",
            )
            self._threads[job.id] = t
            t.start()
            dispatched += 1

        # Clean up finished threads
        finished = [jid for jid, t in self._threads.items() if not t.is_alive()]
        for jid in finished:
            del self._threads[jid]

        return dispatched

    def dispatch_loop(self, interval: float = 1.0):
        """Blocking loop that continuously dispatches jobs.

        Call from a dedicated thread or as the main loop.
        """
        self.start()
        try:
            while self._running:
                self.maybe_dispatch()
                # Also check for retry-ready jobs
                self._check_retries()
                # Check recurring jobs
                self._check_recurring()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stop()

    def _check_retries(self):
        """Move WAITING_RETRY jobs back to QUEUED after a delay."""
        from core.queue_manager import queue
        for job in queue._jobs.values():
            if job.status == JobState.WAITING_RETRY:
                # Simple retry: wait 5s * retry_count
                delay = 5 * job.retries
                if job.finished_at and (time.time() - job.finished_at) > delay:
                    try:
                        job.transition(JobState.QUEUED)
                        queue._counter += 1
                        heapq.heappush(queue._queue, (job.priority, job.created_at, queue._counter, job))
                        bus.emit("job.retry_queued", {"job_id": job.id})
                    except (ValueError, Exception):
                        pass

    def _check_recurring(self):
        """Re-queue recurring jobs that have completed."""
        from core.queue_manager import queue
        import heapq
        for job in list(queue._jobs.values()):
            if job.recurring and job.status == JobState.COMPLETED:
                # Create a new job with the same task
                new_job = Job(
                    task=job.task,
                    priority=job.priority,
                    recurring=job.recurring,
                    max_retries=job.max_retries,
                    metadata={"parent_job": job.id, "recurring": True},
                )
                queue.submit(new_job)
                # Mark the original as non-recurring so we don't re-queue it again
                job.recurring = None

    def idle_workers(self) -> int:
        """Count of workers not currently running a job."""
        return sum(1 for w in self.workers if not w.busy)

    def active_jobs(self) -> list[str]:
        """List of job IDs currently being executed."""
        return [w.current_job.id for w in self.workers if w.current_job]

    def stats(self) -> dict:
        """Pool statistics."""
        return {
            "size": self.size,
            "running": self._running,
            "idle_workers": self.idle_workers(),
            "active_jobs": len(self.active_jobs()),
            "total_completed": sum(w.jobs_completed for w in self.workers),
            "total_failed": sum(w.jobs_failed for w in self.workers),
            "workers": [w.to_dict() for w in self.workers],
        }

    def to_dict(self) -> dict:
        return self.stats()