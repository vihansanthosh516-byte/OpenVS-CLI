"""OpenVS Plugin SDK — extensible plugin runtime system.

Enables third-party plugins to:
- Register slash commands
- Hook into engine lifecycle events
- Add tools to the swarm execution graph
- Render custom UI panels
- Interact with swarm state

Plugins are sandboxed: they never touch raw engine internals.
All interaction goes through the PluginContext API.
"""

from openvs.plugins.runtime import plugin_runtime

__all__ = ["plugin_runtime"]