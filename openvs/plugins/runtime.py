"""
Plugin Runtime — top-level orchestrator for the entire plugin system.

Single entry point that wires together:
- PluginLoader (discovery + loading)
- PluginSandbox (safe execution)
- HookDispatcher (lifecycle events)
- PluginRegistry (persistent tracking)
- PluginContext (API surface)

Usage:
  from openvs.plugins.runtime import plugin_runtime

  plugin_runtime.load()              # load all plugins
  plugin_runtime.emit_hook("before_run", {...})  # fire hooks
  result = plugin_runtime.run_command("hello_plugin", "/hello", [])  # run a command
"""

import time
from typing import Optional

from openvs.plugins.loader import PluginLoader
from openvs.plugins.sandbox import PluginSandbox
from openvs.plugins.hooks import HookDispatcher
from openvs.plugins.registry import PluginRegistry
from openvs.plugins.context import PluginContext, PluginEngineAdapter


class PluginRuntime:
    """Orchestrates the entire plugin lifecycle.

    This is the ONLY thing the rest of OpenVS should import.
    All plugin interaction goes through this class.
    """

    def __init__(self):
        self.engine = PluginEngineAdapter()
        self.context = PluginContext(self.engine)
        self.loader = PluginLoader()
        self.sandbox = PluginSandbox(self.context)
        self.hooks = HookDispatcher(self.sandbox)
        self.registry = PluginRegistry()
        self._loaded = False
        self._load_time: Optional[float] = None

    def load(self) -> dict:
        """Discover and load all plugins from ~/.openvs/plugins/."""
        result = self.loader.load_all()

        # Register each loaded plugin in the registry and hook dispatcher
        for name, plugin in self.loader.plugins.items():
            self.registry.register(name, plugin.manifest)

            # Subscribe plugin to its declared hooks
            valid_hooks = [h for h in plugin.hooks if h in HookDispatcher.VALID_HOOKS]
            self.hooks.register(name, valid_hooks)

        self._loaded = True
        self._load_time = time.time()

        return {
            "loaded": result["loaded"],
            "errors": result["errors"],
            "total": len(self.loader.plugins),
            "load_errors": self.loader.load_errors(),
        }

    def reload(self) -> dict:
        """Reload all plugins (for hot-reload)."""
        # Unregister all hooks
        for name in list(self.loader.plugins.keys()):
            self.hooks.unregister(name)

        return self.load()

    def reload_plugin(self, name: str) -> dict:
        """Reload a single plugin."""
        self.hooks.unregister(name)
        plugin = self.loader.reload_plugin(name)

        if plugin:
            self.registry.register(name, plugin.manifest)
            valid_hooks = [h for h in plugin.hooks if h in HookDispatcher.VALID_HOOKS]
            self.hooks.register(name, valid_hooks)
            return {"status": "reloaded", "plugin": name}
        return {"status": "not_found", "plugin": name}

    def run_command(self, plugin_name: str, command: str, args: list = None) -> dict:
        """Execute a plugin command through the sandbox."""
        plugin = self.loader.get_plugin(plugin_name)
        if not plugin:
            return {"status": "error", "error": f"Plugin '{plugin_name}' not loaded"}
        if not plugin.enabled:
            return {"status": "error", "error": f"Plugin '{plugin_name}' is disabled"}
        if plugin.module is None:
            return {"status": "error", "error": f"Plugin '{plugin_name}' module not loaded"}

        return self.sandbox.call_command(plugin, command, args)

    def emit_hook(self, hook_name: str, payload: dict = None) -> dict:
        """Fire a lifecycle hook to all subscribed plugins."""
        if not self._loaded:
            return {"hook": hook_name, "dispatched": 0, "errors": 0, "results": []}

        return self.hooks.emit(hook_name, self.context, self.loader.plugins, payload)

    def run_tool(self, plugin_name: str, tool_name: str, args: dict = None) -> dict:
        """Execute a plugin tool through the sandbox."""
        plugin = self.loader.get_plugin(plugin_name)
        if not plugin:
            return {"status": "error", "error": f"Plugin '{plugin_name}' not loaded"}

        return self.sandbox.call_tool(plugin, tool_name, args)

    def get_plugin(self, name: str) -> Optional[dict]:
        """Get plugin info by name."""
        plugin = self.loader.get_plugin(name)
        if plugin:
            return {
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "enabled": plugin.enabled,
                "hooks": plugin.hooks,
                "commands": plugin.commands,
                "tools": plugin.tools,
                "permissions": plugin.permissions,
                "load_error": plugin.load_error,
            }
        return None

    def list_plugins(self) -> list[dict]:
        """List all loaded plugins."""
        return self.loader.list_plugins()

    def approve_permissions(self, name: str) -> dict:
        """Approve a plugin's permission request."""
        return self.registry.approve_permissions(name)

    def pending_approvals(self) -> list[dict]:
        """List plugins needing permission approval."""
        return self.registry.pending_approvals()

    def set_ui_writer(self, fn):
        """Set the UI write callback so plugins can output to the terminal."""
        self.engine.set_ui_writer(fn)

    def stats(self) -> dict:
        """Comprehensive stats across all subsystems."""
        return {
            "loaded": self._loaded,
            "load_time": self._load_time,
            "loader": self.loader.stats(),
            "sandbox": self.sandbox.stats(),
            "hooks": self.hooks.stats(),
            "registry": self.registry.stats(),
        }


# Global singleton — the rest of OpenVS uses this
plugin_runtime = PluginRuntime()