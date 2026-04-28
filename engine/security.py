import re
from engine.errors import SecurityError


ALLOWED_COMMANDS = {
    "/help", "/h", "/status", "/st", "/model", "/jobs", "/j",
    "/config", "/cfg", "/agents", "/events", "/ev",
    "/plugin", "/pl", "/diagnostics", "/diag",
    "/swarm", "/sw",
    "/replay", "/rp", "/coordinator", "/coord", "/network", "/net",
    "/exit", "/quit",
}

MAX_INPUT_LENGTH = 10000
DANGEROUS_PATTERNS = [
    r"__\w+__",
    r"import\s+os",
    r"import\s+sys",
    r"subprocess",
    r"eval\s*\(",
    r"exec\s*\(",
    r"open\s*\(",
    r"\bchmod\b",
    r"\brm\s+-rf\b",
]


def validate_command(command):
    if not command or not command.startswith("/"):
        raise SecurityError(
            "invalid command format",
            violation="command_format",
        )

    parts = command.strip().split()
    cmd_name = parts[0].lower()

    if cmd_name not in ALLOWED_COMMANDS:
        raise SecurityError(
            f"command not allowed: {cmd_name}",
            violation="command_not_allowed",
            details={"command": cmd_name},
        )

    return cmd_name, parts[1:]


def sanitize_input(text):
    if not text:
        return ""

    if len(text) > MAX_INPUT_LENGTH:
        raise SecurityError(
            f"input exceeds max length ({MAX_INPUT_LENGTH})",
            violation="input_too_long",
        )

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, text):
            raise SecurityError(
                f"potentially dangerous input detected",
                violation="dangerous_pattern",
                details={"pattern": pattern},
            )

    return text.strip()


def safe_execute(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except SecurityError:
        raise
    except Exception as e:
        return None, e
