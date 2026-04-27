"""
Command Palette — Ctrl+P overlay for OpenVS CLI.

Categories:
  Runtime:  Run Task, Run Tests, Schedule Job, Open Job Queue
  Models:   Switch Model, Show Model Health, Model Fallback Chains
  Swarm:    Toggle Swarm, Scale Workers, Open Agent Graph, Show Consensus
  Debug:    Open Trace, Show Event Log, Rollback Transaction, Run Doctor
  Workspace: Search Files, Open Diff View, Patch File, Clear Session

Supports fuzzy search, recent commands, AI action suggestions,
and a power mode (> prefix for admin commands).
"""

from dataclasses import dataclass, field
from typing import Optional, Callable
import time


class PaletteCategory:
    RUNTIME = "Runtime"
    MODELS = "Models"
    SWARM = "Swarm"
    DEBUG = "Debug"
    WORKSPACE = "Workspace"
    AI = "AI Actions"
    POWER = "Power"


@dataclass
class PaletteItem:
    label: str
    category: str
    action: str  # command or identifier to execute
    badge: str = ""  # e.g. "[Task]", "[Model]"
    keywords: list[str] = field(default_factory=list)
    is_power: bool = False  # requires > prefix

    def match_score(self, query: str) -> float:
        """Fuzzy match score. Higher = better match. 0 = no match."""
        if not query:
            return 1.0

        q = query.lower().strip()
        label_lower = self.label.lower()
        action_lower = self.action.lower()
        all_text = label_lower + " " + action_lower + " " + " ".join(k.lower() for k in self.keywords)

        # Exact match
        if q in label_lower:
            return 10.0

        # Action match
        if q in action_lower:
            return 8.0

        # Keyword match
        for kw in self.keywords:
            if q in kw.lower():
                return 6.0

        # Fuzzy: all query chars appear in order
        score = 0.0
        idx = 0
        for char in q:
            found = all_text.find(char, idx)
            if found == -1:
                return 0.0
            score += 1.0
            # Bonus for consecutive matches
            if found == idx:
                score += 0.5
            idx = found + 1

        return score / len(q)


def get_all_commands() -> list[PaletteItem]:
    """Return all available palette commands."""
    return [
        # Runtime
        PaletteItem("Run Task", PaletteCategory.RUNTIME, "/run", "[Task]",
                    keywords=["execute", "prompt", "ask", "run"]),
        PaletteItem("Run Tests", PaletteCategory.RUNTIME, "__run_tests", "[Task]",
                    keywords=["test", "pytest", "regression"]),
        PaletteItem("Schedule Job", PaletteCategory.RUNTIME, "/jobs", "[Task]",
                    keywords=["schedule", "defer", "job"]),
        PaletteItem("Open Job Queue", PaletteCategory.RUNTIME, "/jobs", "[Task]",
                    keywords=["queue", "jobs", "pending"]),

        # Models
        PaletteItem("Switch to Qwen", PaletteCategory.MODELS, "/model qwen", "[Model]",
                    keywords=["qwen", "coding", "fast"]),
        PaletteItem("Switch to Nemotron", PaletteCategory.MODELS, "/model nemotron", "[Model]",
                    keywords=["nemotron", "planner", "critic", "nvidia"]),
        PaletteItem("Switch to Gemma", PaletteCategory.MODELS, "/model gemma", "[Model]",
                    keywords=["gemma", "tools", "vision"]),
        PaletteItem("Switch to GLM", PaletteCategory.MODELS, "/model glm", "[Model]",
                    keywords=["glm", "general", "reasoning"]),
        PaletteItem("Switch to Local", PaletteCategory.MODELS, "/model local", "[Model]",
                    keywords=["local", "offline", "self-hosted"]),
        PaletteItem("Show Model Health", PaletteCategory.MODELS, "/status", "[Model]",
                    keywords=["models", "health", "status"]),
        PaletteItem("Model Fallback Chains", PaletteCategory.MODELS, "/status", "[Model]",
                    keywords=["fallback", "chain", "arbitration"]),

        # Swarm
        PaletteItem("Toggle Swarm", PaletteCategory.SWARM, "/swarm", "[Swarm]",
                    keywords=["swarm", "toggle", "on", "off"]),
        PaletteItem("Swarm Mode: Parallel", PaletteCategory.SWARM, "/swarm mode parallel", "[Swarm]",
                    keywords=["parallel", "mode"]),
        PaletteItem("Swarm Mode: Pipeline", PaletteCategory.SWARM, "/swarm mode pipeline", "[Swarm]",
                    keywords=["pipeline", "sequential"]),
        PaletteItem("Swarm Mode: Debate", PaletteCategory.SWARM, "/swarm mode debate", "[Swarm]",
                    keywords=["debate", "adversarial"]),
        PaletteItem("Swarm Mode: Map-Reduce", PaletteCategory.SWARM, "/swarm mode map_reduce", "[Swarm]",
                    keywords=["map", "reduce", "split"]),
        PaletteItem("Open Agent Graph", PaletteCategory.SWARM, "__switch_swarm", "[Swarm]",
                    keywords=["agents", "graph", "nodes", "orchestrator"]),
        PaletteItem("Show Consensus State", PaletteCategory.SWARM, "/consensus", "[Swarm]",
                    keywords=["consensus", "vote", "approval"]),
        PaletteItem("Scale Workers", PaletteCategory.SWARM, "/cluster", "[Swarm]",
                    keywords=["workers", "fabric", "scale", "pool"]),
        PaletteItem("List Active DAGs", PaletteCategory.SWARM, "/dags", "[Swarm]",
                    keywords=["dag", "graph", "tasks", "delegation"]),

        # Debug
        PaletteItem("Open Trace", PaletteCategory.DEBUG, "/trace last", "[Debug]",
                    keywords=["trace", "span", "observability"]),
        PaletteItem("Show Event Log", PaletteCategory.DEBUG, "/status", "[Debug]",
                    keywords=["events", "log", "bus"]),
        PaletteItem("Rollback Transaction", PaletteCategory.DEBUG, "/status", "[Debug]",
                    keywords=["rollback", "undo", "revert", "transaction"]),
        PaletteItem("Run Doctor", PaletteCategory.DEBUG, "/doctor", "[Debug]",
                    keywords=["doctor", "health", "diagnose", "check"]),
        PaletteItem("Show Crash Log", PaletteCategory.DEBUG, "/crashes", "[Debug]",
                    keywords=["crash", "error", "shield", "failure"]),

        # Workspace
        PaletteItem("Search Files", PaletteCategory.WORKSPACE, "__search", "[File]",
                    keywords=["search", "find", "grep", "files"]),
        PaletteItem("Open Diff View", PaletteCategory.WORKSPACE, "__switch_diff", "[File]",
                    keywords=["diff", "patch", "changes", "review"]),
        PaletteItem("Clear Session", PaletteCategory.WORKSPACE, "/clear", "[File]",
                    keywords=["clear", "reset", "clean"]),
        PaletteItem("Agent Scopes", PaletteCategory.WORKSPACE, "/agents", "[File]",
                    keywords=["agents", "roles", "policy", "permissions"]),

        # AI Actions
        PaletteItem("Explain Current Trace", PaletteCategory.AI, "__ai_explain_trace", "[AI]",
                    keywords=["explain", "trace", "understand", "why"]),
        PaletteItem("Optimize Worker Routing", PaletteCategory.AI, "__ai_optimize_routing", "[AI]",
                    keywords=["optimize", "routing", "workers", "performance"]),
        PaletteItem("Review This Patch", PaletteCategory.AI, "__ai_review_patch", "[AI]",
                    keywords=["review", "patch", "critic", "approve"]),
        PaletteItem("Suggest Fix", PaletteCategory.AI, "__ai_suggest_fix", "[AI]",
                    keywords=["suggest", "fix", "repair", "improve"]),

        # Power commands (require > prefix)
        PaletteItem("Force Rollback", PaletteCategory.POWER, "__force_rollback", "[Power]",
                    keywords=["force", "rollback", "undo"], is_power=True),
        PaletteItem("Dump Event Bus", PaletteCategory.POWER, "__dump_events", "[Power]",
                    keywords=["dump", "events", "export"], is_power=True),
        PaletteItem("Show Fallback Chain", PaletteCategory.POWER, "__show_fallback", "[Power]",
                    keywords=["fallback", "chain", "models"], is_power=True),
        PaletteItem("Benchmark Models", PaletteCategory.POWER, "__benchmark", "[Power]",
                    keywords=["benchmark", "speed", "latency", "models"], is_power=True),
    ]


def get_suggestions(context: dict = None) -> list[PaletteItem]:
    """Context-aware suggestions. Returns items the user likely wants next."""
    suggestions = []
    ctx = context or {}

    status = ctx.get("status", "idle")
    recent = ctx.get("recent_commands", [])

    if status == "idle":
        suggestions.append(PaletteItem("Run Task", PaletteCategory.AI, "/run", "[Suggested]",
                                       keywords=["start", "begin"]))
        suggestions.append(PaletteItem("Run Doctor", PaletteCategory.DEBUG, "/doctor", "[Suggested]",
                                       keywords=["health", "check"]))

    if "patch" in str(recent).lower() or "write" in str(recent).lower():
        suggestions.append(PaletteItem("Open Diff View", PaletteCategory.WORKSPACE, "__switch_diff", "[Suggested]",
                                       keywords=["review", "changes"]))
        suggestions.append(PaletteItem("Run Tests", PaletteCategory.RUNTIME, "__run_tests", "[Suggested]",
                                       keywords=["verify", "test"]))

    if status == "error":
        suggestions.append(PaletteItem("Show Crash Log", PaletteCategory.DEBUG, "/crashes", "[Suggested]",
                                       keywords=["error", "crash"]))
        suggestions.append(PaletteItem("Run Doctor", PaletteCategory.DEBUG, "/doctor", "[Suggested]",
                                       keywords=["diagnose"]))

    return suggestions


def search_commands(query: str, include_power: bool = False) -> list[PaletteItem]:
    """Search commands with fuzzy matching. Returns sorted by relevance."""
    commands = get_all_commands()
    if not include_power:
        commands = [c for c in commands if not c.is_power]

    if not query:
        return commands

    # Power mode: > prefix
    if query.startswith(">"):
        power_query = query[1:].strip()
        power_commands = [c for c in get_all_commands() if c.is_power]
        if not power_query:
            return power_commands
        scored = [(cmd, cmd.match_score(power_query)) for cmd in power_commands]
        return [cmd for cmd, score in sorted(scored, key=lambda x: -x[1]) if score > 0]

    scored = [(cmd, cmd.match_score(query)) for cmd in commands]
    return [cmd for cmd, score in sorted(scored, key=lambda x: -x[1]) if score > 0]


class CommandHistory:
    """Track recently used commands for the palette's 'Recent' section."""

    def __init__(self, max_size: int = 50):
        self._history: list[str] = []
        self._max_size = max_size

    def record(self, action: str):
        """Record a command execution."""
        if action in self._history:
            self._history.remove(action)
        self._history.insert(0, action)
        if len(self._history) > self._max_size:
            self._history = self._history[:self._max_size]

    def recent(self, limit: int = 5) -> list[str]:
        """Return recent commands."""
        return self._history[:limit]

    def as_palette_items(self, limit: int = 5) -> list[PaletteItem]:
        """Return recent commands as palette items."""
        all_commands = get_all_commands()
        cmd_map = {c.action: c for c in all_commands}
        items = []
        for action in self.recent(limit):
            if action in cmd_map:
                items.append(cmd_map[action])
            else:
                items.append(PaletteItem(action, "Recent", action, "[Recent]"))
        return items

    def clear(self):
        self._history.clear()


# Global singleton
command_history = CommandHistory()