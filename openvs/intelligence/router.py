"""
Intelligent Model Router — cost/latency-aware routing, A/B testing, benchmarking.

Routes prompts to the best model based on:
- Cost optimization (cheapest capable model)
- Latency requirements (fastest model)
- Task type (coder tasks → qwen, planning → nemotron)
- A/B testing (split traffic between models)
- Learned preferences (what worked best historically)
"""

import time
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict


ROUTER_CONFIG = Path.home() / ".openvs" / "model_router.json"


@dataclass
class ModelProfile:
    name: str
    cost_per_1k_tokens: float = 0.0
    avg_latency_ms: float = 500.0
    quality_score: float = 0.8
    capabilities: list[str] = field(default_factory=list)
    call_count: int = 0
    success_count: int = 0
    total_latency_ms: float = 0.0


class IntelligentRouter:
    """Routes prompts to the optimal model based on multiple criteria."""

    STRATEGIES = ["cost", "latency", "quality", "balanced", "ab_test"]

    def __init__(self):
        self._models: dict[str, ModelProfile] = {
            "qwen": ModelProfile(name="qwen", cost_per_1k_tokens=0.0002, avg_latency_ms=300,
                                  quality_score=0.85, capabilities=["coding", "implementation"]),
            "nemotron": ModelProfile(name="nemotron", cost_per_1k_tokens=0.0003, avg_latency_ms=400,
                                     quality_score=0.9, capabilities=["planning", "review", "critic"]),
            "gemma": ModelProfile(name="gemma", cost_per_1k_tokens=0.0001, avg_latency_ms=250,
                                  quality_score=0.75, capabilities=["testing", "vision"]),
            "glm": ModelProfile(name="glm", cost_per_1k_tokens=0.0002, avg_latency_ms=350,
                                quality_score=0.8, capabilities=["reasoning", "general"]),
            "local": ModelProfile(name="local", cost_per_1k_tokens=0.0, avg_latency_ms=1000,
                                  quality_score=0.6, capabilities=["coding", "offline"]),
        }
        self._strategy = "balanced"
        self._ab_config: dict = {}  # model -> traffic_percentage
        self._task_history: list[dict] = []

    def route(self, task_type: str = "general", strategy: str = None) -> dict:
        """Route to the best model for a given task type and strategy."""
        strategy = strategy or self._strategy

        if strategy == "cost":
            model = self._route_by_cost(task_type)
        elif strategy == "latency":
            model = self._route_by_latency(task_type)
        elif strategy == "quality":
            model = self._route_by_quality(task_type)
        elif strategy == "ab_test":
            model = self._route_ab_test()
        else:
            model = self._route_balanced(task_type)

        return {
            "model": model,
            "strategy": strategy,
            "task_type": task_type,
            "reason": self._explain_choice(model, strategy, task_type),
        }

    def record_result(self, model: str, task_type: str, success: bool, latency_ms: float):
        """Record a model execution result for learning."""
        profile = self._models.get(model)
        if profile:
            profile.call_count += 1
            if success:
                profile.success_count += 1
            profile.total_latency_ms += latency_ms
            profile.avg_latency_ms = profile.total_latency_ms / profile.call_count

        self._task_history.append({
            "model": model, "task_type": task_type,
            "success": success, "latency_ms": latency_ms,
            "timestamp": time.time(),
        })

    def set_strategy(self, strategy: str) -> dict:
        if strategy not in self.STRATEGIES:
            return {"status": "error", "reason": f"Unknown strategy. Use: {', '.join(self.STRATEGIES)}"}
        self._strategy = strategy
        return {"status": "ok", "strategy": strategy}

    def configure_ab_test(self, splits: dict) -> dict:
        """Configure A/B test traffic splits. e.g. {"qwen": 50, "nemotron": 50}"""
        self._ab_config = splits
        return {"status": "ok", "splits": splits}

    def benchmark(self, model: str = None) -> dict:
        """Get benchmark stats for models."""
        if model:
            p = self._models.get(model)
            if p:
                return {
                    "model": p.name,
                    "calls": p.call_count,
                    "success_rate": p.success_count / max(p.call_count, 1),
                    "avg_latency_ms": p.avg_latency_ms,
                    "cost_per_1k": p.cost_per_1k_tokens,
                    "quality": p.quality_score,
                }
            return {"error": f"Model {model} not found"}

        return {
            "models": {name: {
                "calls": p.call_count,
                "success_rate": p.success_count / max(p.call_count, 1),
                "avg_latency_ms": p.avg_latency_ms,
                "cost_per_1k": p.cost_per_1k_tokens,
            } for name, p in self._models.items()}
        }

    def stats(self) -> dict:
        return {
            "strategy": self._strategy,
            "total_tasks": len(self._task_history),
            "models": len(self._models),
            "ab_test": self._ab_config or "not configured",
        }

    def _route_by_cost(self, task_type: str) -> str:
        candidates = [m for m in self._models.values() if task_type in m.capabilities or task_type == "general"]
        if not candidates:
            candidates = list(self._models.values())
        return min(candidates, key=lambda m: m.cost_per_1k_tokens).name

    def _route_by_latency(self, task_type: str) -> str:
        candidates = [m for m in self._models.values() if task_type in m.capabilities or task_type == "general"]
        if not candidates:
            candidates = list(self._models.values())
        return min(candidates, key=lambda m: m.avg_latency_ms).name

    def _route_by_quality(self, task_type: str) -> str:
        candidates = [m for m in self._models.values() if task_type in m.capabilities or task_type == "general"]
        if not candidates:
            candidates = list(self._models.values())
        return max(candidates, key=lambda m: m.quality_score).name

    def _route_balanced(self, task_type: str) -> str:
        candidates = [m for m in self._models.values() if task_type in m.capabilities or task_type == "general"]
        if not candidates:
            candidates = list(self._models.values())
        # Score = quality * 0.4 + (1 - normalized_latency) * 0.3 + (1 - normalized_cost) * 0.3
        max_latency = max(m.avg_latency_ms for m in candidates)
        max_cost = max(m.cost_per_1k_tokens for m in candidates) or 1
        best = max(candidates, key=lambda m: (
            m.quality_score * 0.4 +
            (1 - m.avg_latency_ms / max_latency) * 0.3 +
            (1 - m.cost_per_1k_tokens / max_cost) * 0.3
        ))
        return best.name

    def _route_ab_test(self) -> str:
        if not self._ab_config:
            return "qwen"
        import random
        roll = random.random() * 100
        cumulative = 0
        for model, pct in self._ab_config.items():
            cumulative += pct
            if roll < cumulative:
                return model
        return list(self._ab_config.keys())[0]

    def _explain_choice(self, model: str, strategy: str, task_type: str) -> str:
        p = self._models.get(model)
        if not p:
            return "Default selection"
        reasons = {
            "cost": f"Cheapest for {task_type} (${p.cost_per_1k_tokens}/1k tokens)",
            "latency": f"Fastest for {task_type} ({p.avg_latency_ms:.0f}ms avg)",
            "quality": f"Highest quality for {task_type} (score: {p.quality_score})",
            "balanced": f"Best balance for {task_type} (quality={p.quality_score}, latency={p.avg_latency_ms:.0f}ms)",
            "ab_test": f"A/B test allocation",
        }
        return reasons.get(strategy, "Balanced selection")


# Global singleton
intelligent_router = IntelligentRouter()
