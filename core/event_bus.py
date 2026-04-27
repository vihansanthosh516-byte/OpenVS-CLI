"""
Event Bus — connects everything (UI, CLI, agents, tools, streaming, diff).

All communication flows through this single channel:
  agent -> event bus -> subscribers
  tool   -> event bus -> subscribers
  model  -> event bus -> subscribers

Now backed by EventStore for durability. Events survive restarts.
"""

import json
import time
from typing import Callable, Any
from collections import defaultdict


class EventBus:
    """Central publish/subscribe event system with durable storage.

    Events are typed dicts:
        {"type": "state.change", "data": {...}, "ts": 1713945600.0}

    Every event is also persisted to the EventStore (append-only log)
    so they survive restarts and can be replayed for debugging.
    """

    def __init__(self, enable_store: bool = True):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._wildcard_subscribers: list[Callable] = []
        self._history: list[dict] = []
        self._max_history = 500
        self._enable_store = enable_store
        self._store = None

        # Lazy-init the event store
        if enable_store:
            try:
                from core.event_store import store
                self._store = store
            except Exception:
                pass  # store is optional; bus works without it

    def on(self, event_type: str, fn: Callable) -> None:
        """Subscribe to events of a specific type."""
        self._subscribers[event_type].append(fn)

    def on_any(self, fn: Callable) -> None:
        """Subscribe to ALL events (wildcard)."""
        self._wildcard_subscribers.append(fn)

    def off(self, event_type: str, fn: Callable) -> None:
        """Unsubscribe a specific handler."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != fn
            ]

    def emit(self, event_type: str, data: Any = None, task_id: str = None) -> dict:
        """Publish an event to all matching subscribers.

        Also persists the event to the EventStore for durability.
        Returns the event dict for chaining/logging.
        """
        event = {
            "type": event_type,
            "data": data,
            "ts": time.time(),
            "task_id": task_id,
        }

        # In-memory history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Persist to durable event store
        if self._store is not None:
            try:
                self._store.write_event(event)
            except Exception:
                pass  # store failure must not crash the bus

        # Notify type-specific subscribers
        for handler in self._subscribers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                self._history.append({
                    "type": "event_bus.error",
                    "data": {"handler": str(handler), "error": str(e)},
                    "ts": time.time(),
                })

        # Notify wildcard subscribers
        for handler in self._wildcard_subscribers:
            try:
                handler(event)
            except Exception:
                pass

        return event

    def history(self, event_type: str = None, limit: int = 50) -> list[dict]:
        """Return recent events from in-memory cache."""
        events = self._history
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return events[-limit:]

    def query_store(self, event_type: str = None, task_id: str = None,
                    since: float = None, limit: int = 100) -> list[dict]:
        """Query the durable event store (survives restarts)."""
        if self._store is None:
            return []
        return self._store.query(
            event_type=event_type,
            task_id=task_id,
            since=since,
            limit=limit,
        )

    def replay(self, handler, event_type: str = None, task_id: str = None):
        """Replay events from the durable store through a handler."""
        if self._store is not None:
            self._store.replay(handler, event_type=event_type, task_id=task_id)

    def store_stats(self) -> dict:
        """Return stats about the durable event store."""
        if self._store is None:
            return {"enabled": False}
        return {"enabled": True, **self._store.stats()}

    def clear_history(self):
        """Wipe in-memory event history (does NOT clear the store)."""
        self._history.clear()


# Global singleton - import this everywhere
bus = EventBus()