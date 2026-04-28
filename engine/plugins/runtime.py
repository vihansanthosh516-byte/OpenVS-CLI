import time
import uuid
import threading
from engine.errors import OpenVSError, EngineRuntimeError, HookError, SecurityError


DEFAULT_RESOURCE_LIMITS = {
    "max_cpu_time_s": 30,
    "max_memory_mb": 256,
    "max_executions": 100,
    "max_event_subscriptions": 10,
    "max_commands": 5,
    "max_hooks": 5,
}


class ResourceLimits:
    def __init__(self, max_cpu_time_s=None, max_memory_mb=None,
                 max_executions=None, max_event_subscriptions=None,
                 max_commands=None, max_hooks=None):
        self.max_cpu_time_s = max_cpu_time_s or DEFAULT_RESOURCE_LIMITS["max_cpu_time_s"]
        self.max_memory_mb = max_memory_mb or DEFAULT_RESOURCE_LIMITS["max_memory_mb"]
        self.max_executions = max_executions or DEFAULT_RESOURCE_LIMITS["max_executions"]
        self.max_event_subscriptions = max_event_subscriptions or DEFAULT_RESOURCE_LIMITS["max_event_subscriptions"]
        self.max_commands = max_commands or DEFAULT_RESOURCE_LIMITS["max_commands"]
        self.max_hooks = max_hooks or DEFAULT_RESOURCE_LIMITS["max_hooks"]

    def to_dict(self):
        return {
            "max_cpu_time_s": self.max_cpu_time_s,
            "max_memory_mb": self.max_memory_mb,
            "max_executions": self.max_executions,
            "max_event_subscriptions": self.max_event_subscriptions,
            "max_commands": self.max_commands,
            "max_hooks": self.max_hooks,
        }

    @classmethod
    def from_dict(cls, d):
        if not d:
            return cls()
        return cls(
            max_cpu_time_s=d.get("max_cpu_time_s"),
            max_memory_mb=d.get("max_memory_mb"),
            max_executions=d.get("max_executions"),
            max_event_subscriptions=d.get("max_event_subscriptions"),
            max_commands=d.get("max_commands"),
            max_hooks=d.get("max_hooks"),
        )


class PluginSandbox:
    def __init__(self, plugin_name, limits=None, allowed_events=None,
                 allowed_commands=None, event_bus=None):
        self.plugin_name = plugin_name
        self.limits = limits or ResourceLimits()
        self.allowed_events = set(allowed_events) if allowed_events else None
        self.allowed_commands = set(allowed_commands) if allowed_commands else None
        self._event_bus = event_bus
        self._execution_count = 0
        self._cpu_time_used = 0.0
        self._active = True
        self._violations = []

    def check_execution(self):
        if not self._active:
            raise SecurityError(
                f"plugin '{self.plugin_name}' is disabled",
                violation="plugin_disabled",
            )
        if self._execution_count >= self.limits.max_executions:
            self._record_violation("execution_limit_exceeded")
            raise SecurityError(
                f"plugin '{self.plugin_name}' exceeded max executions ({self.limits.max_executions})",
                violation="resource_limit",
            )
        self._execution_count += 1

    def check_event_access(self, event_name):
        if not self._active:
            return False
        if self.allowed_events is not None:
            if event_name not in self.allowed_events and event_name != "*":
                self._record_violation(f"unauthorized_event:{event_name}")
                return False
        return True

    def check_command_access(self, command_name):
        if not self._active:
            return False
        if self.allowed_commands is not None:
            if command_name not in self.allowed_commands:
                self._record_violation(f"unauthorized_command:{command_name}")
                return False
        return True

    def check_subscription_limit(self, current_count):
        if current_count >= self.limits.max_event_subscriptions:
            self._record_violation("subscription_limit_exceeded")
            raise SecurityError(
                f"plugin '{self.plugin_name}' exceeded max event subscriptions ({self.limits.max_event_subscriptions})",
                violation="resource_limit",
            )

    def check_command_limit(self, current_count):
        if current_count >= self.limits.max_commands:
            self._record_violation("command_limit_exceeded")
            raise SecurityError(
                f"plugin '{self.plugin_name}' exceeded max commands ({self.limits.max_commands})",
                violation="resource_limit",
            )

    def check_hook_limit(self, current_count):
        if current_count >= self.limits.max_hooks:
            self._record_violation("hook_limit_exceeded")
            raise SecurityError(
                f"plugin '{self.plugin_name}' exceeded max hooks ({self.limits.max_hooks})",
                violation="resource_limit",
            )

    def track_cpu_time(self, seconds):
        self._cpu_time_used += seconds
        if self._cpu_time_used > self.limits.max_cpu_time_s:
            self._record_violation("cpu_time_exceeded")
            raise SecurityError(
                f"plugin '{self.plugin_name}' exceeded CPU time ({self.limits.max_cpu_time_s}s)",
                violation="resource_limit",
            )

    def deactivate(self):
        self._active = False

    def activate(self):
        self._active = True

    @property
    def active(self):
        return self._active

    def violations(self):
        return list(self._violations)

    def usage(self):
        return {
            "plugin": self.plugin_name,
            "active": self._active,
            "executions": self._execution_count,
            "cpu_time_used_s": round(self._cpu_time_used, 3),
            "limits": self.limits.to_dict(),
            "violations": len(self._violations),
        }

    def _record_violation(self, violation_type):
        self._violations.append({
            "type": violation_type,
            "timestamp": time.time(),
        })
        if self._event_bus:
            self._event_bus.emit("plugin_violation", {
                "plugin": self.plugin_name,
                "violation": violation_type,
            })


class ScopedEventSubscription:
    def __init__(self, plugin_name, event_bus, sandbox):
        self._plugin_name = plugin_name
        self._event_bus = event_bus
        self._sandbox = sandbox
        self._subscriptions = {}

    def subscribe(self, event_name, callback):
        if not self._sandbox.check_event_access(event_name):
            raise SecurityError(
                f"plugin '{self._plugin_name}' not allowed to subscribe to event '{event_name}'",
                violation="event_access_denied",
            )
        self._sandbox.check_subscription_limit(len(self._subscriptions))

        wrapped = self._make_scoped_callback(event_name, callback)
        self._event_bus.on(event_name, wrapped)
        self._subscriptions[event_name] = wrapped
        return True

    def unsubscribe(self, event_name):
        if event_name in self._subscriptions:
            self._event_bus.off(event_name, self._subscriptions[event_name])
            del self._subscriptions[event_name]
            return True
        return False

    def unsubscribe_all(self):
        for event_name, callback in list(self._subscriptions.items()):
            self._event_bus.off(event_name, callback)
        self._subscriptions.clear()

    def _make_scoped_callback(self, event_name, callback):
        plugin_name = self._plugin_name
        sandbox = self._sandbox

        def scoped_cb(ev_name, data):
            if not sandbox.active:
                return
            try:
                sandbox.check_execution()
            except SecurityError:
                return
            start = time.time()
            try:
                result = callback(ev_name, data)
                elapsed = time.time() - start
                sandbox.track_cpu_time(elapsed)
                return result
            except SecurityError:
                raise
            except Exception:
                pass

        return scoped_cb

    @property
    def subscriptions(self):
        return list(self._subscriptions.keys())


class PluginManifest:
    def __init__(self, name, version="0.1.0", description="", commands=None,
                 event_subscriptions=None, hook_subscriptions=None, permissions=None,
                 resource_limits=None, allowed_events=None, allowed_commands=None):
        self.name = name
        self.version = version
        self.description = description
        self.commands = commands or []
        self.event_subscriptions = event_subscriptions or []
        self.hook_subscriptions = hook_subscriptions or []
        self.permissions = permissions or []
        self.resource_limits = ResourceLimits.from_dict(resource_limits) if resource_limits else None
        self.allowed_events = allowed_events
        self.allowed_commands = allowed_commands

    def to_dict(self):
        d = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "commands": self.commands,
            "event_subscriptions": self.event_subscriptions,
            "hook_subscriptions": self.hook_subscriptions,
            "permissions": self.permissions,
        }
        if self.resource_limits:
            d["resource_limits"] = self.resource_limits.to_dict()
        if self.allowed_events is not None:
            d["allowed_events"] = list(self.allowed_events)
        if self.allowed_commands is not None:
            d["allowed_commands"] = list(self.allowed_commands)
        return d


class PluginState:
    UNLOADED = "unloaded"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    ISOLATED = "isolated"


class Plugin:
    def __init__(self, manifest, module=None):
        self.id = str(uuid.uuid4())[:8]
        self.manifest = manifest
        self.module = module
        self.state = PluginState.UNLOADED
        self.loaded_at = None
        self.error = None
        self._registered_commands = []
        self._registered_events = []
        self._registered_hooks = []
        self.sandbox = None
        self.scoped_events = None

    def to_dict(self):
        d = {
            "id": self.id,
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state,
            "error": self.error,
            "commands": self._registered_commands,
            "events_subscribed": self._registered_events,
            "hooks_subscribed": self._registered_hooks,
        }
        if self.sandbox:
            d["sandbox"] = self.sandbox.usage()
        return d


class PluginRuntime:
    def __init__(self, event_bus=None, hook_system=None, command_registry=None, sandbox=None):
        self._plugins = {}
        self._load_order = []
        self.event_bus = event_bus
        self.hook_system = hook_system
        self.command_registry = command_registry
        self.sandbox = sandbox
        self._init_done = False
        self._global_limits = ResourceLimits()

    def register_plugin(self, manifest, module=None):
        if manifest.name in self._plugins:
            return {"status": "error", "error": f"plugin '{manifest.name}' already registered"}

        plugin = Plugin(manifest, module)

        if self.sandbox:
            try:
                self.sandbox.validate_permissions(manifest.permissions)
            except Exception as e:
                plugin.state = PluginState.ERROR
                plugin.error = str(e)
                self._plugins[manifest.name] = plugin
                return {"status": "error", "error": f"permission denied: {e}"}

        limits = manifest.resource_limits or self._global_limits
        plugin.sandbox = PluginSandbox(
            plugin_name=manifest.name,
            limits=limits,
            allowed_events=manifest.allowed_events,
            allowed_commands=manifest.allowed_commands,
            event_bus=self.event_bus,
        )

        plugin.scoped_events = ScopedEventSubscription(
            plugin_name=manifest.name,
            event_bus=self.event_bus,
            sandbox=plugin.sandbox,
        ) if self.event_bus else None

        plugin.state = PluginState.LOADED
        plugin.loaded_at = time.time()

        if self.command_registry:
            for cmd_def in manifest.commands:
                try:
                    cmd_name = cmd_def["name"] if isinstance(cmd_def, dict) else cmd_def
                    handler = cmd_def.get("handler") if isinstance(cmd_def, dict) else None

                    if not plugin.sandbox.check_command_access(cmd_name):
                        continue

                    plugin.sandbox.check_command_limit(len(plugin._registered_commands))

                    if handler and module and hasattr(module, handler):
                        fn = getattr(module, handler)
                    elif module and hasattr(module, f"cmd_{cmd_name.lstrip('/')}"):
                        fn = getattr(module, f"cmd_{cmd_name.lstrip('/')}")
                    else:
                        fn = lambda args, orch: f"[plugin:{manifest.name}] {cmd_name} executed"

                    aliases = cmd_def.get("aliases", []) if isinstance(cmd_def, dict) else []
                    desc = cmd_def.get("description", f"plugin: {manifest.name}") if isinstance(cmd_def, dict) else f"plugin: {manifest.name}"

                    wrapped_fn = self._wrap_plugin_command(fn, plugin)

                    self.command_registry.register(cmd_name, wrapped_fn, description=desc, aliases=aliases)
                    plugin._registered_commands.append(cmd_name)

                    from engine.security import ALLOWED_COMMANDS
                    ALLOWED_COMMANDS.add(cmd_name)
                    for a in aliases:
                        ALLOWED_COMMANDS.add(a)

                except SecurityError as e:
                    plugin.sandbox._record_violation(f"command_registration_denied:{cmd_name}")
                except Exception as e:
                    plugin.error = f"command registration failed: {e}"

        if self.event_bus and plugin.scoped_events:
            for sub in manifest.event_subscriptions:
                event_name = sub if isinstance(sub, str) else sub.get("event", "")
                callback_name = sub.get("callback") if isinstance(sub, dict) else None

                try:
                    if not plugin.sandbox.check_event_access(event_name):
                        continue
                except SecurityError:
                    continue

                if callback_name and module and hasattr(module, callback_name):
                    callback = getattr(module, callback_name)
                else:
                    callback = lambda e, d: None

                try:
                    plugin.scoped_events.subscribe(event_name, callback)
                    plugin._registered_events.append(event_name)
                except SecurityError:
                    plugin.sandbox._record_violation(f"event_subscription_denied:{event_name}")

        if self.hook_system:
            for hook_def in manifest.hook_subscriptions:
                event_name = hook_def if isinstance(hook_def, str) else hook_def.get("event", "")
                callback_name = hook_def.get("callback") if isinstance(hook_def, dict) else None
                priority = hook_def.get("priority", 100) if isinstance(hook_def, dict) else 100

                try:
                    plugin.sandbox.check_hook_limit(len(plugin._registered_hooks))
                except SecurityError:
                    break

                if callback_name and module and hasattr(module, callback_name):
                    callback = getattr(module, callback_name)
                else:
                    callback = lambda e, d: None

                self.hook_system.register(event_name, callback, priority=priority)
                plugin._registered_hooks.append(event_name)

        self._plugins[manifest.name] = plugin
        self._load_order.append(manifest.name)

        if self.event_bus:
            self.event_bus.emit("plugin_loaded", {"plugin": manifest.name, "version": manifest.version})

        return {"status": "ok", "plugin": manifest.name, "id": plugin.id}

    def _wrap_plugin_command(self, fn, plugin):
        sandbox = plugin.sandbox

        def wrapped(args, orchestrator):
            try:
                sandbox.check_execution()
            except SecurityError as e:
                return f"[isolated] {e}"
            start = time.time()
            try:
                result = fn(args, orchestrator)
                elapsed = time.time() - start
                try:
                    sandbox.track_cpu_time(elapsed)
                except SecurityError as e:
                    return result if result else f"[isolated] {e}"
                return result
            except SecurityError:
                raise
            except Exception as e:
                return f"[plugin:{plugin.manifest.name}] error: {e}"

        wrapped.__name__ = getattr(fn, "__name__", "plugin_cmd")
        return wrapped

    def unregister_plugin(self, name):
        if name not in self._plugins:
            return {"status": "error", "error": f"plugin '{name}' not found"}

        plugin = self._plugins[name]

        if self.command_registry:
            for cmd_name in plugin._registered_commands:
                try:
                    self.command_registry.unregister(cmd_name)
                    from engine.security import ALLOWED_COMMANDS
                    ALLOWED_COMMANDS.discard(cmd_name)
                except Exception:
                    pass

        if plugin.scoped_events:
            plugin.scoped_events.unsubscribe_all()

        if self.hook_system:
            for event_name in plugin._registered_hooks:
                self.hook_system.unregister(event_name)

        plugin.sandbox.deactivate()
        del self._plugins[name]
        if name in self._load_order:
            self._load_order.remove(name)

        if self.event_bus:
            self.event_bus.emit("plugin_unloaded", {"plugin": name})

        return {"status": "ok", "unloaded": name}

    def enable_plugin(self, name):
        if name not in self._plugins:
            return {"status": "error", "error": f"plugin '{name}' not found"}
        plugin = self._plugins[name]
        plugin.state = PluginState.ENABLED
        plugin.sandbox.activate()
        if self.event_bus:
            self.event_bus.emit("plugin_enabled", {"plugin": name})
        return {"status": "ok", "plugin": name, "state": "enabled"}

    def disable_plugin(self, name):
        if name not in self._plugins:
            return {"status": "error", "error": f"plugin '{name}' not found"}
        plugin = self._plugins[name]
        plugin.state = PluginState.DISABLED
        plugin.sandbox.deactivate()
        if self.event_bus:
            self.event_bus.emit("plugin_disabled", {"plugin": name})
        return {"status": "ok", "plugin": name, "state": "disabled"}

    def isolate_plugin(self, name):
        if name not in self._plugins:
            return {"status": "error", "error": f"plugin '{name}' not found"}
        plugin = self._plugins[name]
        plugin.state = PluginState.ISOLATED
        plugin.sandbox.deactivate()
        if plugin.scoped_events:
            plugin.scoped_events.unsubscribe_all()
        if self.event_bus:
            self.event_bus.emit("plugin_isolated", {"plugin": name, "violations": plugin.sandbox.violations()})
        return {"status": "ok", "plugin": name, "state": "isolated"}

    def get_plugin(self, name):
        return self._plugins.get(name)

    def list_plugins(self):
        return [p.to_dict() for p in self._plugins.values()]

    def plugin_usage(self, name):
        plugin = self._plugins.get(name)
        if not plugin or not plugin.sandbox:
            return None
        return plugin.sandbox.usage()

    def stats(self):
        by_state = {}
        for p in self._plugins.values():
            by_state[p.state] = by_state.get(p.state, 0) + 1
        total_violations = sum(len(p.sandbox.violations()) for p in self._plugins.values() if p.sandbox)
        return {
            "total_plugins": len(self._plugins),
            "by_state": by_state,
            "load_order": list(self._load_order),
            "total_commands_injected": sum(len(p._registered_commands) for p in self._plugins.values()),
            "total_hooks_injected": sum(len(p._registered_hooks) for p in self._plugins.values()),
            "total_events_subscribed": sum(len(p._registered_events) for p in self._plugins.values()),
            "total_violations": total_violations,
        }

    def initialize(self):
        if self._init_done:
            return
        self._init_done = True
        if self.event_bus:
            self.event_bus.emit("plugin_runtime_initialized", {"plugins": len(self._plugins)})
