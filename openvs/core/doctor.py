"""
Doctor — health check system for OpenVS CLI.

Runs diagnostics and reports:
- API keys configured
- Models reachable
- Swarm engine healthy
- Dependencies installed
- Memory store working
- Event store working
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def run_doctor() -> dict:
    """Run all health checks. Returns a dict of results."""
    checks = {
        "keys": _check_keys(),
        "models": _check_models(),
        "swarm": _check_swarm(),
        "policy": _check_policy(),
        "consensus": _check_consensus(),
        "fabric": _check_fabric(),
        "memory": _check_memory(),
        "events": _check_events(),
        "dependencies": _check_dependencies(),
        "config": _check_config(),
    }

    total = len(checks)
    passed = sum(1 for v in checks.values() if v["status"] == "ok")
    failed = sum(1 for v in checks.values() if v["status"] == "fail")
    warned = sum(1 for v in checks.values() if v["status"] == "warn")

    return {
        "checks": checks,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "healthy": failed == 0,
        },
    }


def format_doctor(result: dict) -> str:
    """Format doctor results for terminal display."""
    checks = result["checks"]
    summary = result["summary"]

    lines = ["", " OpenVS CLI Doctor", "=" * 50, ""]

    for name, check in checks.items():
        icon = {"ok": "[green]✓[/]", "warn": "[yellow]⚠[/]", "fail": "[red]✗[/]"}[check["status"]]
        lines.append(f" {icon} {name:15s} — {check['message']}")

    lines.append("")
    lines.append("=" * 50)
    if summary["healthy"]:
        lines.append(f" [green]All {summary['total']} checks passed[/]")
    else:
        lines.append(f" {summary['passed']}/{summary['total']} passed, {summary['failed']} failed, {summary['warned']} warnings")

    return "\n".join(lines)


def _check_keys() -> dict:
    try:
        from core.key_manager import KeyManager
        km = KeyManager()
        configured = km.list_configured()
        if not configured:
            return {"status": "warn", "message": "No API keys configured"}
        return {"status": "ok", "message": f"{len(configured)} provider(s): {', '.join(configured)}"}
    except Exception as e:
        return {"status": "fail", "message": f"Key manager error: {str(e)[:80]}"}


def _check_models() -> dict:
    try:
        from core.model_registry import ModelRegistry
        reg = ModelRegistry()
        models = reg.list_models()
        if not models:
            return {"status": "warn", "message": "No models registered"}
        return {"status": "ok", "message": f"{len(models)} models: {', '.join(models)}"}
    except Exception as e:
        return {"status": "fail", "message": f"Model registry error: {str(e)[:80]}"}


def _check_swarm() -> dict:
    try:
        from core.swarm_coordinator import swarm
        stats = swarm.stats()
        return {"status": "ok", "message": f"DAGs: {stats['active_dags']}, Strategy: {stats['consensus_strategy']}"}
    except Exception as e:
        return {"status": "fail", "message": f"Swarm engine error: {str(e)[:80]}"}


def _check_policy() -> dict:
    try:
        from core.policy_engine import policy
        stats = policy.stats()
        return {"status": "ok", "message": f"Tokens: {stats['tokens_issued']}, Denied: {stats['denied_actions']}"}
    except Exception as e:
        return {"status": "fail", "message": f"Policy engine error: {str(e)[:80]}"}


def _check_consensus() -> dict:
    try:
        from core.consensus import consensus
        stats = consensus.stats()
        return {"status": "ok", "message": f"Rounds: {stats['total_rounds']}, Strategy: {stats['default_strategy']}"}
    except Exception as e:
        return {"status": "fail", "message": f"Consensus engine error: {str(e)[:80]}"}


def _check_fabric() -> dict:
    try:
        from core.distributed_workers import fabric
        stats = fabric.stats()
        return {"status": "ok", "message": f"Workers: {stats['total_workers']}, Available: {stats['available']}"}
    except Exception as e:
        return {"status": "fail", "message": f"Worker fabric error: {str(e)[:80]}"}


def _check_memory() -> dict:
    try:
        from memory.memory import load_all_memory
        mem = load_all_memory()
        return {"status": "ok", "message": f"{len(mem)} entries loaded"}
    except Exception as e:
        return {"status": "warn", "message": f"Memory store error: {str(e)[:80]}"}


def _check_events() -> dict:
    try:
        from core.event_bus import bus
        stats = bus.store_stats()
        return {"status": "ok", "message": f"{stats.get('total_events', 0)} events, enabled: {stats.get('enabled', False)}"}
    except Exception as e:
        return {"status": "warn", "message": f"Event store error: {str(e)[:80]}"}


def _check_dependencies() -> dict:
    missing = []
    for pkg in ["fastapi", "uvicorn", "faiss", "numpy", "dotenv", "textual", "rich", "httpx"]:
        try:
            __import__(pkg)
        except ImportError:
            # Check alternate import names
            alt = {"dotenv": "python_dotenv", "faiss": "faiss-cpu"}
            try:
                if pkg in alt:
                    __import__(alt[pkg])
                else:
                    raise ImportError
            except ImportError:
                missing.append(pkg)

    if not missing:
        return {"status": "ok", "message": "All dependencies installed"}
    return {"status": "warn", "message": f"Missing: {', '.join(missing)}"}


def _check_config() -> dict:
    try:
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        if os.path.exists(env_path):
            return {"status": "ok", "message": f".env found at {env_path}"}
        return {"status": "warn", "message": "No .env file found"}
    except Exception as e:
        return {"status": "warn", "message": f"Config check error: {str(e)[:80]}"}
