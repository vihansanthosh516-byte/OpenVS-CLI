import time
from engine.errors import EngineRuntimeError


class LifecycleState:
    UNINITIALIZED = "uninitialized"
    STARTING = "starting"
    PLUGINS_LOADING = "plugins_loading"
    EVENTS_ACTIVE = "events_active"
    HOOKS_READY = "hooks_ready"
    COMMANDS_READY = "commands_ready"
    EXECUTOR_READY = "executor_ready"
    READY = "ready"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class LifecycleManager:
    def __init__(self, event_bus=None, hook_system=None, plugin_runtime=None,
                 command_registry=None, orchestrator=None):
        self.state = LifecycleState.UNINITIALIZED
        self.events = event_bus
        self.hooks = hook_system
        self.plugins = plugin_runtime
        self.registry = command_registry
        self.orchestrator = orchestrator
        self._transitions = []
        self._start_time = None
        self._stop_time = None

    def engine_start(self, config=None):
        self._transition(LifecycleState.STARTING)
        self._emit("engine_starting", {"config": config or {}})

        self._transition(LifecycleState.PLUGINS_LOADING)
        self._emit("plugins_loading", {})
        if self.plugins:
            self.plugins.initialize()
            self._emit("plugins_loaded", {"count": self.plugins.stats()["total_plugins"]})

        self._transition(LifecycleState.EVENTS_ACTIVE)
        self._emit("events_active", {})
        if self.events:
            self._emit("system_event_bus_ready", {
                "listeners": self.events.listeners(),
            })

        self._transition(LifecycleState.HOOKS_READY)
        self._emit("hooks_ready", {})
        if self.hooks:
            self._emit("system_hooks_ready", {
                "stats": self.hooks.stats(),
            })

        self._transition(LifecycleState.COMMANDS_READY)
        self._emit("commands_ready", {})
        if self.registry:
            self._emit("system_commands_ready", {
                "commands": len(self.registry.list_commands()),
            })

        self._transition(LifecycleState.EXECUTOR_READY)
        self._emit("executor_ready", {})

        self._transition(LifecycleState.READY)
        self._start_time = time.time()
        startup_ms = 0
        if self._transitions:
            startup_ms = int((time.time() - self._transitions[0]["at"]) * 1000)
        self._emit("engine_ready", {
            "state": self.state,
            "startup_ms": startup_ms,
        })

    def engine_shutdown(self, reason="user_request"):
        self._transition(LifecycleState.SHUTTING_DOWN)
        self._emit("engine_shutting_down", {"reason": reason})

        if self.orchestrator and hasattr(self.orchestrator, "executor"):
            try:
                self.orchestrator.executor.pool.shutdown(wait=False)
            except Exception:
                pass

        self._transition(LifecycleState.STOPPED)
        self._stop_time = time.time()
        uptime = round(self._stop_time - self._start_time, 2) if self._start_time else 0
        self._emit("engine_stopped", {"reason": reason, "uptime_s": uptime})

    def session_restore(self, session_data):
        self._emit("session_restoring", {
            "keys": list(session_data.keys()) if session_data else []
        })

        if session_data and self.orchestrator:
            if "model" in session_data:
                self.orchestrator.model = session_data["model"]
            if "config" in session_data:
                self.orchestrator.config = session_data["config"]

        self._emit("session_restored", {"restored": bool(session_data)})

    def job_resume(self, job_id=None):
        self._emit("job_resuming", {"job_id": job_id})

        if self.orchestrator and hasattr(self.orchestrator, "pipeline"):
            if job_id:
                records = self.orchestrator.pipeline.replay(job_id=job_id)
            else:
                records = self.orchestrator.pipeline.load_history(limit=1)

            resumed = len(records) > 0
            self._emit("job_resumed", {
                "job_id": job_id,
                "found": resumed,
                "records": len(records),
            })
            return resumed

        self._emit("job_resumed", {"job_id": job_id, "found": False})
        return False

    def _transition(self, new_state):
        old_state = self.state
        self.state = new_state
        record = {
            "from": old_state,
            "to": new_state,
            "at": time.time(),
        }
        self._transitions.append(record)

    def _emit(self, event_name, data):
        if self.events:
            self.events.emit(event_name, data)

    def status(self):
        return {
            "state": self.state,
            "uptime_s": round(time.time() - self._start_time, 2) if self._start_time else 0,
            "transitions": len(self._transitions),
            "started": self._start_time is not None,
        }

    def history(self):
        return [
            {"from": t["from"], "to": t["to"], "at": t["at"]}
            for t in self._transitions
        ]
