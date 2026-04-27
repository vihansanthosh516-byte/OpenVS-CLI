"""
Plugin Context — the ONLY API surface plugins can access.

Plugins never touch raw engine internals. They get a controlled
context object that provides:

- send_message(text)       — write to the user's workspace
- run_tool(name, args)     — execute a registered tool
- emit(event, payload)     — fire an event into the bus
- subscribe(event, fn)     — listen for an event
- get_state()              — read-only snapshot of system state

This is the sandbox boundary. Adding methods here expands what
plugins can do. Removing them restricts them.
"""

import time
from typing import Callable, Any, Optional


class PluginContext:
    """Controlled API surface for plugins.

    Plugins receive this object as their first argument.
    They can call any method on it — nothing else.
    """

    def __init__(self, engine=None):
        self._engine = engine
        self._message_buffer: list[str] = []
        self._tool_results: list[dict] = []

    def send_message(self, text: str):
        """Write a message to the user's workspace/terminal."""
        self._message_buffer.append(text)
        if self._engine and hasattr(self._engine, "write"):
            self._engine.write(text)

    def run_tool(self, name: str, args: dict = None) -> Optional[dict]:
        """Execute a registered tool by name. Returns tool result."""
        args = args or {}
        result = {"tool": name, "args": args, "status": "not_found"}

        if self._engine and hasattr(self._engine, "tools"):
            try:
                tool_result = self._engine.tools.run(name, args)
                result = {"tool": name, "args": args, "status": "ok", "result": tool_result}
            except Exception as e:
                result = {"tool": name, "args": args, "status": "error", "error": str(e)}

        self._tool_results.append(result)
        return result

    def emit(self, event: str, payload: dict = None):
        """Fire an event into the OpenVS event bus."""
        if self._engine and hasattr(self._engine, "events"):
            try:
                self._engine.events.emit(event, payload or {})
            except Exception:
                pass

    def subscribe(self, event: str, handler: Callable):
        """Subscribe to an event on the OpenVS event bus."""
        if self._engine and hasattr(self._engine, "events"):
            try:
                self._engine.events.on(event, handler)
            except Exception:
                pass

    def get_state(self) -> dict:
        """Read-only snapshot of current system state.

        Plugins can observe but never mutate this directly.
        """
        state = {
            "timestamp": time.time(),
            "model": "unknown",
            "swarm_enabled": False,
            "swarm_mode": "parallel",
            "mode": "chat",
            "worker_count": 0,
            "messages": 0,
        }

        try:
            from openvs.core.app_state import app_state
            state.update({
                "model": app_state.model,
                "swarm_enabled": app_state.swarm.enabled,
                "swarm_mode": app_state.swarm.mode,
                "mode": app_state.mode.value,
                "worker_count": app_state.worker_count,
                "messages": len(app_state.messages),
            })
        except Exception:
            pass

        return state

    def get_config(self, key: str, default=None):
        """Read a config value. Plugins cannot write config."""
        try:
            from openvs.core.config import get as config_get
            return config_get(key, default)
        except Exception:
            return default

    def flush_messages(self) -> list[str]:
        """Return and clear the message buffer."""
        msgs = list(self._message_buffer)
        self._message_buffer.clear()
        return msgs

    def flush_tool_results(self) -> list[dict]:
        """Return and clear the tool result buffer."""
        results = list(self._tool_results)
        self._tool_results.clear()
        return results


class PluginEngineAdapter:
    """Adapter that gives PluginContext access to engine services.

    This is the bridge between the plugin sandbox and the real engine.
    Only methods exposed here are accessible to plugins.
    """

    def __init__(self):
        self._event_bus = None
        self._tool_registry = None
        self._ui_writer = None

    @property
    def events(self):
        if self._event_bus is None:
            try:
                from core.event_bus import bus
                self._event_bus = bus
            except Exception:
                pass
        return self._event_bus

    @property
    def tools(self):
        if self._tool_registry is None:
            try:
                from tools.registry import registry
                self._tool_registry = registry
            except Exception:
                pass
        return self._tool_registry

    def write(self, text: str):
        """Write a message to the UI workspace."""
        if self._ui_writer:
            self._ui_writer(text)

    def set_ui_writer(self, fn: Callable):
        """Set the UI write callback."""
        self._ui_writer = fn
