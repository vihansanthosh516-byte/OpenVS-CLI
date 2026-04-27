"""
Hook Dispatcher — connects plugins to engine lifecycle events.

Flow:
  Engine event emitted → dispatcher → all subscribed plugins run

Supported hooks:
  before_run           — before a prompt is executed
  after_run            — after a prompt completes
  before_model_call    — before the model API is called
  after_model_call     — after the model returns
  before_patch          — before a file patch is applied
  after_patch           — after a file patch is applied
  on_job_start         — when a job begins execution
  on_job_complete      — when a job finishes
  on_worker_spawn      — when a new worker is created
  on_worker_fail       — when a worker crashes
  on_consensus_vote    — when a consensus round happens
  on_diff_accept       — when a diff is accepted
  on_diff_reject       — when a diff is rejected

Plugins declare which hooks they subscribe to in their manifest.
The dispatcher calls the plugin's handler function named after the hook.
"""

import time
from typing import Optional


class HookDispatcher:
    """Dispatches engine lifecycle events to subscribed plugins.

    Each hook can have multiple plugin subscribers.
    Hooks execute sequentially; a slow plugin blocks later ones.
    Errors in one plugin don't stop others.
    """

    # All valid hook names
    VALID_HOOKS = {
        "before_run", "after_run",
        "before_model_call", "after_model_call",
        "before_patch", "after_patch",
        "on_job_start", "on_job_complete",
        "on_worker_spawn", "on_worker_fail",
        "on_consensus_vote", "on_diff_accept", "on_diff_reject",
    }

    def __init__(self, sandbox=None):
        self._subscribers: dict[str, list[str]] = {}  # hook -> [plugin_name, ...]
        self._sandbox = sandbox
        self._emit_log: list[dict] = []
        self._error_count = 0

    def register(self, plugin_name: str, hooks: list[str]):
        """Subscribe a plugin to a list of hooks."""
        for hook in hooks:
            if hook in self.VALID_HOOKS:
                self._subscribers.setdefault(hook, [])
                if plugin_name not in self._subscribers[hook]:
                    self._subscribers[hook].append(plugin_name)

    def unregister(self, plugin_name: str):
        """Remove a plugin from all hook subscriptions."""
        for hook in list(self._subscribers.keys()):
            if plugin_name in self._subscribers[hook]:
                self._subscribers[hook].remove(plugin_name)
            if not self._subscribers[hook]:
                del self._subscribers[hook]

    def emit(self, hook_name: str, context, plugins: dict, payload: dict = None) -> dict:
        """Fire a hook event to all subscribed plugins.

        Args:
            hook_name: The hook event name
            context: PluginContext instance
            plugins: dict of LoadedPlugin objects from the loader
            payload: Event data to pass to handlers

        Returns:
            {"hook": str, "dispatched": int, "errors": int, "results": list}
        """
        payload = payload or {}
        subscribers = self._subscribers.get(hook_name, [])
        results = []
        errors = 0

        log_entry = {
            "hook": hook_name,
            "timestamp": time.time(),
            "subscribers": len(subscribers),
            "results": [],
        }

        for plugin_name in subscribers:
            plugin = plugins.get(plugin_name)
            if not plugin or not plugin.enabled:
                continue

            if self._sandbox:
                result = self._sandbox.call_hook(plugin, hook_name, payload)
            else:
                # Fallback: direct call (not recommended)
                result = self._direct_call(plugin, hook_name, context, payload)

            results.append({"plugin": plugin_name, "result": result})
            if result.get("status") == "error":
                errors += 1
                self._error_count += 1

        log_entry["results"] = results
        log_entry["errors"] = errors
        self._emit_log.append(log_entry)

        # Keep log bounded
        if len(self._emit_log) > 500:
            self._emit_log = self._emit_log[-500:]

        return {
            "hook": hook_name,
            "dispatched": len(results),
            "errors": errors,
            "results": results,
        }

    def _direct_call(self, plugin, hook_name: str, context, payload: dict) -> dict:
        """Direct hook call without sandbox (fallback only)."""
        module = plugin.module
        if module is None:
            return {"status": "error", "error": "Module not loaded"}

        handler = getattr(module, hook_name, None)
        if handler is None:
            return {"status": "skipped", "reason": "no handler"}

        try:
            result = handler(context, payload)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_subscribers(self, hook_name: str = None) -> dict:
        """List subscribers for a hook or all hooks."""
        if hook_name:
            return {hook_name: self._subscribers.get(hook_name, [])}
        return dict(self._subscribers)

    def emit_log(self, limit: int = 20) -> list[dict]:
        """Return recent hook dispatch log."""
        return self._emit_log[-limit:]

    def stats(self) -> dict:
        total_hooks = sum(len(v) for v in self._subscribers.values())
        return {
            "total_subscriptions": total_hooks,
            "unique_hooks": len(self._subscribers),
            "total_emits": len(self._emit_log),
            "error_count": self._error_count,
            "available_hooks": sorted(self.VALID_HOOKS),
        }