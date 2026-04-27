"""
Context Switcher — switch project contexts (models, plugins, memory).

When switching projects, this module:
1. Saves current project state
2. Loads target project config
3. Reconfigures app_state, plugins, model selection
"""

from openvs.workspace.project import ProjectManager

project_manager = ProjectManager()


class ContextSwitcher:
    """Handles project context switches."""

    def switch(self, project_name: str) -> dict:
        """Switch to a different project context."""
        return project_manager.switch_project(project_name)

    def current(self) -> dict:
        """Get current project context info."""
        project = project_manager.get_active()
        if project:
            return {
                "project": project.name,
                "model": project.model,
                "swarm_mode": project.swarm_mode,
                "plugins": project.plugins,
            }
        return {"project": "default", "model": "qwen"}


context_switcher = ContextSwitcher()