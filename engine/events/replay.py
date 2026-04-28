import json
import time
import os
from engine.errors import EngineRuntimeError


class ReplayEngine:
    def __init__(self, event_store=None, path=None):
        self._store = event_store
        self._path = path or (event_store.path if event_store else None)
        self._handlers = {}
        self._state_builders = {}
        self._register_default_handlers()
        self._register_default_builders()

    def _register_default_handlers(self):
        self._handlers["job_started"] = self._on_job_started
        self._handlers["job_finished"] = self._on_job_finished
        self._handlers["job_recovered"] = self._on_job_recovered
        self._handlers["command_executed"] = self._on_command_executed
        self._handlers["plugin_loaded"] = self._on_plugin_loaded
        self._handlers["plugin_unloaded"] = self._on_plugin_unloaded
        self._handlers["error_occurred"] = self._on_error
        self._handlers["model_changed"] = self._on_model_changed
        self._handlers["engine_starting"] = self._on_engine_starting
        self._handlers["engine_ready"] = self._on_engine_ready
        self._handlers["swarm_initialized"] = self._on_swarm_init
        self._handlers["worker_assigned"] = self._on_worker_assigned
        self._handlers["worker_completed"] = self._on_worker_completed
        self._handlers["worker_failed"] = self._on_worker_failed
        self._handlers["session_restoring"] = self._on_session_restore
        self._handlers["engine_shutting_down"] = self._on_shutdown
        self._handlers["plugin_runtime_initialized"] = self._on_plugin_runtime_init

    def _register_default_builders(self):
        self._state_builders["system"] = SystemStateBuilder()
        self._state_builders["jobs"] = JobStateBuilder()
        self._state_builders["plugins"] = PluginStateBuilder()
        self._state_builders["commands"] = CommandStateBuilder()
        self._state_builders["swarm"] = SwarmStateBuilder()
        self._state_builders["lifecycle"] = LifecycleStateBuilder()

    def register_handler(self, event_type, handler_fn):
        self._handlers[event_type] = handler_fn

    def register_state_builder(self, name, builder):
        self._state_builders[name] = builder

    def load_events(self, path=None, since=None, until=None, event_type=None, job_id=None):
        p = path or self._path
        if not p or not os.path.exists(p):
            return []
        events = []
        try:
            with open(p, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event_type and record.get("event") != event_type:
                        continue
                    if job_id:
                        d = record.get("data", {})
                        if d.get("job_id") != job_id and job_id not in str(d.get("task", "")):
                            continue
                    if since and record.get("timestamp", 0) < since:
                        continue
                    if until and record.get("timestamp", 0) > until:
                        continue
                    events.append(record)
        except Exception:
            pass
        return events

    def replay(self, path=None, since=None, until=None, event_type=None,
               job_id=None, builder_names=None, dry_run=False):
        events = self.load_events(path=path, since=since, until=until,
                                  event_type=event_type, job_id=job_id)
        if dry_run:
            return {
                "status": "ok",
                "events_scanned": len(events),
                "time_range": self._time_range(events),
                "event_types": self._count_types(events),
                "dry_run": True,
            }

        builders = self._resolve_builders(builder_names)
        for b in builders.values():
            b.reset()

        processed = 0
        skipped = 0
        for event in events:
            handler = self._handlers.get(event.get("event"))
            if handler:
                try:
                    handler(event, builders)
                except Exception:
                    skipped += 1
            for b in builders.values():
                b.apply(event)
            processed += 1

        states = {name: b.build() for name, b in builders.items()}
        return {
            "status": "ok",
            "events_scanned": len(events),
            "events_processed": processed,
            "events_skipped": skipped,
            "time_range": self._time_range(events),
            "states": states,
        }

    def replay_job(self, job_id, path=None):
        events = self.load_events(path=path, job_id=job_id)
        job_events = []
        for e in events:
            d = e.get("data", {})
            if d.get("job_id") == job_id or job_id in str(d.get("task", "")):
                job_events.append(e)
        return {
            "status": "ok",
            "job_id": job_id,
            "events": job_events,
            "count": len(job_events),
        }

    def replay_commands(self, path=None, since=None, until=None):
        events = self.load_events(path=path, since=since, until=until,
                                  event_type="command_executed")
        return {
            "status": "ok",
            "commands": events,
            "count": len(events),
        }

    def replay_plugin_flow(self, plugin_name, path=None, since=None, until=None):
        events = self.load_events(path=path, since=since, until=until)
        plugin_events = []
        for e in events:
            d = e.get("data", {})
            if d.get("plugin") == plugin_name:
                plugin_events.append(e)
        return {
            "status": "ok",
            "plugin": plugin_name,
            "events": plugin_events,
            "count": len(plugin_events),
        }

    def rebuild_state(self, path=None, since=None, builder_names=None):
        return self.replay(path=path, since=since, builder_names=builder_names)

    def diff_states(self, state1, state2):
        diffs = {}
        all_keys = set(state1.keys()) | set(state2.keys())
        for key in all_keys:
            v1 = state1.get(key)
            v2 = state2.get(key)
            if v1 != v2:
                diffs[key] = {"before": v1, "after": v2}
        return diffs

    def _resolve_builders(self, names=None):
        if not names:
            return dict(self._state_builders)
        return {n: self._state_builders[n] for n in names if n in self._state_builders}

    @staticmethod
    def _time_range(events):
        if not events:
            return {"start": None, "end": None}
        timestamps = [e.get("timestamp", 0) for e in events]
        return {"start": min(timestamps), "end": max(timestamps)}

    @staticmethod
    def _count_types(events):
        counts = {}
        for e in events:
            name = e.get("event", "unknown")
            counts[name] = counts.get(name, 0) + 1
        return counts

    # --- Default event handlers ---

    @staticmethod
    def _on_job_started(event, builders):
        if "jobs" in builders:
            builders["jobs"]._started += 1

    @staticmethod
    def _on_job_finished(event, builders):
        if "jobs" in builders:
            d = event.get("data", {})
            if d.get("status") == "completed":
                builders["jobs"]._completed += 1
            else:
                builders["jobs"]._failed += 1

    @staticmethod
    def _on_job_recovered(event, builders):
        if "jobs" in builders:
            builders["jobs"]._recovered += 1

    @staticmethod
    def _on_command_executed(event, builders):
        if "commands" in builders:
            d = event.get("data", {})
            builders["commands"]._commands.append({
                "command": d.get("command"),
                "status": d.get("status"),
                "timestamp": event.get("timestamp"),
            })

    @staticmethod
    def _on_plugin_loaded(event, builders):
        if "plugins" in builders:
            d = event.get("data", {})
            builders["plugins"]._loaded.append(d.get("plugin"))

    @staticmethod
    def _on_plugin_unloaded(event, builders):
        if "plugins" in builders:
            d = event.get("data", {})
            name = d.get("plugin")
            if name in builders["plugins"]._loaded:
                builders["plugins"]._loaded.remove(name)
            builders["plugins"]._unloaded.append(name)

    @staticmethod
    def _on_error(event, builders):
        if "system" in builders:
            d = event.get("data", {})
            builders["system"]._errors.append(d.get("type", "unknown"))

    @staticmethod
    def _on_model_changed(event, builders):
        if "system" in builders:
            d = event.get("data", {})
            builders["system"]._model = d.get("model", builders["system"]._model)

    @staticmethod
    def _on_engine_starting(event, builders):
        if "lifecycle" in builders:
            builders["lifecycle"]._transitions.append({
                "state": "starting",
                "timestamp": event.get("timestamp"),
            })

    @staticmethod
    def _on_engine_ready(event, builders):
        if "lifecycle" in builders:
            d = event.get("data", {})
            builders["lifecycle"]._startup_ms = d.get("startup_ms", 0)
            builders["lifecycle"]._transitions.append({
                "state": "ready",
                "timestamp": event.get("timestamp"),
            })

    @staticmethod
    def _on_swarm_init(event, builders):
        if "swarm" in builders:
            d = event.get("data", {})
            builders["swarm"]._initial_workers = d.get("workers", 0)

    @staticmethod
    def _on_worker_assigned(event, builders):
        if "swarm" in builders:
            builders["swarm"]._tasks_assigned += 1

    @staticmethod
    def _on_worker_completed(event, builders):
        if "swarm" in builders:
            builders["swarm"]._tasks_completed += 1

    @staticmethod
    def _on_worker_failed(event, builders):
        if "swarm" in builders:
            builders["swarm"]._tasks_failed += 1

    @staticmethod
    def _on_session_restore(event, builders):
        if "system" in builders:
            builders["system"]._session_restored = True

    @staticmethod
    def _on_shutdown(event, builders):
        if "lifecycle" in builders:
            builders["lifecycle"]._transitions.append({
                "state": "stopped",
                "timestamp": event.get("timestamp"),
            })

    @staticmethod
    def _on_plugin_runtime_init(event, builders):
        if "plugins" in builders:
            d = event.get("data", {})
            builders["plugins"]._runtime_initialized = True


class SystemStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._model = "qwen"
        self._errors = []
        self._session_restored = False
        self._total_events = 0
        self._event_counts = {}

    def apply(self, event):
        self._total_events += 1
        name = event.get("event", "")
        self._event_counts[name] = self._event_counts.get(name, 0) + 1

    def build(self):
        return {
            "model": self._model,
            "errors": list(self._errors),
            "error_count": len(self._errors),
            "session_restored": self._session_restored,
            "total_events": self._total_events,
            "event_counts": dict(self._event_counts),
        }


class JobStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._started = 0
        self._completed = 0
        self._failed = 0
        self._recovered = 0
        self._jobs = []

    def apply(self, event):
        name = event.get("event", "")
        d = event.get("data", {})
        if name == "job_started":
            self._jobs.append({
                "job_id": d.get("job_id", "unknown"),
                "task": d.get("task", "")[:80],
                "model": d.get("model"),
                "status": "running",
                "started_at": event.get("timestamp"),
            })
        elif name == "job_finished":
            jid = d.get("job_id")
            for j in self._jobs:
                if j.get("job_id") == jid or j.get("task", "").startswith(str(jid)):
                    j["status"] = d.get("status", "completed")
                    j["finished_at"] = event.get("timestamp")
                    break
        elif name == "job_recovered":
            jid = d.get("job_id")
            self._jobs.append({
                "job_id": jid,
                "status": "recovered",
                "previous_status": d.get("previous_status"),
                "timestamp": event.get("timestamp"),
            })

    def build(self):
        return {
            "started": self._started,
            "completed": self._completed,
            "failed": self._failed,
            "recovered": self._recovered,
            "jobs": list(self._jobs),
            "total": len(self._jobs),
        }


class PluginStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._loaded = []
        self._unloaded = []
        self._runtime_initialized = False

    def apply(self, event):
        pass

    def build(self):
        return {
            "loaded": list(self._loaded),
            "unloaded": list(self._unloaded),
            "active": list(self._loaded),
            "runtime_initialized": self._runtime_initialized,
        }


class CommandStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._commands = []

    def apply(self, event):
        pass

    def build(self):
        return {
            "executed": list(self._commands),
            "total": len(self._commands),
        }


class SwarmStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._initial_workers = 0
        self._tasks_assigned = 0
        self._tasks_completed = 0
        self._tasks_failed = 0

    def apply(self, event):
        pass

    def build(self):
        return {
            "initial_workers": self._initial_workers,
            "tasks_assigned": self._tasks_assigned,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
        }


class LifecycleStateBuilder:
    def __init__(self):
        self.reset()

    def reset(self):
        self._transitions = []
        self._startup_ms = 0

    def apply(self, event):
        pass

    def build(self):
        return {
            "transitions": list(self._transitions),
            "startup_ms": self._startup_ms,
        }
