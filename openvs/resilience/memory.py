"""
Hierarchical Memory — short-term, long-term, and episodic memory with decay.

Three tiers:
- Short-term: current conversation context (last N messages, fast access)
- Long-term: persistent knowledge (FAISS-backed, slower access, high retention)
- Episodic: task-specific memories linked to execution runs

Decay: memories lose importance over time unless reinforced by access.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


MEMORY_DIR = Path.home() / ".openvs" / "memory"


@dataclass
class MemoryEntry:
    """A single memory item."""
    id: str
    content: str
    tier: str = "short"  # short, long, episodic
    importance: float = 1.0
    access_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    source: str = ""  # conversation, task, manual
    episode_id: str = ""  # for episodic tier

    def decay(self, halflife_hours: float = 168.0) -> float:
        """Calculate decayed importance. Returns new importance."""
        hours_elapsed = (time.time() - self.last_accessed) / 3600
        decay_factor = 0.5 ** (hours_elapsed / halflife_hours)
        self.importance *= decay_factor
        return self.importance

    def reinforce(self, boost: float = 0.5):
        """Reinforce a memory by accessing it."""
        self.access_count += 1
        self.last_accessed = time.time()
        self.importance = min(self.importance + boost, 10.0)


class HierarchicalMemory:
    """Three-tier memory system with decay and importance scoring."""

    def __init__(self, short_term_limit: int = 100, importance_threshold: float = 0.1):
        self._short_term: list[MemoryEntry] = []
        self._long_term: dict[str, MemoryEntry] = {}
        self._episodic: dict[str, list[MemoryEntry]] = {}
        self._short_term_limit = short_term_limit
        self._importance_threshold = importance_threshold
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    def store(self, content: str, tier: str = "short", tags: list[str] = None,
              source: str = "conversation", episode_id: str = "", importance: float = 1.0) -> dict:
        """Store a memory in the specified tier."""
        entry_id = hashlib.sha256(f"{content}{time.time()}".encode()).hexdigest()[:12]
        entry = MemoryEntry(
            id=entry_id, content=content, tier=tier,
            tags=tags or [], source=source, episode_id=episode_id,
            importance=importance,
        )

        if tier == "short":
            self._short_term.append(entry)
            if len(self._short_term) > self._short_term_limit:
                self._promote_oldest()
        elif tier == "long":
            self._long_term[entry_id] = entry
        elif tier == "episodic":
            self._episodic.setdefault(episode_id, []).append(entry)

        return {"status": "stored", "id": entry_id, "tier": tier}

    def recall(self, query: str = None, tier: str = None, limit: int = 10,
               min_importance: float = 0.0) -> list[dict]:
        """Recall memories, optionally filtered by tier, query, and importance."""
        candidates = []

        if tier in (None, "short"):
            candidates.extend(self._short_term)
        if tier in (None, "long"):
            candidates.extend(self._long_term.values())
        if tier in (None, "episodic"):
            for entries in self._episodic.values():
                candidates.extend(entries)

        # Filter by importance
        candidates = [m for m in candidates if m.importance >= min_importance]

        # Simple text search if query provided
        if query:
            q = query.lower()
            scored = []
            for m in candidates:
                score = 0
                if q in m.content.lower():
                    score += 10
                if any(q in t.lower() for t in m.tags):
                    score += 5
                score += m.importance
                scored.append((m, score))
            candidates = [m for m, s in sorted(scored, key=lambda x: -x[1])]
        else:
            candidates.sort(key=lambda m: -m.importance)

        # Reinforce accessed memories
        for m in candidates[:limit]:
            m.reinforce()

        return [
            {"id": m.id, "content": m.content, "tier": m.tier,
             "importance": round(m.importance, 3), "access_count": m.access_count,
             "tags": m.tags, "source": m.source}
            for m in candidates[:limit]
        ]

    def run_decay(self):
        """Run decay on all memories. Low-importance entries get pruned."""
        # Decay long-term
        to_remove = []
        for mid, entry in self._long_term.items():
            entry.decay()
            if entry.importance < self._importance_threshold:
                to_remove.append(mid)
        for mid in to_remove:
            del self._long_term[mid]

        # Decay short-term
        for entry in self._short_term:
            entry.decay()
        self._short_term = [m for m in self._short_term if m.importance >= self._importance_threshold]

        return {"pruned": len(to_remove), "long_term_remaining": len(self._long_term)}

    def get_episode(self, episode_id: str) -> list[dict]:
        """Get all memories for a specific episode."""
        entries = self._episodic.get(episode_id, [])
        return [{"id": m.id, "content": m.content, "importance": m.importance} for m in entries]

    def stats(self) -> dict:
        return {
            "short_term": len(self._short_term),
            "long_term": len(self._long_term),
            "episodes": len(self._episodic),
            "total_memories": len(self._short_term) + len(self._long_term) +
                sum(len(v) for v in self._episodic.values()),
        }

    def _promote_oldest(self):
        """Promote the oldest short-term memory to long-term if important enough."""
        if self._short_term:
            entry = self._short_term.pop(0)
            if entry.importance >= 1.0:
                entry.tier = "long"
                self._long_term[entry.id] = entry


hierarchical_memory = HierarchicalMemory()
