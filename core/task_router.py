"""
Adaptive Task Router — intelligent routing of subtasks to workers.

The router decides:
1. Which worker gets which subtask (role matching, load balancing)
2. When to split tasks further (decomposition)
3. When to retry failed tasks on different workers
4. Priority-based scheduling (urgent tasks jump the queue)

Routing strategies:
- ROUND_ROBIN: distribute evenly across workers
- LEAST_LOADED: pick the worker with fewest active jobs
- CAPABILITY_MATCH: strict role-to-capability matching
- ADAPTIVE: combine load + capability + recent success rate
"""

import time
from enum import Enum
from typing import Optional
from core.event_bus import bus
from core.jobs import Job
from core.policy_engine import policy


class RoutingStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CAPABILITY_MATCH = "capability_match"
    ADAPTIVE = "adaptive"


class RoutingDecision:
    """The result of a routing decision."""

    def __init__(self, job_id: str, worker_id: str, strategy: RoutingStrategy, score: float = 0.0):
        self.job_id = job_id
        self.worker_id = worker_id
        self.strategy = strategy
        self.score = score
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "worker_id": self.worker_id,
            "strategy": self.strategy.value,
            "score": round(self.score, 3),
            "timestamp": self.timestamp,
        }


class TaskRouter:
    """Routes subtasks to the best available worker.

    The adaptive strategy considers:
    - Worker capability match (role alignment)
    - Current load (utilization)
    - Recent success rate (completed / (completed + failed))
    - Priority weighting (urgent tasks get preferred workers)
    """

    def __init__(self, default_strategy: RoutingStrategy = RoutingStrategy.ADAPTIVE):
        self.default_strategy = default_strategy
        self._round_robin_idx = 0
        self._routing_history: list[RoutingDecision] = []
        self._worker_scores: dict[str, dict] = {}  # worker_id → {successes, failures}

    def route(self, job: Job, workers: list, strategy: RoutingStrategy = None) -> Optional[RoutingDecision]:
        """Route a job to a worker using the specified strategy.

        Args:
            job: The job to route
            workers: List of WorkerNode objects
            strategy: Routing strategy (defaults to self.default_strategy)

        Returns:
            RoutingDecision or None if no suitable worker found
        """
        strategy = strategy or self.default_strategy
        agent_role = job.metadata.get("agent_role", "coder")

        # Filter to workers that can handle this role
        eligible = [w for w in workers if w.can_handle(agent_role) and w.is_available]

        if not eligible:
            bus.emit("router.no_eligible_worker", {
                "job_id": job.id,
                "agent_role": agent_role,
                "total_workers": len(workers),
            })
            return None

        if strategy == RoutingStrategy.ROUND_ROBIN:
            worker = self._round_robin(eligible)
        elif strategy == RoutingStrategy.LEAST_LOADED:
            worker = self._least_loaded(eligible)
        elif strategy == RoutingStrategy.CAPABILITY_MATCH:
            worker = self._capability_match(eligible, agent_role)
        else:
            worker = self._adaptive(eligible, agent_role, job)

        if worker is None:
            return None

        decision = RoutingDecision(job.id, worker.id, strategy)
        self._routing_history.append(decision)
        self._init_worker_score(worker.id)

        bus.emit("router.routed", {
            "job_id": job.id,
            "worker_id": worker.id,
            "strategy": strategy.value,
        })

        return decision

    def _round_robin(self, workers: list):
        """Simple round-robin distribution."""
        if not workers:
            return None
        idx = self._round_robin_idx % len(workers)
        self._round_robin_idx += 1
        return workers[idx]

    def _least_loaded(self, workers: list):
        """Pick the worker with lowest utilization."""
        return min(workers, key=lambda w: w.utilization)

    def _capability_match(self, workers: list, agent_role: str):
        """Pick the worker whose primary capability matches the role."""
        # Sort by: exact role match first, then fewer capabilities (more specialized)
        for worker in workers:
            if worker.capabilities and worker.capabilities[0] == agent_role:
                return worker
        # Fallback to first eligible
        return workers[0] if workers else None

    def _adaptive(self, workers: list, agent_role: str, job: Job):
        """Adaptive routing: capability + load + success rate."""
        scored = []
        for worker in workers:
            score = self._compute_adaptive_score(worker, agent_role, job)
            scored.append((worker, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else None

    def _compute_adaptive_score(self, worker, agent_role: str, job: Job) -> float:
        """Compute a routing score for a worker (higher is better).

        Components:
        - Capability match: 40 points (exact match on primary role)
        - Load: 30 points (lower utilization = higher score)
        - Success rate: 20 points (recent completion rate)
        - Priority bonus: 10 points (for urgent/high priority jobs)
        """
        score = 0.0

        # Capability match (0-40)
        if worker.capabilities and worker.capabilities[0] == agent_role:
            score += 40
        elif agent_role in worker.capabilities:
            score += 20

        # Load (0-30): lower utilization = higher score
        score += (1.0 - worker.utilization) * 30

        # Success rate (0-20)
        ws = self._worker_scores.get(worker.id, {})
        successes = ws.get("successes", 0)
        failures = ws.get("failures", 0)
        total = successes + failures
        if total > 0:
            score += (successes / total) * 20
        else:
            score += 10  # unknown workers get average score

        # Priority bonus (0-10)
        from core.jobs import JobPriority
        if job.priority == JobPriority.URGENT:
            score += 10
        elif job.priority == JobPriority.HIGH:
            score += 5

        return score

    def _init_worker_score(self, worker_id: str):
        """Initialize score tracking for a worker."""
        if worker_id not in self._worker_scores:
            self._worker_scores[worker_id] = {"successes": 0, "failures": 0}

    def record_success(self, worker_id: str):
        """Record a successful job completion for a worker."""
        self._init_worker_score(worker_id)
        self._worker_scores[worker_id]["successes"] += 1

    def record_failure(self, worker_id: str):
        """Record a failed job for a worker."""
        self._init_worker_score(worker_id)
        self._worker_scores[worker_id]["failures"] += 1

    def history(self, limit: int = 50) -> list[dict]:
        """Return recent routing decisions."""
        return [d.to_dict() for d in self._routing_history[-limit:]]

    def worker_performance(self) -> dict:
        """Return performance metrics per worker."""
        return dict(self._worker_scores)

    def stats(self) -> dict:
        return {
            "total_routes": len(self._routing_history),
            "strategy": self.default_strategy.value,
            "workers_tracked": len(self._worker_scores),
            "worker_performance": self.worker_performance(),
        }


# Global singleton
task_router = TaskRouter()
