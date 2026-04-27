"""
Fallback Orchestrator — fallback workflows when primary execution fails.

Unlike model_fallback.py (which only falls back between models),
this orchestrates fallback across entire workflow strategies:

Example:
  1. Try swarm parallel execution
  2. If that fails → try pipeline execution
  3. If that fails → try single-agent execution
  4. If all fail → return error with diagnostics
"""

import time
from typing import Callable, Optional
from dataclasses import dataclass, field


@dataclass
class FallbackStep:
    name: str
    fn: Callable
    condition: str = "always"  # always, on_timeout, on_error, on_worker_fail


class FallbackOrchestrator:
    """Orchestrates fallback across execution strategies."""

    def __init__(self):
        self._chains: dict[str, list[FallbackStep]] = {}
        self._execution_log: list[dict] = []

    def register_chain(self, name: str, steps: list[FallbackStep]):
        """Register a fallback chain."""
        self._chains[name] = steps

    def execute(self, chain_name: str, *args, **kwargs) -> dict:
        """Execute a fallback chain. Tries each step until one succeeds."""
        steps = self._chains.get(chain_name, [])
        if not steps:
            return {"status": "no_chain", "chain": chain_name}

        errors = []
        for step in steps:
            start = time.time()
            try:
                result = step.fn(*args, **kwargs)
                duration = (time.time() - start) * 1000

                self._execution_log.append({
                    "chain": chain_name, "step": step.name,
                    "status": "ok", "duration_ms": duration,
                })

                return {
                    "status": "ok",
                    "step": step.name,
                    "result": result,
                    "fallbacks_attempted": len(errors),
                    "errors": errors,
                }
            except Exception as e:
                duration = (time.time() - start) * 1000
                errors.append({"step": step.name, "error": str(e)[:200], "duration_ms": duration})

                self._execution_log.append({
                    "chain": chain_name, "step": step.name,
                    "status": "failed", "error": str(e)[:100],
                })

        return {
            "status": "all_failed",
            "chain": chain_name,
            "steps_attempted": len(errors),
            "errors": errors,
        }

    def get_default_swarm_chain(self) -> list[FallbackStep]:
        """Default fallback chain for swarm execution."""
        return [
            FallbackStep("swarm_parallel", lambda: None, "always"),
            FallbackStep("swarm_pipeline", lambda: None, "on_worker_fail"),
            FallbackStep("single_agent", lambda: None, "on_error"),
        ]

    def stats(self) -> dict:
        return {
            "chains": list(self._chains.keys()),
            "total_executions": len(self._execution_log),
            "successes": sum(1 for e in self._execution_log if e["status"] == "ok"),
            "failures": sum(1 for e in self._execution_log if e["status"] == "failed"),
        }


fallback_orchestrator = FallbackOrchestrator()
