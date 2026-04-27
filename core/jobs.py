"""
Job Model — every task becomes a durable job with its own state machine.

Job lifecycle: QUEUED → RUNNING → (WAITING_RETRY → RUNNING)* → COMPLETED/FAILED/CANCELLED

Jobs are separate from the agent state machine. This is important:
  - Agent state machine controls execution flow within a single step
  - Job state machine controls task lifecycle across scheduling/retries
"""

import uuid
import time
from enum import Enum
from typing import Optional, Any


class JobState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority:
    URGENT = 0
    HIGH = 1
    NORMAL = 2
    BACKGROUND = 3

    @classmethod
    def from_string(cls, s: str) -> int:
        mapping = {"urgent": 0, "high": 1, "normal": 2, "background": 3}
        return mapping.get(s.lower(), 2)

    @classmethod
    def to_string(cls, v: int) -> str:
        mapping = {0: "urgent", 1: "high", 2: "normal", 3: "background"}
        return mapping.get(v, "normal")


# Valid job state transitions
JOB_TRANSITIONS = {
    JobState.QUEUED: [JobState.RUNNING, JobState.CANCELLED],
    JobState.RUNNING: [JobState.COMPLETED, JobState.FAILED, JobState.WAITING_RETRY, JobState.CANCELLED],
    JobState.WAITING_RETRY: [JobState.RUNNING, JobState.CANCELLED, JobState.FAILED],
    JobState.COMPLETED: [],
    JobState.FAILED: [JobState.QUEUED],  # can re-queue a failed job
    JobState.CANCELLED: [JobState.QUEUED],  # can re-queue a cancelled job
}


class Job:
    """A durable, schedulable task with lifecycle management.

    Attributes:
        id: Unique job identifier
        task: The task description
        priority: 0=urgent, 1=high, 2=normal, 3=background
        status: Current JobState
        schedule_at: Timestamp for deferred execution (None = immediate)
        recurring: Interval string for recurring jobs (None = one-shot)
        max_retries: Maximum retry attempts on failure
        retries: Current retry count
        result: Final result dict (populated on completion)
        worker_id: ID of the worker currently running this job
        created_at: Creation timestamp
        started_at: Execution start timestamp
        finished_at: Execution end timestamp
    """

    def __init__(
        self,
        task: str,
        priority: int = JobPriority.NORMAL,
        schedule_at: Optional[float] = None,
        recurring: Optional[str] = None,
        max_retries: int = 2,
        job_id: str = None,
        metadata: dict = None,
    ):
        self.id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        self.task = task
        self.priority = priority
        self.status = JobState.QUEUED
        self.schedule_at = schedule_at
        self.recurring = recurring
        self.max_retries = max_retries
        self.retries = 0
        self.result: Optional[dict] = None
        self.worker_id: Optional[str] = None
        self.metadata = metadata or {}
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.history: list[dict] = []

    def transition(self, new_state: JobState) -> JobState:
        """Attempt a job state transition. Raises on illegal transitions."""
        allowed = JOB_TRANSITIONS.get(self.status, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid job transition {self.status.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        old = self.status
        self.status = new_state
        self.history.append({
            "from": old.value,
            "to": new_state.value,
            "ts": time.time(),
        })
        return self.status

    @property
    def is_ready(self) -> bool:
        """Whether this job is ready to be executed now."""
        if self.status != JobState.QUEUED:
            return False
        if self.schedule_at is not None and time.time() < self.schedule_at:
            return False
        return True

    @property
    def is_terminal(self) -> bool:
        """Whether this job is in a terminal state."""
        return self.status in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)

    @property
    def duration_ms(self) -> Optional[float]:
        """Duration in milliseconds if job has run."""
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at) * 1000, 1)
        return None

    def __lt__(self, other):
        """Priority queue ordering: lower priority number = higher priority."""
        if not isinstance(other, Job):
            return NotImplemented
        return self.priority < other.priority

    def to_dict(self) -> dict:
        """Serialize job to dict."""
        return {
            "id": self.id,
            "task": self.task,
            "priority": JobPriority.to_string(self.priority),
            "status": self.status.value,
            "schedule_at": self.schedule_at,
            "recurring": self.recurring,
            "max_retries": self.max_retries,
            "retries": self.retries,
            "worker_id": self.worker_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }