"""
Plugin System — extensible architecture for OpenVS CLI.

Plugins can add:
- Commands (/audit, /review-pr)
- Tools (custom tool implementations)
- Hooks (pre_patch, post_run, worker_failure, etc.)
- Panels (custom UI panels)

Install: openvs plugin install <name>
Remove:  openvs plugin remove <name>
List:    openvs plugin list
"""

import os
import json
import time
from dataclasses import dataclass, field
from typing import Optional, Callable


PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".openvs", "plugins")


@dataclass
class PluginManifest:
    """A plugin's manifest — defines what it provides."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    commands: list[str] = field(default_factory=list)     # e.g. ["/audit"]
    tools: list[str] = field(default_factory=list)         # e.g. ["kubernetes_apply"]
    hooks: list[str] = field(default_factory=list)         # e.g. ["pre_patch", "post_run"]
    agent_roles: list[str] = field(default_factory=list)   # e.g. ["security_auditor"]
    dependencies: list[str] = field(default_factory=list)  # e.g. ["kubernetes"]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "commands": self.commands,
            "tools": self.tools,
            "hooks": self.hooks,
            "agent_roles": self.agent_roles,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            commands=data.get("commands", []),
            tools=data.get("tools", []),
            hooks=data.get("hooks", []),
            agent_roles=data.get("agent_roles", []),
            dependencies=data.get("dependencies", []),
        )


@dataclass
class PluginInstance:
    """A loaded plugin with its manifest and handler functions."""
    manifest: PluginManifest
    installed_at: float = field(default_factory=time.time)
    enabled: bool = True
    _command_handlers: dict = field(default_factory=dict)
    _hook_handlers: dict = field(default_factory=dict)

    def register_command(self, command: str, handler: Callable):
        """Register a handler for a slash command."""
        self._command_handlers[command] = handler

    def register_hook(self, hook: str, handler: Callable):
        """Register a handler for an event hook."""
        self._hook_handlers.setdefault(hook, []).append(handler)

    def handle_command(self, command: str, args: str = "") -> Optional[str]:
        """Try to handle a command. Returns None if not handled."""
        handler = self._command_handlers.get(command)
        if handler:
            try:
                return handler(args)
            except Exception as e:
                return f"Plugin error ({self.manifest.name}): {e}"
        return None

    def fire_hook(self, hook: str, data: dict = None):
        """Fire an event hook to all registered handlers."""
        for handler in self._hook_handlers.get(hook, []):
            try:
                handler(data or {})
            except Exception:
                pass  # plugins must not crash the host


class PluginManager:
    """Manages plugin lifecycle: install, remove, enable, disable, execute.

    Plugins are stored in ~/.openvs/plugins/<name>/
    Each plugin directory contains:
      - manifest.json (plugin metadata)
      - plugin.py (plugin code, optional)
    """

    HOOKS = [
        "before_model_call",
        "after_model_call",
        "pre_patch",
        "post_patch",
        "pre_run",
        "post_run",
        "worker_failure",
        "job_complete",
        "diff_accept",
        "diff_reject",
        "consensus_vote",
        "swarm_start",
        "swarm_complete",
    ]

    def __init__(self):
        self._plugins: dict[str, PluginInstance] = {}
        os.makedirs(PLUGIN_DIR, exist_ok=True)
        self._load_all()

    def _load_all(self):
        """Load all installed plugins from disk."""
        if not os.path.exists(PLUGIN_DIR):
            return
        for name in os.listdir(PLUGIN_DIR):
            plugin_path = os.path.join(PLUGIN_DIR, name)
            if os.path.isdir(plugin_path):
                manifest_path = os.path.join(plugin_path, "manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, "r") as f:
                            data = json.load(f)
                        manifest = PluginManifest.from_dict(data)
                        self._plugins[name] = PluginInstance(manifest=manifest)
                    except Exception:
                        pass  # skip broken plugins

    def install(self, name: str, manifest: PluginManifest) -> dict:
        """Install a plugin by writing its manifest to disk."""
        plugin_path = os.path.join(PLUGIN_DIR, name)
        os.makedirs(plugin_path, exist_ok=True)

        manifest_path = os.path.join(plugin_path, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest.to_dict(), f, indent=2)

        instance = PluginInstance(manifest=manifest)
        self._plugins[name] = instance

        return {"status": "installed", "plugin": name, "version": manifest.version}

    def remove(self, name: str) -> dict:
        """Remove a plugin."""
        if name not in self._plugins:
            return {"status": "not_found", "plugin": name}

        del self._plugins[name]

        plugin_path = os.path.join(PLUGIN_DIR, name)
        if os.path.exists(plugin_path):
            import shutil
            shutil.rmtree(plugin_path)

        return {"status": "removed", "plugin": name}

    def enable(self, name: str) -> dict:
        if name in self._plugins:
            self._plugins[name].enabled = True
            return {"status": "enabled", "plugin": name}
        return {"status": "not_found", "plugin": name}

    def disable(self, name: str) -> dict:
        if name in self._plugins:
            self._plugins[name].enabled = False
            return {"status": "disabled", "plugin": name}
        return {"status": "not_found", "plugin": name}

    def list_plugins(self) -> list[dict]:
        """List all installed plugins."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "enabled": p.enabled,
                "commands": p.manifest.commands,
                "hooks": p.manifest.hooks,
            }
            for p in self._plugins.values()
        ]

    def handle_command(self, command: str, args: str = "") -> Optional[str]:
        """Try to handle a command across all enabled plugins."""
        for plugin in self._plugins.values():
            if not plugin.enabled:
                continue
            result = plugin.handle_command(command, args)
            if result is not None:
                return result
        return None

    def fire_hook(self, hook: str, data: dict = None):
        """Fire an event hook to all enabled plugins."""
        if hook not in self.HOOKS:
            return
        for plugin in self._plugins.values():
            if plugin.enabled:
                plugin.fire_hook(hook, data)

    def stats(self) -> dict:
        return {
            "total_plugins": len(self._plugins),
            "enabled": sum(1 for p in self._plugins.values() if p.enabled),
            "disabled": sum(1 for p in self._plugins.values() if not p.enabled),
            "available_hooks": self.HOOKS,
            "plugin_dir": PLUGIN_DIR,
        }


# Global singleton
plugin_manager = PluginManager()


# ---- Built-in starter plugins ----

def install_starter_plugins():
    """Install the 5 starter plugins if not already installed."""
    starters = [
        PluginManifest(
            name="github-pr-reviewer",
            version="1.0.0",
            description="Review GitHub pull requests with AI analysis",
            commands=["/pr-review"],
            hooks=["post_patch", "diff_accept"],
            author="OpenVS",
        ),
        PluginManifest(
            name="security-audit",
            version="1.0.0",
            description="Automated security auditing for code changes",
            commands=["/audit"],
            hooks=["pre_patch", "post_run"],
            agent_roles=["security_auditor"],
            author="OpenVS",
        ),
        PluginManifest(
            name="test-generator",
            version="1.0.0",
            description="Auto-generate test cases for code changes",
            commands=["/gen-tests"],
            hooks=["post_patch"],
            author="OpenVS",
        ),
        PluginManifest(
            name="kubernetes-agent",
            version="1.0.0",
            description="Kubernetes deployment and management agent",
            commands=["/k8s-deploy", "/k8s-status"],
            hooks=["post_run"],
            tools=["kubernetes_apply", "kubernetes_rollout"],
            author="OpenVS",
        ),
        PluginManifest(
            name="docs-writer",
            version="1.0.0",
            description="Auto-generate documentation from code",
            commands=["/docs"],
            hooks=["post_patch"],
            agent_roles=["doc_writer"],
            author="OpenVS",
        ),
    ]

    installed = 0
    for manifest in starters:
        if manifest.name not in plugin_manager._plugins:
            plugin_manager.install(manifest.name, manifest)
            installed += 1

    return {"installed": installed, "total_starters": len(starters)}
