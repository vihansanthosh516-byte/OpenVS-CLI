"""
Delegation Graph — DAG engine for decomposing tasks into subtask networks.

Not linear plans anymore. Tasks become directed acyclic graphs where:
  - Parallel nodes run simultaneously
  - Dependency chains enforce ordering
  - Failed branches can be repaired independently
  - The whole graph is serializable and replayable

Example:
  Refactor monolith
  ├── analyze architecture (no deps)
  ├── refactor auth service (depends on: analyze)
  ├── refactor db layer (depends on: analyze)
  ├── generate tests (depends on: auth, db)
  └── security review (depends on: auth, db, tests)
"""

import uuid
import time
from enum import Enum
from typing import Optional


class NodeState(Enum):
    PENDING = "pending"
    READY = "ready"       # all dependencies satisfied
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SubtaskNode:
    """A single node in the delegation DAG."""

    def __init__(
        self,
        task: str,
        agent_role: str = "coder",
        priority: str = "normal",
        node_id: str = None,
        depends_on: list[str] = None,
        metadata: dict = None,
    ):
        self.id = node_id or f"node_{uuid.uuid4().hex[:8]}"
        self.task = task
        self.agent_role = agent_role
        self.priority = priority
        self.depends_on: list[str] = depends_on or []
        self.state = NodeState.PENDING
        self.result: Optional[dict] = None
        self.worker_id: Optional[str] = None
        self.retries = 0
        self.max_retries = 2
        self.metadata = metadata or {}
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

    @property
    def is_terminal(self) -> bool:
        return self.state in (NodeState.COMPLETED, NodeState.FAILED, NodeState.SKIPPED)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at) * 1000, 1)
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "agent_role": self.agent_role,
            "priority": self.priority,
            "depends_on": self.depends_on,
            "state": self.state.value,
            "worker_id": self.worker_id,
            "retries": self.retries,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class DelegationGraph:
    """A DAG of subtask nodes with dependency resolution.

    Supports:
    - Parallel execution of independent nodes
    - Dependency-ordered execution
    - Per-node retries
    - Failed branch repair
    - Topological sort for execution order
    """

    def __init__(self, root_task: str, graph_id: str = None):
        self.id = graph_id or f"dag_{uuid.uuid4().hex[:8]}"
        self.root_task = root_task
        self.nodes: dict[str, SubtaskNode] = {}
        self.created_at = time.time()

    def add_node(self, node: SubtaskNode) -> str:
        """Add a node to the graph."""
        self.nodes[node.id] = node
        return node.id

    def add_subtask(
        self,
        task: str,
        agent_role: str = "coder",
        priority: str = "normal",
        depends_on: list[str] = None,
        metadata: dict = None,
    ) -> str:
        """Convenience: create and add a subtask node."""
        node = SubtaskNode(
            task=task,
            agent_role=agent_role,
            priority=priority,
            depends_on=depends_on or [],
            metadata=metadata,
        )
        return self.add_node(node)

    def ready_nodes(self) -> list[SubtaskNode]:
        """Return nodes whose dependencies are all completed.

        These are the nodes eligible for execution right now.
        """
        ready = []
        for node in self.nodes.values():
            if node.state != NodeState.PENDING:
                continue
            if not node.depends_on:
                node.state = NodeState.READY
                ready.append(node)
                continue
            # Check all deps are completed
            all_done = True
            for dep_id in node.depends_on:
                dep = self.nodes.get(dep_id)
                if dep is None or dep.state != NodeState.COMPLETED:
                    all_done = False
                    break
            if all_done:
                node.state = NodeState.READY
                ready.append(node)
        return ready

    def running_nodes(self) -> list[SubtaskNode]:
        """Return currently running nodes."""
        return [n for n in self.nodes.values() if n.state == NodeState.RUNNING]

    def failed_nodes(self) -> list[SubtaskNode]:
        """Return failed nodes."""
        return [n for n in self.nodes.values() if n.state == NodeState.FAILED]

    def completed_nodes(self) -> list[SubtaskNode]:
        """Return completed nodes."""
        return [n for n in self.nodes.values() if n.state == NodeState.COMPLETED]

    def is_complete(self) -> bool:
        """Check if all nodes are in terminal states."""
        return all(n.is_terminal for n in self.nodes.values())

    def is_failed(self) -> bool:
        """Check if any required node has failed (beyond retry)."""
        for node in self.nodes.values():
            if node.state == NodeState.FAILED and node.retries >= node.max_retries:
                return True
        return False

    def topological_order(self) -> list[str]:
        """Return node IDs in topological order (dependencies first)."""
        # Kahn's algorithm
        in_degree = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep in in_degree:
                    in_degree[dep]  # ensure dep exists
                in_degree[node.id] = in_degree.get(node.id, 0)

        # Build adjacency list (dep -> dependents)
        dependents: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep in dependents:
                    dependents[dep].append(node.id)

        # Count in-degrees
        in_count = {nid: len(self.nodes[nid].depends_on) for nid in self.nodes}

        queue = [nid for nid, count in in_count.items() if count == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for dependent in dependents.get(nid, []):
                in_count[dependent] -= 1
                if in_count[dependent] == 0:
                    queue.append(dependent)

        return result

    def progress(self) -> dict:
        """Return progress statistics."""
        total = len(self.nodes)
        completed = len(self.completed_nodes())
        failed = len(self.failed_nodes())
        running = len(self.running_nodes())
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": total - completed - failed - running,
            "percent": round(completed / total * 100, 1) if total > 0 else 0,
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "root_task": self.root_task,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "progress": self.progress(),
            "topological_order": self.topological_order(),
            "created_at": self.created_at,
        }

    def render(self) -> str:
        """Render the DAG as a human-readable tree."""
        lines = [f"DAG: {self.root_task}"]
        order = self.topological_order()
        for i, nid in enumerate(order):
            node = self.nodes[nid]
            deps = ", ".join(node.depends_on) if node.depends_on else "no deps"
            state_icon = {"completed": "+", "failed": "X", "running": "*", "pending": " ", "ready": "R"}.get(node.state.value, "?")
            lines.append(f"  [{state_icon}] {node.id}: {node.task[:50]}  (role={node.agent_role}, deps=[{deps}])")
        return "\n".join(lines)