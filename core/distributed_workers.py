"""
Distributed Worker Fabric — worker nodes that execute subtasks from the swarm.

Each worker:
1. Registers with the swarm coordinator
2. Pulls subtasks from the job queue
3. Validates capability tokens before executing
4. Reports results back with timing and status
5. Handles retries and failure reporting

This is the execution layer. Workers are the hands of the swarm.
"""

import time
import threading
from typing import Optional
from core.event_bus import bus
from core.jobs import Job, JobState, JobPriority
from core.policy_engine import policy, CapabilityToken


class WorkerState:
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    OFFLINE = "offline"


class WorkerNode:
    """A single worker node in the distributed fabric.

    Workers pull jobs from the queue, verify capability tokens,
    execute the subtask, and report results back.
    """

    def __init__(
        self,
        worker_id: str,
        capabilities: list[str] = None,
        max_concurrent: int = 1,
    ):
        self.id = worker_id
        self.capabilities = capabilities or ["coder", "tester", "planner"]
        self.max_concurrent = max_concurrent
        self.state = WorkerState.IDLE
        self._active_jobs: dict[str, Job] = {}
        self._completed_count = 0
        self._failed_count = 0
        self._last_heartbeat = time.time()
        self._lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        return (
            self.state != WorkerState.OFFLINE
            and len(self._active_jobs) < self.max_concurrent
        )

    @property
    def utilization(self) -> float:
        if self.max_concurrent == 0:
            return 0.0
        return len(self._active_jobs) / self.max_concurrent

    def can_handle(self, agent_role: str) -> bool:
        """Check if this worker can handle a given agent role."""
        return agent_role in self.capabilities

    def assign_job(self, job: Job, token: CapabilityToken) -> dict:
        """Assign a job to this worker after token verification."""
        # Verify the token is valid and the agent role has READ permission
        # (specific tool permissions are checked during execution, not assignment)
        if token.is_expired:
            return {"status": "denied", "reason": f"Token {token.token_id} expired"}
        from core.policy_engine import Permission
        if not token.has_permission(Permission.READ):
            bus.emit("worker.assignment_denied", {
                "worker_id": self.id,
                "job_id": job.id,
                "reason": f"Role '{token.agent_role}' lacks READ permission",
            })
            return {"status": "denied", "reason": f"Role '{token.agent_role}' lacks READ permission"}

        with self._lock:
            if len(self._active_jobs) >= self.max_concurrent:
                return {"status": "rejected", "reason": "worker at capacity"}

            self._active_jobs[job.id] = job
            job.status = JobState.RUNNING
            self.state = WorkerState.RUNNING

        bus.emit("worker.job_assigned", {
            "worker_id": self.id,
            "job_id": job.id,
            "agent_role": job.metadata.get("agent_role", "unknown"),
        })

        return {"status": "assigned", "job_id": job.id}

    def complete_job(self, job_id: str, result: dict) -> dict:
        """Mark a job as completed with result."""
        with self._lock:
            if job_id not in self._active_jobs:
                return {"status": "error", "reason": "job not found"}

            job = self._active_jobs.pop(job_id)
            job.status = JobState.COMPLETED
            job.result = result
            self._completed_count += 1

            if not self._active_jobs:
                self.state = WorkerState.IDLE

        bus.emit("worker.job_completed", {
            "worker_id": self.id,
            "job_id": job_id,
        })

        return {"status": "completed", "job_id": job_id}

    def fail_job(self, job_id: str, error: str) -> dict:
        """Mark a job as failed."""
        with self._lock:
            if job_id not in self._active_jobs:
                return {"status": "error", "reason": "job not found"}

            job = self._active_jobs.pop(job_id)
            job.status = JobState.FAILED
            job.result = {"error": error}
            self._failed_count += 1

            if not self._active_jobs:
                self.state = WorkerState.IDLE

        bus.emit("worker.job_failed", {
            "worker_id": self.id,
            "job_id": job_id,
            "error": error[:100],
        })

        return {"status": "failed", "job_id": job_id}

    def heartbeat(self) -> dict:
        """Send a heartbeat signal."""
        self._last_heartbeat = time.time()
        return {
            "worker_id": self.id,
            "state": self.state,
            "active_jobs": len(self._active_jobs),
            "completed": self._completed_count,
            "failed": self._failed_count,
            "utilization": self.utilization,
        }

    def stats(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "capabilities": self.capabilities,
            "max_concurrent": self.max_concurrent,
            "active_jobs": len(self._active_jobs),
            "completed": self._completed_count,
            "failed": self._failed_count,
            "utilization": self.utilization,
            "last_heartbeat": self._last_heartbeat,
        }


class WorkerFabric:
    """Manages the pool of distributed worker nodes.

    Responsibilities:
    - Register/deregister workers
    - Route jobs to appropriate workers based on role matching
    - Track worker health via heartbeats
    - Report aggregate stats
    """

    def __init__(self, heartbeat_timeout: float = 30.0):
        self._workers: dict[str, WorkerNode] = {}
        self._heartbeat_timeout = heartbeat_timeout

    def register_worker(
        self,
        worker_id: str,
        capabilities: list[str] = None,
        max_concurrent: int = 1,
    ) -> WorkerNode:
        """Register a new worker node."""
        if worker_id in self._workers:
            return self._workers[worker_id]

        worker = WorkerNode(worker_id, capabilities, max_concurrent)
        self._workers[worker_id] = worker

        bus.emit("fabric.worker_registered", {
            "worker_id": worker_id,
            "capabilities": capabilities or [],
        })

        return worker

    def deregister_worker(self, worker_id: str) -> dict:
        """Remove a worker from the fabric."""
        worker = self._workers.pop(worker_id, None)
        if worker is None:
            return {"status": "not_found"}

        worker.state = WorkerState.OFFLINE
        bus.emit("fabric.worker_deregistered", {"worker_id": worker_id})
        return {"status": "deregistered", "worker_id": worker_id}

    def find_worker(self, agent_role: str) -> Optional[WorkerNode]:
        """Find an available worker that can handle the given role."""
        for worker in self._workers.values():
            if worker.is_available and worker.can_handle(agent_role):
                return worker
        return None

    def available_workers(self) -> list[WorkerNode]:
        """Return all currently available workers."""
        return [w for w in self._workers.values() if w.is_available]

    def check_health(self) -> dict:
        """Check worker health based on heartbeat timeouts."""
        now = time.time()
        stale = []
        healthy = []

        for worker in self._workers.values():
            elapsed = now - worker._last_heartbeat
            if elapsed > self._heartbeat_timeout and worker.state != WorkerState.OFFLINE:
                stale.append(worker.id)
            else:
                healthy.append(worker.id)

        return {
            "total": len(self._workers),
            "healthy": len(healthy),
            "stale": len(stale),
            "stale_ids": stale,
        }

    def route_job(self, job: Job, token: CapabilityToken) -> dict:
        """Route a job to an appropriate worker."""
        agent_role = job.metadata.get("agent_role", "coder")
        worker = self.find_worker(agent_role)

        if worker is None:
            bus.emit("fabric.no_worker_available", {
                "job_id": job.id,
                "agent_role": agent_role,
            })
            return {"status": "no_worker", "reason": f"no available worker for role '{agent_role}'"}

        return worker.assign_job(job, token)

    def stats(self) -> dict:
        total_active = sum(len(w._active_jobs) for w in self._workers.values())
        total_completed = sum(w._completed_count for w in self._workers.values())
        total_failed = sum(w._failed_count for w in self._workers.values())

        return {
            "total_workers": len(self._workers),
            "available": len(self.available_workers()),
            "total_active_jobs": total_active,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "workers": [w.stats() for w in self._workers.values()],
        }


# Global singleton
fabric = WorkerFabric()
