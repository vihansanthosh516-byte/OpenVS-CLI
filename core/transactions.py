"""
Transaction Engine — atomic change sets with rollback.

Every tool action that modifies the filesystem is wrapped in a transaction.
If verification fails, ALL changes in the transaction are rolled back.

This is git-lite for agent actions:
  BEGIN TRANSACTION
    edit file A
    edit file B
  VERIFY
    COMMIT or ROLLBACK

Without this, a failed agent step leaves the codebase in a broken state.
With this, the workspace always returns to a known-good state on failure.
"""

import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from core.event_bus import bus


class FileSnapshot:
    """Captures the state of a single file before modification."""

    def __init__(self, path: str, content: Optional[str] = None, existed: bool = True):
        self.path = path
        self.content = content  # None means file didn't exist
        self.existed = existed
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "content": self.content,
            "existed": self.existed,
            "timestamp": self.timestamp,
        }


class Transaction:
    """A single atomic change set.

    Tracks all file modifications made during a group of tool actions.
    On rollback, restores every file to its pre-transaction state.
    """

    def __init__(self, tx_id: str, workspace: str):
        self.tx_id = tx_id
        self.workspace = workspace
        self.snapshots: list[FileSnapshot] = []
        self.committed = False
        self.rolled_back = False
        self.created_at = time.time()
        self.operations: list[dict] = []

    def snapshot_file(self, path: str):
        """Capture the current state of a file before it's modified.

        Only snapshots a file once per transaction (first write wins).
        """
        # Don't re-snapshot if we already captured this file
        if any(s.path == path for s in self.snapshots):
            return

        full_path = os.path.join(self.workspace, path) if not os.path.isabs(path) else path

        if os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self.snapshots.append(FileSnapshot(path, content, existed=True))
            except Exception:
                # Can't read — treat as non-existent (binary, locked, etc.)
                self.snapshots.append(FileSnapshot(path, None, existed=True))
        else:
            self.snapshots.append(FileSnapshot(path, None, existed=False))

    def record_operation(self, op_type: str, details: dict):
        """Record a tool operation within this transaction."""
        self.operations.append({
            "type": op_type,
            "details": details,
            "timestamp": time.time(),
        })

    def commit(self):
        """Mark transaction as committed. Changes are permanent."""
        self.committed = True
        bus.emit("transaction.commit", {
            "tx_id": self.tx_id,
            "files_affected": len(self.snapshots),
            "operations": len(self.operations),
        })

    def rollback(self) -> dict:
        """Roll back all changes in this transaction.

        Restores every modified file to its pre-transaction state.
        Deletes files that were created by the transaction.
        Returns a summary of what was rolled back.
        """
        if self.committed:
            return {"error": "Cannot rollback a committed transaction"}

        rolled_back = []

        for snapshot in reversed(self.snapshots):
            full_path = os.path.join(self.workspace, snapshot.path) if not os.path.isabs(snapshot.path) else snapshot.path

            try:
                if snapshot.existed and snapshot.content is not None:
                    # Restore original content
                    os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(snapshot.content)
                    rolled_back.append({"path": snapshot.path, "action": "restored"})

                elif snapshot.existed and snapshot.content is None:
                    # File existed but we couldn't read it — can't safely restore
                    rolled_back.append({"path": snapshot.path, "action": "unreadable_skip"})

                elif not snapshot.existed:
                    # File was created by the transaction — delete it
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        # Clean up empty parent dirs
                        parent = os.path.dirname(full_path)
                        try:
                            if parent and not os.listdir(parent):
                                os.rmdir(parent)
                        except OSError:
                            pass
                    rolled_back.append({"path": snapshot.path, "action": "deleted"})
            except Exception as e:
                rolled_back.append({"path": snapshot.path, "action": f"error: {e}"})

        self.rolled_back = True

        bus.emit("transaction.rollback", {
            "tx_id": self.tx_id,
            "files_affected": len(rolled_back),
        })

        return {
            "tx_id": self.tx_id,
            "rolled_back": rolled_back,
            "total_files": len(rolled_back),
        }

    def summary(self) -> dict:
        """Return a summary of this transaction."""
        return {
            "tx_id": self.tx_id,
            "files_snapshotted": len(self.snapshots),
            "operations": len(self.operations),
            "committed": self.committed,
            "rolled_back": self.rolled_back,
            "duration_ms": round((time.time() - self.created_at) * 1000, 1),
            "files": [s.path for s in self.snapshots],
        }


class TransactionManager:
    """Manages transactions across the system.

    Usage:
        tm = TransactionManager(workspace)
        tx = tm.begin()

        # Before each file write, snapshot the file:
        tx.snapshot_file("app.py")

        # Execute tools (they modify files)...

        # Verify the result:
        if result_ok:
            tx.commit()
        else:
            tx.rollback()
    """

    def __init__(self, workspace: str = None):
        self.workspace = workspace or self._default_workspace()
        self._transactions: dict[str, Transaction] = []
        self._active: Optional[Transaction] = None
        self._counter = 0

    @staticmethod
    def _default_workspace() -> str:
        from tools.registry import get_workspace
        return get_workspace()

    def begin(self) -> Transaction:
        """Start a new transaction."""
        self._counter += 1
        tx_id = f"tx_{self._counter:04d}_{int(time.time())}"
        tx = Transaction(tx_id, self.workspace)
        self._transactions.append(tx)
        self._active = tx

        bus.emit("transaction.begin", {"tx_id": tx_id})

        return tx

    @property
    def active(self) -> Optional[Transaction]:
        """Return the currently active transaction."""
        return self._active

    def commit_active(self) -> dict:
        """Commit the active transaction."""
        if self._active is None:
            return {"error": "No active transaction"}
        summary = self._active.summary()
        self._active.commit()
        self._active = None
        return summary

    def rollback_active(self) -> dict:
        """Roll back the active transaction."""
        if self._active is None:
            return {"error": "No active transaction"}
        result = self._active.rollback()
        self._active = None
        return result

    def history(self, limit: int = 20) -> list[dict]:
        """Return recent transaction summaries."""
        return [tx.summary() for tx in self._transactions[-limit:]]

    def get_transaction(self, tx_id: str) -> Optional[Transaction]:
        """Find a transaction by ID."""
        for tx in self._transactions:
            if tx.tx_id == tx_id:
                return tx
        return None

    def rollback_to(self, tx_id: str) -> dict:
        """Roll back a specific transaction (even if it was committed).

        This is the "undo" operation — restores files to pre-transaction state.
        Only works if we still have the snapshots.
        """
        tx = self.get_transaction(tx_id)
        if tx is None:
            return {"error": f"Transaction {tx_id} not found"}

        if tx.rolled_back:
            return {"error": f"Transaction {tx_id} already rolled back"}

        # Force rollback even if committed
        tx.committed = False
        return tx.rollback()

    def stats(self) -> dict:
        """Return transaction manager statistics."""
        committed = sum(1 for t in self._transactions if t.committed)
        rolled_back = sum(1 for t in self._transactions if t.rolled_back)
        return {
            "total_transactions": len(self._transactions),
            "committed": committed,
            "rolled_back": rolled_back,
            "active": self._active is not None,
            "workspace": self.workspace,
        }


# Global singleton
tx_manager = TransactionManager()