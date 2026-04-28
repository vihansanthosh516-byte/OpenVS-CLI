import re
from engine.errors import CommandError, SecurityError

ENGINE_VERSION = "0.5.0"

VALID_COMMAND_PATTERN = re.compile(r"^/[a-z][a-z0-9_-]{0,30}$")
VALID_PERMISSIONS = {
    "read_repo", "write_repo", "read_files", "write_files",
    "network", "hooks", "events", "model_call",
}
DANGEROUS_PERMISSIONS = {"admin", "root", "system", "unrestricted"}

VALID_RESOURCE_LIMIT_KEYS = {
    "max_cpu_time_s", "max_memory_mb", "max_executions",
    "max_event_subscriptions", "max_commands", "max_hooks",
}


class PluginSchema:
    REQUIRED_FIELDS = ["name", "version"]
    OPTIONAL_FIELDS = [
        "description", "commands", "events", "hooks", "permissions",
        "engine_version", "resource_limits", "allowed_events",
        "allowed_commands",
    ]

    def __init__(self):
        self._errors = []

    def validate(self, manifest_dict):
        self._errors = []

        if not isinstance(manifest_dict, dict):
            self._error("manifest must be a dict")
            return not bool(self._errors)

        for field in self.REQUIRED_FIELDS:
            if field not in manifest_dict:
                self._error(f"required field missing: {field}")

        name = manifest_dict.get("name", "")
        if not name or not isinstance(name, str) or len(name) < 2:
            self._error("name must be a non-empty string (min 2 chars)")

        version = manifest_dict.get("version", "")
        if not self._valid_version(version):
            self._error(f"invalid version format: {version}")

        engine_ver = manifest_dict.get("engine_version")
        if engine_ver and not self._compatible_version(engine_ver):
            self._error(f"incompatible engine version: {engine_ver} (expected {ENGINE_VERSION})")

        commands = manifest_dict.get("commands", [])
        if not isinstance(commands, list):
            self._error("commands must be a list")
        else:
            for i, cmd in enumerate(commands):
                if isinstance(cmd, dict):
                    cmd_name = cmd.get("name", "")
                    if not VALID_COMMAND_PATTERN.match(cmd_name):
                        self._error(f"invalid command name at index {i}: {cmd_name}")
                elif isinstance(cmd, str):
                    if not VALID_COMMAND_PATTERN.match(cmd):
                        self._error(f"invalid command name at index {i}: {cmd}")
                else:
                    self._error(f"command at index {i} must be string or dict")

        events = manifest_dict.get("events", manifest_dict.get("event_subscriptions", []))
        if not isinstance(events, list):
            self._error("events must be a list")

        hooks = manifest_dict.get("hooks", manifest_dict.get("hook_subscriptions", []))
        if not isinstance(hooks, list):
            self._error("hooks must be a list")
        else:
            for i, hook in enumerate(hooks):
                if isinstance(hook, dict):
                    if "event" not in hook:
                        self._error(f"hook at index {i} missing 'event' field")
                elif isinstance(hook, str):
                    pass
                else:
                    self._error(f"hook at index {i} must be string or dict")

        permissions = manifest_dict.get("permissions", [])
        if not isinstance(permissions, list):
            self._error("permissions must be a list")
        else:
            for perm in permissions:
                if perm in DANGEROUS_PERMISSIONS:
                    self._error(f"dangerous permission not allowed: {perm}")
                elif perm not in VALID_PERMISSIONS and perm not in DANGEROUS_PERMISSIONS:
                    self._warn(f"unknown permission: {perm}")

        resource_limits = manifest_dict.get("resource_limits")
        if resource_limits is not None:
            if not isinstance(resource_limits, dict):
                self._error("resource_limits must be a dict")
            else:
                for key, value in resource_limits.items():
                    if key not in VALID_RESOURCE_LIMIT_KEYS:
                        self._warn(f"unknown resource limit key: {key}")
                    elif not isinstance(value, (int, float)) or value < 0:
                        self._error(f"resource limit '{key}' must be a non-negative number")

        allowed_events = manifest_dict.get("allowed_events")
        if allowed_events is not None:
            if not isinstance(allowed_events, list):
                self._error("allowed_events must be a list")
            else:
                for ev in allowed_events:
                    if not isinstance(ev, str):
                        self._error(f"allowed_events entry must be a string: {ev}")

        allowed_commands = manifest_dict.get("allowed_commands")
        if allowed_commands is not None:
            if not isinstance(allowed_commands, list):
                self._error("allowed_commands must be a list")
            else:
                for cmd in allowed_commands:
                    if not isinstance(cmd, str):
                        self._error(f"allowed_commands entry must be a string: {cmd}")

        return not bool(self._errors)

    def errors(self):
        return list(self._errors)

    def _error(self, msg):
        self._errors.append({"level": "error", "message": msg})

    def _warn(self, msg):
        self._errors.append({"level": "warn", "message": msg})

    @staticmethod
    def _valid_version(version):
        return bool(re.match(r"^\d+\.\d+(\.\d+)?", str(version)))

    @staticmethod
    def _compatible_version(required):
        try:
            req_parts = [int(x) for x in str(required).split(".")[:2]]
            eng_parts = [int(x) for x in ENGINE_VERSION.split(".")[:2]]
            return req_parts <= eng_parts
        except (ValueError, IndexError):
            return False


def validate_plugin_manifest(manifest_dict):
    schema = PluginSchema()
    valid = schema.validate(manifest_dict)
    return valid, schema.errors()
