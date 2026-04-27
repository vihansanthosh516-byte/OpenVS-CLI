"""
Queue Manager — priority queue for jobs.

Manages job submission, ordering, and retrieval.
Persists queue state to disk so jobs survive restarts.
"""

import json
import heapq
import time
from pathlib import Path
from typing import Optional

from core.jobs import Job, JobPriority, JobState
from core.event_bus import bus

QUEUE_PATH = Path(__file__).resolve().parent.parent / "memory_store" / "job_queue.json"


class QueueManager:
    """Priority queue for scheduling jobs.

    Lower priority number = higher urgency:
      0=urgent, 1=high, 2=normal, 3=background

    Jobs are ordered by (priority, created_at) so urgent jobs
    always run first, and within a priority level, FIFO applies.
    """

    def __init__(self):
        self._queue: list[tuple] = []  # (priority, created_at, job)
        self._jobs: dict[str, Job] = {}  # id -> Job
        self._counter = 0
        self._load()

    def submit(self, job: Job) -> str:
        """Add a job to the queue. Returns the job ID."""
        self._counter += 1
        # Use counter as tiebreaker for stable FIFO ordering
        heapq.heappush(self._queue, (job.priority, job.created_at, self._counter, job))
        self._jobs[job.id] = job

        bus.emit("job.queued", {"job_id": job.id, "task": job.task[:100], "priority": job.priority})
        self._save()
        return job.id

    def next_job(self) -> Optional[Job]:
        """Get the next ready job from the queue.

        Skips jobs that aren't ready yet (deferred/scheduled).
        Returns None if no jobs are available.
        """
        skipped = []
        result = None

        while self._queue:
            entry = heapq.heappop(self._queue)
            _, _, _, job = entry

            if job.is_ready:
                result = job
                break
            else:
                # Not ready yet — put it back later
                skipped.append(entry)

        # Re-queue skipped entries
        for entry in skipped:
            heapq.heappush(self._queue, entry)

        return result

    def peek(self) -> Optional[Job]:
        """Look at the next job without removing it."""
        # Temporarily pop and re-push
        job = self.next_job()
        if job is not None:
            self._requeue(job)
        return job

    def _requeue(self, job: Job):
        """Put a job back at the front of the queue."""
        self._counter += 1
        heapq.heappush(self._queue, (job.priority, job.created_at, self._counter, job))

    def get_job(self, job_id: str) -> Optional[Job]:
        """Look up a job by ID."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued job."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}
        if job.is_terminal:
            return {"error": f"Job {job_id} is already {job.status.value}"}
        try:
            job.transition(JobState.CANCELLED)
            bus.emit("job.cancelled", {"job_id": job_id})
            self._save()
            return {"status": "cancelled", "job_id": job_id}
        except ValueError as e:
            return {"error": str(e)}

    def requeue_failed(self, job_id: str) -> dict:
        """Re-queue a failed or cancelled job."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}
        try:
            job.transition(JobState.QUEUED)
            self._counter += 1
            heapq.heappush(self._queue, (job.priority, job.created_at, self._counter, job))
            bus.emit("job.requeued", {"job_id": job_id})
            self._save()
            return {"status": "requeued", "job_id": job_id}
        except ValueError as e:
            return {"error": str(e)}

    def pending_count(self) -> int:
        """Count of queued (not yet running) jobs."""
        return len(self._queue)

    def list_jobs(self, status: str = None, limit: int = 50) -> list[dict]:
        """List jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status.value == status]
        # Sort by creation time, newest first
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def stats(self) -> dict:
        """Queue statistics."""
        by_status = {}
        for job in self._jobs.values():
            s = job.status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total_jobs": len(self._jobs),
            "queued": len(self._queue),
            "by_status": by_status,
        }

    def _save(self):
        """Persist queue state to disk."""
        path = Path(QUEUE_PATH) if not isinstance(QUEUE_PATH, Path) else QUEUE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "counter": self._counter,
            "jobs": {jid: job.to_dict() for jid, job in self._jobs.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _load(self):
        """Load queue state from disk."""
        path = Path(QUEUE_PATH) if not isinstance(QUEUE_PATH, Path) else QUEUE_PATH
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._counter = data.get("counter", 0)
            for jid, jdata in data.get("jobs", {}).items():
                # Reconstruct Job objects
                job = Job(
                    task=jdata["task"],
                    priority=JobPriority.from_string(jdata.get("priority", "normal")),
                    schedule_at=jdata.get("schedule_at"),
                    recurring=jdata.get("recurring"),
                    max_retries=jdata.get("max_retries", 2),
                    job_id=jid,
                    metadata=jdata.get("metadata", {}),
                )
                job.status = JobState(jdata["status"])
                job.retries = jdata.get("retries", 0)
                job.created_at = jdata.get("created_at", time.time())
                job.started_at = jdata.get("started_at")
                job.finished_at = jdata.get("finished_at")
                job.worker_id = jdata.get("worker_id")
                self._jobs[jid] = job
                # Re-queue if still queued
                if job.status == JobState.QUEUED:
                    self._counter += 1
                    heapq.heappush(self._queue, (job.priority, job.created_at, self._counter, job))
        except Exception:
            pass  # Corrupted file — start fresh


# Global singleton
queue = QueueManager()