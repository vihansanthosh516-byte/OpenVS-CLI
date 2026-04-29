import json
import os
from engine.commands.registry import registry
from engine import model_client as mc


def cmd_help(args, orchestrator):
    return """COMMANDS
 ────────────────────────────
 Model Control:
   /model <name>       Switch active model
   /models             List available models + key status

 Config:
   /config             Show current config
   /config set-key <provider> <key>
                       Set API key for provider (nvidia/openai/local)

 Jobs:
   /jobs               Recent jobs
   /jobs history       Persisted job history

 System:
   /status             Engine status
   /events             Event store operations
   /diagnostics        Observability & traces

 Execution:
   /swarm              Swarm/worker status
   /coordinator        Task coordinator
   /network            Network layer
   /replay             Event replay engine
   /plugin             Plugin management
   /agents             Agent roles

 Exit:
   /exit               Quit session"""


def cmd_status(args, orchestrator):
    status = orchestrator.status()
    model_info = mc.MODELS.get(orchestrator.model, {})
    provider = model_info.get("provider", "?")
    key_ok = bool(mc.PROVIDER_KEYS.get(provider, ""))
    client_state = "connected" if key_ok else "no API key"

    lines = [
        f"Engine: v{status['version']}",
        f"Model: {status['model']} ({model_info.get('model_id', '?')})",
        f"Provider: {provider} ({'key set' if key_ok else 'NO KEY'})",
        f"Client: {client_state}",
        f"Mode: {status['mode']}",
        f"Jobs: {status['jobs_completed']} completed, {status['jobs_failed']} failed, {status['jobs_total']} total",
        f"Uptime: {status['uptime']}",
    ]
    return "\n".join(lines)


def cmd_model(args, orchestrator):
    if not args:
        return cmd_models([], orchestrator)

    model = args[0].lower()
    if model in mc.MODELS:
        orchestrator.model = model
        info = mc.MODELS[model]
        provider = info.get("provider", "?")
        key_ok = bool(mc.PROVIDER_KEYS.get(provider, ""))
        return f"Model switched\n  Active: {model} ({info.get('model_id', '?')})\n  Provider: {provider}\n  API Key: {'configured' if key_ok else 'MISSING — run /config set-key " + provider + " <key>'}"
    return f"Unknown model: {model}\nType /models to list available models"


def cmd_models(args, orchestrator):
    current = orchestrator.model
    lines = ["Available Models:", ""]
    for name, info in mc.MODELS.items():
        provider = info.get("provider", "?")
        key_ok = bool(mc.PROVIDER_KEYS.get(provider, ""))
        marker = " <--" if name == current else ""
        key_icon = "+" if key_ok else "NO KEY"
        lines.append(f"  {name:16s} {info.get('model_id', '?'):40s} [{provider}] [{key_icon}]{marker}")
    lines.append("")
    lines.append(f"Active: {current}")
    lines.append("Use /model <name> to switch")
    return "\n".join(lines)


def cmd_jobs(args, orchestrator):
    if args and args[0] == "history":
        records = orchestrator.pipeline.load_history(limit=20)
        if not records:
            return "No job history."
        lines = ["Job History (persisted):"]
        for r in records:
            lines.append(f" {r.get('id', '?'):12s} {r.get('status', '?'):10s} {r.get('model', '?'):10s} {r.get('task', '?')[:50]}")
        return "\n".join(lines)

    jobs = orchestrator.pipeline.recent_jobs(limit=10)
    if not jobs:
        return "No jobs yet. Use /jobs history for persisted records."
    lines = ["Recent Jobs:"]
    for j in jobs:
        lines.append(f" {j['id']} {j['status']:10s} {j['model']:10s} {j['task'][:50]}")
    return "\n".join(lines)


def cmd_config(args, orchestrator):
    if args and args[0] == "set-key":
        if len(args) < 3:
            return "Usage: /config set-key <provider> <key>\nProviders: nvidia, openai, local"
        provider = args[1].lower()
        key = args[2]
        _config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
        config_path = os.path.join(_config_dir, "config.json")
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
            mc.PROVIDER_KEYS = mc._load_api_keys()
            orchestrator.model_client.available = orchestrator.model_client._check_connectivity()
            masked = "*" * 8 + key[-4:] if len(key) > 4 else "****"
            return f"API key set for {provider}: {masked}\nModel client reloaded."
        except Exception as e:
            return f"Error setting key: {e}"

    if args and args[0] == "set":
        if len(args) < 3:
            return "Usage: /config set <key> <value>"
        key = args[1]
        value = args[2]
        _config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
        config_path = os.path.join(_config_dir, "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    cfg = json.load(f)
            else:
                cfg = {}
            cfg[key] = value
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
            return f"Config updated: {key} = {value}"
        except Exception as e:
            return f"Error: {e}"

    _config_dir = os.getenv("OPENVS_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".openvs"))
    config_path = os.path.join(_config_dir, "config.json")
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        masked = dict(cfg)
        if "api_keys" in masked and isinstance(masked["api_keys"], dict):
            masked["api_keys"] = {
                k: ("*" * 8 + v[-4:]) if isinstance(v, str) and len(v) > 4 else "****"
                for k, v in masked["api_keys"].items() if v
            }
        lines = ["Config:", ""]
        for k, v in sorted(masked.items()):
            lines.append(f"  {k:20s} = {v}")
        return "\n".join(lines)
    except Exception:
        return "No config file found. Use /config set-key <provider> <key> to get started."


def cmd_agents(args, orchestrator):
    return """Agent Roles:
 planner — decomposes tasks into steps
 coder — writes and modifies code
 critic — reviews and validates output"""


def cmd_events(args, orchestrator):
    es = getattr(orchestrator, "_event_store", None)
    if args and args[0] == "query" and es:
        event_type = args[1] if len(args) > 1 else None
        results = es.query(event_type=event_type, limit=15)
        if not results:
            return "No stored events found."
        lines = ["Stored Events:", ""]
        for e in results:
            v = e.get("version", "?")
            sid = e.get("schema_id", "?")[:8]
            lines.append(f" {e['event']:24s} v{v} sid={sid} seq={e.get('seq', '?')} @ {e.get('timestamp', 0):.0f}")
        return "\n".join(lines)

    if args and args[0] == "replay" and es:
        state = es.replay_reconstruct()
        lines = ["Reconstructed State:", ""]
        for k, v in state.items():
            if isinstance(v, list):
                lines.append(f" {k}: {len(v)} items")
            else:
                lines.append(f" {k}: {v}")
        return "\n".join(lines)

    if args and args[0] == "stats" and es:
        stats = es.stats()
        lines = ["Event Store Stats:", ""]
        for k, v in stats.items():
            lines.append(f" {k}: {v}")
        return "\n".join(lines)

    if args and args[0] == "compat" and es:
        result = es.validate_backwards_compat()
        lines = ["Compatibility Check:", ""]
        lines.append(f" Checked: {result['checked']}")
        lines.append(f" Status: {result['status']}")
        if result.get("incompatible"):
            for inc in result["incompatible"]:
                lines.append(f"  INCOMPATIBLE seq={inc.get('seq')} event={inc.get('event')} v{inc.get('version')}")
        return "\n".join(lines)

    if args and args[0] == "versions" and es:
        vstats = es.version_stats()
        lines = ["Event Version Distribution:", ""]
        for k, v in sorted(vstats.items()):
            lines.append(f" {k}: {v}")
        return "\n".join(lines)

    history = orchestrator.events.history(limit=20)
    if not history:
        return "No events recorded. Use /events query|replay|stats|compat|versions for persistent store."
    lines = ["Recent Events:"]
    for e in history:
        lines.append(f" {e['event']:24s} @ {e['timestamp']:.0f}")
    return "\n".join(lines)


def cmd_plugin(args, orchestrator):
    plugins = getattr(orchestrator, "_plugin_runtime", None)
    if not plugins:
        return "Plugin runtime not available."

    if not args or args[0] == "list":
        plist = plugins.list_plugins()
        if not plist:
            return "No plugins loaded."
        lines = ["Loaded Plugins:", ""]
        for p in plist:
            m = p.get("manifest", p)
            name = m.get("name", p.get("name", "?")) if isinstance(m, dict) else p.get("name", "?")
            state = p.get("state", "?")
            sandbox_info = ""
            if p.get("sandbox"):
                sandbox_info = f" exec={p['sandbox'].get('executions', 0)}"
            lines.append(f" {name:20s} [{state}]{sandbox_info}")
        return "\n".join(lines)

    if args[0] == "stats":
        stats = plugins.stats()
        lines = ["Plugin Runtime Stats:", ""]
        for k, v in stats.items():
            lines.append(f" {k}: {v}")
        return "\n".join(lines)

    if args[0] == "usage" and len(args) > 1:
        usage = plugins.plugin_usage(args[1])
        if not usage:
            return f"No plugin: {args[1]}"
        lines = [f"Plugin Usage: {args[1]}", ""]
        for k, v in usage.items():
            lines.append(f" {k}: {v}")
        return "\n".join(lines)

    return "Usage: /plugin list|stats|usage <name>"


def cmd_diagnostics(args, orchestrator):
    obs = getattr(orchestrator, "_observability", None)
    if not obs:
        return "Observability not available."

    if not args or args[0] == "metrics":
        m = obs.metrics()
        lines = ["Observability Metrics:", ""]
        for k, v in m.items():
            lines.append(f" {k}: {v}")
        return "\n".join(lines)

    if args[0] == "timeline":
        event_name = args[1] if len(args) > 1 else None
        timeline = obs.timeline(event_name=event_name, limit=15)
        if not timeline:
            return "No timeline events."
        lines = ["Event Timeline:", ""]
        for e in timeline:
            lines.append(f" {e['event']:24s} @ {e['timestamp']:.0f}")
        return "\n".join(lines)

    if args[0] == "trace" and len(args) > 1:
        trace = obs.trace(args[1])
        if not trace:
            return f"No trace for job: {args[1]}"
        return f"Trace for {args[1]}: {trace}"

    if args[0] == "stream":
        return "Use /diagnostics stream via bridge request (type=diagnostics, action=stream)"

    return "Usage: /diagnostics metrics|timeline [event]|trace <job_id>|stream"


def cmd_swarm(args, orchestrator):
    swarm = getattr(orchestrator, "_swarm", None)
    if not swarm:
        return "Swarm not available."

    if not args or args[0] == "status":
        stats = swarm.stats()
        lines = ["Swarm Status:", ""]
        lines.append(f" Workers: {stats['registry']['total']}")
        lines.append(f" By state: {stats['registry']['by_state']}")
        lines.append(f" Completed: {stats['registry']['total_completed']}")
        lines.append(f" Failed: {stats['registry']['total_failed']}")
        return "\n".join(lines)

    if args[0] == "workers":
        workers = swarm.registry.list_all()
        lines = ["Workers:", ""]
        for w in workers:
            lines.append(f" {w['id']:12s} [{w['state']:8s}] {w['host']} jobs={w['jobs_completed']}")
        return "\n".join(lines)

    if args[0] == "heartbeat":
        stale = swarm.heartbeat.check()
        if stale:
            return f"Stale workers detected: {', '.join(stale)}"
        return "All workers healthy."

    return "Usage: /swarm status|workers|heartbeat"


def cmd_replay(args, orchestrator):
    replay = getattr(orchestrator, "_replay", None)
    if not replay:
        return "Replay engine not available."

    if not args or args[0] == "status":
        result = replay.replay(dry_run=True)
        lines = ["Replay Engine:", ""]
        lines.append(f" Events scanned: {result.get('events_scanned', 0)}")
        lines.append(f" Event types: {result.get('event_types', {})}")
        return "\n".join(lines)

    if args[0] == "full":
        result = replay.replay()
        states = result.get("states", {})
        lines = ["Replayed System State:", ""]
        for name, state in states.items():
            lines.append(f" [{name}]")
            if isinstance(state, dict):
                for k, v in state.items():
                    if isinstance(v, list):
                        lines.append(f"  {k}: {len(v)} items")
                    else:
                        lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    if args[0] == "job" and len(args) > 1:
        result = replay.replay_job(args[1])
        lines = [f"Replay for job {args[1]}:", ""]
        for e in result.get("events", []):
            lines.append(f" {e.get('event', '?'):24s} @ {e.get('timestamp', 0):.0f}")
        return "\n".join(lines)

    if args[0] == "commands":
        result = replay.replay_commands()
        lines = ["Command History:", ""]
        for e in result.get("commands", []):
            d = e.get("data", {})
            lines.append(f" {d.get('command', '?'):20s} status={d.get('status', '?')}")
        return "\n".join(lines)

    return "Usage: /replay status|full|job <id>|commands"


def cmd_coordinator(args, orchestrator):
    coord = getattr(orchestrator, "_coordinator", None)
    if not coord:
        return "Coordinator not available."

    if not args or args[0] == "status":
        status = coord.status()
        lines = ["Coordinator Status:", ""]
        lines.append(f" Strategy: {status['strategy']}")
        lines.append(f" Registry: {status['registry']}")
        lines.append(f" Assignments: {status['assignments']}")
        return "\n".join(lines)

    if args[0] == "assignments":
        assignments = coord.list_assignments()
        if not assignments:
            return "No task assignments."
        lines = ["Task Assignments:", ""]
        for a in assignments:
            lines.append(f" {a['id']:12s} [{a['status']:10s}] worker={a.get('worker_id', '?')} pri={a.get('priority', 0)}")
        return "\n".join(lines)

    if args[0] == "rebalance":
        result = coord.rebalance()
        return f"Rebalance: moved {result['moved']} tasks"

    return "Usage: /coordinator status|assignments|rebalance"


def cmd_network(args, orchestrator):
    net = getattr(orchestrator, "_network", None)
    if not net:
        return "Network layer not available."

    if not args or args[0] == "stats":
        stats = net.stats()
        lines = ["Network Layer:", ""]
        lines.append(f" Transport: {stats.get('transport', {})}")
        lines.append(f" Nodes: {stats.get('nodes', {})}")
        lines.append(f" Tasks: {stats.get('tasks', {})}")
        return "\n".join(lines)

    if args[0] == "nodes":
        nodes = net.node_registry.list_all()
        if not nodes:
            return "No nodes registered."
        lines = ["Network Nodes:", ""]
        for nid, n in nodes.items():
            lines.append(f" {nid:16s} [{n.get('status', '?'):8s}] {n.get('host')} cap={n.get('capabilities', [])}")
        return "\n".join(lines)

    return "Usage: /network stats|nodes"


def register_default_commands():
    registry.register("/help", cmd_help, description="Show available commands", aliases=["/h"])
    registry.register("/status", cmd_status, description="Show engine status", aliases=["/st"])
    registry.register("/model", cmd_model, description="Show or switch model")
    registry.register("/models", cmd_models, description="List available models", aliases=["/ml"])
    registry.register("/jobs", cmd_jobs, description="Show recent jobs", aliases=["/j"])
    registry.register("/config", cmd_config, description="Show or edit config", aliases=["/cfg"])
    registry.register("/agents", cmd_agents, description="Show agent roles")
    registry.register("/events", cmd_events, description="Event history and store", aliases=["/ev"])
    registry.register("/plugin", cmd_plugin, description="Plugin management", aliases=["/pl"])
    registry.register("/diagnostics", cmd_diagnostics, description="Observability and traces", aliases=["/diag"])
    registry.register("/swarm", cmd_swarm, description="Swarm/worker status", aliases=["/sw"])
    registry.register("/replay", cmd_replay, description="Event replay engine", aliases=["/rp"])
    registry.register("/coordinator", cmd_coordinator, description="Task coordinator", aliases=["/coord"])
    registry.register("/network", cmd_network, description="Distributed network layer", aliases=["/net"])
