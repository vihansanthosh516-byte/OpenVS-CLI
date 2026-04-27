"""
Plugin Registry — tracks installed plugins, versions, permissions.

Distinct from the simpler core/plugins.py PluginManager.
This registry tracks the full SDK-level plugin metadata:
- Version and engine compatibility
- Declared permissions (with user approval state)
- Installation source (local, marketplace, url)
- Ratings and install counts (for marketplace)

The registry persists to ~/.openvs/plugin_registry.json.
"""

import json
import time
from pathlib import Path
from typing import Optional


REGISTRY_PATH = Path.home() / ".openvs" / "plugin_registry.json"


class PluginRegistry:
    """Persistent registry of installed plugins."""

    def __init__(self):
        self._entries: dict[str, dict] = {}
        self._load_from_disk()

    def register(self, name: str, manifest: dict) -> dict:
        """Register a plugin in the registry."""
        entry = {
            "name": name,
            "version": manifest.get("version", "0.0.0"),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "permissions": manifest.get("permissions", []),
            "permissions_approved": False,
            "hooks": manifest.get("hooks", []),
            "commands": manifest.get("commands", []),
            "tools": manifest.get("tools", []),
            "engine_version": manifest.get("engine_version", ""),
            "source": manifest.get("source", "local"),
            "enabled": True,
            "installed_at": time.time(),
            "updated_at": time.time(),
        }

        # Preserve existing approval state and timestamps on re-register
        if name in self._entries:
            old = self._entries[name]
            entry["permissions_approved"] = old.get("permissions_approved", False)
            entry["installed_at"] = old.get("installed_at", time.time())

        self._entries[name] = entry
        self._save_to_disk()

        return {"status": "registered", "plugin": name}

    def unregister(self, name: str) -> dict:
        """Remove a plugin from the registry."""
        if name in self._entries:
            del self._entries[name]
            self._save_to_disk()
            return {"status": "removed", "plugin": name}
        return {"status": "not_found", "plugin": name}

    def get(self, name: str) -> Optional[dict]:
        return self._entries.get(name)

    def list_plugins(self) -> list[dict]:
        return list(self._entries.values())

    def approve_permissions(self, name: str) -> dict:
        """Mark a plugin's permissions as approved by the user."""
        if name not in self._entries:
            return {"status": "not_found", "plugin": name}
        self._entries[name]["permissions_approved"] = True
        self._save_to_disk()
        return {"status": "approved", "plugin": name}

    def set_enabled(self, name: str, enabled: bool) -> dict:
        """Enable or disable a plugin."""
        if name not in self._entries:
            return {"status": "not_found", "plugin": name}
        self._entries[name]["enabled"] = enabled
        self._entries[name]["updated_at"] = time.time()
        self._save_to_disk()
        return {"status": "ok", "plugin": name, "enabled": enabled}

    def needs_approval(self, name: str) -> bool:
        """Check if a plugin has permissions that need user approval."""
        entry = self._entries.get(name)
        if not entry:
            return False
        if not entry.get("permissions"):
            return False
        return not entry.get("permissions_approved", False)

    def pending_approvals(self) -> list[dict]:
        """List plugins that need permission approval."""
        return [
            e for e in self._entries.values()
            if e.get("permissions") and not e.get("permissions_approved", False)
        ]

    def stats(self) -> dict:
        return {
            "total_plugins": len(self._entries),
            "enabled": sum(1 for e in self._entries.values() if e.get("enabled")),
            "pending_approvals": len(self.pending_approvals()),
            "registry_path": str(REGISTRY_PATH),
        }

    def _load_from_disk(self):
        """Load registry from disk."""
        if REGISTRY_PATH.exists():
            try:
                data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._entries = data
            except Exception:
                pass

    def _save_to_disk(self):
        """Persist registry to disk."""
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            REGISTRY_PATH.write_text(
                json.dumps(self._entries, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass