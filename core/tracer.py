"""
Observability Tracer — per-task spans with latency, failures, and metrics.

Provides structured traces for every task execution:
  Task 42
  ├─ planner    430ms  model=nemotron  tokens=812
  ├─ critic     180ms  model=nemotron  tokens=234
  ├─ tool:patch  21ms  file=app.py
  └─ verify     300ms  model=nemotron  tokens=156

This is how you see WHERE time goes, WHAT fails, and HOW OFTEN
fallbacks are triggered. Without this, optimization is blind.
"""

import time
import json
from typing import Optional, Any
from pathlib import Path

from core.event_bus import bus


class Span:
    """A single timed operation within a trace.

    Spans are nested: a task trace contains agent spans,
    agent spans contain tool spans, tool spans contain model spans.
    """

    def __init__(self, name: str, parent_id: str = None, trace_id: str = None):
        self.name = name
        self.span_id = f"span_{id(self):x}"
        self.parent_id = parent_id
        self.trace_id = trace_id
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.status = "pending"  # pending | ok | error | blocked
        self.attributes: dict = {}
        self.events: list[dict] = []
        self.children: list[Span] = []

    def start(self):
        """Mark span as started."""
        self.start_time = time.time()
        self.status = "running"

    def finish(self, status: str = "ok"):
        """Mark span as finished."""
        self.end_time = time.time()
        self.status = status

    @property
    def duration_ms(self) -> Optional[float]:
        """Duration in milliseconds, or None if not finished."""
        if self.start_time is not None and self.end_time is not None:
            return round((self.end_time - self.start_time) * 1000, 1)
        return None

    def set_attr(self, key: str, value: Any):
        """Set a span attribute (model, file, tokens, etc.)."""
        self.attributes[key] = value

    def add_event(self, name: str, data: dict = None):
        """Add a point-in-time event to this span."""
        self.events.append({
            "name": name,
            "data": data or {},
            "timestamp": time.time(),
        })

    def child(self, name: str) -> "Span":
        """Create a child span."""
        child = Span(name, parent_id=self.span_id, trace_id=self.trace_id)
        self.children.append(child)
        return child

    def to_dict(self) -> dict:
        """Serialize span to dict."""
        return {
            "span_id": self.span_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "children": [c.to_dict() for c in self.children],
        }

    def render(self, indent: int = 0) -> str:
        """Render as a human-readable trace tree."""
        prefix = "  " * indent
        connector = "├─ " if indent > 0 else ""
        duration = f"{self.duration_ms:.0f}ms" if self.duration_ms is not None else "..."
        attrs = "  ".join(f"{k}={v}" for k, v in self.attributes.items() if v is not None)

        status_icon = {"ok": "", "error": " FAIL", "blocked": " BLOCKED"}.get(self.status, "")

        line = f"{prefix}{connector}{self.name}  {duration}  {attrs}{status_icon}"

        lines = [line]
        for i, child in enumerate(self.children):
            if i == len(self.children) - 1:
                lines.append(prefix + "  └─ " + child.render(indent + 1).lstrip())
            else:
                lines.append(prefix + "  ├─ " + child.render(indent + 1).lstrip())

        return "\n".join(lines)


class Trace:
    """A complete task execution trace.

    Contains the root span and all nested child spans.
    Persisted to disk for historical analysis.
    """

    STORE_DIR = Path(__file__).resolve().parent.parent / "memory_store" / "traces"

    def __init__(self, task_id: str, task: str):
        self.task_id = task_id
        self.task = task
        self.root = Span("task", trace_id=task_id)
        self.root.set_attr("task", task[:200])
        self.created_at = time.time()

    def span(self, name: str) -> Span:
        """Create a top-level child span of the root."""
        return self.root.child(name)

    def finish(self, status: str = "ok"):
        """Finish the root span."""
        self.root.finish(status)

    def to_dict(self) -> dict:
        """Serialize entire trace to dict."""
        return {
            "task_id": self.task_id,
            "task": self.task,
            "created_at": self.created_at,
            "trace": self.root.to_dict(),
        }

    def render(self) -> str:
        """Render the full trace as a tree."""
        return self.root.render()

    def save(self):
        """Persist trace to disk."""
        self.STORE_DIR.mkdir(parents=True, exist_ok=True)
        path = self.STORE_DIR / f"{self.task_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    @classmethod
    def load(cls, task_id: str) -> Optional["Trace"]:
        """Load a trace from disk."""
        path = cls.STORE_DIR / f"{task_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        trace = cls(data["task_id"], data["task"])
        trace.created_at = data["created_at"]
        # Reconstruct spans from dict
        trace.root = cls._dict_to_span(data["trace"], trace_id=data["task_id"])
        return trace

    @staticmethod
    def _dict_to_span(d: dict, trace_id: str) -> Span:
        """Reconstruct a Span from a serialized dict."""
        span = Span(d["name"], parent_id=d.get("parent_id"), trace_id=trace_id)
        span.span_id = d.get("span_id", span.span_id)
        span.status = d.get("status", "pending")
        span.start_time = d.get("start_time")
        span.end_time = d.get("end_time")
        span.attributes = d.get("attributes", {})
        span.events = d.get("events", [])
        span.children = [Trace._dict_to_span(c, trace_id) for c in d.get("children", [])]
        return span

    @classmethod
    def list_traces(cls, limit: int = 20) -> list[dict]:
        """List recent trace metadata."""
        if not cls.STORE_DIR.exists():
            return []
        traces = []
        for path in sorted(cls.STORE_DIR.glob("*.json"), reverse=True)[:limit]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                traces.append({
                    "task_id": data["task_id"],
                    "task": data["task"][:80],
                    "created_at": data["created_at"],
                    "status": data["trace"].get("status", "unknown"),
                    "duration_ms": data["trace"].get("duration_ms"),
                })
            except Exception:
                continue
        return traces


class Tracer:
    """Global tracer — creates and manages traces.

    Usage:
        tracer = Tracer()
        trace = tracer.start("task_001", "Add error handling")
        span = trace.span("planner")
        span.start()
        # ... do work ...
        span.finish()
        trace.finish()
        tracer.persist(trace)
    """

    def __init__(self):
        self._counter = 0
        self._active: Optional[Trace] = None

    def start(self, task: str, task_id: str = None) -> Trace:
        """Start a new trace for a task."""
        self._counter += 1
        if task_id is None:
            task_id = f"task_{self._counter:04d}_{int(time.time())}"

        trace = Trace(task_id, task)
        self._active = trace
        trace.root.start()

        bus.emit("trace.start", {"task_id": task_id, "task": task[:100]})

        return trace

    @property
    def active(self) -> Optional[Trace]:
        """Return the currently active trace."""
        return self._active

    def finish(self, status: str = "ok"):
        """Finish the active trace and persist it."""
        if self._active is None:
            return

        self._active.finish(status)
        self._active.save()

        bus.emit("trace.finish", {
            "task_id": self._active.task_id,
            "status": status,
            "duration_ms": self._active.root.duration_ms,
        })

        self._active = None

    def list_traces(self, limit: int = 20) -> list[dict]:
        """List recent traces."""
        return Trace.list_traces(limit)

    def load_trace(self, task_id: str) -> Optional[Trace]:
        """Load a specific trace for inspection."""
        return Trace.load(task_id)


# Global singleton
tracer = Tracer()