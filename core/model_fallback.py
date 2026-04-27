"""
Model Fallback System — resilient multi-model calls with fallback chains.

Every model call now tries: PRIMARY → SECONDARY → SAFE_MODE
If all fail, returns a structured error instead of crashing the orchestrator.
"""

import time
from typing import Optional

from core.key_manager import KeyManager
from core.model_registry import ModelRegistry, ModelConfig
from core.model_client import ModelClient
from core.event_bus import bus


# Fallback chains per role
# Format: {role: [primary_model, fallback_model, safe_model]}
FALLBACK_CHAINS = {
    "planner": ["nemotron", "glm", "local"],
    "coder":   ["qwen", "glm", "local"],
    "fast":    ["glm", "qwen", "local"],
    "vision":  ["gemma", "glm", "local"],
    "critic":  ["nemotron", "glm", "local"],
}


class ModelCallResult:
    """Result of a model call attempt, with metadata about which model succeeded."""

    def __init__(self, response: dict, model_used: str, attempt: int,
                 latency_ms: float, fallback_used: bool = False):
        self.response = response
        self.model_used = model_used
        self.attempt = attempt
        self.latency_ms = latency_ms
        self.fallback_used = fallback_used

    def to_dict(self) -> dict:
        return {
            "model_used": self.model_used,
            "attempt": self.attempt,
            "latency_ms": round(self.latency_ms, 1),
            "fallback_used": self.fallback_used,
            "has_error": "error" in self.response if isinstance(self.response, dict) else True,
        }


class FallbackRouter:
    """Calls models with automatic fallback chains.

    Usage:
        router = FallbackRouter()
        result = router.call("planner", messages)
        # If nemotron fails, tries glm, then local
    """

    def __init__(
        self,
        key_manager: KeyManager = None,
        registry: ModelRegistry = None,
        max_attempts: int = 3,
    ):
        self.km = key_manager or KeyManager()
        self.registry = registry or ModelRegistry()
        self.client = ModelClient(self.km, self.registry)
        self.max_attempts = max_attempts
        self._call_log: list[dict] = []

    def call(
        self,
        role: str,
        messages: list,
        temperature: float = 0.5,
        task_id: str = None,
    ) -> ModelCallResult:
        """Call the model for a role, falling back through the chain.

        Returns a ModelCallResult with response + metadata.
        """
        chain = FALLBACK_CHAINS.get(role, ["local"])

        for attempt, model_name in enumerate(chain[:self.max_attempts], 1):
            start = time.time()

            bus.emit("model.call", {
                "role": role,
                "model": model_name,
                "attempt": attempt,
                "task_id": task_id,
            })

            try:
                response = self.client.call_sync(model_name, messages, temperature)
                latency = (time.time() - start) * 1000

                # Check if the response itself is an error
                if isinstance(response, dict) and "error" in response:
                    bus.emit("model.error", {
                        "role": role,
                        "model": model_name,
                        "attempt": attempt,
                        "error": response["error"][:200],
                    })
                    self._log_call(role, model_name, attempt, latency, failed=True,
                                   error=response["error"][:200], task_id=task_id)
                    continue  # try next in chain

                # Success
                result = ModelCallResult(
                    response=response,
                    model_used=model_name,
                    attempt=attempt,
                    latency_ms=latency,
                    fallback_used=(attempt > 1),
                )

                bus.emit("model.success", {
                    "role": role,
                    "model": model_name,
                    "attempt": attempt,
                    "latency_ms": round(latency, 1),
                    "task_id": task_id,
                })

                self._log_call(role, model_name, attempt, latency, failed=False,
                               task_id=task_id)
                return result

            except Exception as e:
                latency = (time.time() - start) * 1000
                bus.emit("model.exception", {
                    "role": role,
                    "model": model_name,
                    "attempt": attempt,
                    "error": str(e)[:200],
                })
                self._log_call(role, model_name, attempt, latency, failed=True,
                               error=str(e)[:200], task_id=task_id)
                continue

        # All models in chain failed
        bus.emit("model.all_failed", {"role": role, "chain": chain})

        return ModelCallResult(
            response={"error": f"All models failed for role '{role}': {chain}"},
            model_used="none",
            attempt=len(chain),
            latency_ms=0,
            fallback_used=True,
        )

    async def call_async(
        self,
        role: str,
        messages: list,
        temperature: float = 0.5,
        task_id: str = None,
    ) -> ModelCallResult:
        """Async version with same fallback logic."""
        chain = FALLBACK_CHAINS.get(role, ["local"])

        for attempt, model_name in enumerate(chain[:self.max_attempts], 1):
            start = time.time()

            try:
                response = await self.client.call(model_name, messages, temperature)
                latency = (time.time() - start) * 1000

                if isinstance(response, dict) and "error" in response:
                    continue

                return ModelCallResult(
                    response=response,
                    model_used=model_name,
                    attempt=attempt,
                    latency_ms=latency,
                    fallback_used=(attempt > 1),
                )

            except Exception:
                continue

        return ModelCallResult(
            response={"error": f"All models failed for role '{role}': {chain}"},
            model_used="none",
            attempt=len(chain),
            latency_ms=0,
            fallback_used=True,
        )

    def get_call_log(self, role: str = None, limit: int = 50) -> list[dict]:
        """Return recent call log entries, optionally filtered by role."""
        entries = self._call_log
        if role:
            entries = [e for e in entries if e["role"] == role]
        return entries[-limit:]

    def _log_call(self, role: str, model: str, attempt: int,
                  latency_ms: float, failed: bool, error: str = "",
                  task_id: str = None):
        """Record a model call attempt."""
        self._call_log.append({
            "role": role,
            "model": model,
            "attempt": attempt,
            "latency_ms": round(latency_ms, 1),
            "failed": failed,
            "error": error,
            "task_id": task_id,
            "ts": time.time(),
        })
        # Keep log bounded
        if len(self._call_log) > 500:
            self._call_log = self._call_log[-500:]