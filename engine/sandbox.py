import signal
import time
import threading
from engine.errors import SecurityError, EngineRuntimeError


class Sandbox:
    def __init__(self, default_timeout=30, max_memory_mb=256):
        self.default_timeout = default_timeout
        self.max_memory_mb = max_memory_mb
        self._allowed_modules = set()
        self._blocked_modules = {"os", "sys", "subprocess", "shutil", "signal"}
        self._executions = 0
        self._timeouts = 0
        self._blocked = 0

    def allow_module(self, module_name):
        self._allowed_modules.add(module_name)
        self._blocked_modules.discard(module_name)

    def block_module(self, module_name):
        self._blocked_modules.add(module_name)
        self._allowed_modules.discard(module_name)

    def wrap(self, fn, timeout=None, plugin=None):
        timeout = timeout or self.default_timeout

        def safe_wrapper(*args, **kwargs):
            return self.execute(fn, *args, timeout=timeout, plugin=plugin, **kwargs)

        safe_wrapper.__name__ = fn.__name__ if hasattr(fn, "__name__") else "sandboxed_fn"
        safe_wrapper.__wrapped__ = fn
        return safe_wrapper

    def execute(self, fn, *args, timeout=None, plugin=None, **kwargs):
        timeout = timeout or self.default_timeout
        self._executions += 1

        result = [None]
        error = [None]

        def target():
            try:
                result[0] = fn(*args, **kwargs)
            except Exception as e:
                error[0] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            self._timeouts += 1
            raise EngineRuntimeError(
                f"sandbox timeout ({timeout}s) executing {getattr(fn, '__name__', '?')}",
                component="sandbox",
                details={"plugin": plugin, "timeout": timeout},
            )

        if error[0] is not None:
            raise error[0]

        return result[0]

    def check_import(self, module_name):
        if module_name in self._blocked_modules and module_name not in self._allowed_modules:
            self._blocked += 1
            raise SecurityError(
                f"module '{module_name}' is blocked in sandbox",
                violation="blocked_import",
                details={"module": module_name},
            )

    def validate_permissions(self, permissions):
        dangerous = {"admin", "root", "system", "unrestricted"}
        for perm in (permissions or []):
            if perm in dangerous:
                raise SecurityError(
                    f"permission '{perm}' is not allowed",
                    violation="dangerous_permission",
                    details={"permission": perm},
                )

    def stats(self):
        return {
            "executions": self._executions,
            "timeouts": self._timeouts,
            "blocked": self._blocked,
            "default_timeout": self.default_timeout,
            "max_memory_mb": self.max_memory_mb,
            "blocked_modules": list(self._blocked_modules),
            "allowed_modules": list(self._allowed_modules),
        }


sandbox = Sandbox()
