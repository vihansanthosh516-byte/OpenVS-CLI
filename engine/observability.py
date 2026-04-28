import time
import json
import os
from engine.events import EventBus


class ObservabilitySystem:
    def __init__(self, event_bus=None, store_dir=None):
        self._event_bus = event_bus
        self._store_dir = store_dir
        self._spans = {}
        self._traces = {}
        self._metrics = {
            "total_events": 0,
            "event_counts": {},
            "job_latencies": [],
            "command_latencies": [],
            "errors": [],
        }
        self._timeline = []
        self._live_subscribers = []
        self._stream_active = False

        if self._store_dir:
            os.makedirs(self._store_dir, exist_ok=True)

        if event_bus:
            event_bus.on("*", self._on_any_event)

    def _on_any_event(self, event_name, data):
        self._metrics["total_events"] += 1
        self._metrics["event_counts"][event_name] = self._metrics["event_counts"].get(event_name, 0) + 1

        record = {
            "event": event_name,
            "data": _safe_serialize(data),
            "timestamp": time.time(),
            "index": len(self._timeline),
        }
        self._timeline.append(record)

        if len(self._timeline) > 5000:
            self._timeline = self._timeline[-5000:]

        self._push_live(event_name, record)

        if event_name == "job_started":
            job_id = data.get("job_id", data.get("task", "unknown"))
            self._spans[job_id] = {"start": time.time(), "data": data}

        if event_name == "job_finished":
            job_id = data.get("job_id", "unknown")
            if job_id in self._spans:
                span = self._spans.pop(job_id)
                latency = time.time() - span["start"]
                self._metrics["job_latencies"].append({
                    "job_id": job_id,
                    "latency_s": round(latency, 4),
                    "status": data.get("status", "unknown"),
                })
                if len(self._metrics["job_latencies"]) > 500:
                    self._metrics["job_latencies"] = self._metrics["job_latencies"][-500:]

                self._traces[job_id] = {
                    "job_id": job_id,
                    "start": span["start"],
                    "end": time.time(),
                    "latency_s": round(latency, 4),
                    "start_data": _safe_serialize(span["data"]),
                    "end_data": _safe_serialize(data),
                }

        if event_name == "command_executed":
            cmd = data.get("command", "unknown")
            self._metrics["command_latencies"].append({
                "command": cmd,
                "status": data.get("status", "unknown"),
                "timestamp": time.time(),
            })
            if len(self._metrics["command_latencies"]) > 500:
                self._metrics["command_latencies"] = self._metrics["command_latencies"][-500:]

        if event_name == "error_occurred":
            self._metrics["errors"].append({
                "type": data.get("type", "unknown"),
                "timestamp": time.time(),
            })
            if len(self._metrics["errors"]) > 100:
                self._metrics["errors"] = self._metrics["errors"][-100:]

    def subscribe_live(self, callback, event_filter=None):
        sub = {
            "id": id(callback),
            "callback": callback,
            "filter": event_filter,
        }
        self._live_subscribers.append(sub)
        return sub["id"]

    def unsubscribe_live(self, sub_id):
        self._live_subscribers = [s for s in self._live_subscribers if s["id"] != sub_id]

    def _push_live(self, event_name, record):
        for sub in self._live_subscribers:
            if sub["filter"] and event_name != sub["filter"]:
                continue
            try:
                sub["callback"](event_name, record)
            except Exception:
                pass

    def start_stream(self, bridge, event_filter=None):
        self._stream_active = True
        def _bridge_stream(event_name, record):
            if not self._stream_active:
                return
            try:
                bridge.write_response({
                    "type": "event_stream",
                    "event": event_name,
                    "data": record.get("data", {}),
                    "timestamp": record.get("timestamp"),
                })
            except Exception:
                self._stream_active = False

        sub_id = self.subscribe_live(_bridge_stream, event_filter=event_filter)
        return sub_id

    def stop_stream(self):
        self._stream_active = False
        self._live_subscribers.clear()

    @property
    def stream_active(self):
        return self._stream_active

    def trace(self, job_id):
        if job_id in self._traces:
            return self._traces[job_id]

        events = [
            e for e in self._timeline
            if e.get("data", {}).get("job_id") == job_id
               or e.get("data", {}).get("task", "").startswith(job_id)
        ]
        if events:
            return {"job_id": job_id, "events": events}

        return None

    def timeline(self, event_name=None, limit=100):
        records = self._timeline
        if event_name:
            records = [r for r in records if r["event"] == event_name]
        return records[-limit:]

    def metrics(self):
        job_latencies = self._metrics["job_latencies"]
        avg_job_latency = 0
        if job_latencies:
            avg_job_latency = round(
                sum(l["latency_s"] for l in job_latencies) / len(job_latencies), 4
            )

        return {
            "total_events": self._metrics["total_events"],
            "event_counts": dict(self._metrics["event_counts"]),
            "avg_job_latency_s": avg_job_latency,
            "total_jobs_tracked": len(job_latencies),
            "total_commands_tracked": len(self._metrics["command_latencies"]),
            "total_errors": len(self._metrics["errors"]),
            "timeline_size": len(self._timeline),
            "active_spans": len(self._spans),
            "traces_stored": len(self._traces),
            "live_subscribers": len(self._live_subscribers),
            "stream_active": self._stream_active,
        }

    def export_bundle(self, path=None):
        bundle = {
            "timestamp": time.time(),
            "metrics": self.metrics(),
            "timeline": self.timeline(limit=500),
            "traces": {k: v for k, v in list(self._traces.items())[-50:]},
            "recent_job_latencies": self._metrics["job_latencies"][-50:],
            "recent_errors": self._metrics["errors"][-20:],
        }

        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(bundle, f, indent=2, default=str)
            except Exception:
                pass

        return bundle


def _safe_serialize(data):
    if isinstance(data, dict):
        return {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                for k, v in data.items()}
    return data


observability = ObservabilitySystem()
