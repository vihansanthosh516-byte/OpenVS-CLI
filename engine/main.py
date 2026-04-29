#!/usr/bin/env python3
import sys
import os
import json

_engine_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_engine_dir)
sys.path.insert(0, _project_dir)
sys.path.insert(0, _engine_dir)

from engine.bridge import Bridge
from engine.commands.registry import registry
from engine.commands.builtin import register_default_commands
from engine.orchestrator import Orchestrator
from engine.events import bus, ReplayEngine
from engine.events.store import EventStore
from engine.hooks import HookSystem
from engine.security import validate_command, sanitize_input
from engine.errors import OpenVSError, BridgeError, SecurityError
from engine.plugins.runtime import PluginRuntime, PluginManifest
from engine.plugins.schema import validate_plugin_manifest
from engine.lifecycle import LifecycleManager, LifecycleState
from engine.sandbox import sandbox
from engine.observability import ObservabilitySystem
from engine.distributed.core import SwarmFoundation
from engine.distributed.coordinator import SwarmCoordinator, SelectionStrategy
from engine.distributed.network import NetworkLayer

VERSION = "0.5.0"


def main():
    bridge = Bridge(sys.stdin, sys.stdout)

    config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
    store_path = os.path.join(config_dir, "jobs.jsonl")
    obs_store_dir = os.path.join(config_dir, "diagnostics")
    event_store_path = os.path.join(config_dir, "events.jsonl")

    event_store = EventStore(path=event_store_path, event_bus=bus)
    bus.on("*", lambda e, d: event_store.append(e, d))

    hooks = HookSystem(event_bus=bus)
    observability = ObservabilitySystem(event_bus=bus, store_dir=obs_store_dir)
    orchestrator = Orchestrator(events=bus, hooks=hooks, store_path=store_path)

    register_default_commands()

    swarm = SwarmFoundation(event_bus=bus)
    swarm.initialize()

    coordinator = SwarmCoordinator(registry=swarm.registry, event_bus=bus, selection_strategy=SelectionStrategy.LEAST_LOADED)

    network = NetworkLayer(event_bus=bus)
    network.initialize(node_id="coordinator-0")
    for wid, worker in swarm.registry._workers.items():
        network.register_worker(wid, capabilities=worker.capabilities, host=worker.host)

    replay_engine = ReplayEngine(event_store=event_store, path=event_store_path)

    plugin_runtime = PluginRuntime(
        event_bus=bus,
        hook_system=hooks,
        command_registry=registry,
        sandbox=sandbox,
    )

    orchestrator.attach_plugin_runtime(plugin_runtime)
    orchestrator.attach_observability(observability)
    orchestrator.attach_sandbox(sandbox)
    orchestrator.attach_event_store(event_store)
    orchestrator.attach_swarm(swarm)
    orchestrator.attach_coordinator(coordinator)
    orchestrator.attach_network(network)
    orchestrator.attach_replay(replay_engine)

    lifecycle = LifecycleManager(
        event_bus=bus,
        hook_system=hooks,
        plugin_runtime=plugin_runtime,
        command_registry=registry,
        orchestrator=orchestrator,
    )

    ctx = EngineContext(
        bridge=bridge,
        orchestrator=orchestrator,
        plugin_runtime=plugin_runtime,
        lifecycle=lifecycle,
        observability=observability,
        sandbox=sandbox,
        event_store=event_store,
        swarm=swarm,
        coordinator=coordinator,
        network=network,
        replay_engine=replay_engine,
    )

    recovered = orchestrator.pipeline.recover()
    if recovered:
        bus.emit("jobs_recovered", {"count": len(recovered)})
        bridge.log(f"recovered {len(recovered)} incomplete jobs")

    compat = event_store.validate_backwards_compat()
    if compat["incompatible"]:
        bridge.log(f"warning: {len(compat['incompatible'])} incompatible events detected")

    lifecycle.engine_start()

    bridge.log(f"engine starting v{VERSION} (lifecycle: {lifecycle.state}, workers: {swarm.registry.stats()['total']})")

    request = None
    while True:
        try:
            request = bridge.read_request()
            if request is None:
                break

            response = dispatch(request, ctx)
            bridge.write_response(response, request)

        except KeyboardInterrupt:
            break
        except BridgeError as e:
            bridge.log(f"bridge error: {e}")
            bridge.write_response({"status": "error", "error": e.to_dict()}, request)
        except OpenVSError as e:
            bridge.log(f"engine error: {e}")
            bridge.write_response({"status": "error", "error": e.to_dict()}, request)
        except Exception as e:
            bridge.log(f"error: {e}")
            bridge.write_response({"status": "error", "error": str(e)}, request)

    event_store.flush()
    lifecycle.engine_shutdown(reason="loop_exit")
    bridge.log("engine shutting down")


class EngineContext:
    def __init__(self, bridge, orchestrator, plugin_runtime, lifecycle,
                 observability, sandbox, event_store, swarm,
                 coordinator, network, replay_engine):
        self.bridge = bridge
        self.orchestrator = orchestrator
        self.plugins = plugin_runtime
        self.lifecycle = lifecycle
        self.observability = observability
        self.sandbox = sandbox
        self.event_store = event_store
        self.swarm = swarm
        self.coordinator = coordinator
        self.network = network
        self.replay_engine = replay_engine


def dispatch(request, ctx):
    payload = request.get("payload", request)
    req_type = payload.get("type", request.get("type", ""))

    if req_type == "init":
        return handle_init(payload, ctx)

    if req_type == "shutdown":
        return handle_shutdown(ctx)

    if req_type == "command":
        return handle_command(payload, ctx)

    if req_type == "prompt":
        return handle_prompt(payload, ctx)

    if req_type == "stream":
        return handle_stream(payload, ctx)

    if req_type == "plugin":
        return handle_plugin(payload, ctx)

    if req_type == "diagnostics":
        return handle_diagnostics(payload, ctx)

    if req_type == "events":
        return handle_events(payload, ctx)

    if req_type == "swarm":
        return handle_swarm(payload, ctx)

    if req_type == "replay":
        return handle_replay(payload, ctx)

    if req_type == "coordinator":
        return handle_coordinator(payload, ctx)

    if req_type == "network":
        return handle_network(payload, ctx)

    if req_type == "config":
        return handle_config(payload, ctx)

    return {"status": "error", "error": f"unknown request type: {req_type}"}


def handle_init(request, ctx):
    config = request.get("config", {})
    model = config.get("default_model", "qwen")
    bus.emit("command_executed", {"command": "init", "model": model})

    session_data = config.get("session")
    if session_data:
        ctx.lifecycle.session_restore(session_data)

    return {
        "status": "ok",
        "version": VERSION,
        "model": model,
        "protocol_version": 1,
        "lifecycle": ctx.lifecycle.state,
        "plugins": ctx.plugins.stats()["total_plugins"],
        "workers": ctx.swarm.registry.stats()["total"],
        "schema_version": bus.schema_version,
    }


def handle_shutdown(ctx):
    ctx.event_store.flush()
    ctx.lifecycle.engine_shutdown(reason="user_request")
    return {"status": "ok", "message": "shutting down"}


def handle_command(request, ctx):
    command = request.get("command", "")
    try:
        validate_command(command)
    except SecurityError as e:
        bus.emit("error_occurred", {"type": "security", "command": command})
        return {"status": "error", "output": str(e)}

    result = registry.execute(command, ctx.orchestrator)
    bus.emit("command_executed", {"command": command, "status": result.get("status")})
    return result


def handle_prompt(request, ctx):
    text = request.get("text", "")
    try:
        text = sanitize_input(text)
    except SecurityError as e:
        bus.emit("error_occurred", {"type": "security", "input": text[:50]})
        return {"status": "error", "error": str(e)}

    if not text.strip():
        return {"status": "error", "error": "empty prompt"}

    result = ctx.orchestrator.execute(text)
    return {
        "status": "ok",
        "output": result.get("output", ""),
        "trace": result.get("trace", {}),
    }


def handle_stream(request, ctx):
    text = request.get("text", "")
    try:
        text = sanitize_input(text)
    except SecurityError as e:
        return {"status": "error", "error": str(e)}

    if not text.strip():
        return {"status": "error", "error": "empty prompt"}

    if request.get("live_events"):
        ctx.observability.start_stream(ctx.bridge, event_filter=request.get("event_filter"))

    result = ctx.orchestrator.execute_streaming(text, bridge=ctx.bridge)
    return {
        "status": "ok",
        "output": result.get("output", ""),
        "streamed": result.get("streamed", False),
        "trace": result.get("trace", {}),
    }


def handle_plugin(request, ctx):
    action = request.get("action", "")

    if action == "register":
        name = request.get("name", "")
        if not name:
            return {"status": "error", "error": "plugin name required"}

        manifest_dict = {
            "name": name,
            "version": request.get("version", "0.1.0"),
            "description": request.get("description", ""),
            "commands": request.get("commands", []),
            "events": request.get("events", []),
            "hooks": request.get("hooks", []),
            "permissions": request.get("permissions", []),
            "engine_version": request.get("engine_version"),
            "resource_limits": request.get("resource_limits"),
            "allowed_events": request.get("allowed_events"),
            "allowed_commands": request.get("allowed_commands"),
        }

        valid, errors = validate_plugin_manifest(manifest_dict)
        if not valid:
            error_msgs = [e["message"] for e in errors if e["level"] == "error"]
            bus.emit("error_occurred", {"type": "plugin_validation", "plugin": name})
            return {"status": "error", "error": f"validation failed: {'; '.join(error_msgs)}"}

        manifest = PluginManifest(
            name=manifest_dict["name"],
            version=manifest_dict["version"],
            description=manifest_dict["description"],
            commands=manifest_dict["commands"],
            event_subscriptions=manifest_dict["events"],
            hook_subscriptions=manifest_dict["hooks"],
            permissions=manifest_dict["permissions"],
            resource_limits=manifest_dict.get("resource_limits"),
            allowed_events=manifest_dict.get("allowed_events"),
            allowed_commands=manifest_dict.get("allowed_commands"),
        )
        return ctx.plugins.register_plugin(manifest)

    if action == "validate":
        manifest_dict = request.get("manifest", {})
        valid, errors = validate_plugin_manifest(manifest_dict)
        return {"status": "ok", "valid": valid, "errors": errors}

    if action == "unregister":
        return ctx.plugins.unregister_plugin(request.get("name", ""))

    if action == "enable":
        return ctx.plugins.enable_plugin(request.get("name", ""))

    if action == "disable":
        return ctx.plugins.disable_plugin(request.get("name", ""))

    if action == "isolate":
        return ctx.plugins.isolate_plugin(request.get("name", ""))

    if action == "usage":
        usage = ctx.plugins.plugin_usage(request.get("name", ""))
        if usage:
            return {"status": "ok", "usage": usage}
        return {"status": "error", "error": "plugin not found"}

    if action == "list":
        return {"status": "ok", "plugins": ctx.plugins.list_plugins()}

    if action == "stats":
        return {"status": "ok", "stats": ctx.plugins.stats()}

    return {"status": "error", "error": f"unknown plugin action: {action}"}


def handle_diagnostics(request, ctx):
    action = request.get("action", "bundle")

    if action == "bundle":
        export_path = os.path.join(
            os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs")),
            "diagnostics",
            f"bundle_{int(__import__('time').time())}.json",
        )
        bundle = ctx.observability.export_bundle(path=export_path)
        bundle["lifecycle"] = ctx.lifecycle.status()
        bundle["lifecycle_history"] = ctx.lifecycle.history()
        bundle["sandbox"] = ctx.sandbox.stats()
        bundle["plugins"] = ctx.plugins.stats()
        bundle["event_store"] = ctx.event_store.stats()
        bundle["swarm"] = ctx.swarm.stats()
        bundle["coordinator"] = ctx.coordinator.status()
        bundle["network"] = ctx.network.stats()
        bundle["schema_version"] = bus.schema_version
        return {"status": "ok", "bundle": bundle, "export_path": export_path}

    if action == "trace":
        job_id = request.get("job_id", "")
        trace = ctx.observability.trace(job_id)
        return {"status": "ok", "trace": trace}

    if action == "timeline":
        event_name = request.get("event_name")
        limit = request.get("limit", 50)
        timeline = ctx.observability.timeline(event_name=event_name, limit=limit)
        return {"status": "ok", "timeline": timeline}

    if action == "metrics":
        return {"status": "ok", "metrics": ctx.observability.metrics()}

    if action == "stream":
        event_filter = request.get("event_filter")
        sub_id = ctx.observability.start_stream(ctx.bridge, event_filter=event_filter)
        return {"status": "ok", "streaming": True, "subscriber_id": sub_id}

    if action == "stream_stop":
        ctx.observability.stop_stream()
        return {"status": "ok", "streaming": False}

    return {"status": "error", "error": f"unknown diagnostics action: {action}"}


def handle_events(request, ctx):
    action = request.get("action", "query")

    if action == "query":
        results = ctx.event_store.query(
            event_type=request.get("event_type"),
            job_id=request.get("job_id"),
            since=request.get("since"),
            until=request.get("until"),
            limit=request.get("limit", 100),
            schema_version=request.get("schema_version"),
            schema_id=request.get("schema_id"),
        )
        return {"status": "ok", "events": results, "count": len(results)}

    if action == "replay":
        events = ctx.event_store.replay(
            event_type=request.get("event_type"),
            since=request.get("since"),
            limit=request.get("limit", 5000),
        )
        return {"status": "ok", "events": events, "count": len(events)}

    if action == "reconstruct":
        state = ctx.event_store.replay_reconstruct(since=request.get("since"))
        return {"status": "ok", "reconstructed_state": state}

    if action == "stats":
        stats = ctx.event_store.stats()
        stats["version_distribution"] = ctx.event_store.version_stats()
        return {"status": "ok", "stats": stats}

    if action == "compat_check":
        result = ctx.event_store.validate_backwards_compat()
        return {"status": "ok", "compat": result}

    return {"status": "error", "error": f"unknown events action: {action}"}


def handle_swarm(request, ctx):
    action = request.get("action", "status")

    if action == "status":
        return {"status": "ok", "swarm": ctx.swarm.stats()}

    if action == "workers":
        return {"status": "ok", "workers": ctx.swarm.registry.list_all()}

    if action == "heartbeat":
        stale = ctx.swarm.heartbeat.check()
        return {"status": "ok", "stale_workers": stale}

    if action == "submit":
        task_data = request.get("task", {})
        priority = request.get("priority", 0)
        capabilities = request.get("required_capabilities")
        result = ctx.coordinator.submit(task_data, priority=priority, required_capabilities=capabilities)
        return {"status": "ok", "assignment": result}

    if action == "complete":
        task_id = request.get("task_id", "")
        result_data = request.get("result", {})
        return ctx.coordinator.complete(task_id, result_data)

    if action == "fail":
        task_id = request.get("task_id", "")
        error = request.get("error", "unknown")
        return ctx.coordinator.fail(task_id, error)

    return {"status": "error", "error": f"unknown swarm action: {action}"}


def handle_replay(request, ctx):
    action = request.get("action", "full")

    if action == "full":
        result = ctx.replay_engine.replay(
            since=request.get("since"),
            builder_names=request.get("builders"),
            dry_run=request.get("dry_run", False),
        )
        return {"status": "ok", "replay": result}

    if action == "job":
        job_id = request.get("job_id", "")
        return ctx.replay_engine.replay_job(job_id)

    if action == "commands":
        return ctx.replay_engine.replay_commands(
            since=request.get("since"),
            until=request.get("until"),
        )

    if action == "plugin":
        plugin_name = request.get("plugin", "")
        return ctx.replay_engine.replay_plugin_flow(
            plugin_name,
            since=request.get("since"),
            until=request.get("until"),
        )

    if action == "diff":
        since1 = request.get("since1")
        since2 = request.get("since2")
        state1 = ctx.replay_engine.rebuild_state(since=since1).get("states", {})
        state2 = ctx.replay_engine.rebuild_state(since=since2).get("states", {})
        diffs = {}
        for key in set(list(state1.keys()) + list(state2.keys())):
            s1 = state1.get(key, {})
            s2 = state2.get(key, {})
            if s1 != s2:
                diffs[key] = {"before": s1, "after": s2}
        return {"status": "ok", "diffs": diffs}

    if action == "dry_run":
        result = ctx.replay_engine.replay(
            since=request.get("since"),
            dry_run=True,
        )
        return {"status": "ok", "replay": result}

    return {"status": "error", "error": f"unknown replay action: {action}"}


def handle_coordinator(request, ctx):
    action = request.get("action", "status")

    if action == "status":
        return {"status": "ok", "coordinator": ctx.coordinator.status()}

    if action == "assignments":
        return {"status": "ok", "assignments": ctx.coordinator.list_assignments()}

    if action == "dead_worker":
        worker_id = request.get("worker_id", "")
        ctx.coordinator.handle_dead_worker(worker_id)
        return {"status": "ok", "action": "dead_worker_handled"}

    if action == "rebalance":
        result = ctx.coordinator.rebalance()
        return {"status": "ok", "rebalance": result}

    return {"status": "error", "error": f"unknown coordinator action: {action}"}


def handle_network(request, ctx):
    action = request.get("action", "stats")

    if action == "stats":
        return {"status": "ok", "network": ctx.network.stats()}

    if action == "register_worker":
        worker_id = request.get("worker_id", "")
        capabilities = request.get("capabilities", ["execute"])
        host = request.get("host", "localhost")
        result = ctx.network.register_worker(worker_id, capabilities=capabilities, host=host)
        return {"status": "ok", "handshake": result}

    if action == "submit_task":
        task_id = request.get("task_id", "")
        task_data = request.get("task_data", {})
        target = request.get("target_worker")
        result = ctx.network.submit_task(task_id, task_data, target_worker=target)
        return {"status": "ok", "result": result.to_dict() if hasattr(result, 'to_dict') else str(result)}

    if action == "nodes":
        return {"status": "ok", "nodes": ctx.network.node_registry.list_all()}

    return {"status": "error", "error": f"unknown network action: {action}"}


def handle_config(request, ctx):
    action = request.get("action", "show")
    config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
    config_path = os.path.join(config_dir, "config.json")

    if action == "show":
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            masked = dict(cfg)
            if "api_keys" in masked and isinstance(masked["api_keys"], dict):
                masked["api_keys"] = {k: ("*" * 8 + v[-4:]) if isinstance(v, str) and len(v) > 4 else "****" for k, v in masked["api_keys"].items() if v}
            return {"status": "ok", "config": masked}
        except Exception:
            return {"status": "ok", "config": {}}

    if action == "set-key":
        provider = request.get("provider", "")
        key = request.get("key", "")
        if not provider or not key:
            return {"status": "error", "error": "usage: set-key <provider> <key>"}
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    cfg = json.load(f)
            else:
                cfg = {}
            if "api_keys" not in cfg:
                cfg["api_keys"] = {}
            cfg["api_keys"][provider] = key
            if not cfg.get("provider"):
                cfg["provider"] = provider
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
            from engine import model_client
            model_client.PROVIDER_KEYS = model_client._load_api_keys()
            model_client_reload = model_client.ModelClient()
            ctx.orchestrator.model_client = model_client_reload
            bus.emit("config_updated", {"action": "set-key", "provider": provider})
            return {"status": "ok", "message": f"API key set for {provider}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    if action == "set":
        key = request.get("key", "")
        value = request.get("value", "")
        if not key:
            return {"status": "error", "error": "key required"}
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    cfg = json.load(f)
            else:
                cfg = {}
            cfg[key] = value
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
            return {"status": "ok", "message": f"config '{key}' updated"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    return {"status": "error", "error": f"unknown config action: {action}"}


if __name__ == "__main__":
    main()
