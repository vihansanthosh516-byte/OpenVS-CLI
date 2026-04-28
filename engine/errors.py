class OpenVSError(Exception):
    def __init__(self, message, *, code=None, details=None):
        super().__init__(message)
        self.code = code or "OPENVS_ERROR"
        self.details = details or {}

    def to_dict(self):
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class ModelError(OpenVSError):
    def __init__(self, message, *, model=None, provider=None, **kw):
        super().__init__(message, code="MODEL_ERROR", details={"model": model, "provider": provider, **kw})
        self.model = model
        self.provider = provider


class BridgeError(OpenVSError):
    def __init__(self, message, *, direction=None, request_type=None, **kw):
        super().__init__(message, code="BRIDGE_ERROR", details={"direction": direction, "request_type": request_type, **kw})
        self.direction = direction
        self.request_type = request_type


class CommandError(OpenVSError):
    def __init__(self, message, *, command=None, **kw):
        super().__init__(message, code="COMMAND_ERROR", details={"command": command, **kw})
        self.command = command


class EngineRuntimeError(OpenVSError):
    def __init__(self, message, *, component=None, **kw):
        super().__init__(message, code="RUNTIME_ERROR", details={"component": component, **kw})
        self.component = component


class JobError(OpenVSError):
    def __init__(self, message, *, job_id=None, job_status=None, **kw):
        super().__init__(message, code="JOB_ERROR", details={"job_id": job_id, "job_status": job_status, **kw})
        self.job_id = job_id
        self.job_status = job_status


class HookError(OpenVSError):
    def __init__(self, message, *, event_name=None, hook=None, **kw):
        super().__init__(message, code="HOOK_ERROR", details={"event_name": event_name, "hook": hook, **kw})
        self.event_name = event_name
        self.hook = hook


class SecurityError(OpenVSError):
    def __init__(self, message, *, violation=None, **kw):
        super().__init__(message, code="SECURITY_ERROR", details={"violation": violation, **kw})
        self.violation = violation
