"""
Command System — slash command handler for OpenVS CLI.

Commands are prefixed with /. They control the system:
/model <name>       Switch active model
/swarm on|off       Toggle swarm mode
/swarm mode <m>     Set swarm mode (parallel/pipeline/debate/map_reduce)
/jobs               List current jobs
/trace <id>         Show a specific trace
/status             Show system status
/clear              Clear chat history
/help               Show available commands
/agents             List agent roles and scopes
/consensus          Show consensus stats
/cluster            Show worker fabric status
/plugin list|install|remove|enable|disable|reload|approve|hooks|stats
/ext list|enable|disable  Extension system
/update [check|now|channel] Self-update
/session load|save|clear|info Session persistence
/export             Export diagnostic bundle
/marketplace        Browse community plugins
/profile <name>     Switch plugin profile
/config [set|get|reset] View or edit persistent config
/login              OpenVS account (placeholder)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from openvs.core.app_state import app_state, AppMode


def handle_command(cmd: str) -> str:
    """Handle a slash command. Returns output text."""
    parts = cmd.strip().split()
    if not parts:
        return ""

    command = parts[0].lower()
    args = parts[1:]

    # Check if any loaded plugin handles this command
    try:
        from openvs.plugins.runtime import plugin_runtime
        if plugin_runtime._loaded:
            for plugin in plugin_runtime.loader.plugins.values():
                if not plugin.enabled or not plugin.commands:
                    continue
                for cmd_def in plugin.commands:
                    cmd_name = cmd_def.get("name", "") if isinstance(cmd_def, dict) else cmd_def
                    if cmd_name == command:
                        result = plugin_runtime.run_command(plugin.name, command, args)
                        if result.get("status") == "ok":
                            msgs = plugin_runtime.context.flush_messages()
                            output = "\n".join(msgs) if msgs else str(result.get("result", ""))
                            return output or "Plugin command executed."
                        elif result.get("status") == "denied":
                            return f"Plugin command denied: {result.get('error', '')}"
    except Exception:
        pass

    handlers = {
        "/model": _cmd_model,
        "/swarm": _cmd_swarm,
        "/jobs": _cmd_jobs,
        "/trace": _cmd_trace,
        "/status": _cmd_status,
        "/clear": _cmd_clear,
        "/help": _cmd_help,
        "/agents": _cmd_agents,
        "/consensus": _cmd_consensus,
        "/cluster": _cmd_cluster,
        "/dags": _cmd_dags,
        "/doctor": _cmd_doctor,
        "/crashes": _cmd_crashes,
        "/plugin": lambda a: _cmd_plugin(a),
        "/ext": lambda a: _cmd_ext(a),
        "/update": lambda a: _cmd_update(a),
        "/session": lambda a: _cmd_session(a),
        "/export": _cmd_export,
        "/marketplace": _cmd_marketplace,
        "/profile": lambda a: _cmd_profile(a),
        "/config": lambda a: _cmd_config(a),
        "/login": _cmd_login,
    }

    handler = handlers.get(command)
    if handler:
        if command in ("/plugin", "/ext", "/update", "/session", "/profile", "/config"):
            return handler(args)
        return handler() if handler.__code__.co_argcount == 0 else handler(args)
    return f"Unknown command: {command}\nType /help for available commands."


# ---- Core commands ----

def _cmd_model(args: list) -> str:
    if not args:
        return f"Current model: {app_state.model}\nAvailable: qwen, nemotron, gemma, glm, local"
    model = args[0].lower()
    valid = ["qwen", "nemotron", "gemma", "glm", "local"]
    if model in valid:
        app_state.set_model(model)
        return f"Model switched to: {model}"
    return f"Unknown model: {model}\nAvailable: {', '.join(valid)}"


def _cmd_swarm(args: list) -> str:
    if not args:
        state = "ON" if app_state.swarm.enabled else "OFF"
        return f"Swarm: {state} | Mode: {app_state.swarm.mode}"
    first = args[0].lower()
    if first in ("on", "enable", "true"):
        app_state.set_swarm_enabled(True)
        return "Swarm enabled"
    elif first in ("off", "disable", "false"):
        app_state.set_swarm_enabled(False)
        return "Swarm disabled"
    elif first == "mode" and len(args) > 1:
        mode = args[1].lower()
        valid = ["parallel", "pipeline", "debate", "map_reduce"]
        if mode in valid:
            app_state.swarm.mode = mode
            return f"Swarm mode set to: {mode}"
        return f"Unknown mode: {mode}\nAvailable: {', '.join(valid)}"
    return "Usage: /swarm on|off | /swarm mode <parallel|pipeline|debate|map_reduce>"


def _cmd_jobs() -> str:
    try:
        from core.scheduler import scheduler
        jobs = scheduler.list_jobs(limit=10)
        if not jobs:
            return "No jobs."
        lines = []
        for j in jobs:
            lines.append(f"  {j['id'][:20]} {j['status']:10s} {j['priority']:8s} {j['task'][:40]}")
        return "Recent Jobs:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error fetching jobs: {e}"


def _cmd_trace(args: list) -> str:
    if not args:
        return "Usage: /trace <task_id>"
    task_id = args[0]
    if task_id == "last":
        try:
            from core.tracer import tracer
            traces = tracer.list_traces(limit=1)
            if traces:
                task_id = traces[0]["task_id"]
        except Exception:
            pass
    try:
        from core.tracer import tracer
        trace = tracer.load_trace(task_id)
        if trace is None:
            return f"Trace '{task_id}' not found."
        app_state.mode = AppMode.TRACE
        return trace.render()
    except Exception as e:
        return f"Error loading trace: {e}"


def _cmd_status() -> str:
    from openvs.core.runtime import get_system_stats
    stats = get_system_stats()
    lines = [
        f"Models: {', '.join(stats.get('models', []))}",
        f"Swarm: {stats.get('swarm', {})}",
        f"Policy: {stats.get('policy', {})}",
        f"Fabric: {stats.get('fabric', {})}",
        f"Consensus: {stats.get('consensus', {})}",
    ]
    return "\n".join(lines)


def _cmd_clear() -> str:
    app_state.messages.clear()
    app_state.current_stream = ""
    return "Chat cleared."


def _cmd_agents() -> str:
    try:
        from core.policy_engine import policy, ROLE_SCOPES
        roles = policy.list_roles()
        lines = []
        for role, scope in roles.items():
            perms = ", ".join(scope["permissions"][:4])
            lines.append(f"  {role:18s} | {perms:30s} | delegate: {'Y' if scope['can_delegate'] else 'N'}")
        return "Agent Roles:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_consensus() -> str:
    try:
        from core.consensus import consensus, ROLE_WEIGHTS
        stats = consensus.stats()
        lines = [
            f"Total rounds: {stats['total_rounds']}",
            f"Approved: {stats['approved']} | Rejected: {stats['rejected']}",
            f"Strategy: {stats['default_strategy']}",
            "",
            "Role weights:",
        ]
        for role, weight in ROLE_WEIGHTS.items():
            lines.append(f"  {role:18s} = {weight}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_cluster() -> str:
    try:
        from core.distributed_workers import fabric
        from core.task_router import task_router
        fs = fabric.stats()
        rs = task_router.stats()
        lines = [
            f"Workers: {fs['total_workers']} | Available: {fs['available']}",
            f"Active: {fs['total_active_jobs']} | Completed: {fs['total_completed']} | Failed: {fs['total_failed']}",
            f"Router: {rs['strategy']} | Routes: {rs['total_routes']}",
        ]
        for w in fs.get("workers", []):
            lines.append(f"  {w['id']:12s} | {w['state']:8s} | done={w['completed']} fail={w['failed']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_dags() -> str:
    try:
        from core.swarm_coordinator import swarm
        dags = swarm.list_dags()
        if not dags:
            return "No active DAGs."
        lines = []
        for d in dags:
            p = d.get("progress", {})
            lines.append(f"  {d['id']:20s} | nodes={p.get('total', 0)} done={p.get('completed', 0)} | {d['root_task'][:30]}")
        return "Active DAGs:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _cmd_help() -> str:
    return """Available Commands:

 Core:
 /model <name>      Switch active model (qwen, nemotron, gemma, glm, local)
 /swarm on|off      Toggle swarm orchestration
 /swarm mode <m>    Set swarm mode (parallel, pipeline, debate, map_reduce)
 /jobs              List recent jobs
 /trace <id|last>   Show execution trace
 /status            Show system statistics
 /agents            List agent role scopes
 /consensus         Show consensus engine stats
 /cluster           Show worker fabric status
 /dags              List active delegation DAGs

 Diagnostics:
 /doctor            Run system health checks
 /crashes           Show recent crash log
 /export            Export diagnostic bundle for bug reports

 Session & Updates:
 /session load      Restore previous session
 /session save      Save current session
 /session clear     Clear saved sessions
 /session info      Show session info
 /update check      Check for updates
 /update now        Install latest update
 /update channel <stable|beta|nightly>  Set update channel

 Plugins & Extensions:
 /plugin list       List loaded plugins (SDK runtime)
 /plugin install <name>   Install a plugin
 /plugin remove <name>    Remove a plugin
 /plugin enable|disable <name>  Toggle plugin
 /plugin reload [name]    Reload plugins (hot-reload)
 /plugin approve <name>   Approve plugin permissions
 /plugin hooks      Show hook subscriptions
 /plugin stats      Show plugin runtime stats
 /ext list          List extensions
 /ext enable <name> Enable an extension
 /ext disable <name> Disable an extension
 /marketplace       Browse community plugins
 /profile <name>    Switch plugin profile (backend, security, devops, frontend)

 Other:
 /clear             Clear chat history
 /config [set|get|reset]  View or edit persistent config
 /login             OpenVS account (coming soon)
 /help              Show this help

 Keyboard:
 TAB                Cycle mode (chat, diff, swarm, trace, jobs)
 CTRL+M             Model selector
 CTRL+P             Command palette
 CTRL+S             Toggle swarm panel"""


def _cmd_doctor() -> str:
    try:
        from openvs.core.doctor import run_doctor
        result = run_doctor()
        lines = []
        checks = result["checks"]
        summary = result["summary"]
        lines.append("")
        lines.append("  OpenVS CLI Doctor")
        lines.append("=" * 50)
        lines.append("")
        for name, check in checks.items():
            icon = {"ok": "+", "warn": "!", "fail": "X"}[check["status"]]
            lines.append("  [" + icon + "] " + name + ": " + check["message"])
        lines.append("")
        lines.append("=" * 50)
        if summary["healthy"]:
            lines.append("  All " + str(summary["total"]) + " checks passed")
        else:
            lines.append("  " + str(summary["passed"]) + "/" + str(summary["total"]) + " passed, " + str(summary["failed"]) + " failed, " + str(summary["warned"]) + " warnings")
        return "\n".join(lines)
    except Exception as e:
        return "Doctor error: " + str(e)


def _cmd_crashes() -> str:
    try:
        from openvs.core.shield import shield
        crashes = shield.recent_crashes(limit=10)
        stats = shield.stats()
        if not crashes:
            return "No crashes recorded. (Total recoveries: " + str(stats["recoveries"]) + ")"
        lines = ["Recent crashes (" + str(stats["total_crashes"]) + " total, " + str(stats["recoveries"]) + " recovered):", ""]
        for c in crashes:
            lines.append("  [" + c["id"] + "] " + c["context"] + ": " + c["error"][:80])
        return "\n".join(lines)
    except Exception as e:
        return "Error reading crash log: " + str(e)


# ---- Update commands ----

def _cmd_update(args: list) -> str:
    from openvs.core.updater import check_for_update, perform_update, set_channel, get_update_config

    if not args:
        config = get_update_config()
        result = check_for_update(force=True)
        status = result["status"]
        if status == "update_available":
            return f"Update available: v{result['latest']} (current: v{result['current']})\nRun /update now to install."
        elif status == "up_to_date":
            return f"Up to date: v{result['current']} (channel: {result.get('channel', 'stable')})"
        else:
            return f"Check failed. Current: v{result['current']}"

    sub = args[0].lower()

    if sub == "check":
        result = check_for_update(force=True)
        if result["status"] == "update_available":
            return f"Update available: v{result['latest']} (current: v{result['current']})\nChannel: {result.get('channel', 'stable')}"
        elif result["status"] == "up_to_date":
            return f"Up to date: v{result['current']} (channel: {result.get('channel', 'stable')})"
        return f"Check failed. Current: v{result['current']}"

    elif sub == "now":
        result = perform_update()
        if result["status"] == "updated":
            return f"Updated to v{result['version']}"
        return f"Update failed: {result.get('error', 'unknown')}"

    elif sub == "channel" and len(args) > 1:
        result = set_channel(args[1])
        if result.get("status") == "ok":
            return f"Update channel set to: {result['channel']}"
        return f"Error: {result.get('reason', 'unknown')}"

    return "Usage: /update [check|now|channel <stable|beta|nightly>]"


# ---- Plugin commands (SDK Runtime) ----

def _ensure_plugin_runtime():
    """Lazily load the plugin runtime on first use."""
    from openvs.plugins.runtime import plugin_runtime
    if not plugin_runtime._loaded:
        plugin_runtime.load()
    return plugin_runtime


def _cmd_plugin(args: list) -> str:
    if not args:
        return "Usage: /plugin list|install|remove|enable|disable|reload|approve|hooks|stats"

    sub = args[0].lower()
    runtime = _ensure_plugin_runtime()

    if sub == "list":
        plugins = runtime.list_plugins()
        if not plugins:
            from openvs.core.plugins import install_starter_plugins
            install_starter_plugins()
            runtime.reload()
            plugins = runtime.list_plugins()
        lines = ["Loaded Plugins:", ""]
        for p in plugins:
            state = "enabled" if p.get("enabled", True) else "disabled"
            cmds = ", ".join(str(c) for c in p.get("commands", [])) or "-"
            hooks = ", ".join(p.get("hooks", [])) or "-"
            err = f"  ERROR: {p['load_error']}" if p.get("load_error") else ""
            lines.append(f"  {p['name']:24s} v{p['version']} [{state}]")
            lines.append(f"    commands: {cmds}  hooks: {hooks}{err}")
        return "\n".join(lines)

    elif sub == "install" and len(args) > 1:
        name = args[1]
        from openvs.core.plugins import plugin_manager, PluginManifest
        manifest = PluginManifest(name=name, description=f"Custom plugin: {name}")
        result = plugin_manager.install(name, manifest)
        runtime.reload()
        return f"Plugin {result['status']}: {name}"

    elif sub == "remove" and len(args) > 1:
        name = args[1]
        from openvs.core.plugins import plugin_manager
        result = plugin_manager.remove(name)
        runtime.registry.unregister(name)
        return f"Plugin {result['status']}: {result['plugin']}"

    elif sub == "enable" and len(args) > 1:
        name = args[1]
        runtime.registry.set_enabled(name, True)
        plugin = runtime.loader.get_plugin(name)
        if plugin:
            plugin.enabled = True
        return f"Plugin enabled: {name}"

    elif sub == "disable" and len(args) > 1:
        name = args[1]
        runtime.registry.set_enabled(name, False)
        plugin = runtime.loader.get_plugin(name)
        if plugin:
            plugin.enabled = False
        return f"Plugin disabled: {name}"

    elif sub == "reload":
        if len(args) > 1:
            result = runtime.reload_plugin(args[1])
            return f"Plugin {result['status']}: {args[1]}"
        result = runtime.reload()
        return f"Plugins reloaded: {result['loaded']} loaded, {result['errors']} errors"

    elif sub == "approve" and len(args) > 1:
        result = runtime.approve_permissions(args[1])
        return f"Permissions {result['status']}: {result['plugin']}"

    elif sub == "hooks":
        subscribers = runtime.hooks.list_subscribers()
        if not subscribers:
            return "No hook subscriptions."
        lines = ["Hook Subscriptions:", ""]
        for hook, plugin_names in sorted(subscribers.items()):
            lines.append(f"  {hook:24s} -> {', '.join(plugin_names)}")
        return "\n".join(lines)

    elif sub == "stats":
        stats = runtime.stats()
        lines = ["Plugin Runtime Stats:", ""]
        for key, val in stats.items():
            if isinstance(val, dict):
                lines.append(f"  {key}:")
                for k, v in val.items():
                    lines.append(f"    {k}: {v}")
            else:
                lines.append(f"  {key}: {val}")
        return "\n".join(lines)

    return "Usage: /plugin list|install|remove|enable|disable|reload|approve|hooks|stats"


# ---- Extension commands ----

# Extensions are integration plugins that connect OpenVS to external services
EXTENSIONS = {
    "github": {
        "description": "GitHub integration: PR reviews, issue tracking, repo management",
        "commands": ["/pr", "/issues", "/repo"],
        "hooks": ["after_patch", "on_job_complete"],
        "permissions": ["network", "write_comments"],
    },
    "slack": {
        "description": "Slack integration: notifications, status updates, alerts",
        "commands": ["/slack", "/notify"],
        "hooks": ["on_worker_fail", "on_job_complete"],
        "permissions": ["network"],
    },
    "jira": {
        "description": "Jira integration: ticket tracking, sprint status",
        "commands": ["/jira", "/ticket"],
        "hooks": ["after_run", "on_job_complete"],
        "permissions": ["network", "read_repo"],
    },
    "docker": {
        "description": "Docker integration: container management, image builds",
        "commands": ["/docker", "/container"],
        "hooks": ["after_patch"],
        "permissions": ["network", "admin"],
    },
    "vscode": {
        "description": "VS Code integration: editor commands, file navigation",
        "commands": ["/code", "/open"],
        "hooks": ["after_patch", "on_diff_accept"],
        "permissions": ["read_repo", "write_files"],
    },
}


def _cmd_ext(args: list) -> str:
    if not args:
        lines = ["Extensions — external service integrations:", ""]
        for name, info in EXTENSIONS.items():
            lines.append(f"  {name:12s} — {info['description']}")
        lines.append("")
        lines.append("Usage: /ext list|enable <name>|disable <name>")
        return "\n".join(lines)

    sub = args[0].lower()

    if sub == "list":
        lines = ["Extensions:", ""]
        enabled_exts = set()
        try:
            from openvs.core.config import get
            enabled_exts = set(get("enabled_extensions", []))
        except Exception:
            pass

        for name, info in EXTENSIONS.items():
            state = "enabled" if name in enabled_exts else "available"
            cmds = ", ".join(info["commands"])
            lines.append(f"  {name:12s} [{state}]  commands: {cmds}")
            lines.append(f"    {info['description']}")
        return "\n".join(lines)

    elif sub == "enable" and len(args) > 1:
        name = args[1].lower()
        if name not in EXTENSIONS:
            return f"Unknown extension: {name}\nAvailable: {', '.join(EXTENSIONS.keys())}"

        try:
            from openvs.core.config import load_config, save_config
            config = load_config()
            enabled = set(config.get("enabled_extensions", []))
            enabled.add(name)
            config["enabled_extensions"] = list(enabled)
            save_config(config)
        except Exception:
            pass

        ext = EXTENSIONS[name]
        return (f"Extension '{name}' enabled.\n"
                f"Commands: {', '.join(ext['commands'])}\n"
                f"Permissions: {', '.join(ext['permissions'])}\n"
                f"Restart OpenVS to activate.")

    elif sub == "disable" and len(args) > 1:
        name = args[1].lower()
        if name not in EXTENSIONS:
            return f"Unknown extension: {name}"

        try:
            from openvs.core.config import load_config, save_config
            config = load_config()
            enabled = set(config.get("enabled_extensions", []))
            enabled.discard(name)
            config["enabled_extensions"] = list(enabled)
            save_config(config)
        except Exception:
            pass

        return f"Extension '{name}' disabled."

    return "Usage: /ext list|enable <name>|disable <name>"


# ---- Session commands ----

def _cmd_session(args: list) -> str:
    from openvs.core.session import save_session, load_session, has_session, clear_sessions, session_age_hours

    if not args:
        return "Usage: /session load|save|clear|info"

    sub = args[0].lower()

    if sub == "load":
        if not has_session():
            return "No saved session found."
        session = load_session()
        if session:
            msg_count = len(session.get("messages", []))
            model = session.get("model", "qwen")
            mode = session.get("mode", "chat")
            app_state.set_model(model)
            for m in session.get("messages", []):
                app_state.add_message(m.get("role", "user"), m.get("content", ""))
            return f"Session restored: {msg_count} messages, model={model}, mode={mode}"
        return "Failed to load session."

    elif sub == "save":
        result = save_session({
            "model": app_state.model,
            "mode": app_state.mode.value,
            "swarm_enabled": app_state.swarm.enabled,
            "swarm_mode": app_state.swarm.mode,
            "worker_count": app_state.worker_count,
            "messages": [{"role": m.role, "content": m.content} for m in app_state.messages],
            "command_history": [],
        })
        return f"Session saved. ({result['messages']} messages)"

    elif sub == "clear":
        result = clear_sessions()
        return "Sessions cleared."

    elif sub == "info":
        if not has_session():
            return "No saved session."
        session = load_session()
        age = session_age_hours()
        if session:
            return (f"Session: {len(session.get('messages', []))} messages, "
                    f"model={session.get('model', '?')}, "
                    f"age={age:.1f}h" if age else "Session: exists (age unknown)")
        return "No session info available."

    return "Usage: /session load|save|clear|info"


# ---- Export command ----

def _cmd_export() -> str:
    try:
        from openvs.core.session import export_diagnostics
        result = export_diagnostics()
        path = result.get("_export_path", "unknown")
        return f"Diagnostic bundle exported to:\n  {path}\nShare this file for bug reports."
    except Exception as e:
        return f"Export error: {e}"


# ---- Marketplace command ----

def _cmd_marketplace() -> str:
    from openvs.core.plugins import plugin_manager, install_starter_plugins

    install_starter_plugins()

    plugins = plugin_manager.list_plugins()
    lines = ["OpenVS Plugin Marketplace:", ""]

    categories = {
        "Security": ["security-audit"],
        "Code Review": ["github-pr-reviewer"],
        "Testing": ["test-generator"],
        "DevOps": ["kubernetes-agent"],
        "Documentation": ["docs-writer"],
        "Extensions": ["github", "slack", "jira", "docker", "vscode"],
    }

    installed_names = {p["name"] for p in plugins}

    for cat, names in categories.items():
        lines.append(f"  {cat}:")
        for name in names:
            installed = "installed" if name in installed_names else "available"
            lines.append(f"    {name:24s} [{installed}]")
        lines.append("")

    lines.append("Install plugin: /plugin install <name>")
    lines.append("Enable extension: /ext enable <name>")
    lines.append("List installed: /plugin list")
    return "\n".join(lines)


# ---- Profile command ----

def _cmd_profile(args: list) -> str:
    profiles = {
        "backend": {
            "description": "Backend engineering: security audit, test generator, PR reviewer",
            "plugins": ["security-audit", "test-generator", "github-pr-reviewer"],
        },
        "security": {
            "description": "Security-focused: security audit, PR reviewer",
            "plugins": ["security-audit", "github-pr-reviewer"],
        },
        "devops": {
            "description": "DevOps: Kubernetes agent, test generator, docs writer",
            "plugins": ["kubernetes-agent", "test-generator", "docs-writer"],
        },
        "frontend": {
            "description": "Frontend: PR reviewer, test generator, docs writer",
            "plugins": ["github-pr-reviewer", "test-generator", "docs-writer"],
        },
        "fullstack": {
            "description": "Full stack: all plugins enabled",
            "plugins": ["security-audit", "test-generator", "github-pr-reviewer", "kubernetes-agent", "docs-writer"],
        },
    }

    if not args:
        lines = ["Available Profiles:", ""]
        for name, info in profiles.items():
            lines.append(f"  {name:14s} — {info['description']}")
        lines.append("")
        lines.append("Usage: /profile <name>")
        return "\n".join(lines)

    profile_name = args[0].lower()
    if profile_name not in profiles:
        return f"Unknown profile: {profile_name}\nAvailable: {', '.join(profiles.keys())}"

    from openvs.core.plugins import plugin_manager

    profile = profiles[profile_name]

    for plugin in plugin_manager._plugins.values():
        if plugin.manifest.name in profile["plugins"]:
            plugin.enabled = True
        else:
            plugin.enabled = False

    enabled = [p for p in profile["plugins"]]
    return f"Profile '{profile_name}' activated.\nEnabled plugins: {', '.join(enabled)}"


# ---- Login placeholder ----

def _cmd_login() -> str:
    return ("OpenVS Login — coming soon.\n\n"
            "Future capability:\n"
            "  openvs login\n"
            "  → Authenticate with OpenVS hosted platform\n"
            "  → Sync plugins, sessions, and preferences\n"
            "  → Access shared swarm workers\n\n"
            "For now, configure via .env and ~/.openvs/config.json")


# ---- Config command ----

def _cmd_config(args: list) -> str:
    from openvs.core.config import load_config, save_config, show, set as config_set, reset

    if not args:
        return show()

    sub = args[0].lower()

    if sub == "set" and len(args) >= 3:
        key = args[1]
        value = " ".join(args[2:])
        if value.lower() in ("true", "yes", "on"):
            value = True
        elif value.lower() in ("false", "no", "off"):
            value = False
        else:
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass
        result = config_set(key, value)
        return f"Config set: {key} = {value}"

    elif sub == "reset":
        result = reset()
        return "Config reset to defaults."

    elif sub == "get" and len(args) >= 2:
        from openvs.core.config import get as config_get
        value = config_get(args[1])
        if value is not None:
            return f"{args[1]} = {value}"
        return f"Key '{args[1]}' not found in config."

    return "Usage: /config [set <key> <value>|get <key>|reset]"
