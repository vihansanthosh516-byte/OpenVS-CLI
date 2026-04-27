"""
Distributed Cluster Mode — remote worker nodes and GPU-aware scheduling.

Enables OpenVS to scale across multiple machines.
Workers register with a cluster coordinator and receive jobs.
"""

import time
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


CLUSTER_CONFIG = Path.home() / ".openvs" / "cluster.json"


@dataclass
class ClusterNode:
    """A remote worker node in the cluster."""
    id: str
    host: str
    port: int = 8421
    gpu_available: bool = False
    gpu_name: str = ""
    capabilities: list[str] = field(default_factory=list)
    max_concurrent: int = 3
    status: str = "offline"  # online, busy, offline
    last_heartbeat: float = 0


class ClusterCoordinator:
    """Manages a distributed cluster of OpenVS worker nodes."""

    def __init__(self):
        self._nodes: dict[str, ClusterNode] = {}
        self._load_config()

    def register_node(self, node_id: str, host: str, port: int = 8421,
                      gpu: bool = False, gpu_name: str = "",
                      capabilities: list[str] = None) -> dict:
        """Register a new worker node."""
        node = ClusterNode(
            id=node_id, host=host, port=port,
            gpu_available=gpu, gpu_name=gpu_name,
            capabilities=capabilities or ["coder"],
            status="online", last_heartbeat=time.time(),
        )
        self._nodes[node_id] = node
        self._save_config()
        return {"status": "registered", "node": node_id}

    def deregister_node(self, node_id: str) -> dict:
        """Remove a worker node."""
        if node_id in self._nodes:
            del self._nodes[node_id]
            self._save_config()
            return {"status": "deregistered", "node": node_id}
        return {"status": "not_found", "node": node_id}

    def heartbeat(self, node_id: str) -> dict:
        """Record a heartbeat from a node."""
        node = self._nodes.get(node_id)
        if node:
            node.last_heartbeat = time.time()
            node.status = "online"
            return {"status": "ok"}
        return {"status": "not_found"}

    def find_gpu_node(self) -> Optional[ClusterNode]:
        """Find an available GPU node."""
        for node in self._nodes.values():
            if node.gpu_available and node.status == "online":
                return node
        return None

    def schedule(self, requirements: dict = None) -> Optional[ClusterNode]:
        """Schedule a job to the best available node."""
        needs_gpu = (requirements or {}).get("gpu", False)
        needs_cap = (requirements or {}).get("capability", "coder")

        candidates = []
        for node in self._nodes.values():
            if node.status != "online":
                continue
            if needs_gpu and not node.gpu_available:
                continue
            if needs_cap not in node.capabilities:
                continue
            candidates.append(node)

        if not candidates:
            return None

        # Simple: pick least busy (would be least_loaded in real impl)
        return candidates[0]

    def list_nodes(self) -> list[dict]:
        return [
            {
                "id": n.id, "host": n.host, "port": n.port,
                "gpu": n.gpu_available, "gpu_name": n.gpu_name,
                "capabilities": n.capabilities, "status": n.status,
            }
            for n in self._nodes.values()
        ]

    def stats(self) -> dict:
        online = sum(1 for n in self._nodes.values() if n.status == "online")
        gpu_nodes = sum(1 for n in self._nodes.values() if n.gpu_available)
        return {
            "total_nodes": len(self._nodes),
            "online": online,
            "gpu_nodes": gpu_nodes,
        }

    def _load_config(self):
        if CLUSTER_CONFIG.exists():
            try:
                data = json.loads(CLUSTER_CONFIG.read_text(encoding="utf-8"))
                for nid, info in data.items():
                    self._nodes[nid] = ClusterNode(
                        id=nid, host=info.get("host", "localhost"),
                        port=info.get("port", 8421),
                        gpu_available=info.get("gpu", False),
                        gpu_name=info.get("gpu_name", ""),
                        capabilities=info.get("capabilities", ["coder"]),
                        status=info.get("status", "offline"),
                    )
            except Exception:
                pass

    def _save_config(self):
        data = {}
        for nid, node in self._nodes.items():
            data[nid] = {
                "host": node.host, "port": node.port,
                "gpu": node.gpu_available, "gpu_name": node.gpu_name,
                "capabilities": node.capabilities, "status": node.status,
            }
        CLUSTER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CLUSTER_CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")


# Global singleton
cluster = ClusterCoordinator()