"""OpenVS Workspace — multi-project support, per-project config and context."""

from openvs.workspace.project import ProjectManager
from openvs.workspace.context_switch import ContextSwitcher

__all__ = ["ProjectManager", "ContextSwitcher"]
