"""
Event Store — durable, replayable event log.

Upgrades the in-memory EventBus to an event sourcing system:
- Every event is persisted to disk (append-only log)
- Events are replayable on restart
- Full time-travel debugging
- UI desync becomes impossible (replay from store)
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional


# Default storage path
STORE_DIR = Path(__file__).resolve().parent.parent / "memory_store"
EVENT_LOG = STORE_DIR / "events.jsonl"


class EventStore:
    """Durable append-only event log.

    Every event written here survives restarts.
    Replay: load events from disk to rebuild state.
    Query: filter by type, time range, or task.
    """

    def __init__(self, path: str = None):
        self.path = Path(path) if path else EVENT_LOG
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    def write(self, event_type: str, data=None, task_id: str = None) -> dict:
        """Append an event to the log. Returns the stored event dict."""
        self._seq += 1
        event = {
            "id": f"evt_{self._seq:06d}_{uuid.uuid4().hex[:8]}",
            "seq": self._seq,
            "type": event_type,
            "data": data,
            "task_id": task_id,
            "timestamp": time.time(),
        }

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

        return event

    def write_event(self, event: dict) -> dict:
        """Write a pre-formed event dict (e.g. from EventBus.emit).

        Adds id/seq/timestamp if missing.
        """
        self._seq += 1
        if "id" not in event:
            event["id"] = f"evt_{self._seq:06d}_{uuid.uuid4().hex[:8]}"
        if "seq" not in event:
            event["seq"] = self._seq
        if "timestamp" not in event:
            event["timestamp"] = time.time()

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

        return event

    def read_all(self, limit: int = 0) -> list[dict]:
        """Read all events from the log. 0 = unlimited."""
        events = []
        if not self.path.exists():
            return events
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if limit:
            return events[-limit:]
        return events

    def query(
        self,
        event_type: str = None,
        task_id: str = None,
        since: float = None,
        until: float = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with filters."""
        events = self.read_all()

        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        if task_id:
            events = [e for e in events if e.get("task_id") == task_id]
        if since is not None:
            events = [e for e in events if e.get("timestamp", 0) >= since]
        if until is not None:
            events = [e for e in events if e.get("timestamp", 0) <= until]

        return events[-limit:]

    def replay(self, handler, event_type: str = None, task_id: str = None):
        """Replay events through a handler function.

        handler(event_dict) is called for each matching event.
        This is how you rebuild state from the log.
        """
        events = self.query(event_type=event_type, task_id=task_id, limit=0)
        for event in events:
            try:
                handler(event)
            except Exception:
                continue  # don't crash replay on one bad event

    def count(self) -> int:
        """Count total events in the log."""
        if not self.path.exists():
            return 0
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def stats(self) -> dict:
        """Return stats about the event log."""
        events = self.read_all()
        types = {}
        for e in events:
            t = e.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        return {
            "total_events": len(events),
            "event_types": types,
            "log_file": str(self.path),
            "log_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def truncate(self, keep: int = 1000):
        """Truncate the log, keeping only the last N events."""
        events = self.read_all()
        if len(events) <= keep:
            return
        kept = events[-keep:]
        with open(self.path, "w", encoding="utf-8") as f:
            for event in kept:
                f.write(json.dumps(event, default=str) + "\n")
        self._seq = kept[-1].get("seq", 0) if kept else 0

    def clear(self):
        """Wipe the entire event log."""
        if self.path.exists():
            self.path.write_text("")
        self._seq = 0


# Global singleton
store = EventStore()