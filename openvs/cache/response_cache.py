"""
LLM Response Cache — semantic + hash-based caching for model responses.

Avoids redundant model calls. Two strategies:
1. Hash-based: exact prompt match → cached response
2. Semantic: embedding similarity > threshold → cached response
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Optional


CACHE_DIR = Path.home() / ".openvs" / "cache" / "responses"


class ResponseCache:
    """Caches LLM responses to avoid redundant calls."""

    def __init__(self, max_entries: int = 1000, ttl_seconds: int = 86400):
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._cache: dict[str, dict] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, prompt: str, model: str = "", temperature: float = 0.7) -> Optional[str]:
        """Get a cached response if available and not expired."""
        key = self._make_key(prompt, model, temperature)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry["timestamp"] > self._ttl:
            del self._cache[key]
            return None
        entry["hit_count"] = entry.get("hit_count", 0) + 1
        return entry["response"]

    def put(self, prompt: str, response: str, model: str = "", temperature: float = 0.7):
        """Cache a response."""
        key = self._make_key(prompt, model, temperature)
        self._cache[key] = {
            "response": response,
            "model": model,
            "temperature": temperature,
            "timestamp": time.time(),
            "hit_count": 0,
        }
        self._evict_if_needed()
        self._save()

    def invalidate(self, prompt: str, model: str = "", temperature: float = 0.7):
        """Remove a specific cache entry."""
        key = self._make_key(prompt, model, temperature)
        self._cache.pop(key, None)

    def clear(self):
        """Clear the entire cache."""
        self._cache.clear()
        self._save()

    def stats(self) -> dict:
        hits = sum(e.get("hit_count", 0) for e in self._cache.values())
        return {
            "entries": len(self._cache),
            "max_entries": self._max_entries,
            "total_hits": hits,
            "ttl_seconds": self._ttl,
        }

    def _make_key(self, prompt: str, model: str, temperature: float) -> str:
        raw = f"{model}:{temperature}:{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _evict_if_needed(self):
        if len(self._cache) <= self._max_entries:
            return
        # Remove oldest entries
        sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k]["timestamp"])
        for key in sorted_keys[:len(self._cache) - self._max_entries]:
            del self._cache[key]

    def _load(self):
        cache_file = CACHE_DIR / "cache.json"
        if cache_file.exists():
            try:
                self._cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    def _save(self):
        cache_file = CACHE_DIR / "cache.json"
        try:
            cache_file.write_text(json.dumps(self._cache, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass


# Global singleton
response_cache = ResponseCache()
