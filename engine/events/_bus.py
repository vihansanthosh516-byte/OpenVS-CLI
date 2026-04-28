import time
import hashlib
import json
from engine.errors import OpenVSError


EVENT_SCHEMA_VERSION = 1


class EventSchemaRegistry:
    _schemas = {}
    _compatibility = {}

    @classmethod
    def register(cls, schema_id, version, fields, compatible_with=None):
        key = (schema_id, version)
        cls._schemas[key] = {
            "schema_id": schema_id,
            "version": version,
            "fields": fields,
            "registered_at": time.time(),
        }
        if compatible_with:
            for cv in compatible_with:
                compat_key = (schema_id, version, cv)
                cls._compatibility[compat_key] = True

    @classmethod
    def get(cls, schema_id, version):
        return cls._schemas.get((schema_id, version))

    @classmethod
    def is_compatible(cls, schema_id, reader_version, writer_version):
        if reader_version == writer_version:
            return True
        key = (schema_id, reader_version, writer_version)
        return cls._compatibility.get(key, False)

    @classmethod
    def list_schemas(cls):
        return {f"{k[0]}:v{k[1]}": v for k, v in cls._schemas.items()}


def _generate_schema_id(event_name, data):
    payload = json.dumps({"event": event_name, "data_keys": sorted(data.keys()) if isinstance(data, dict) else []}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class EventBus:
    def __init__(self):
        self._listeners = {}
        self._history = []
        self._max_history = 1000
        self._schema_version = EVENT_SCHEMA_VERSION
        self._schema_registry = EventSchemaRegistry()

    def on(self, event_name, callback):
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def off(self, event_name, callback=None):
        if event_name not in self._listeners:
            return
        if callback is None:
            del self._listeners[event_name]
        else:
            self._listeners[event_name] = [
                cb for cb in self._listeners[event_name] if cb != callback
            ]

    def emit(self, event_name, data=None):
        if data is None:
            data = {}

        schema_id = _generate_schema_id(event_name, data)

        record = {
            "event": event_name,
            "data": data,
            "timestamp": time.time(),
            "version": self._schema_version,
            "schema_id": schema_id,
        }
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        matched = set()

        exact = self._listeners.get(event_name, [])
        for cb in exact:
            matched.add(id(cb))
            self._safe_call(cb, event_name, data)

        wildcard = self._listeners.get("*", [])
        for cb in wildcard:
            if id(cb) not in matched:
                self._safe_call(cb, event_name, data)

        return record

    def _safe_call(self, callback, event_name, data):
        try:
            result = callback(event_name, data)
            if __import__("inspect").isawaitable(result):
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    asyncio.run(result)
        except Exception as e:
            __import__("sys").stderr.write(
                f"[EVENT] hook error on '{event_name}': {e}\n"
            )

    def validate_event(self, record):
        if not isinstance(record, dict):
            return False, "event must be a dict"
        if "event" not in record:
            return False, "missing 'event' field"
        if "version" not in record:
            return True, "legacy event (no version field)"
        writer_version = record.get("version", 0)
        schema_id = record.get("schema_id", "")
        if writer_version > self._schema_version:
            return False, f"event version {writer_version} exceeds engine version {self._schema_version}"
        if schema_id and writer_version > 1:
            expected_id = _generate_schema_id(record["event"], record.get("data", {}))
            if schema_id != expected_id:
                return True, f"schema_id mismatch (evolution detected: stored={schema_id}, current={expected_id})"
        return True, "valid"

    def upgrade_event(self, record):
        version = record.get("version", 0)
        if version == self._schema_version:
            return record
        upgraded = dict(record)
        upgraded["version"] = self._schema_version
        if "schema_id" not in upgraded:
            upgraded["schema_id"] = _generate_schema_id(
                upgraded.get("event", ""), upgraded.get("data", {})
            )
        return upgraded

    def listeners(self, event_name=None):
        if event_name:
            return [cb for cb in self._listeners.get(event_name, [])]
        return {k: len(v) for k, v in self._listeners.items()}

    def history(self, event_name=None, limit=50):
        records = self._history
        if event_name:
            records = [r for r in records if r["event"] == event_name]
        return records[-limit:]

    def clear(self):
        self._history.clear()

    @property
    def schema_version(self):
        return self._schema_version

    @property
    def schema_registry(self):
        return self._schema_registry


bus = EventBus()
