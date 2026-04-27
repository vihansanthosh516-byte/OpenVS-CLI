"""
Project Manager — multi-project workspace support.

Each project gets its own:
- .openvs/project.json
- Model selection
- Plugin set
- Memory store
- Git context
"""

import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Project:
    """A single OpenVS project configuration."""
    name: str
    path: str = ""
    model: str = "qwen"
    swarm_mode: str = "parallel"
    swarm_enabled: bool = True
    plugins: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    profile: str = "fullstack"
    created_at: float = field(default_factory=time.time)


class ProjectManager:
    """Manages multiple OpenVS project workspaces."""

    def __init__(self):
        self._projects: dict[str, Project] = {}
        self._active_project: Optional[str] = None
        self._load_all()

    def create_project(self, name: str, path: str = "", **kwargs) -> dict:
        """Create a new project."""
        project = Project(
            name=name, path=path,
            model=kwargs.get("model", "qwen"),
            swarm_mode=kwargs.get("swarm_mode", "parallel"),
            plugins=kwargs.get("plugins", []),
            extensions=kwargs.get("extensions", []),
        )
        self._projects[name] = project
        self._save_project(name)
        return {"status": "created", "project": name}

    def switch_project(self, name: str) -> dict:
        """Switch to a different project context."""
        if name not in self._projects:
            return {"status": "not_found", "project": name}
        self._active_project = name
        project = self._projects[name]

        # Apply project context
        try:
            from openvs.core.app_state import app_state
            app_state.set_model(project.model)
            app_state.swarm.mode = project.swarm_mode
            app_state.set_swarm_enabled(project.swarm_enabled)
        except Exception:
            pass

        return {"status": "switched", "project": name, "model": project.model}

    def get_active(self) -> Optional[Project]:
        if self._active_project and self._active_project in self._projects:
            return self._projects[self._active_project]
        return None

    def list_projects(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "path": p.path,
                "model": p.model,
                "active": p.name == self._active_project,
            }
            for p in self._projects.values()
        ]

    def remove_project(self, name: str) -> dict:
        if name in self._projects:
            del self._projects[name]
            if self._active_project == name:
                self._active_project = None
            return {"status": "removed", "project": name}
        return {"status": "not_found", "project": name}

    def _save_project(self, name: str):
        project = self._projects.get(name)
        if not project:
            return
        project_dir = Path(project.path or ".") / ".openvs"
        project_dir.mkdir(parents=True, exist_ok=True)
        config_path = project_dir / "project.json"
        config_path.write_text(json.dumps({
            "name": project.name,
            "model": project.model,
            "swarm_mode": project.swarm_mode,
            "swarm_enabled": project.swarm_enabled,
            "plugins": project.plugins,
            "extensions": project.extensions,
            "profile": project.profile,
        }, indent=2), encoding="utf-8")

    def _load_all(self):
        # Load from ~/.openvs/projects.json
        projects_file = Path.home() / ".openvs" / "projects.json"
        if projects_file.exists():
            try:
                data = json.loads(projects_file.read_text(encoding="utf-8"))
                for name, info in data.items():
                    self._projects[name] = Project(
                        name=name,
                        path=info.get("path", ""),
                        model=info.get("model", "qwen"),
                        swarm_mode=info.get("swarm_mode", "parallel"),
                        plugins=info.get("plugins", []),
                        extensions=info.get("extensions", []),
                    )
                if data:
                    self._active_project = list(data.keys())[0]
            except Exception:
                pass