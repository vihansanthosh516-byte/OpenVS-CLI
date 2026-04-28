import json
import time
import os
from engine.errors import EngineRuntimeError


EVENT_STORE_SCHEMA_VERSION = 1


class EventStore:
    def __init__(self, path=None, event_bus=None):
        self.path = path
        self._count = 0
        self._write_buffer = []
        self._buffer_limit = 50
        self._event_bus = event_bus
        self._schema_version = EVENT_STORE_SCHEMA_VERSION
        self._version_stats = {"v0": 0, "v1": 0}
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    def append(self, event_name, data):
        version = self._schema_version
        schema_id = self._compute_schema_id(event_name, data)

        record = {
            "event": event_name,
            "data": _serialize_data(data),
            "timestamp": time.time(),
            "seq": self._count,
            "version": version,
            "schema_id": schema_id,
        }
        self._count += 1

        if self.path:
            self._write_buffer.append(record)
            if len(self._write_buffer) >= self._buffer_limit:
                self._flush()

        return record

    def _flush(self):
        if not self.path or not self._write_buffer:
            return
        try:
            with open(self.path, "a") as f:
                for record in self._write_buffer:
                    f.write(json.dumps(record, default=str) + "\n")
            self._write_buffer.clear()
        except Exception:
            pass

    def flush(self):
        self._flush()

    def query(self, event_type=None, job_id=None, since=None, until=None,
              limit=200, schema_version=None, schema_id=None):
        self.flush()
        if not self.path or not os.path.exists(self.path):
            return []

        results = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event_type and record.get("event") != event_type:
                        continue
                    if job_id:
                        d = record.get("data", {})
                        if d.get("job_id") != job_id and job_id not in str(d.get("task", "")):
                            continue
                    if since and record.get("timestamp", 0) < since:
                        continue
                    if until and record.get("timestamp", 0) > until:
                        continue
                    if schema_version is not None and record.get("version") != schema_version:
                        continue
                    if schema_id and record.get("schema_id") != schema_id:
                        continue

                    results.append(record)
                    if len(results) >= limit:
                        break
        except Exception:
            pass

        return results

    def replay(self, event_type=None, since=None, until=None, limit=5000):
        return self.query(event_type=event_type, since=since, until=until, limit=limit)

    def replay_reconstruct(self, since=None):
        events = self.replay(since=since, limit=50000)
        state = {
            "model": "qwen",
            "jobs_completed": 0,
            "jobs_failed": 0,
            "plugins_loaded": [],
            "commands_executed": [],
            "errors": [],
        }

        for e in events:
            name = e.get("event", "")
            data = e.get("data", {})

            if name == "command_executed" and "model" in data:
                if data.get("command") == "init":
                    state["model"] = data["model"]
            if name == "job_finished":
                if data.get("status") == "completed":
                    state["jobs_completed"] += 1
                else:
                    state["jobs_failed"] += 1
            if name == "plugin_loaded":
                state["plugins_loaded"].append(data.get("plugin"))
            if name == "plugin_unloaded":
                pname = data.get("plugin")
                if pname in state["plugins_loaded"]:
                    state["plugins_loaded"].remove(pname)
            if name == "command_executed":
                state["commands_executed"].append({
                    "command": data.get("command"),
                    "status": data.get("status"),
                })
            if name == "error_occurred":
                state["errors"].append(data.get("type"))

        return state

    def validate_backwards_compat(self):
        self.flush()
        if not self.path or not os.path.exists(self.path):
            return {"status": "ok", "checked": 0, "incompatible": []}

        incompatible = []
        checked = 0
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    checked += 1
                    version = record.get("version", 0)
                    if version > self._schema_version:
                        incompatible.append({
                            "seq": record.get("seq"),
                            "event": record.get("event"),
                            "version": version,
                            "reason": f"event version {version} > store version {self._schema_version}",
                        })
        except Exception:
            pass

        return {
            "status": "ok" if not incompatible else "incompatible",
            "checked": checked,
            "incompatible": incompatible,
            "store_schema_version": self._schema_version,
        }

    def version_stats(self):
        self.flush()
        if not self.path or not os.path.exists(self.path):
            return {"v0": 0, "v1": 0, "total": 0}

        counts = {}
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    v = record.get("version", 0)
                    key = f"v{v}"
                    counts[key] = counts.get(key, 0) + 1
        except Exception:
            pass

        counts["total"] = sum(counts.values())
        return counts

    def count(self):
        return self._count

    def stats(self):
        self.flush()
        file_size = 0
        if self.path and os.path.exists(self.path):
            try:
                file_size = os.path.getsize(self.path)
            except Exception:
                pass
        return {
            "total_events": self._count,
            "buffer_pending": len(self._write_buffer),
            "path": self.path,
            "file_size_bytes": file_size,
            "schema_version": self._schema_version,
        }

    @staticmethod
    def _compute_schema_id(event_name, data):
        payload = json.dumps({
            "event": event_name,
            "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        }, sort_keys=True)
        import hashlib
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _serialize_data(data):
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            try:
                json.dumps({k: v})
                out[k] = v
            except (TypeError, ValueError):
                out[k] = str(v)
        return out
    return str(data)
