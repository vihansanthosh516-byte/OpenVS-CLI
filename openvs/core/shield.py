"""
Crash Shield — wraps all engine calls in try/except to prevent
malformed responses, broken tool calls, or dead workers from
crashing the UI.

Graceful degradation: if something breaks, we log it, show a
user-friendly message, and keep running. No exceptions escape.
"""

import sys
import os
import traceback
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from openvs.core.app_state import app_state, SystemStatus, AgentState


class CrashShield:
    """Wraps every engine call. Returns (result, error) tuples.

    If the engine crashes, we get a clean error dict instead of
    an exception that kills the UI.
    """

    def __init__(self):
        self._crash_log: list[dict] = []
        self._recovery_count = 0

    def call(self, fn, *args, **kwargs) -> tuple:
        """Call a function safely. Returns (result, None) or (None, error_str)."""
        try:
            result = fn(*args, **kwargs)
            return result, None
        except Exception as e:
            error = self._capture(e, fn.__name__ if hasattr(fn, '__name__') else str(fn))
            return None, error

    async def call_async(self, fn, *args, **kwargs) -> tuple:
        """Call an async function safely."""
        try:
            result = await fn(*args, **kwargs)
            return result, None
        except Exception as e:
            error = self._capture(e, fn.__name__ if hasattr(fn, '__name__') else str(fn))
            return None, error

    def _capture(self, exc: Exception, context: str) -> str:
        """Capture an exception, log it, and return a clean error string."""
        tb = traceback.format_exc()
        error_id = f"err_{int(time.time())}"

        entry = {
            "id": error_id,
            "context": context,
            "error": str(exc),
            "traceback": tb,
            "timestamp": time.time(),
        }
        self._crash_log.append(entry)
        self._recovery_count += 1

        # Reset agent states that might be stuck in RUNNING
        for agent in app_state.swarm.agents:
            if agent.state == AgentState.RUNNING:
                agent.state = AgentState.FAILED
                agent.current_task = f"crashed: {context}"

        # Reset system status if stuck
        if app_state.system_status in (SystemStatus.THINKING, SystemStatus.PLANNING,
                                        SystemStatus.EXECUTING, SystemStatus.STREAMING):
            app_state.set_status(SystemStatus.ERROR)

        return f"[{error_id}] {context}: {str(exc)[:200]}"

    def recent_crashes(self, limit: int = 10) -> list[dict]:
        """Return recent crash entries."""
        return self._crash_log[-limit:]

    def stats(self) -> dict:
        return {
            "total_crashes": len(self._crash_log),
            "recoveries": self._recovery_count,
            "recent": len(self._crash_log[-10:]),
        }

    def clear(self):
        self._crash_log.clear()


# Global singleton
shield = CrashShield()
