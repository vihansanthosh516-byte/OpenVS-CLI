"""
Auto-Updater — checks for new versions and updates OpenVS CLI.

Supports:
- Manual: openvs update
- Check on startup (silent)
- Channels: stable, beta, nightly
- Self-update via pip
"""

import sys
import os
import json
import time
import subprocess
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from openvs import __version__


UPDATE_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".openvs", "update_config.json")

PYPI_PACKAGE = "openvs-cli"
NPM_PACKAGE = "openvs-cli"


class UpdateChannel:
    STABLE = "stable"
    BETA = "beta"
    NIGHTLY = "nightly"


class UpdateStatus:
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    CHECK_FAILED = "check_failed"
    UPDATED = "updated"
    UPDATE_FAILED = "update_failed"


def get_update_config() -> dict:
    """Load update configuration."""
    defaults = {
        "channel": UpdateChannel.STABLE,
        "auto_check": True,
        "last_check": 0,
        "check_interval_hours": 24,
        "last_version_seen": __version__,
    }
    if os.path.exists(UPDATE_CONFIG_PATH):
        try:
            with open(UPDATE_CONFIG_PATH, "r") as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_update_config(config: dict):
    """Save update configuration."""
    os.makedirs(os.path.dirname(UPDATE_CONFIG_PATH), exist_ok=True)
    with open(UPDATE_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def check_for_update(force: bool = False) -> dict:
    """Check if a new version is available.

    Returns:
        {"status": "up_to_date"|"update_available"|"check_failed",
         "current": str, "latest": str|null, "channel": str}
    """
    config = get_update_config()

    # Skip if checked recently (unless forced)
    if not force:
        elapsed = time.time() - config.get("last_check", 0)
        interval = config.get("check_interval_hours", 24) * 3600
        if elapsed < interval:
            return {
                "status": UpdateStatus.UP_TO_DATE,
                "current": __version__,
                "latest": config.get("last_version_seen", __version__),
                "channel": config["channel"],
                "reason": "checked recently",
            }

    # Check PyPI for latest version
    latest = _fetch_latest_version(config["channel"])
    config["last_check"] = time.time()

    if latest:
        config["last_version_seen"] = latest
        save_update_config(config)

        if _version_is_newer(latest, __version__):
            return {
                "status": UpdateStatus.UPDATE_AVAILABLE,
                "current": __version__,
                "latest": latest,
                "channel": config["channel"],
            }
        else:
            return {
                "status": UpdateStatus.UP_TO_DATE,
                "current": __version__,
                "latest": latest,
                "channel": config["channel"],
            }

    save_update_config(config)
    return {
        "status": UpdateStatus.CHECK_FAILED,
        "current": __version__,
        "latest": None,
        "channel": config["channel"],
    }


def perform_update(channel: str = None) -> dict:
    """Run the update via pip.

    Returns:
        {"status": "updated"|"update_failed", "version": str}
    """
    config = get_update_config()
    if channel:
        config["channel"] = channel
        save_update_config(config)

    # Determine pip install target
    tag = config["channel"]
    if tag == UpdateChannel.STABLE:
        target = PYPI_PACKAGE
    elif tag == UpdateChannel.BETA:
        target = f"{PYPI_PACKAGE} --pre"
    else:
        target = PYPI_PACKAGE  # nightly uses latest

    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
        cmd.extend(target.split())
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            # Reload version after update
            try:
                from importlib import reload
                import openvs
                reload(openvs)
                new_version = openvs.__version__
            except Exception:
                new_version = "updated"

            return {
                "status": UpdateStatus.UPDATED,
                "version": new_version,
                "output": result.stdout[:200],
            }
        else:
            return {
                "status": UpdateStatus.UPDATE_FAILED,
                "error": result.stderr[:200],
            }
    except Exception as e:
        return {
            "status": UpdateStatus.UPDATE_FAILED,
            "error": str(e)[:200],
        }


def startup_check() -> Optional[dict]:
    """Run on startup. Returns update info if available, None otherwise."""
    config = get_update_config()
    if not config.get("auto_check", True):
        return None

    result = check_for_update(force=False)
    if result.get("status") == UpdateStatus.UPDATE_AVAILABLE:
        return result
    return None


def set_channel(channel: str) -> dict:
    """Set the update channel."""
    valid = [UpdateChannel.STABLE, UpdateChannel.BETA, UpdateChannel.NIGHTLY]
    if channel not in valid:
        return {"status": "error", "reason": f"Invalid channel. Use: {', '.join(valid)}"}
    config = get_update_config()
    config["channel"] = channel
    save_update_config(config)
    return {"status": "ok", "channel": channel}


def _fetch_latest_version(channel: str) -> Optional[str]:
    """Fetch the latest version from PyPI."""
    try:
        import urllib.request
        url = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "openvs-cli"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
        return None


def _version_is_newer(remote: str, local: str) -> bool:
    """Compare version strings. Returns True if remote > local."""
    def parse(v):
        try:
            return [int(x) for x in v.split(".")]
        except Exception:
            return [0]

    r = parse(remote)
    l = parse(local)
    return r > l
