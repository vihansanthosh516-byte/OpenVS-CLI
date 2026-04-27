"""
Tool Result Cache — caches tool execution results to avoid redundant runs.

If the same tool + args produce the same result, we serve from cache.
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Optional


CACHE_DIR = Path.home() / ".openvs" / "cache" / "tools"


class ToolCache:
    """Caches tool execution results."""

    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._cache: dict[str, dict] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, tool_name: str, args: dict) -> Optional[dict]:
        """Get a cached tool result."""
        key = self._make_key(tool_name, args)
        entry = self._cache.get(key)
        if entry and time.time() - entry["timestamp"] < self._ttl:
            return entry["result"]
        return None

    def put(self, tool_name: str, args: dict, result: dict):
        """Cache a tool result."""
        key = self._make_key(tool_name, args)
        self._cache[key] = {"result": result, "timestamp": time.time()}

    def invalidate(self, tool_name: str, args: dict):
        """Remove a cached tool result."""
        key = self._make_key(tool_name, args)
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()

    def stats(self) -> dict:
        return {"entries": len(self._cache), "ttl_seconds": self._ttl}

    def _make_key(self, tool_name: str, args: dict) -> str:
        raw = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


# Global singleton
tool_cache = ToolCache()
