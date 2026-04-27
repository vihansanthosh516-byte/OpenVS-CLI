"""
Scheduler — controls when and how jobs run.

Supports:
  - Immediate execution: submit and run now
  - Deferred execution: schedule for later
  - Recurring execution: run every N seconds/minutes/hours
  - Event-triggered: run when specific events fire

The scheduler sits ABOVE the orchestrator. It controls orchestrators,
not the other way around. This separation is critical.
"""

import time
import threading
from typing import Optional, Callable

from core.jobs import Job, JobPriority
from core.queue_manager import queue
from core.workers import WorkerPool
from core.event_bus import bus


class Scheduler:
    """Controls job scheduling, dispatch, and lifecycle.

    The scheduler is the top-level controller in v12:
      Scheduler → Queue → WorkerPool → Orchestrator → Agent Runtime

    It does NOT run inside the orchestrator. It wraps it.
    """

    def __init__(self, pool_size: int = 4):
        self.pool = WorkerPool(size=pool_size)
        self._watchers: list[dict] = []
        self._event_triggers: dict[str, list[dict]] = {}
        self._running = False
        self._loop_thread: Optional[threading.Thread] = None

        # Subscribe to event bus for event-triggered scheduling
        bus.on_any(self._on_event)

    # ---- Job Submission ----

    def submit(self, task: str, priority: str = "normal") -> str:
        """Submit a job for immediate execution."""
        job = Job(task=task, priority=JobPriority.from_string(priority))
        return queue.submit(job)

    def schedule(self, task: str, run_at: float, priority: str = "normal") -> str:
        """Schedule a job for future execution.

        Args:
            run_at: Unix timestamp when the job should run
        """
        job = Job(task=task, priority=JobPriority.from_string(priority), schedule_at=run_at)
        return queue.submit(job)

    def schedule_delayed(self, task: str, delay_seconds: float, priority: str = "normal") -> str:
        """Schedule a job to run after a delay."""
        return self.schedule(task, time.time() + delay_seconds, priority)

    def recurring(self, task: str, interval: str, priority: str = "background") -> str:
        """Submit a recurring job.

        Args:
            interval: e.g. "30s", "5m", "1h"
        """
        job = Job(task=task, priority=JobPriority.from_string(priority), recurring=interval)
        return queue.submit(job)

    # ---- Watchers ----

    def watch(self, path: str, on_event: str, task: str, priority: str = "high") -> str:
        """Register a watcher — triggers a job when a filesystem event occurs.

        Args:
            path: Directory or file to watch
            on_event: "change", "create", "delete", "failure"
            task: Task to run when triggered
        """
        watcher_id = f"watch_{len(self._watchers) + 1}"
        self._watchers.append({
            "id": watcher_id,
            "path": path,
            "on_event": on_event,
            "task": task,
            "priority": JobPriority.from_string(priority),
            "last_triggered": None,
        })

        bus.emit("watcher.registered", {"watcher_id": watcher_id, "path": path, "on_event": on_event})
        return watcher_id

    # ---- Event-Triggered Scheduling ----

    def on_event(self, event_type: str, task: str, priority: str = "normal") -> str:
        """Register an event-triggered job.

        When an event of the given type fires, the task is submitted.
        """
        trigger_id = f"trigger_{len(self._event_triggers) + 1}"
        if event_type not in self._event_triggers:
            self._event_triggers[event_type] = []
        self._event_triggers[event_type].append({
            "id": trigger_id,
            "task": task,
            "priority": JobPriority.from_string(priority),
        })

        bus.emit("trigger.registered", {"trigger_id": trigger_id, "event_type": event_type})
        return trigger_id

    def _on_event(self, event: dict):
        """Handle events from the bus — check for triggers."""
        event_type = event.get("type", "")
        if event_type in self._event_triggers:
            for trigger in self._event_triggers[event_type]:
                # Throttle: don't re-trigger within 10 seconds
                last = trigger.get("last_triggered", 0)
                if time.time() - last < 10:
                    continue
                trigger["last_triggered"] = time.time()
                job = Job(
                    task=trigger["task"],
                    priority=trigger["priority"],
                    metadata={"triggered_by": event_type, "event_data": event.get("data")},
                )
                queue.submit(job)
                bus.emit("job.event_triggered", {
                    "job_id": job.id,
                    "trigger": trigger["id"],
                    "event_type": event_type,
                })

    # ---- Lifecycle ----

    def start(self, interval: float = 1.0):
        """Start the scheduler loop in a background thread."""
        self._running = True
        self.pool.start()

        def _loop():
            self.pool.dispatch_loop(interval)

        self._loop_thread = threading.Thread(target=_loop, daemon=True, name="scheduler")
        self._loop_thread.start()

        bus.emit("scheduler.started", {"pool_size": self.pool.size})

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        self.pool.stop()

        bus.emit("scheduler.stopped", {})

    def tick(self):
        """Manually dispatch one round of jobs (for testing or CLI mode)."""
        return self.pool.maybe_dispatch()

    # ---- Status ----

    def stats(self) -> dict:
        """Scheduler + pool + queue statistics."""
        return {
            "running": self._running,
            "pool": self.pool.stats(),
            "queue": queue.stats(),
            "watchers": len(self._watchers),
            "event_triggers": {
                et: len(triggers) for et, triggers in self._event_triggers.items()
            },
        }

    def list_jobs(self, status: str = None, limit: int = 50) -> list[dict]:
        """List all jobs."""
        return queue.list_jobs(status=status, limit=limit)

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get a specific job's status."""
        job = queue.get_job(job_id)
        return job.to_dict() if job else None

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a job."""
        return queue.cancel_job(job_id)


# Global singleton
scheduler = Scheduler()