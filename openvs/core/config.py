"""
Config — persistent configuration for OpenVS CLI.

Stores user preferences at ~/.openvs/config.json:
- Provider selection
- Default model
- Update channel
- Swarm defaults
- Plugin preferences

This is the single source of truth for all persistent settings.
.env is for secrets. config.json is for everything else.
"""

import os
import json
from typing import Optional


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".openvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "provider": "nvidia",
    "default_model": "qwen",
    "update_channel": "stable",
    "auto_check_updates": True,
    "swarm_enabled": True,
    "swarm_mode": "parallel",
    "worker_count": 3,
    "profile": "fullstack",
    "telemetry_enabled": False,
    "session_restore": True,
}


def load_config() -> dict:
    """Load config from disk, merging with defaults."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            config.update(saved)
        except Exception:
            pass
    return config


def save_config(config: dict):
    """Save config to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, default=None):
    """Get a single config value."""
    config = load_config()
    return config.get(key, default)


def set(key: str, value) -> dict:
    """Set a single config value and save."""
    config = load_config()
    config[key] = value
    save_config(config)
    return {"status": "ok", "key": key, "value": value}


def reset() -> dict:
    """Reset config to defaults."""
    save_config(dict(DEFAULT_CONFIG))
    return {"status": "reset", "config": DEFAULT_CONFIG}


def show() -> str:
    """Format config for display."""
    config = load_config()
    lines = ["OpenVS Config:", ""]
    for key, value in sorted(config.items()):
        lines.append(f"  {key:24s} = {value}")
    lines.append("")
    lines.append(f"  Config file: {CONFIG_PATH}")
    return "\n".join(lines)
