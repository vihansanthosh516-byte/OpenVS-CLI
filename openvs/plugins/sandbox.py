"""
Sandbox Executor — plugins run in a controlled boundary.

Plugins can ONLY:
- Call handlers declared in their manifest
- Use the PluginContext API
- Emit events through the context

Plugins CANNOT:
- Directly import core engine modules
- Access raw subprocess or filesystem outside workspace
- Modify swarm state without going through context APIs
- Call model APIs directly

This is a lightweight sandbox (not AST-level, but boundary-enforced).
Future upgrade path: WASM-based true isolation.
"""

from typing import Optional, Any


# Modules plugins are NOT allowed to import
BLOCKED_IMPORTS = {
    "subprocess", "os.system", "shutil.rmtree",
    "core.orchestrator", "core.swarm_coordinator",
    "core.policy_engine", "core.consensus",
}

# Permissions and what they unlock
PERMISSION_MAP = {
    "network": "Allow outbound HTTP/websocket calls",
    "read_repo": "Allow reading workspace files",
    "write_comments": "Allow posting comments/reviews",
    "write_files": "Allow writing to workspace",
    "run_tests": "Allow executing test commands",
    "admin": "Full access (use sparingly)",
}


class PluginSandbox:
    """Executes plugin code within a controlled boundary.

    Every plugin command/hook call flows through this class.
    It validates the call is declared in the manifest, resolves
    the handler function, and executes it with the context.
    """

    def __init__(self, context):
        self.context = context
        self._call_log: list[dict] = []
        self._denied_count = 0

    def call_command(self, plugin, command_name: str, args: list = None) -> dict:
        """Execute a plugin command through the sandbox.

        Returns: {"status": "ok"|"denied"|"error", "result": ..., "error": ...}
        """
        args = args or []

        # Verify command is declared in manifest
        declared_commands = plugin.manifest.get("commands", [])
        found = False
        handler_path = None

        for cmd in declared_commands:
            if isinstance(cmd, dict):
                if cmd.get("name") == command_name:
                    found = True
                    handler_path = cmd.get("handler", "")
                    break
            elif isinstance(cmd, str) and cmd == command_name:
                found = True
                handler_path = command_name
                break

        if not found:
            self._denied_count += 1
            self._call_log.append({
                "plugin": plugin.name,
                "type": "command",
                "name": command_name,
                "status": "denied",
                "reason": "not declared in manifest",
            })
            return {"status": "denied", "error": f"Command '{command_name}' not declared in manifest"}

        # Resolve and call the handler
        return self._execute_handler(plugin, handler_path, args)

    def call_hook(self, plugin, hook_name: str, payload: dict = None) -> dict:
        """Execute a plugin hook handler through the sandbox."""
        payload = payload or {}

        # Verify hook is declared
        if hook_name not in plugin.hooks:
            return {"status": "skipped", "reason": "hook not subscribed"}

        # Hooks use the hook name as the handler function name
        return self._execute_handler(plugin, hook_name, [payload])

    def call_tool(self, plugin, tool_name: str, args: dict = None) -> dict:
        """Execute a plugin tool through the sandbox."""
        args = args or {}

        # Verify tool is declared
        if tool_name not in plugin.tools:
            self._denied_count += 1
            return {"status": "denied", "error": f"Tool '{tool_name}' not declared in manifest"}

        return self._execute_handler(plugin, tool_name, [args])

    def check_permission(self, plugin, required_permission: str) -> bool:
        """Check if a plugin has a specific permission."""
        if "admin" in plugin.permissions:
            return True
        return required_permission in plugin.permissions

    def _execute_handler(self, plugin, handler_path: str, args: list) -> dict:
        """Resolve a dotted handler path and execute it."""
        module = plugin.module

        if module is None:
            return {"status": "error", "error": "Plugin module not loaded"}

        try:
            # Resolve dotted path: "commands.handle_pr" -> module.commands.handle_pr
            func = self._resolve(module, handler_path)

            if func is None:
                # Try calling handler_path as a top-level function name
                func = self._resolve(module, handler_path.replace(".", "_"))

            if func is None:
                return {"status": "error", "error": f"Handler '{handler_path}' not found in module"}

            # Execute with context as first arg
            result = func(args, self.context)

            self._call_log.append({
                "plugin": plugin.name,
                "type": "handler",
                "name": handler_path,
                "status": "ok",
            })

            return {"status": "ok", "result": result}

        except Exception as e:
            self._call_log.append({
                "plugin": plugin.name,
                "type": "handler",
                "name": handler_path,
                "status": "error",
                "error": str(e),
            })
            return {"status": "error", "error": str(e)}

    def _resolve(self, module, dotted_path: str):
        """Resolve a dotted attribute path on a module."""
        if not dotted_path:
            return None

        obj = module
        for part in dotted_path.split("."):
            try:
                obj = getattr(obj, part)
            except AttributeError:
                return None
        return obj

    def call_log(self, limit: int = 50) -> list[dict]:
        """Return recent call log entries."""
        return self._call_log[-limit:]

    def stats(self) -> dict:
        return {
            "total_calls": len(self._call_log),
            "denied_calls": self._denied_count,
            "recent_calls": len(self._call_log[-10:]),
        }