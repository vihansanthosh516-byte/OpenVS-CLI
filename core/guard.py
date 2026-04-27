"""
Execution Guard — sits between Coder Agent → Tool Registry.

Validates every tool call before it reaches the OS.
Blocks: path traversal, dangerous commands, malformed actions,
unknown tools, schema mismatches, oversized payloads.
"""

import os
import re
from typing import Optional

# ---- Tool Schemas ----
# Each tool defines required + optional args and their types

TOOL_SCHEMAS = {
    "read": {
        "required": {"path": str},
        "optional": {},
    },
    "write": {
        "required": {"path": str, "content": str},
        "optional": {},
    },
    "patch": {
        "required": {"path": str, "old": str, "new": str},
        "optional": {},
    },
    "search": {
        "required": {"query": str},
        "optional": {"directory": str},
    },
    "search_files": {
        "required": {"pattern": str},
        "optional": {"directory": str},
    },
    "list_dir": {
        "required": {},
        "optional": {"path": str},
    },
    "run": {
        "required": {"cmd": str},
        "optional": {"timeout": int},
    },
    "add_note": {
        "required": {"note": str},
        "optional": {},
    },
}

# ---- Dangerous Shell Patterns ----
BLOCKED_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\s+-f\b",
    r"\bdel\s+/[sS]\b",
    r"\bformat\s+[A-Z]:",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+-R\b",
    r"\bsudo\s+rm\b",
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bcurl\b.*\|\s*sh\b",
    r"\bwget\b.*\|\s*sh\b",
    r"\b:()\s*\{\s*:\s*\|\s*:&\s*\}",  # fork bomb
]

BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]

# ---- Limits ----
MAX_CMD_LENGTH = 2000
MAX_CONTENT_LENGTH = 500_000   # 500KB max file write
MAX_NOTE_LENGTH = 10_000
MAX_SHELL_TIMEOUT = 60


class GuardViolation(Exception):
    """Raised when an action fails validation."""
    pass


class ExecutionGuard:
    """Validates tool calls before execution.

    Sits between the coder agent and the tool registry.
    Every action MUST pass through this guard or it never reaches the OS.
    """

    def __init__(self, workspace: str = None):
        self.workspace = workspace or self._default_workspace()
        self.violations: list[dict] = []

    @staticmethod
    def _default_workspace() -> str:
        from tools.registry import get_workspace
        return get_workspace()

    def validate(self, action: dict) -> dict:
        """Validate a tool action. Returns the action if valid.

        Raises GuardViolation if the action is blocked.
        """
        # 1. Structural check
        self._check_structure(action)

        tool = action.get("tool", action.get("action", ""))
        args = action.get("args", action.get("arguments", {}))

        # 2. Tool exists
        self._check_tool_exists(tool)

        # 3. Schema match
        self._check_schema(tool, args)

        # 4. Path isolation (for tools that take paths)
        if "path" in args:
            self._check_path(args["path"])

        if "directory" in args:
            self._check_path(args["directory"])

        # 5. Shell command safety
        if tool == "run":
            self._check_command(args["cmd"])
            self._check_timeout(args.get("timeout", 30))

        # 6. Payload size limits
        if tool == "write":
            self._check_content_size(args.get("content", ""))
        if tool == "add_note":
            self._check_note_size(args.get("note", ""))

        return action

    def validate_batch(self, actions: list[dict]) -> list[dict]:
        """Validate a batch of actions. Returns only valid ones.

        Invalid actions are logged and skipped (not raised).
        """
        valid = []
        for action in actions:
            try:
                self.validate(action)
                valid.append(action)
            except GuardViolation as e:
                self.violations.append({
                    "action": action,
                    "reason": str(e),
                })
        return valid

    def get_violations(self) -> list[dict]:
        """Return all logged violations."""
        return self.violations

    def clear_violations(self):
        """Clear violation log."""
        self.violations.clear()

    # ---- Internal Checks ----

    def _check_structure(self, action: dict):
        """Ensure action has required keys."""
        if not isinstance(action, dict):
            raise GuardViolation(f"Action is not a dict: {type(action)}")

        tool = action.get("tool", action.get("action", ""))
        if not tool:
            raise GuardViolation("Action has no 'tool' or 'action' key")

        args = action.get("args", action.get("arguments", {}))
        if not isinstance(args, dict):
            raise GuardViolation(f"Args must be a dict, got {type(args)}")

    def _check_tool_exists(self, tool: str):
        """Ensure tool is in the registry."""
        if tool not in TOOL_SCHEMAS:
            raise GuardViolation(
                f"Unknown tool '{tool}'. Allowed: {list(TOOL_SCHEMAS.keys())}"
            )

    def _check_schema(self, tool: str, args: dict):
        """Validate args match the tool's schema."""
        schema = TOOL_SCHEMAS[tool]

        # Check required args
        for param, expected_type in schema["required"].items():
            if param not in args:
                raise GuardViolation(f"Tool '{tool}' missing required arg '{param}'")
            if not isinstance(args[param], expected_type):
                raise GuardViolation(
                    f"Tool '{tool}' arg '{param}' must be {expected_type.__name__}, "
                    f"got {type(args[param]).__name__}"
                )

        # Check optional arg types if provided
        for param, expected_type in schema["optional"].items():
            if param in args and not isinstance(args[param], expected_type):
                raise GuardViolation(
                    f"Tool '{tool}' arg '{param}' must be {expected_type.__name__}, "
                    f"got {type(args[param]).__name__}"
                )

    def _check_path(self, path: str):
        """Block path traversal and enforce workspace isolation."""
        if not isinstance(path, str):
            raise GuardViolation(f"Path must be string, got {type(path)}")

        # Block traversal patterns
        if "../" in path or "..\\" in path:
            raise GuardViolation(f"Path traversal blocked: '{path}'")

        # Block absolute system paths (allow workspace-relative only)
        if os.path.isabs(path):
            resolved = os.path.normpath(path)
            ws_norm = os.path.normpath(self.workspace)
            if not resolved.startswith(ws_norm):
                raise GuardViolation(
                    f"Absolute path outside workspace blocked: '{path}'"
                )

        # Block sensitive directories
        sensitive = ["/etc", "/usr", "/bin", "/sbin", "/System", "/Windows",
                     "C:\\Windows", "C:\\Program Files", "C:\\Users"]
        path_lower = path.lower()
        for prefix in sensitive:
            if path_lower.startswith(prefix.lower()):
                raise GuardViolation(f"Sensitive path blocked: '{path}'")

    def _check_command(self, cmd: str):
        """Block dangerous shell commands."""
        if not isinstance(cmd, str):
            raise GuardViolation(f"Command must be string, got {type(cmd)}")

        if len(cmd) > MAX_CMD_LENGTH:
            raise GuardViolation(
                f"Command too long ({len(cmd)} chars, max {MAX_CMD_LENGTH})"
            )

        for pattern in BLOCKED_RE:
            if pattern.search(cmd):
                raise GuardViolation(
                    f"Dangerous command blocked: pattern matched in '{cmd[:100]}'"
                )

    def _check_timeout(self, timeout):
        """Enforce timeout limits."""
        if isinstance(timeout, int) and timeout > MAX_SHELL_TIMEOUT:
            raise GuardViolation(
                f"Timeout {timeout}s exceeds max ({MAX_SHELL_TIMEOUT}s)"
            )

    def _check_content_size(self, content: str):
        """Limit write payload size."""
        if len(content) > MAX_CONTENT_LENGTH:
            raise GuardViolation(
                f"Content too large ({len(content)} chars, max {MAX_CONTENT_LENGTH})"
            )

    def _check_note_size(self, note: str):
        """Limit note payload size."""
        if len(note) > MAX_NOTE_LENGTH:
            raise GuardViolation(
                f"Note too long ({len(note)} chars, max {MAX_NOTE_LENGTH})"
            )