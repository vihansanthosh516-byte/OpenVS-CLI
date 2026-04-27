"""
Policy Engine — capability scoping for every agent role.

No unrestricted swarm agents. Ever.

Every agent gets a signed capability scope that defines:
  - What tools it can use
  - What paths it can access
  - What commands it can run
  - Whether it can modify files or only suggest changes

This is the security layer that makes swarm safe.
"""

import json
import time
import hashlib
from enum import Enum
from typing import Optional


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    PATCH = "patch"
    SEARCH = "search"
    SHELL = "shell"
    SUGGEST_ONLY = "suggest_only"  # can propose but not execute
    NETWORK = "network"            # can make network calls


# Default capability scopes per agent role
ROLE_SCOPES = {
    "planner": {
        "permissions": [Permission.READ, Permission.SEARCH],
        "denied": [Permission.WRITE, Permission.PATCH, Permission.SHELL],
        "path_restrictions": ["*"],  # can read anything
        "command_allowlist": [],     # no shell commands
        "max_write_bytes": 0,
        "can_delegate": True,        # planner can create subtasks
        "description": "Read-only strategist. Can explore and plan but cannot modify code.",
    },
    "coder": {
        "permissions": [Permission.READ, Permission.WRITE, Permission.PATCH, Permission.SEARCH, Permission.SHELL],
        "denied": [Permission.NETWORK],
        "path_restrictions": ["workspace/*"],
        "command_allowlist": ["python", "pip", "pytest", "git", "node", "npm", "cargo", "go"],
        "max_write_bytes": 500_000,
        "can_delegate": False,
        "description": "Full code modification. Workspace-scoped. Restricted shell commands.",
    },
    "critic": {
        "permissions": [Permission.READ, Permission.SEARCH],
        "denied": [Permission.WRITE, Permission.PATCH, Permission.SHELL, Permission.NETWORK],
        "path_restrictions": ["*"],
        "command_allowlist": [],
        "max_write_bytes": 0,
        "can_delegate": False,
        "description": "Read-only reviewer. Can analyze but never modify.",
    },
    "security_auditor": {
        "permissions": [Permission.READ, Permission.SEARCH, Permission.SUGGEST_ONLY],
        "denied": [Permission.WRITE, Permission.PATCH, Permission.SHELL, Permission.NETWORK],
        "path_restrictions": ["*"],
        "command_allowlist": [],
        "max_write_bytes": 0,
        "can_delegate": False,
        "description": "Read-only with suggest_only. Patches are proposals, not direct edits.",
    },
    "tester": {
        "permissions": [Permission.READ, Permission.WRITE, Permission.SEARCH, Permission.SHELL],
        "denied": [Permission.PATCH, Permission.NETWORK],
        "path_restrictions": ["workspace/tests/*", "workspace/test_*"],
        "command_allowlist": ["python", "pytest", "node", "npm"],
        "max_write_bytes": 100_000,
        "can_delegate": False,
        "description": "Can write test files and run test commands. Scoped to test directories.",
    },
    "doc_writer": {
        "permissions": [Permission.READ, Permission.WRITE, Permission.SEARCH],
        "denied": [Permission.PATCH, Permission.SHELL, Permission.NETWORK],
        "path_restrictions": ["workspace/docs/*", "workspace/*.md", "workspace/README*"],
        "command_allowlist": [],
        "max_write_bytes": 200_000,
        "can_delegate": False,
        "description": "Can write documentation files only. No code modification.",
    },
}


class CapabilityToken:
    """A signed capability token granted to an agent for a specific task.

    Tokens are scoped: they contain the agent role, allowed permissions,
    path restrictions, and an expiry. Tokens can be verified by any
    component in the system without calling back to the policy engine.
    """

    def __init__(
        self,
        agent_role: str,
        task_id: str,
        scope: dict,
        issued_at: float = None,
        expires_at: float = None,
    ):
        self.agent_role = agent_role
        self.task_id = task_id
        self.scope = scope
        self.issued_at = issued_at or time.time()
        self.expires_at = expires_at  # None = no expiry
        self.token_id = f"cap_{hashlib.sha256(f'{agent_role}:{task_id}:{self.issued_at}'.encode()).hexdigest()[:12]}"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def has_permission(self, permission: Permission) -> bool:
        """Check if this token grants a specific permission."""
        if self.is_expired:
            return False
        if permission in self.scope.get("denied", []):
            return False
        return permission in self.scope.get("permissions", [])

    def can_access_path(self, path: str) -> bool:
        """Check if this token allows access to a given path."""
        if self.is_expired:
            return False
        restrictions = self.scope.get("path_restrictions", [])
        if not restrictions:
            return False
        if "*" in restrictions:
            return True  # wildcard access
        import fnmatch
        return any(fnmatch.fnmatch(path, pattern) for pattern in restrictions)

    def can_run_command(self, cmd: str) -> bool:
        """Check if this token allows running a specific command."""
        if self.is_expired:
            return False
        allowlist = self.scope.get("command_allowlist", [])
        if not allowlist:
            return False
        # Check if the command starts with any allowed prefix
        cmd_parts = cmd.strip().split()
        if not cmd_parts:
            return False
        base_cmd = cmd_parts[0]
        # Handle path-prefixed commands (e.g. /usr/bin/python)
        if "/" in base_cmd:
            base_cmd = base_cmd.rsplit("/", 1)[-1]
        return base_cmd in allowlist

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "agent_role": self.agent_role,
            "task_id": self.task_id,
            "permissions": [p.value for p in self.scope.get("permissions", [])],
            "denied": [p.value for p in self.scope.get("denied", [])],
            "path_restrictions": self.scope.get("path_restrictions", []),
            "command_allowlist": self.scope.get("command_allowlist", []),
            "max_write_bytes": self.scope.get("max_write_bytes", 0),
            "can_delegate": self.scope.get("can_delegate", False),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired,
        }


class PolicyEngine:
    """Central policy authority. Issues and verifies capability tokens.

    Every action in the swarm must be authorized by a valid token.
    No token = no execution. Expired token = no execution.
    Insufficient permissions = action blocked.
    """

    def __init__(self):
        self._issued_tokens: dict[str, CapabilityToken] = {}
        self._denied_actions: list[dict] = []

    def issue_token(
        self,
        agent_role: str,
        task_id: str,
        expires_in: float = None,
    ) -> CapabilityToken:
        """Issue a capability token for an agent role on a specific task.

        Args:
            agent_role: The agent's role (planner, coder, critic, etc.)
            task_id: The task this token is scoped to
            expires_in: Seconds until token expires (None = no expiry)
        """
        scope = ROLE_SCOPES.get(agent_role, ROLE_SCOPES["critic"]).copy()
        # Deep copy permission enums
        scope["permissions"] = list(scope.get("permissions", []))
        scope["denied"] = list(scope.get("denied", []))

        expires_at = None
        if expires_in is not None:
            expires_at = time.time() + expires_in

        token = CapabilityToken(
            agent_role=agent_role,
            task_id=task_id,
            scope=scope,
            expires_at=expires_at,
        )
        self._issued_tokens[token.token_id] = token
        return token

    def verify_action(
        self,
        token: CapabilityToken,
        action: str,
        args: dict = None,
    ) -> dict:
        """Verify that a token authorizes a specific action.

        Returns {"allowed": True} or {"allowed": False, "reason": "..."}.
        """
        args = args or {}

        if token.is_expired:
            reason = f"Token {token.token_id} expired"
            self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
            return {"allowed": False, "reason": reason}

        # Map tool actions to permissions
        action_permission_map = {
            "read": Permission.READ,
            "write": Permission.WRITE,
            "patch": Permission.PATCH,
            "search": Permission.SEARCH,
            "search_files": Permission.SEARCH,
            "list_dir": Permission.READ,
            "run": Permission.SHELL,
            "add_note": Permission.READ,  # notes are low-risk
        }

        required_perm = action_permission_map.get(action)
        if required_perm is None:
            reason = f"Unknown action '{action}' — not in permission map"
            self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
            return {"allowed": False, "reason": reason}

        # Check suggest_only mode
        if Permission.SUGGEST_ONLY in token.scope.get("permissions", []):
            if action in ("write", "patch", "run"):
                reason = f"Role '{token.agent_role}' is suggest_only — cannot execute {action}"
                self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
                return {"allowed": False, "reason": reason}

        # Check permission
        if not token.has_permission(required_perm):
            reason = f"Role '{token.agent_role}' lacks {required_perm.value} permission for action '{action}'"
            self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
            return {"allowed": False, "reason": reason}

        # Check path access for file operations
        if action in ("read", "write", "patch") and "path" in args:
            if not token.can_access_path(args["path"]):
                reason = f"Role '{token.agent_role}' cannot access path '{args['path']}'"
                self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
                return {"allowed": False, "reason": reason}

        # Check command allowlist for shell operations
        if action == "run" and "cmd" in args:
            if not token.can_run_command(args["cmd"]):
                reason = f"Role '{token.agent_role}' cannot run command: {args['cmd'][:50]}"
                self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
                return {"allowed": False, "reason": reason}

        # Check write size limits
        if action == "write" and "content" in args:
            max_bytes = token.scope.get("max_write_bytes", 0)
            if max_bytes > 0 and len(args["content"]) > max_bytes:
                reason = f"Write exceeds {max_bytes} byte limit for role '{token.agent_role}'"
                self._denied_actions.append({"token": token.token_id, "action": action, "reason": reason})
                return {"allowed": False, "reason": reason}

        return {"allowed": True}

    def get_denied_actions(self, limit: int = 50) -> list[dict]:
        """Return recent denied actions for audit."""
        return self._denied_actions[-limit:]

    def list_roles(self) -> dict:
        """List all role scope definitions."""
        result = {}
        for role, scope in ROLE_SCOPES.items():
            result[role] = {
                "permissions": [p.value for p in scope.get("permissions", [])],
                "denied": [p.value for p in scope.get("denied", [])],
                "path_restrictions": scope.get("path_restrictions", []),
                "can_delegate": scope.get("can_delegate", False),
                "description": scope.get("description", ""),
            }
        return result

    def stats(self) -> dict:
        return {
            "tokens_issued": len(self._issued_tokens),
            "denied_actions": len(self._denied_actions),
        }


# Global singleton
policy = PolicyEngine()