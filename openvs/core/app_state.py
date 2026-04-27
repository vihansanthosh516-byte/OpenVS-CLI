"""
Application State — global reactive state for OpenVS CLI.

All UI components read from this. State changes trigger re-renders.
No component owns state directly. This is the single source of truth.
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class AppMode(Enum):
    CHAT = "chat"
    DIFF = "diff"
    SWARM = "swarm"
    TRACE = "trace"
    JOBS = "jobs"


class AgentState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SystemStatus(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    PLANNING = "planning"
    EXECUTING = "executing"
    STREAMING = "streaming"
    DIFF_VIEW = "diff_view"
    ERROR = "error"


@dataclass
class AgentInfo:
    name: str
    role: str
    state: AgentState = AgentState.IDLE
    model: str = ""
    current_task: str = ""


@dataclass
class SwarmStatus:
    enabled: bool = True
    mode: str = "parallel"  # parallel, pipeline, debate, map_reduce
    agents: list[AgentInfo] = field(default_factory=list)
    active_dags: int = 0
    total_tasks: int = 0


@dataclass
class Message:
    role: str  # "user", "assistant", "system", "diff", "error"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class AppState:
    """Single source of truth for the entire application.

    UI components subscribe to changes. State mutations trigger re-renders.
    """

    def __init__(self):
        self.model: str = "qwen"
        self.mode: AppMode = AppMode.CHAT
        self.system_status: SystemStatus = SystemStatus.IDLE
        self.session_status: str = "active"
        self.worker_count: int = 3
        self.swarm: SwarmStatus = SwarmStatus(
            agents=[
                AgentInfo("Orchestrator", "orchestrator"),
                AgentInfo("Planner", "planner", model="nemotron"),
                AgentInfo("Coder", "coder", model="qwen"),
                AgentInfo("Critic", "critic", model="nemotron"),
                AgentInfo("Tester", "tester", model="gemma"),
            ]
        )
        self.messages: list[Message] = []
        self.current_stream: str = ""
        self.diff_content: Optional[dict] = None
        self.traces: list[dict] = field(default_factory=list)
        self.jobs: list[dict] = field(default_factory=list)
        self._listeners: list = []

    def on_change(self, callback):
        """Register a listener for state changes."""
        self._listeners.append(callback)

    def _notify(self, key: str, value):
        """Notify all listeners of a state change."""
        for cb in self._listeners:
            try:
                cb(key, value)
            except Exception:
                pass

    def set_mode(self, mode: AppMode):
        self.mode = mode
        self._notify("mode", mode)

    def set_model(self, model: str):
        self.model = model
        self._notify("model", model)

    def set_status(self, status: SystemStatus):
        self.system_status = status
        self._notify("status", status)

    def set_swarm_enabled(self, enabled: bool):
        self.swarm.enabled = enabled
        self._notify("swarm_enabled", enabled)

    def set_agent_state(self, role: str, state: AgentState, task: str = ""):
        for agent in self.swarm.agents:
            if agent.role == role:
                agent.state = state
                agent.current_task = task
                self._notify(f"agent_{role}", agent)
                break

    def add_message(self, role: str, content: str, metadata: dict = None):
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        self._notify("message", msg)

    def set_stream(self, text: str):
        self.current_stream = text
        self._notify("stream", text)

    def append_stream(self, token: str):
        self.current_stream += token
        self._notify("stream_token", token)

    def clear_stream(self):
        if self.current_stream:
            self.add_message("assistant", self.current_stream)
            self.current_stream = ""
        self._notify("stream_cleared", None)

    def set_diff(self, diff: dict):
        self.diff_content = diff
        self.mode = AppMode.DIFF
        self._notify("diff", diff)

    def status_bar_text(self) -> str:
        status_icons = {
            SystemStatus.IDLE: "idle",
            SystemStatus.THINKING: "thinking",
            SystemStatus.PLANNING: "planning",
            SystemStatus.EXECUTING: "executing",
            SystemStatus.STREAMING: "streaming",
            SystemStatus.DIFF_VIEW: "diff",
            SystemStatus.ERROR: "error",
        }
        return (
            f"model:{self.model} "
            f"swarm:{'ON' if self.swarm.enabled else 'OFF'} "
            f"workers:{self.worker_count} "
            f"session:{self.session_status} "
            f"status:{status_icons.get(self.system_status, '?')}"
        )

    def mode_cycle(self) -> AppMode:
        """Cycle to the next mode."""
        modes = list(AppMode)
        idx = modes.index(self.mode)
        next_mode = modes[(idx + 1) % len(modes)]
        self.set_mode(next_mode)
        return next_mode


# Global singleton
app_state = AppState()
