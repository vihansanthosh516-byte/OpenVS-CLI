from engine.commands.registry import registry


def cmd_help(args, orchestrator):
    return registry.help_text()


def cmd_status(args, orchestrator):
    status = orchestrator.status()
    lines = [
        f"Engine: v{status['version']}",
        f"Model: {status['model']}",
        f"Client: {status['model_client']}",
        f"Mode: {status['mode']}",
        f"Jobs: {status['jobs_completed']} completed, {status['jobs_failed']} failed, {status['jobs_total']} total",
        f"Uptime: {status['uptime']}",
    ]
    return "\n".join(lines)


def cmd_model(args, orchestrator):
    if not args:
        return f"Current model: {orchestrator.model}\nAvailable: qwen, nemotron, gemma, glm, local"

    model = args[0].lower()
    valid = ["qwen", "nemotron", "gemma", "glm", "local"]
    if model in valid:
        orchestrator.model = model
        return f"Model switched to: {model}"
    return f"Unknown model: {model}\nAvailable: {', '.join(valid)}"


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
    config = orchestrator.config
    lines = ["OpenVS Config:", ""]
    for key, value in sorted(config.items()):
        lines.append(f" {key:24s} = {value}")
    return "\n".join(lines)


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
        lines = [f"Compatibility Check:", ""]
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
                        lines.append(f"   {k}: {len(v)} items")
                    else:
                        lines.append(f"   {k}: {v}")
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
    registry.register("/jobs", cmd_jobs, description="Show recent jobs", aliases=["/j"])
    registry.register("/config", cmd_config, description="Show current config", aliases=["/cfg"])
    registry.register("/agents", cmd_agents, description="Show agent roles")
    registry.register("/events", cmd_events, description="Event history and store", aliases=["/ev"])
    registry.register("/plugin", cmd_plugin, description="Plugin management", aliases=["/pl"])
    registry.register("/diagnostics", cmd_diagnostics, description="Observability and traces", aliases=["/diag"])
    registry.register("/swarm", cmd_swarm, description="Swarm/worker status", aliases=["/sw"])
    registry.register("/replay", cmd_replay, description="Event replay engine", aliases=["/rp"])
    registry.register("/coordinator", cmd_coordinator, description="Task coordinator", aliases=["/coord"])
    registry.register("/network", cmd_network, description="Distributed network layer", aliases=["/net"])
