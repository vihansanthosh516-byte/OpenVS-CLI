"""
Metrics System — latency, token usage, swarm efficiency tracking.

Collects runtime metrics and exposes them for dashboards, alerts, and profiling.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class MetricSample:
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict = field(default_factory=dict)


class MetricsCollector:
    """Collects and aggregates OpenVS runtime metrics."""

    def __init__(self):
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._timers: dict[str, float] = {}

    def increment(self, name: str, value: float = 1.0, tags: dict = None):
        """Increment a counter metric."""
        self._counters[name] += value

    def gauge(self, name: str, value: float):
        """Set a gauge metric."""
        self._gauges[name] = value

    def histogram(self, name: str, value: float):
        """Record a histogram value."""
        self._histograms[name].append(value)
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-500:]

    def start_timer(self, name: str):
        """Start a timer."""
        self._timers[name] = time.time()

    def stop_timer(self, name: str) -> float:
        """Stop a timer and record the duration."""
        start = self._timers.pop(name, None)
        if start is None:
            return 0.0
        duration = time.time() - start
        self.histogram(f"{name}.duration_ms", duration * 1000)
        self.increment(f"{name}.count")
        return duration

    def get_counter(self, name: str) -> float:
        return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0)

    def get_histogram_stats(self, name: str) -> dict:
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p99": 0}
        sorted_vals = sorted(values)
        return {
            "count": len(values),
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "avg": sum(values) / len(values),
            "p50": sorted_vals[len(values) // 2],
            "p99": sorted_vals[int(len(values) * 0.99)],
        }

    def snapshot(self) -> dict:
        """Return a snapshot of all metrics."""
        result = {"counters": dict(self._counters), "gauges": dict(self._gauges), "histograms": {}}
        for name in self._histograms:
            result["histograms"][name] = self.get_histogram_stats(name)
        return result

    def reset(self):
        """Clear all metrics."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._timers.clear()


# Global singleton
metrics = MetricsCollector()
