"""
Watchdog — continuous autonomous agents that monitor and react.

Watchers observe the filesystem or event stream and trigger
jobs when specific conditions are met. This is what turns
the system from "run tasks on demand" into "autonomous operating environment."

Examples:
  - Watch tests/ and auto-fix failures
  - Watch logs/ and alert on errors
  - Watch for model.fallback events and queue analysis
"""

import os
import time
import threading
from typing import Optional, Callable

from core.event_bus import bus
from core.jobs import Job, JobPriority
from core.queue_manager import queue


class Watchdog:
    """Monitors filesystem and events, triggers jobs on conditions.

    Unlike event triggers (which are instant), watchers can:
    - Poll filesystem for changes
    - Track state over time
    - Trigger with cooldowns
    - Provide context about what changed
    """

    def __init__(self):
        self._watchers: dict[str, dict] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register(
        self,
        watcher_id: str,
        path: str,
        condition: str,
        task: str,
        priority: str = "background",
        cooldown: float = 60.0,
        metadata: dict = None,
    ) -> str:
        """Register a new watcher.

        Args:
            watcher_id: Unique identifier for this watcher
            path: File or directory to watch
            condition: "change", "failure", "error", "exists"
            task: Task to run when condition is met
            priority: Job priority
            cooldown: Minimum seconds between triggers
            metadata: Extra context
        """
        self._watchers[watcher_id] = {
            "id": watcher_id,
            "path": path,
            "condition": condition,
            "task": task,
            "priority": JobPriority.from_string(priority),
            "cooldown": cooldown,
            "metadata": metadata or {},
            "last_triggered": 0,
            "last_state": self._snapshot_path(path),
            "trigger_count": 0,
        }

        bus.emit("watchdog.registered", {
            "watcher_id": watcher_id,
            "path": path,
            "condition": condition,
        })

        return watcher_id

    def unregister(self, watcher_id: str) -> dict:
        """Remove a watcher."""
        if watcher_id not in self._watchers:
            return {"error": f"Watcher {watcher_id} not found"}
        del self._watchers[watcher_id]
        bus.emit("watchdog.unregistered", {"watcher_id": watcher_id})
        return {"status": "unregistered", "watcher_id": watcher_id}

    def start(self, interval: float = 5.0):
        """Start the watchdog polling loop."""
        self._running = True

        def _loop():
            while self._running:
                self.check_all()
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="watchdog")
        self._thread.start()

        bus.emit("watchdog.started", {"watchers": len(self._watchers)})

    def stop(self):
        """Stop the watchdog."""
        self._running = False
        bus.emit("watchdog.stopped", {})

    def check_all(self):
        """Check all watchers and trigger jobs if conditions are met."""
        for watcher_id, watcher in list(self._watchers.items()):
            try:
                self._check_watcher(watcher)
            except Exception as e:
                bus.emit("watchdog.error", {
                    "watcher_id": watcher_id,
                    "error": str(e)[:200],
                })

    def _check_watcher(self, watcher: dict):
        """Check a single watcher and trigger if needed."""
        now = time.time()

        # Cooldown check
        if now - watcher["last_triggered"] < watcher["cooldown"]:
            return

        path = watcher["path"]
        condition = watcher["condition"]
        current_state = self._snapshot_path(path)

        should_trigger = False
        context = {}

        if condition == "change":
            if current_state != watcher["last_state"]:
                should_trigger = True
                context = {"change": "filesystem modified"}

        elif condition == "failure":
            # Check if path contains failure indicators
            if self._check_failure(path):
                should_trigger = True
                context = {"failure": "detected in " + path}

        elif condition == "exists":
            if os.path.exists(path) and not watcher["last_state"].get("exists", False):
                should_trigger = True
                context = {"exists": True}

        if should_trigger:
            watcher["last_triggered"] = now
            watcher["trigger_count"] += 1

            # Submit job
            job = Job(
                task=watcher["task"],
                priority=watcher["priority"],
                metadata={
                    "triggered_by": "watchdog",
                    "watcher_id": watcher["id"],
                    "watcher_condition": condition,
                    **context,
                },
            )
            queue.submit(job)

            bus.emit("watchdog.triggered", {
                "watcher_id": watcher["id"],
                "condition": condition,
                "job_id": job.id,
            })

        # Update state
        watcher["last_state"] = current_state

    @staticmethod
    def _snapshot_path(path: str) -> dict:
        """Take a snapshot of a path's current state."""
        if not os.path.exists(path):
            return {"exists": False}

        if os.path.isfile(path):
            try:
                stat = os.stat(path)
                return {
                    "exists": True,
                    "type": "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            except OSError:
                return {"exists": True, "type": "file", "error": True}

        if os.path.isdir(path):
            try:
                entries = sorted(os.listdir(path))
                return {
                    "exists": True,
                    "type": "dir",
                    "entries": entries[:50],  # cap
                    "count": len(entries),
                }
            except OSError:
                return {"exists": True, "type": "dir", "error": True}

        return {"exists": True}

    @staticmethod
    def _check_failure(path: str) -> bool:
        """Check if a file/directory contains failure indicators.

        Looks for: FAILED, ERROR, traceback, etc. in file content.
        """
        if not os.path.exists(path):
            return False

        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    # Read last 500 lines (failures usually at end)
                    lines = f.readlines()[-500:]
                    for line in lines:
                        lower = line.lower()
                        if any(marker in lower for marker in ["failed", "error", "traceback", "exception"]):
                            return True
            except Exception:
                pass

        return False

    def list_watchers(self) -> list[dict]:
        """List all registered watchers."""
        return [
            {
                "id": w["id"],
                "path": w["path"],
                "condition": w["condition"],
                "task": w["task"][:80],
                "trigger_count": w["trigger_count"],
                "last_triggered": w["last_triggered"],
            }
            for w in self._watchers.values()
        ]

    def stats(self) -> dict:
        """Watchdog statistics."""
        return {
            "running": self._running,
            "watchers": len(self._watchers),
            "total_triggers": sum(w["trigger_count"] for w in self._watchers.values()),
        }


# Global singleton
watchdog = Watchdog()