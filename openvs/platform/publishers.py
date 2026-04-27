"""
Trusted Publishers Registry — verified plugin authors.

Publishers become "trusted" through:
- Manual verification (initial)
- Consistent good ratings + downloads
- Code signing key verification

Stored at ~/.openvs/trusted_publishers.json
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


TRUSTED_PUBLISHERS_PATH = Path.home() / ".openvs" / "trusted_publishers.json"

# Built-in trusted publishers (OpenVS core team)
BUILTIN_TRUSTED = ["OpenVS", "openvs-core"]


@dataclass
class Publisher:
    name: str
    verified: bool = False
    verified_at: float = 0
    key_id: str = ""
    publish_count: int = 0
    avg_rating: float = 0.0


class TrustStore:
    """Registry of trusted plugin publishers."""

    def __init__(self):
        self._publishers: dict[str, Publisher] = {}
        self._load()

        # Ensure built-ins are always trusted
        for name in BUILTIN_TRUSTED:
            if name not in self._publishers:
                self._publishers[name] = Publisher(name=name, verified=True)

    def is_trusted(self, publisher_name: str) -> bool:
        """Check if a publisher is in the trusted registry."""
        pub = self._publishers.get(publisher_name)
        return pub is not None and pub.verified

    def add_trusted(self, name: str, key_id: str = "") -> dict:
        """Manually add a trusted publisher."""
        self._publishers[name] = Publisher(
            name=name, verified=True, key_id=key_id,
        )
        self._save()
        return {"status": "added", "publisher": name}

    def remove_trusted(self, name: str) -> dict:
        """Remove a publisher from the trusted list."""
        if name in BUILTIN_TRUSTED:
            return {"status": "denied", "reason": "Cannot remove built-in trusted publisher"}
        if name in self._publishers:
            del self._publishers[name]
            self._save()
            return {"status": "removed", "publisher": name}
        return {"status": "not_found", "publisher": name}

    def list_publishers(self) -> list[dict]:
        """List all trusted publishers."""
        return [
            {
                "name": p.name,
                "verified": p.verified,
                "key_id": p.key_id,
                "publish_count": p.publish_count,
                "avg_rating": p.avg_rating,
            }
            for p in self._publishers.values()
        ]

    def verify_publisher(self, name: str, key_id: str) -> dict:
        """Verify a publisher by checking their signing key."""
        pub = self._publishers.get(name)
        if pub and pub.key_id == key_id:
            pub.verified = True
            self._save()
            return {"status": "verified", "publisher": name}
        return {"status": "failed", "reason": "Key mismatch or publisher not found"}

    def _load(self):
        if TRUSTED_PUBLISHERS_PATH.exists():
            try:
                data = json.loads(TRUSTED_PUBLISHERS_PATH.read_text(encoding="utf-8"))
                for name, info in data.items():
                    self._publishers[name] = Publisher(
                        name=name,
                        verified=info.get("verified", False),
                        key_id=info.get("key_id", ""),
                        publish_count=info.get("publish_count", 0),
                        avg_rating=info.get("avg_rating", 0.0),
                    )
            except Exception:
                pass

    def _save(self):
        TRUSTED_PUBLISHERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for name, pub in self._publishers.items():
            if name not in BUILTIN_TRUSTED:
                data[name] = {
                    "verified": pub.verified,
                    "key_id": pub.key_id,
                    "publish_count": pub.publish_count,
                    "avg_rating": pub.avg_rating,
                }
        TRUSTED_PUBLISHERS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# Global singleton
trusted_publishers = TrustStore()
