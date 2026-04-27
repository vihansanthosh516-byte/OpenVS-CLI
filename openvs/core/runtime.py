"""
Runtime Bridge — connects OpenVS UI to the v13 swarm engine.

This is the glue layer. The UI never calls the engine directly.
All execution flows through the runtime bridge which:
1. Translates UI prompts into engine calls
2. Streams results back as tokens
3. Updates app_state as execution progresses
4. Handles errors gracefully (crash shield)
5. Fires plugin hooks before/after execution
"""

import sys
import os
import time
import asyncio

# Ensure the parent project is on the path so we can import core/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from openvs.core.app_state import app_state, SystemStatus, AgentState
from openvs.core.shield import shield


def _get_plugin_runtime():
    """Get the plugin runtime, loading it lazily."""
    try:
        from openvs.plugins.runtime import plugin_runtime
        if not plugin_runtime._loaded:
            plugin_runtime.load()
        return plugin_runtime
    except Exception:
        return None


async def run_prompt(prompt: str):
    """Execute a prompt through the swarm engine, yielding streaming tokens.

    All engine calls are wrapped in the crash shield. If anything
    blows up, we get a clean error message instead of a crash.

    Plugin hooks fire before and after execution:
    - before_run: before the prompt is dispatched
    - after_run: after the prompt completes
    """
    app_state.add_message("user", prompt)
    app_state.set_status(SystemStatus.PLANNING)

    # Fire before_run hook
    runtime = _get_plugin_runtime()
    if runtime:
        try:
            runtime.emit_hook("before_run", {"prompt": prompt})
        except Exception:
            pass

    if app_state.swarm.enabled:
        result_text = await _run_swarm(prompt)
    else:
        result_text = await _run_single(prompt)

    # Stream the result token by token
    app_state.set_status(SystemStatus.STREAMING)
    words = result_text.split(" ")
    accumulated = ""
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        accumulated += token
        app_state.set_stream(accumulated)
        yield token
        await asyncio.sleep(0.02)  # simulate streaming speed

    app_state.clear_stream()
    app_state.set_status(SystemStatus.IDLE)

    # Fire after_run hook
    if runtime:
        try:
            runtime.emit_hook("after_run", {"prompt": prompt, "result_length": len(result_text)})
        except Exception:
            pass


async def _run_swarm(prompt: str) -> str:
    """Execute via the swarm coordinator, with crash shield."""
    result, error = await shield.call_async(_swarm_inner, prompt)
    if error:
        return error
    return result


async def _swarm_inner(prompt: str) -> str:
    """Inner swarm execution (unshielded — called through shield)."""
    from core.swarm_coordinator import swarm

    app_state.set_agent_state("orchestrator", AgentState.RUNNING, prompt)
    app_state.set_agent_state("planner", AgentState.RUNNING, "analyzing")
    await asyncio.sleep(0.1)

    # Fire before_model_call hook
    runtime = _get_plugin_runtime()
    if runtime:
        try:
            runtime.emit_hook("before_model_call", {"prompt": prompt, "agent": "planner"})
        except Exception:
            pass

    result = swarm.execute(prompt, mode=app_state.swarm.mode)

    # Fire after_model_call hook
    if runtime:
        try:
            runtime.emit_hook("after_model_call", {"prompt": prompt, "agent": "planner"})
        except Exception:
            pass

    app_state.set_agent_state("planner", AgentState.SUCCESS)
    app_state.set_agent_state("coder", AgentState.RUNNING, "implementing")
    await asyncio.sleep(0.1)

    app_state.set_agent_state("coder", AgentState.SUCCESS)
    app_state.set_agent_state("critic", AgentState.RUNNING, "reviewing")
    await asyncio.sleep(0.05)

    app_state.set_agent_state("critic", AgentState.SUCCESS)
    app_state.set_agent_state("orchestrator", AgentState.SUCCESS)

    # Format result for display
    status = result.get("status", "unknown")
    duration = result.get("duration_ms", 0)
    dag = result.get("dag", {})
    progress = dag.get("progress", {})
    consensus = result.get("consensus")

    parts = [
        f"Swarm execution: {status}",
        f"Duration: {duration}ms",
        f"Nodes: {progress.get('total', 0)} total, {progress.get('completed', 0)} completed",
    ]
    if consensus:
        parts.append(f"Consensus: {consensus.get('decision', '?')} ({consensus.get('strategy', '?')})")
        parts.append(f"Reasoning: {consensus.get('reasoning', '')}")

    merge = result.get("merge", {})
    if merge:
        parts.append(f"Merge: {merge.get('status', '?')}, conflicts: {merge.get('total_conflicts', 0)}")

    return "\n".join(parts)


async def _run_single(prompt: str) -> str:
    """Execute via the single-agent orchestrator, with crash shield."""
    result, error = await shield.call_async(_single_inner, prompt)
    if error:
        return error
    return result


async def _single_inner(prompt: str) -> str:
    """Inner single-agent execution (unshielded — called through shield)."""
    from core.orchestrator import Orchestrator

    app_state.set_agent_state("coder", AgentState.RUNNING, prompt)

    # Fire before_model_call hook
    runtime = _get_plugin_runtime()
    if runtime:
        try:
            runtime.emit_hook("before_model_call", {"prompt": prompt, "agent": "coder"})
        except Exception:
            pass

    orch = Orchestrator()
    result = orch.run(prompt)

    # Fire after_model_call hook
    if runtime:
        try:
            runtime.emit_hook("after_model_call", {"prompt": prompt, "agent": "coder", "result_status": result.get("status")})
        except Exception:
            pass

    app_state.set_agent_state("coder", AgentState.SUCCESS)

    status = result.get("status", "unknown")
    if status == "completed" and isinstance(result.get("result"), dict):
        r = result["result"]
        steps = r.get("steps_executed", "?")
        blocked = r.get("steps_blocked", 0)
        return f"Completed: {steps} steps executed, {blocked} blocked"
    elif status == "completed":
        return f"Completed"
    else:
        error = result.get("error", "unknown error")
        return f"Failed: {error}"


def get_system_stats() -> dict:
    """Fetch current system statistics from the v13 engine (shielded)."""
    stats = {
        "models": [],
        "swarm": {},
        "jobs": {},
        "fabric": {},
        "policy": {},
    }

    result, _ = shield.call(_safe_models)
    if result:
        stats["models"] = result

    result, _ = shield.call(_safe_swarm_stats)
    if result:
        stats["swarm"] = result

    result, _ = shield.call(_safe_policy_stats)
    if result:
        stats["policy"] = result

    result, _ = shield.call(_safe_fabric_stats)
    if result:
        stats["fabric"] = result

    result, _ = shield.call(_safe_consensus_stats)
    if result:
        stats["consensus"] = result

    # Add plugin runtime stats
    runtime = _get_plugin_runtime()
    if runtime:
        try:
            stats["plugins"] = runtime.stats()
        except Exception:
            pass

    return stats


def _safe_models():
    from core.model_registry import ModelRegistry
    return list(ModelRegistry().to_dict().keys())

def _safe_swarm_stats():
    from core.swarm_coordinator import swarm
    return swarm.stats()

def _safe_policy_stats():
    from core.policy_engine import policy
    return policy.stats()

def _safe_fabric_stats():
    from core.distributed_workers import fabric
    return fabric.stats()

def _safe_consensus_stats():
    from core.consensus import consensus
    return consensus.stats()
