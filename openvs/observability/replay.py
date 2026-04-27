"""
Crash Replay — deterministic rerun from event store.

Replays events from the EventStore to reproduce crashes
and debug failures step-by-step.
"""

import json
import time
from pathlib import Path
from typing import Optional


EVENT_STORE_PATH = Path.home() / ".openvs" / "memory_store" / "events.jsonl"


class CrashReplay:
    """Replay events to reproduce crashes and debug failures."""

    def __init__(self):
        self._replay_log: list[dict] = []

    def replay_crash(self, crash_id: str = None, limit: int = 100) -> dict:
        """Replay events leading up to a crash.

        If crash_id is given, replays events before that crash.
        If None, replays the most recent crash.
        """
        events = self._load_events()

        if not events:
            return {"status": "no_events", "events": 0}

        # Find the crash point
        crash_idx = len(events)
        if crash_id:
            for i, event in enumerate(events):
                if event.get("crash_id") == crash_id:
                    crash_idx = i
                    break
        else:
            # Find last error event
            for i in range(len(events) - 1, -1, -1):
                if events[i].get("type", "").startswith("error") or events[i].get("level") == "error":
                    crash_idx = i
                    break

        # Get events leading up to crash
        start_idx = max(0, crash_idx - limit)
        replay_events = events[start_idx:crash_idx + 1]

        self._replay_log = replay_events

        return {
            "status": "replayed",
            "total_events": len(events),
            "replayed_events": len(replay_events),
            "crash_index": crash_idx,
            "events": replay_events[-10:],  # last 10 for display
        }

    def step(self, offset: int = 0) -> Optional[dict]:
        """Get a single event from the replay log."""
        if 0 <= offset < len(self._replay_log):
            return self._replay_log[offset]
        return None

    def format_replay(self, result: dict) -> str:
        """Format replay results for display."""
        lines = ["Crash Replay:", ""]
        lines.append(f"  Total events: {result.get('total_events', 0)}")
        lines.append(f"  Replayed: {result.get('replayed_events', 0)}")
        lines.append(f"  Crash at index: {result.get('crash_index', '?')}")
        lines.append("")

        for event in result.get("events", []):
            event_type = event.get("type", "unknown")
            timestamp = event.get("ts", 0)
            data = event.get("data", {})
            lines.append(f"  [{event_type:20s}] {json.dumps(data)[:80]}")

        return "\n".join(lines)

    def _load_events(self) -> list[dict]:
        """Load events from the event store."""
        events = []
        if EVENT_STORE_PATH.exists():
            try:
                for line in EVENT_STORE_PATH.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
            except Exception:
                pass
        return events


# Global singleton
crash_replay = CrashReplay()
