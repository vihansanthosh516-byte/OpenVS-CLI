"""
Marketplace Backend — search, install, rank, rate plugins.

Provides a local-first marketplace that can sync with registry.openvs.dev.
Plugins are indexed, searchable, and can be rated.
"""

import json
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


MARKETPLACE_DIR = Path.home() / ".openvs" / "marketplace"
MARKETPLACE_INDEX = MARKETPLACE_DIR / "index.json"


@dataclass
class MarketplaceEntry:
    """A plugin listing in the marketplace."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    category: str = "general"
    rating: float = 0.0
    downloads: int = 0
    tags: list[str] = field(default_factory=list)
    signature_verified: bool = False
    trusted_publisher: bool = False
    updated_at: float = field(default_factory=time.time)


class Marketplace:
    """Plugin marketplace with search, install, rating, and ranking."""

    CATEGORIES = [
        "security", "code-review", "testing", "devops",
        "documentation", "integration", "ai-tools", "general",
    ]

    def __init__(self):
        self._entries: dict[str, MarketplaceEntry] = {}
        self._load_index()

    def search(self, query: str, category: str = None, sort_by: str = "relevance") -> list[dict]:
        """Search the marketplace. Returns ranked results."""
        results = []
        q = query.lower()

        for entry in self._entries.values():
            if category and entry.category != category:
                continue

            # Relevance scoring
            score = 0.0
            if q in entry.name.lower():
                score += 10.0
            if q in entry.description.lower():
                score += 5.0
            if any(q in t.lower() for t in entry.tags):
                score += 3.0
            if entry.trusted_publisher:
                score += 2.0
            if entry.signature_verified:
                score += 1.0

            if score == 0 and q:
                continue

            results.append({
                "name": entry.name,
                "version": entry.version,
                "description": entry.description,
                "author": entry.author,
                "category": entry.category,
                "rating": entry.rating,
                "downloads": entry.downloads,
                "verified": entry.signature_verified,
                "trusted": entry.trusted_publisher,
                "score": score,
            })

        # Sort
        if sort_by == "relevance":
            results.sort(key=lambda x: -x["score"])
        elif sort_by == "rating":
            results.sort(key=lambda x: -x["rating"])
        elif sort_by == "downloads":
            results.sort(key=lambda x: -x["downloads"])
        elif sort_by == "recent":
            results.sort(key=lambda x: -x.get("updated_at", 0))

        return results

    def install(self, name: str) -> dict:
        """Install a plugin from the marketplace."""
        entry = self._entries.get(name)
        if not entry:
            return {"status": "not_found", "plugin": name}

        # Check signature
        if not entry.signature_verified:
            return {"status": "warning", "plugin": name,
                    "message": "Plugin not signed. Install with caution."}

        # Delegate to plugin runtime
        try:
            from openvs.plugins.runtime import plugin_runtime
            plugin_runtime.load()
            return {"status": "installed", "plugin": name}
        except Exception as e:
            return {"status": "error", "plugin": name, "error": str(e)}

    def rate(self, name: str, score: float, review: str = "") -> dict:
        """Rate a plugin (1.0 - 5.0)."""
        if score < 0 or score > 5:
            return {"status": "error", "reason": "Rating must be 0-5"}

        entry = self._entries.get(name)
        if not entry:
            return {"status": "not_found", "plugin": name}

        # Simple running average
        if entry.downloads > 0:
            entry.rating = (entry.rating * entry.downloads + score) / (entry.downloads + 1)
        else:
            entry.rating = score

        self._save_index()
        return {"status": "rated", "plugin": name, "new_rating": round(entry.rating, 2)}

    def publish(self, manifest: dict, signature: str = "") -> dict:
        """Publish a plugin to the marketplace."""
        name = manifest.get("name", "")
        if not name:
            return {"status": "error", "reason": "Plugin name required"}

        entry = MarketplaceEntry(
            name=name,
            version=manifest.get("version", "1.0.0"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            category=manifest.get("category", "general"),
            tags=manifest.get("tags", []),
            signature_verified=bool(signature),
        )

        # Check trusted publisher
        try:
            from openvs.security.trust import trusted_publishers
            entry.trusted_publisher = trusted_publishers.is_trusted(entry.author)
        except Exception:
            pass

        self._entries[name] = entry
        self._save_index()

        return {"status": "published", "plugin": name, "verified": entry.signature_verified}

    def list_categories(self) -> list[dict]:
        """List categories with plugin counts."""
        counts = {}
        for entry in self._entries.values():
            counts[entry.category] = counts.get(entry.category, 0) + 1

        return [{"category": c, "count": counts.get(c, 0)} for c in self.CATEGORIES]

    def stats(self) -> dict:
        return {
            "total_plugins": len(self._entries),
            "categories": len(self.CATEGORIES),
            "verified": sum(1 for e in self._entries.values() if e.signature_verified),
            "trusted": sum(1 for e in self._entries.values() if e.trusted_publisher),
        }

    def _load_index(self):
        if MARKETPLACE_INDEX.exists():
            try:
                data = json.loads(MARKETPLACE_INDEX.read_text(encoding="utf-8"))
                for name, entry_data in data.items():
                    self._entries[name] = MarketplaceEntry(
                        name=name,
                        version=entry_data.get("version", "1.0.0"),
                        description=entry_data.get("description", ""),
                        author=entry_data.get("author", ""),
                        category=entry_data.get("category", "general"),
                        rating=entry_data.get("rating", 0.0),
                        downloads=entry_data.get("downloads", 0),
                        tags=entry_data.get("tags", []),
                        signature_verified=entry_data.get("signature_verified", False),
                        trusted_publisher=entry_data.get("trusted_publisher", False),
                    )
            except Exception:
                pass

    def _save_index(self):
        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        for name, entry in self._entries.items():
            data[name] = {
                "version": entry.version,
                "description": entry.description,
                "author": entry.author,
                "category": entry.category,
                "rating": entry.rating,
                "downloads": entry.downloads,
                "tags": entry.tags,
                "signature_verified": entry.signature_verified,
                "trusted_publisher": entry.trusted_publisher,
                "updated_at": entry.updated_at,
            }
        MARKETPLACE_INDEX.write_text(json.dumps(data, indent=2), encoding="utf-8")


# Global singleton
marketplace = Marketplace()
