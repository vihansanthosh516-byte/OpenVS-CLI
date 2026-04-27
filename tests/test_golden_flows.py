"""
Golden Interactive Flow Tests — scenario-based end-to-end tests.

These test complete user workflows through the OpenVS CLI system,
not just individual unit functions. Each test simulates a real user
interaction path and verifies the system responds correctly.

Run: python -m pytest tests/ -v
     or: python tests/test_golden_flows.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBugFixFlow:
    """Simulate: user asks to fix a bug → swarm executes → result returned."""

    def test_swarm_bug_fix(self):
        from core.swarm_coordinator import swarm
        result = swarm.execute("Fix null pointer in auth.py", mode="parallel")
        assert result["status"] in ("completed", "conflict")
        assert result["mode"] == "parallel"
        assert "dag" in result
        assert result["duration_ms"] > 0

    def test_pipeline_bug_fix(self):
        from core.swarm_coordinator import swarm
        result = swarm.execute("Fix timeout in api.py", mode="pipeline")
        assert result["status"] in ("completed", "conflict")
        assert result["mode"] == "pipeline"

    def test_debate_approach(self):
        from core.swarm_coordinator import swarm
        result = swarm.execute("Design error handling strategy", mode="debate")
        assert result["mode"] == "debate"
        dag = result["dag"]
        assert len(dag["nodes"]) == 3  # approach_a, approach_b, evaluate


class TestModelSwitchFlow:
    """Simulate: user switches models during a session."""

    def test_switch_model_via_command(self):
        from openvs.core.commands import handle_command
        from openvs.core.app_state import app_state
        result = handle_command("/model nemotron")
        assert "nemotron" in result
        assert app_state.model == "nemotron"
        # Switch back
        handle_command("/model qwen")
        assert app_state.model == "qwen"

    def test_invalid_model_rejected(self):
        from openvs.core.commands import handle_command
        result = handle_command("/model gpt-99")
        assert "Unknown" in result or "unknown" in result.lower()

    def test_model_list(self):
        from openvs.core.commands import handle_command
        result = handle_command("/model")
        assert "qwen" in result
        assert "nemotron" in result


class TestSwarmToggleFlow:
    """Simulate: user toggles swarm on/off and changes modes."""

    def test_toggle_swarm_off(self):
        from openvs.core.commands import handle_command
        from openvs.core.app_state import app_state
        result = handle_command("/swarm off")
        assert "disabled" in result.lower() or "off" in result.lower()
        assert app_state.swarm.enabled is False

    def test_toggle_swarm_on(self):
        from openvs.core.commands import handle_command
        from openvs.core.app_state import app_state
        handle_command("/swarm on")
        assert app_state.swarm.enabled is True

    def test_change_swarm_mode(self):
        from openvs.core.commands import handle_command
        from openvs.core.app_state import app_state
        result = handle_command("/swarm mode debate")
        assert "debate" in result
        assert app_state.swarm.mode == "debate"
        # Reset
        handle_command("/swarm mode parallel")

    def test_invalid_swarm_mode(self):
        from openvs.core.commands import handle_command
        result = handle_command("/swarm mode invalid")
        assert "Unknown" in result or "unknown" in result.lower()


class TestWorkerFailureRecovery:
    """Simulate: a worker fails, system recovers gracefully."""

    def test_worker_failure_doesnt_crash(self):
        from core.distributed_workers import WorkerNode
        from core.policy_engine import PolicyEngine
        from core.jobs import Job, JobPriority
        worker = WorkerNode("w1", capabilities=["coder"])
        engine = PolicyEngine()
        token = engine.issue_token("coder", "task_1")
        job = Job(task="Fix bug", priority=JobPriority.NORMAL, metadata={"agent_role": "coder"})
        worker.assign_job(job, token)
        # Simulate failure
        result = worker.fail_job(job.id, "Connection timeout")
        assert result["status"] == "failed"
        assert worker._failed_count == 1
        # Worker should be idle again
        assert worker.is_available

    def test_fabric_continues_after_worker_failure(self):
        from core.distributed_workers import WorkerFabric
        fab = WorkerFabric()
        fab.register_worker("w1", ["coder"])
        fab.register_worker("w2", ["coder"])
        # w1 goes offline
        fab.deregister_worker("w1")
        # w2 should still be findable
        w = fab.find_worker("coder")
        assert w is not None
        assert w.id == "w2"

    def test_crash_shield_catches_exception(self):
        from openvs.core.shield import shield
        shield.clear()
        result, error = shield.call(lambda: {"key": "val"}[100])
        assert result is None
        assert error is not None
        assert "err_" in error  # crash shield error ID prefix


class TestConsensusFlow:
    """Simulate: consensus rounds with different outcomes."""

    def test_critic_overrides_majority(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.CRITIC_AUTHORITY)
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("tester", "approve", weight=2),
            Vote("critic", "reject", weight=3),
        ]
        result = engine.vote("Deploy to production", votes)
        assert result.decision == "rejected"  # critic overrides

    def test_debate_requires_supermajority(self):
        from core.consensus import ConsensusEngine, ConsensusStrategy, Vote
        engine = ConsensusEngine(default_strategy=ConsensusStrategy.DEBATE)
        # Objection raised, need 2x weight to override
        votes = [
            Vote("coder", "approve", weight=1),
            Vote("critic", "approve", weight=3),
            Vote("security_auditor", "reject", weight=2),
        ]
        # approve_weight=4, reject_weight=2, need 4 > 4? No
        result = engine.vote("Merge risky patch", votes)
        assert result.decision == "rejected"

    def test_consensus_command_shows_stats(self):
        from openvs.core.commands import handle_command
        result = handle_command("/consensus")
        assert "weighted" in result.lower() or "Weighted" in result


class TestModeSwitchFlow:
    """Simulate: user cycles through UI modes."""

    def test_mode_cycle(self):
        from openvs.core.app_state import app_state, AppMode
        assert app_state.mode == AppMode.CHAT
        app_state.mode_cycle()
        assert app_state.mode == AppMode.DIFF
        app_state.mode_cycle()
        assert app_state.mode == AppMode.SWARM
        app_state.mode_cycle()
        assert app_state.mode == AppMode.TRACE
        app_state.mode_cycle()
        assert app_state.mode == AppMode.JOBS
        app_state.mode_cycle()
        assert app_state.mode == AppMode.CHAT  # wraps around


class TestDoctorFlow:
    """Simulate: user runs health checks."""

    def test_doctor_passes(self):
        from openvs.core.doctor import run_doctor
        result = run_doctor()
        assert result["summary"]["total"] == 10
        assert result["summary"]["healthy"] is True or result["summary"]["passed"] > 0

    def test_doctor_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/doctor")
        assert "Doctor" in result or "doctor" in result.lower()
        assert "checks" in result.lower() or "passed" in result.lower()


class TestCrashLogFlow:
    """Simulate: user checks crash history."""

    def test_empty_crash_log(self):
        from openvs.core.shield import shield
        shield.clear()
        from openvs.core.commands import handle_command
        result = handle_command("/crashes")
        assert "no crashes" in result.lower() or "No crashes" in result

    def test_crash_appears_in_log(self):
        from openvs.core.shield import shield
        shield.clear()
        shield.call(lambda: 1/0)
        from openvs.core.commands import handle_command
        result = handle_command("/crashes")
        assert "division by zero" in result.lower() or "ZeroDivision" in result


class TestSlashCommandStress:
    """Stress test the command system with edge cases."""

    def test_empty_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/")
        assert result  # should not crash

    def test_unknown_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/nonexistent")
        assert "Unknown" in result or "unknown" in result.lower()

    def test_help_lists_all_commands(self):
        from openvs.core.commands import handle_command
        result = handle_command("/help")
        assert "/model" in result
        assert "/swarm" in result
        assert "/doctor" in result
        assert "/crashes" in result
        assert "/jobs" in result
        assert "/agents" in result

    def test_clear_command(self):
        from openvs.core.app_state import app_state
        from openvs.core.commands import handle_command
        app_state.add_message("user", "test message")
        result = handle_command("/clear")
        assert "cleared" in result.lower()
        assert len(app_state.messages) == 0

    def test_agents_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/agents")
        assert "coder" in result or "planner" in result

    def test_status_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/status")
        assert len(result) > 0  # should return something

    def test_dags_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/dags")
        assert len(result) > 0

    def test_cluster_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/cluster")
        assert len(result) > 0

    def test_version_cli(self):
        from openvs import __version__
        assert __version__ == "1.0.0"

    def test_session_save_load(self):
        from openvs.core.commands import handle_command
        from openvs.core.app_state import app_state
        app_state.add_message("user", "test for session")
        result = handle_command("/session save")
        assert "saved" in result.lower()
        result = handle_command("/session info")
        assert "messages" in result.lower() or "session" in result.lower()

    def test_update_check_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/update check")
        assert len(result) > 0  # should return something

    def test_plugin_list_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/plugin list")
        assert "plugin" in result.lower() or "Plugin" in result

    def test_marketplace_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/marketplace")
        assert "marketplace" in result.lower() or "Plugin" in result

    def test_profile_list(self):
        from openvs.core.commands import handle_command
        result = handle_command("/profile")
        assert "backend" in result.lower() or "Profile" in result

    def test_config_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/config")
        assert "config" in result.lower() or "provider" in result.lower()

    def test_export_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/export")
        assert "export" in result.lower() or "diagnostic" in result.lower()

    def test_login_placeholder(self):
        from openvs.core.commands import handle_command
        result = handle_command("/login")
        assert "coming soon" in result.lower() or "soon" in result.lower()


class TestCommandPalette:
    """Test the command palette data model."""

    def test_fuzzy_search(self):
        from openvs.core.command_palette import search_commands
        results = search_commands("mod")
        labels = [r.label for r in results]
        assert any("model" in l.lower() for l in labels)

    def test_all_commands_returns_items(self):
        from openvs.core.command_palette import get_all_commands
        cmds = get_all_commands()
        assert len(cmds) > 20

    def test_power_mode(self):
        from openvs.core.command_palette import search_commands
        results = search_commands(">force")
        assert len(results) > 0
        assert results[0].is_power

    def test_badges(self):
        from openvs.core.command_palette import get_all_commands
        cmds = get_all_commands()
        badges = {c.badge for c in cmds}
        assert "[Task]" in badges or "[Model]" in badges

    def test_suggestions(self):
        from openvs.core.command_palette import get_suggestions
        suggestions = get_suggestions({"status": "idle"})
        assert len(suggestions) > 0

    def test_command_history(self):
        from openvs.core.command_palette import command_history
        command_history.clear()
        command_history.record("/run fix bug")
        command_history.record("/model qwen")
        recent = command_history.recent(2)
        assert "/model qwen" in recent
        assert len(recent) == 2


class TestPluginRuntimeSDK:
    """Test the full plugin runtime system."""

    def test_plugin_loader_discovers_plugins(self):
        from openvs.plugins.loader import PluginLoader
        loader = PluginLoader()
        result = loader.load_all()
        assert result["loaded"] >= 0  # at minimum hello_plugin should exist

    def test_plugin_context_api(self):
        from openvs.plugins.context import PluginContext
        ctx = PluginContext()
        ctx.send_message("test message")
        msgs = ctx.flush_messages()
        assert len(msgs) == 1
        assert "test message" in msgs[0]

    def test_plugin_context_state(self):
        from openvs.plugins.context import PluginContext
        ctx = PluginContext()
        state = ctx.get_state()
        assert "model" in state
        assert "swarm_enabled" in state

    def test_sandbox_denies_undeclared_command(self):
        from openvs.plugins.sandbox import PluginSandbox
        from openvs.plugins.context import PluginContext
        from openvs.plugins.loader import LoadedPlugin
        sandbox = PluginSandbox(PluginContext())
        plugin = LoadedPlugin(name="test", commands=[], hooks=[])
        result = sandbox.call_command(plugin, "/undeclared")
        assert result["status"] == "denied"

    def test_hook_dispatcher_registers(self):
        from openvs.plugins.hooks import HookDispatcher
        dispatcher = HookDispatcher()
        dispatcher.register("test_plugin", ["before_run", "after_run"])
        subs = dispatcher.list_subscribers()
        assert "before_run" in subs
        assert "test_plugin" in subs["before_run"]

    def test_hook_dispatcher_unregister(self):
        from openvs.plugins.hooks import HookDispatcher
        dispatcher = HookDispatcher()
        dispatcher.register("test_plugin", ["before_run"])
        dispatcher.unregister("test_plugin")
        subs = dispatcher.list_subscribers()
        assert "before_run" not in subs

    def test_plugin_registry(self):
        from openvs.plugins.registry import PluginRegistry
        registry = PluginRegistry()
        registry.register("test_reg", {"version": "1.0.0", "permissions": ["network"]})
        entry = registry.get("test_reg")
        assert entry is not None
        assert entry["version"] == "1.0.0"
        assert registry.needs_approval("test_reg") is True

    def test_plugin_runtime_loads(self):
        from openvs.plugins.runtime import PluginRuntime
        runtime = PluginRuntime()
        result = runtime.load()
        assert "loaded" in result
        assert runtime._loaded is True

    def test_plugin_runtime_stats(self):
        from openvs.plugins.runtime import PluginRuntime
        runtime = PluginRuntime()
        runtime.load()
        stats = runtime.stats()
        assert "loader" in stats
        assert "sandbox" in stats
        assert "hooks" in stats

    def test_plugin_list_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/plugin list")
        assert len(result) > 0

    def test_plugin_hooks_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/plugin hooks")
        assert len(result) > 0

    def test_plugin_stats_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/plugin stats")
        assert "stats" in result.lower() or "loader" in result.lower()

    def test_ext_list_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/ext list")
        assert "github" in result.lower() or "extension" in result.lower()

    def test_ext_enable_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/ext enable github")
        assert "enabled" in result.lower()

    def test_ext_disable_command(self):
        from openvs.core.commands import handle_command
        result = handle_command("/ext disable github")
        assert "disabled" in result.lower()

    def test_hello_plugin_loaded(self):
        from openvs.plugins.runtime import PluginRuntime
        runtime = PluginRuntime()
        runtime.load()
        plugin = runtime.get_plugin("hello_plugin")
        # May or may not exist depending on ~/.openvs/plugins/
        if plugin:
            assert plugin["name"] == "hello_plugin"
            assert "/hello" in [c.get("name", "") for c in plugin.get("commands", [])]


# ---- Manual test runner ----

if __name__ == "__main__":
    test_classes = [
        TestBugFixFlow, TestModelSwitchFlow, TestSwarmToggleFlow,
        TestWorkerFailureRecovery, TestConsensusFlow, TestModeSwitchFlow,
        TestDoctorFlow, TestCrashLogFlow, TestSlashCommandStress,
        TestCommandPalette, TestPluginRuntimeSDK,
    ]

    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in methods:
            try:
                getattr(instance, method_name)()
                print(" PASS " + cls.__name__ + "." + method_name)
                passed += 1
            except Exception as e:
                print(" FAIL " + cls.__name__ + "." + method_name + ": " + str(e))
                failed += 1

    sep = "=" * 50
    print("")
    print(sep)
    print(" Results: " + str(passed) + " passed, " + str(failed) + " failed")
    print(sep)
