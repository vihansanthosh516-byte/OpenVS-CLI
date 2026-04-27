"""
A/B Testing Framework — split traffic between models and compare.

Configure traffic splits, collect results, and determine statistical winners.
"""

import time
import random
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ABExperiment:
    name: str
    variants: dict = field(default_factory=dict)  # model -> traffic_pct
    results: dict = field(default_factory=dict)  # model -> {success, total, latency_sum}
    active: bool = True
    started_at: float = field(default_factory=time.time)


class ABFramework:
    """A/B testing framework for model comparison."""

    def __init__(self):
        self._experiments: dict[str, ABExperiment] = {}

    def create_experiment(self, name: str, variants: dict) -> dict:
        """Create a new A/B test. variants: {"qwen": 50, "nemotron": 50}"""
        total = sum(variants.values())
        if abs(total - 100) > 1:
            return {"status": "error", "reason": "Traffic splits must sum to 100"}

        exp = ABExperiment(name=name, variants=variants, results={m: {"success": 0, "total": 0, "latency_sum": 0} for m in variants})
        self._experiments[name] = exp
        return {"status": "created", "experiment": name, "variants": variants}

    def assign(self, experiment_name: str) -> str:
        """Assign a request to a variant."""
        exp = self._experiments.get(experiment_name)
        if not exp or not exp.active:
            return list(exp.variants.keys())[0] if exp else "qwen"

        roll = random.random() * 100
        cumulative = 0
        for model, pct in exp.variants.items():
            cumulative += pct
            if roll < cumulative:
                return model
        return list(exp.variants.keys())[0]

    def record(self, experiment_name: str, model: str, success: bool, latency_ms: float):
        """Record a result for an A/B test."""
        exp = self._experiments.get(experiment_name)
        if not exp or model not in exp.results:
            return
        exp.results[model]["total"] += 1
        if success:
            exp.results[model]["success"] += 1
        exp.results[model]["latency_sum"] += latency_ms

    def get_results(self, experiment_name: str) -> dict:
        """Get experiment results with statistical comparison."""
        exp = self._experiments.get(experiment_name)
        if not exp:
            return {"status": "not_found"}

        results = {}
        for model, data in exp.results.items():
            total = data["total"] or 1
            results[model] = {
                "total_requests": data["total"],
                "success_rate": data["success"] / total,
                "avg_latency_ms": data["latency_sum"] / total,
                "traffic_pct": exp.variants.get(model, 0),
            }

        # Determine winner
        winner = max(results.items(), key=lambda x: x[1]["success_rate"]) if results else None

        return {
            "experiment": experiment_name,
            "active": exp.active,
            "variants": exp.variants,
            "results": results,
            "winner": winner[0] if winner else None,
        }

    def stop_experiment(self, name: str) -> dict:
        exp = self._experiments.get(name)
        if exp:
            exp.active = False
            return {"status": "stopped", "experiment": name}
        return {"status": "not_found"}

    def list_experiments(self) -> list[dict]:
        return [
            {"name": e.name, "active": e.active, "variants": e.variants}
            for e in self._experiments.values()
        ]


# Global singleton
ab_framework = ABFramework()
