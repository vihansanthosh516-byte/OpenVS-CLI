"""
Debug Mode — live hook inspection, visual swarm debugger, state explorer.

Enables deep inspection of the running OpenVS system:
- Which hooks are active and what they've done
- Swarm DAG visualization (text-based)
- Agent state timeline
- Event stream tail
- Plugin call trace
"""

import time
import json
from typing import Optional


class DebugMode:
    """Interactive debug mode for OpenVS internals."""

    def __init__(self):
        self._active = False
        self._trace_buffer: list[dict] = []
        self._max_trace = 500

    def enable(self):
        """Enable debug mode."""
        self._active = True
        return {"status": "enabled", "message": "Debug mode active. Use /debug for options."}

    def disable(self):
        """Disable debug mode."""
        self._active = False
        return {"status": "disabled"}

    @property
    def is_active(self) -> bool:
        return self._active

    def trace(self, event: str, data: dict = None):
        """Record a debug trace event."""
        if not self._active:
            return
        entry = {"event": event, "data": data or {}, "timestamp": time.time()}
        self._trace_buffer.append(entry)
        if len(self._trace_buffer) > self._max_trace:
            self._trace_buffer = self._trace_buffer[-self._max_trace:]

    def inspect_hooks(self) -> str:
        """Show all active hook subscriptions."""
        try:
            from openvs.plugins.runtime import plugin_runtime
            subs = plugin_runtime.hooks.list_subscribers()
            lines = ["Hook Inspection:", ""]
            for hook, plugins in sorted(subs.items()):
                lines.append(f"  {hook}")
                for p in plugins:
                    lines.append(f"    <- {p}")
            return "\n".join(lines) if lines else "No hooks registered."
        except Exception as e:
            return f"Error inspecting hooks: {e}"

    def inspect_swarm(self) -> str:
        """Show swarm DAG state."""
        try:
            from openvs.core.app_state import app_state
            lines = ["Swarm State:", ""]
            lines.append(f"  Enabled: {app_state.swarm.enabled}")
            lines.append(f"  Mode: {app_state.swarm.mode}")
            lines.append(f"  DAGs: {app_state.swarm.active_dags}")
            lines.append("")
            lines.append("  Agents:")
            for agent in app_state.swarm.agents:
                icon = {"idle": "o", "running": "*", "success": "+", "failed": "X"}.get(agent.state.value, "?")
                task = f" — {agent.current_task[:30]}" if agent.current_task and agent.state.value == "running" else ""
                lines.append(f"    [{icon}] {agent.name:16s} ({agent.role}){task}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    def inspect_plugins(self) -> str:
        """Show plugin runtime internals."""
        try:
            from openvs.plugins.runtime import plugin_runtime
            stats = plugin_runtime.stats()
            lines = ["Plugin Runtime Internals:", ""]
            for key, val in stats.items():
                if isinstance(val, dict):
                    lines.append(f"  {key}:")
                    for k, v in val.items():
                        lines.append(f"    {k}: {v}")
                else:
                    lines.append(f"  {key}: {val}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    def tail_events(self, limit: int = 20) -> str:
        """Show recent trace events."""
        if not self._trace_buffer:
            return "No trace events recorded."

        lines = [f"Trace Events (last {limit}):", ""]
        for entry in self._trace_buffer[-limit:]:
            ts = entry["timestamp"]
            event = entry["event"]
            data = json.dumps(entry["data"])[:60]
            lines.append(f"  [{ts:.3f}] {event:30s} {data}")

        return "\n".join(lines)

    def format_status(self) -> str:
        """Show full debug dashboard."""
        sections = [
            self.inspect_hooks(),
            "",
            self.inspect_swarm(),
            "",
            self.inspect_plugins(),
            "",
            self.tail_events(10),
        ]
        return "\n".join(sections)


# Global singleton
debug_mode = DebugMode()
