"""
Profiler — performance profiling for OpenVS runs.

Usage:
  /profile start    — begin profiling
  /profile stop     — stop and show results
  openvs --profile  — profile from CLI
"""

import time
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


PROFILE_DIR = Path.home() / ".openvs" / "profiles"


@dataclass
class ProfileSpan:
    name: str
    start: float
    end: float = 0
    metadata: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000 if self.end else 0


class Profiler:
    """Performance profiler for OpenVS execution runs."""

    def __init__(self):
        self._active = False
        self._spans: list[ProfileSpan] = []
        self._open_spans: dict[str, ProfileSpan] = {}
        self._run_start: float = 0

    def start(self):
        """Start profiling."""
        self._active = True
        self._spans.clear()
        self._open_spans.clear()
        self._run_start = time.time()

    def stop(self) -> dict:
        """Stop profiling and return results."""
        self._active = False
        # Close any open spans
        now = time.time()
        for span in self._open_spans.values():
            span.end = now

        total_ms = (now - self._run_start) * 1000 if self._run_start else 0

        result = {
            "total_ms": total_ms,
            "span_count": len(self._spans),
            "spans": [
                {"name": s.name, "duration_ms": s.duration_ms, "meta": s.metadata}
                for s in self._spans
            ],
        }

        # Save profile
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        profile_path = PROFILE_DIR / f"profile_{int(time.time())}.json"
        profile_path.write_text(json.dumps(result, indent=2, default=str))

        result["_path"] = str(profile_path)
        return result

    def span_start(self, name: str, metadata: dict = None):
        """Start a profile span."""
        if not self._active:
            return
        span = ProfileSpan(name=name, start=time.time(), metadata=metadata or {})
        self._open_spans[name] = span

    def span_end(self, name: str):
        """End a profile span."""
        if not self._active:
            return
        span = self._open_spans.pop(name, None)
        if span:
            span.end = time.time()
            self._spans.append(span)

    def format_results(self, result: dict) -> str:
        """Format profiler results for display."""
        lines = ["Profile Results:", ""]
        lines.append(f"  Total: {result['total_ms']:.1f}ms")
        lines.append(f"  Spans: {result['span_count']}")
        lines.append("")

        # Sort spans by duration
        spans = sorted(result.get("spans", []), key=lambda s: -s.get("duration_ms", 0))
        for s in spans[:20]:
            lines.append(f"  {s['name']:30s} {s['duration_ms']:8.1f}ms")

        if result.get("_path"):
            lines.append(f"\n  Saved: {result['_path']}")

        return "\n".join(lines)

    @property
    def is_active(self) -> bool:
        return self._active


# Global singleton
profiler = Profiler()
