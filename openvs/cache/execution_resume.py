"""
Execution Resume — partial execution resume for interrupted swarm runs.

When a swarm run is interrupted (crash, timeout, user cancel),
the resume engine can pick up from the last completed node.
"""

import json
import time
from pathlib import Path
from typing import Optional


RESUME_DIR = Path.home() / ".openvs" / "resume"


class ResumeEngine:
    """Enables partial execution resume for interrupted runs."""

    def __init__(self):
        RESUME_DIR.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, run_id: str, completed_nodes: list[str], pending_nodes: list[str], state: dict):
        """Save a checkpoint for a running execution."""
        checkpoint = {
            "run_id": run_id,
            "completed_nodes": completed_nodes,
            "pending_nodes": pending_nodes,
            "state": state,
            "timestamp": time.time(),
        }
        path = RESUME_DIR / f"{run_id}.json"
        path.write_text(json.dumps(checkpoint, indent=2, default=str), encoding="utf-8")
        return {"status": "saved", "run_id": run_id, "nodes_completed": len(completed_nodes)}

    def load_checkpoint(self, run_id: str) -> Optional[dict]:
        """Load a checkpoint for resume."""
        path = RESUME_DIR / f"{run_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def has_checkpoint(self, run_id: str) -> bool:
        return (RESUME_DIR / f"{run_id}.json").exists()

    def resume(self, run_id: str) -> dict:
        """Resume an interrupted execution from its last checkpoint."""
        checkpoint = self.load_checkpoint(run_id)
        if not checkpoint:
            return {"status": "no_checkpoint", "run_id": run_id}

        return {
            "status": "resumable",
            "run_id": run_id,
            "completed_nodes": checkpoint["completed_nodes"],
            "pending_nodes": checkpoint["pending_nodes"],
            "resume_from": checkpoint["completed_nodes"][-1] if checkpoint["completed_nodes"] else "start",
        }

    def list_resumable(self) -> list[dict]:
        """List all runs that can be resumed."""
        results = []
        for path in RESUME_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "run_id": data.get("run_id", path.stem),
                    "completed": len(data.get("completed_nodes", [])),
                    "pending": len(data.get("pending_nodes", [])),
                    "timestamp": data.get("timestamp", 0),
                })
            except Exception:
                pass
        return sorted(results, key=lambda x: -x.get("timestamp", 0))

    def clear_checkpoint(self, run_id: str):
        """Remove a checkpoint after successful completion."""
        path = RESUME_DIR / f"{run_id}.json"
        if path.exists():
            path.unlink()


# Global singleton
resume_engine = ResumeEngine()
