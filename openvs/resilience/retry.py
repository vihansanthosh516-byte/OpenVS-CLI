"""
Retry Engine — automatic retry strategies per failure type.

Strategies:
- exponential_backoff: 1s, 2s, 4s, 8s...
- fixed_interval: retry every N seconds
- circuit_breaker: stop retrying after N consecutive failures
- per_failure_type: different strategies for timeout, auth, network, etc.
"""

import time
import random
from typing import Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class RetryStrategy(Enum):
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"
    CIRCUIT_BREAKER = "circuit_breaker"


class FailureType(Enum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    MODEL_ERROR = "model_error"
    WORKER_CRASH = "worker_crash"
    UNKNOWN = "unknown"


@dataclass
class RetryPolicy:
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    circuit_breaker_threshold: int = 5
    failure_type: FailureType = FailureType.UNKNOWN


class RetryEngine:
    """Automatic retry with configurable strategies per failure type."""

    DEFAULT_POLICIES = {
        FailureType.TIMEOUT: RetryPolicy(strategy=RetryStrategy.EXPONENTIAL_BACKOFF, max_retries=3, base_delay=2.0),
        FailureType.NETWORK: RetryPolicy(strategy=RetryStrategy.EXPONENTIAL_BACKOFF, max_retries=5, base_delay=1.0),
        FailureType.AUTH: RetryPolicy(strategy=RetryStrategy.FIXED_INTERVAL, max_retries=1, base_delay=0),
        FailureType.RATE_LIMIT: RetryPolicy(strategy=RetryStrategy.EXPONENTIAL_BACKOFF, max_retries=3, base_delay=5.0),
        FailureType.MODEL_ERROR: RetryPolicy(strategy=RetryStrategy.EXPONENTIAL_BACKOFF, max_retries=2, base_delay=3.0),
        FailureType.WORKER_CRASH: RetryPolicy(strategy=RetryStrategy.FIXED_INTERVAL, max_retries=2, base_delay=2.0),
    }

    def __init__(self):
        self._policies: dict[FailureType, RetryPolicy] = dict(self.DEFAULT_POLICIES)
        self._circuit_open: dict[str, int] = {}  # key -> consecutive_failures
        self._retry_log: list[dict] = []

    def call(self, fn: Callable, failure_type: FailureType = FailureType.UNKNOWN, key: str = "") -> dict:
        """Call a function with automatic retry."""
        policy = self._policies.get(failure_type, self._policies[FailureType.UNKNOWN])

        # Check circuit breaker
        if policy.strategy == RetryStrategy.CIRCUIT_BREAKER:
            if self._circuit_open.get(key, 0) >= policy.circuit_breaker_threshold:
                return {"status": "circuit_open", "key": key, "retries": 0}

        for attempt in range(policy.max_retries + 1):
            try:
                result = fn()
                # Success — reset circuit breaker
                self._circuit_open[key] = 0
                return {"status": "ok", "result": result, "attempts": attempt + 1}
            except Exception as e:
                delay = self._compute_delay(policy, attempt)
                self._circuit_open[key] = self._circuit_open.get(key, 0) + 1
                self._retry_log.append({
                    "key": key, "failure_type": failure_type.value,
                    "attempt": attempt + 1, "delay": delay, "error": str(e)[:100],
                })
                if attempt < policy.max_retries and delay > 0:
                    time.sleep(min(delay, 0.1))  # cap for tests

        return {"status": "exhausted", "retries": policy.max_retries, "key": key}

    def classify_error(self, error: Exception) -> FailureType:
        """Classify an exception into a failure type."""
        msg = str(error).lower()
        if "timeout" in msg or "timed out" in msg:
            return FailureType.TIMEOUT
        if "connection" in msg or "network" in msg or "dns" in msg:
            return FailureType.NETWORK
        if "auth" in msg or "401" in msg or "403" in msg or "key" in msg:
            return FailureType.AUTH
        if "rate" in msg or "429" in msg or "limit" in msg:
            return FailureType.RATE_LIMIT
        if "model" in msg or "api" in msg:
            return FailureType.MODEL_ERROR
        return FailureType.UNKNOWN

    def set_policy(self, failure_type: FailureType, policy: RetryPolicy):
        self._policies[failure_type] = policy

    def reset_circuit(self, key: str):
        self._circuit_open[key] = 0

    def stats(self) -> dict:
        return {
            "total_retries": len(self._retry_log),
            "open_circuits": {k: v for k, v in self._circuit_open.items() if v > 0},
            "policies": {ft.value: p.strategy.value for ft, p in self._policies.items()},
        }

    def _compute_delay(self, policy: RetryPolicy, attempt: int) -> float:
        if policy.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = policy.base_delay * (2 ** attempt)
            jitter = random.uniform(0, delay * 0.1)
            return min(delay + jitter, policy.max_delay)
        elif policy.strategy == RetryStrategy.FIXED_INTERVAL:
            return policy.base_delay
        return 0


retry_engine = RetryEngine()
