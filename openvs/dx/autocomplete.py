"""
Autocomplete Engine — smart command completion for OpenVS CLI.

Provides fuzzy-matched completions for:
- Slash commands
- Model names
- Swarm modes
- Plugin names
- File paths
"""

from typing import Optional


class AutocompleteEngine:
    """Smart autocomplete for OpenVS commands and arguments."""

    COMMANDS = {
        "/model": ["qwen", "nemotron", "gemma", "glm", "local"],
        "/swarm": ["on", "off", "mode"],
        "/swarm mode": ["parallel", "pipeline", "debate", "map_reduce"],
        "/session": ["load", "save", "clear", "info"],
        "/update": ["check", "now", "channel"],
        "/update channel": ["stable", "beta", "nightly"],
        "/plugin": ["list", "install", "remove", "enable", "disable", "reload", "approve", "hooks", "stats"],
        "/ext": ["list", "enable", "disable"],
        "/profile": ["backend", "security", "devops", "frontend", "fullstack"],
        "/config": ["set", "get", "reset"],
        "/ext enable": ["github", "slack", "jira", "docker", "vscode"],
        "/ext disable": ["github", "slack", "jira", "docker", "vscode"],
    }

    ALL_COMMANDS = [
        "/model", "/swarm", "/jobs", "/trace", "/status", "/clear",
        "/help", "/agents", "/consensus", "/cluster", "/dags",
        "/doctor", "/crashes", "/plugin", "/ext", "/update",
        "/session", "/export", "/marketplace", "/profile",
        "/config", "/login", "/hello",
    ]

    def complete(self, text: str) -> list[str]:
        """Get completions for the given text."""
        text = text.strip()
        if not text:
            return self.ALL_COMMANDS

        parts = text.split()

        if len(parts) == 1:
            # Completing command name
            prefix = parts[0].lower()
            return [c for c in self.ALL_COMMANDS if c.startswith(prefix)]

        if len(parts) == 2:
            # Completing first argument
            cmd = parts[0].lower()
            completions = self.COMMANDS.get(cmd, [])
            prefix = parts[1].lower()
            return [c for c in completions if c.startswith(prefix)]

        if len(parts) >= 3:
            # Completing deeper arguments
            key = f"{parts[0]} {parts[1]}"
            completions = self.COMMANDS.get(key, [])
            if completions:
                prefix = parts[-1].lower()
                return [c for c in completions if c.startswith(prefix)]

        return []

    def complete_plugin_names(self, prefix: str = "") -> list[str]:
        """Get plugin name completions."""
        try:
            from openvs.plugins.runtime import plugin_runtime
            if plugin_runtime._loaded:
                names = [p["name"] for p in plugin_runtime.list_plugins()]
                if prefix:
                    return [n for n in names if n.startswith(prefix)]
                return names
        except Exception:
            pass
        return []


# Global singleton
autocomplete = AutocompleteEngine()
