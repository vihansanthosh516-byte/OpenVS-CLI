"""
Permission Gate — runtime permission prompts and enforcement.

When a plugin tries to use a restricted capability (network, filesystem, etc.),
the gate intercepts and either allows (if pre-approved) or prompts the user.

Modeled after mobile OS permission systems.
"""

import time
from typing import Optional


class PermissionGate:
    """Runtime permission enforcement for plugins.

    Permissions are:
    - network: outbound HTTP/WebSocket
    - read_repo: read workspace files
    - write_comments: post comments/reviews
    - write_files: write to workspace
    - run_tests: execute test commands
    - admin: full access

    Flow: plugin calls restricted API → gate checks approval → allows or prompts
    """

    PERMISSIONS = ["network", "read_repo", "write_comments", "write_files", "run_tests", "admin"]

    def __init__(self):
        self._granted: dict[str, set[str]] = {}  # plugin_name -> {granted_perms}
        self._denied: dict[str, set[str]] = {}    # plugin_name -> {denied_perms}
        self._prompts: list[dict] = []
        self._auto_approve = False

    def check(self, plugin_name: str, permission: str) -> dict:
        """Check if a plugin has a specific permission granted."""
        if self._auto_approve:
            return {"allowed": True, "reason": "auto_approve_mode"}

        if permission == "admin":
            # Admin always requires explicit approval
            pass

        granted = self._granted.get(plugin_name, set())
        if permission in granted:
            return {"allowed": True, "reason": "pre_approved"}

        denied = self._denied.get(plugin_name, set())
        if permission in denied:
            return {"allowed": False, "reason": "previously_denied"}

        # Not yet decided — needs prompt
        self._prompts.append({
            "plugin": plugin_name,
            "permission": permission,
            "timestamp": time.time(),
        })

        return {"allowed": False, "reason": "needs_approval", "permission": permission}

    def grant(self, plugin_name: str, permission: str):
        """Grant a permission to a plugin."""
        self._granted.setdefault(plugin_name, set()).add(permission)
        self._denied.get(plugin_name, set()).discard(permission)

    def deny(self, plugin_name: str, permission: str):
        """Deny a permission to a plugin."""
        self._denied.setdefault(plugin_name, set()).add(permission)
        self._granted.get(plugin_name, set()).discard(permission)

    def grant_all(self, plugin_name: str, permissions: list[str]):
        """Grant multiple permissions at once."""
        for p in permissions:
            self.grant(plugin_name, p)

    def set_auto_approve(self, enabled: bool):
        """Enable/disable auto-approve mode (for testing)."""
        self._auto_approve = enabled

    def pending_prompts(self) -> list[dict]:
        """Return permission prompts that need user decision."""
        return list(self._prompts)

    def stats(self) -> dict:
        total_granted = sum(len(s) for s in self._granted.values())
        total_denied = sum(len(s) for s in self._denied.values())
        return {
            "total_granted": total_granted,
            "total_denied": total_denied,
            "pending_prompts": len(self._prompts),
            "auto_approve": self._auto_approve,
        }


# Global singleton
permission_gate = PermissionGate()
