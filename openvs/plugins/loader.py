"""
Plugin Loader — discovers and loads plugins from ~/.openvs/plugins/.

Scans each subdirectory for a plugin.json manifest, validates it,
then dynamically loads the entry module via importlib.

Schema validation catches broken manifests before they crash the system.
"""

import json
import importlib.util
import time
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field


PLUGIN_DIR = Path.home() / ".openvs" / "plugins"

MANIFEST_SCHEMA = {
    "required": ["name", "version", "entry"],
    "optional": ["description", "author", "commands", "hooks", "tools",
                 "permissions", "engine_version", "agent_roles"],
}

HOOK_TYPES = {
    "before_run", "after_run",
    "before_model_call", "after_model_call",
    "before_patch", "after_patch",
    "on_job_start", "on_job_complete",
    "on_worker_spawn", "on_worker_fail",
    "on_consensus_vote", "on_diff_accept", "on_diff_reject",
}


@dataclass
class LoadedPlugin:
    """A fully loaded plugin with its manifest and Python module."""
    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    entry: str = "index.py"
    manifest: dict = field(default_factory=dict)
    module: Optional[Any] = None
    commands: list[dict] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    engine_version: str = ""
    enabled: bool = True
    loaded_at: float = field(default_factory=time.time)
    load_error: Optional[str] = None


class PluginLoader:
    """Discovers, validates, and loads plugins from the plugin directory."""

    def __init__(self):
        self.plugins: dict[str, LoadedPlugin] = {}
        self._load_errors: list[dict] = []

    def load_all(self) -> dict:
        """Scan plugin directory and load all valid plugins."""
        self.plugins.clear()
        self._load_errors.clear()

        if not PLUGIN_DIR.exists():
            PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
            return {"loaded": 0, "errors": 0}

        loaded = 0
        errors = 0

        for plugin_path in sorted(PLUGIN_DIR.iterdir()):
            if not plugin_path.is_dir():
                continue
            if plugin_path.name.startswith(".") or plugin_path.name.startswith("__"):
                continue

            result = self.load_plugin(plugin_path)
            if result:
                loaded += 1
            else:
                errors += 1

        return {"loaded": loaded, "errors": errors}

    def load_plugin(self, path: Path) -> Optional[LoadedPlugin]:
        """Load a single plugin from its directory."""
        manifest_path = path / "plugin.json"

        if not manifest_path.exists():
            self._load_errors.append({
                "path": str(path),
                "error": "No plugin.json found",
            })
            return None

        # Read and validate manifest
        try:
            raw = manifest_path.read_text(encoding="utf-8")
            manifest = json.loads(raw)
        except json.JSONDecodeError as e:
            self._load_errors.append({
                "path": str(path),
                "error": f"Invalid JSON: {e}",
            })
            return None

        # Validate required fields
        for field_name in MANIFEST_SCHEMA["required"]:
            if field_name not in manifest:
                self._load_errors.append({
                    "path": str(path),
                    "error": f"Missing required field: {field_name}",
                })
                return None

        # Validate hook names
        for hook in manifest.get("hooks", []):
            if hook not in HOOK_TYPES:
                self._load_errors.append({
                    "path": str(path),
                    "error": f"Unknown hook type: {hook}",
                })
                # Don't fail — just skip this hook later

        # Check engine version compatibility
        engine_version = manifest.get("engine_version", "")
        if engine_version:
            try:
                from openvs import __version__
                if not _version_compatible(engine_version, __version__):
                    self._load_errors.append({
                        "path": str(path),
                        "error": f"Requires engine >= {engine_version}, have {__version__}",
                    })
                    return None
            except Exception:
                pass

        # Load entry module
        entry_file = path / manifest["entry"]
        if not entry_file.exists():
            self._load_errors.append({
                "path": str(path),
                "error": f"Entry file not found: {manifest['entry']}",
            })
            return None

        module = None
        load_error = None
        try:
            spec = importlib.util.spec_from_file_location(
                f"openvs_plugin_{manifest['name']}",
                str(entry_file),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            load_error = str(e)
            self._load_errors.append({
                "path": str(path),
                "error": f"Failed to load module: {e}",
            })

        plugin = LoadedPlugin(
            name=manifest["name"],
            version=manifest.get("version", "0.0.0"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            entry=manifest.get("entry", "index.py"),
            manifest=manifest,
            module=module,
            commands=manifest.get("commands", []),
            hooks=manifest.get("hooks", []),
            tools=manifest.get("tools", []),
            permissions=manifest.get("permissions", []),
            engine_version=engine_version,
            load_error=load_error,
        )

        self.plugins[manifest["name"]] = plugin
        return plugin

    def reload_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """Reload a single plugin by name."""
        if name not in self.plugins:
            return None

        plugin = self.plugins[name]
        # Find its directory
        for plugin_path in PLUGIN_DIR.iterdir():
            if plugin_path.is_dir() and plugin_path.name == name:
                return self.load_plugin(plugin_path)

        return None

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        return self.plugins.get(name)

    def list_plugins(self) -> list[dict]:
        """Return plugin info dicts for display."""
        results = []
        for p in self.plugins.values():
            results.append({
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "enabled": p.enabled,
                "commands": [c.get("name", "?") if isinstance(c, dict) else c for c in p.commands],
                "hooks": p.hooks,
                "tools": p.tools,
                "permissions": p.permissions,
                "load_error": p.load_error,
            })
        return results

    def load_errors(self) -> list[dict]:
        return list(self._load_errors)

    def stats(self) -> dict:
        return {
            "total_plugins": len(self.plugins),
            "enabled": sum(1 for p in self.plugins.values() if p.enabled),
            "disabled": sum(1 for p in self.plugins.values() if not p.enabled),
            "load_errors": len(self._load_errors),
            "plugin_dir": str(PLUGIN_DIR),
        }


def _version_compatible(required: str, actual: str) -> bool:
    """Check if actual version satisfies >= required."""
    def parse(v):
        try:
            return [int(x) for x in v.lstrip(">=").split(".")]
        except Exception:
            return [0]

    return parse(actual) >= parse(required)