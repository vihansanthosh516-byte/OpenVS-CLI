"""
Session Manager — persist and restore OpenVS CLI sessions.

When the user reopens OpenVS, they get their previous:
- Chat messages
- Model selection
- Swarm state
- Mode
- Command history

This is a massive usability upgrade.
"""

import os
import sys
import json
import time
from typing import Optional

sys_path_fix = os.path.join(os.path.dirname(__file__), "..", "..")
if sys_path_fix not in sys.path:
    sys.path.insert(0, sys_path_fix)


SESSION_DIR = os.path.join(os.path.expanduser("~"), ".openvs", "sessions")
LATEST_SESSION = os.path.join(SESSION_DIR, "latest.json")


def save_session(state: dict) -> dict:
    """Save the current session state to disk."""
    os.makedirs(SESSION_DIR, exist_ok=True)

    session = {
        "timestamp": time.time(),
        "model": state.get("model", "qwen"),
        "mode": state.get("mode", "chat"),
        "swarm_enabled": state.get("swarm_enabled", True),
        "swarm_mode": state.get("swarm_mode", "parallel"),
        "worker_count": state.get("worker_count", 3),
        "messages": state.get("messages", [])[-100:],  # keep last 100
        "command_history": state.get("command_history", [])[-20:],
    }

    # Write as latest
    with open(LATEST_SESSION, "w") as f:
        json.dump(session, f, indent=2)

    # Also write a timestamped copy (keep last 5)
    ts_path = os.path.join(SESSION_DIR, f"session_{int(time.time())}.json")
    with open(ts_path, "w") as f:
        json.dump(session, f, indent=2)

    _cleanup_old_sessions(max_keep=5)

    return {"status": "saved", "messages": len(session["messages"])}


def load_session() -> Optional[dict]:
    """Load the most recent session. Returns None if no session exists."""
    if not os.path.exists(LATEST_SESSION):
        return None

    try:
        with open(LATEST_SESSION, "r") as f:
            return json.load(f)
    except Exception:
        return None


def has_session() -> bool:
    """Check if a restorable session exists."""
    return os.path.exists(LATEST_SESSION)


def clear_sessions() -> dict:
    """Clear all saved sessions."""
    if os.path.exists(SESSION_DIR):
        import shutil
        shutil.rmtree(SESSION_DIR)
    os.makedirs(SESSION_DIR, exist_ok=True)
    return {"status": "cleared"}


def _cleanup_old_sessions(max_keep: int = 5):
    """Remove old timestamped sessions, keeping only the most recent."""
    sessions = []
    if not os.path.exists(SESSION_DIR):
        return

    for name in os.listdir(SESSION_DIR):
        if name.startswith("session_") and name.endswith(".json"):
            sessions.append(name)

    sessions.sort(reverse=True)

    for old in sessions[max_keep:]:
        try:
            os.remove(os.path.join(SESSION_DIR, old))
        except Exception:
            pass


def session_age_hours() -> Optional[float]:
    """How long since the last session was saved (in hours)."""
    if not os.path.exists(LATEST_SESSION):
        return None
    try:
        with open(LATEST_SESSION, "r") as f:
            data = json.load(f)
        elapsed = time.time() - data.get("timestamp", 0)
        return elapsed / 3600
    except Exception:
        return None


def export_diagnostics() -> dict:
    """Export a full diagnostic bundle for bug reports.

    Collects: system info, doctor results, crash log, session state,
    event stats, and config.
    """
    from openvs.core.doctor import run_doctor
    from openvs.core.shield import shield

    bundle = {
        "openvs_version": "1.0.0",
        "timestamp": time.time(),
        "doctor": run_doctor(),
        "crashes": shield.recent_crashes(limit=20),
        "crash_stats": shield.stats(),
        "session": load_session(),
    }

    try:
        from core.swarm_coordinator import swarm
        bundle["swarm_stats"] = swarm.stats()
    except Exception:
        pass

    try:
        from core.policy_engine import policy
        bundle["policy_stats"] = policy.stats()
    except Exception:
        pass

    try:
        from core.event_bus import bus
        bundle["event_stats"] = bus.store_stats()
    except Exception:
        pass

    try:
        from core.consensus import consensus
        bundle["consensus_stats"] = consensus.stats()
    except Exception:
        pass

    # Write to file
    export_dir = os.path.join(os.path.expanduser("~"), ".openvs", "diagnostics")
    os.makedirs(export_dir, exist_ok=True)
    export_path = os.path.join(export_dir, f"diag_{int(time.time())}.json")
    with open(export_path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    bundle["_export_path"] = export_path
    return bundle
