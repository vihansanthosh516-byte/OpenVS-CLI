import time
import json


class StreamManager:
    def __init__(self, bridge=None):
        self._active = {}
        self.bridge = bridge

    def start(self, job_id):
        self._active[job_id] = {
            "id": job_id,
            "tokens": [],
            "started_at": time.time(),
            "finished_at": None,
            "status": "streaming",
        }
        return self._active[job_id]

    def push(self, job_id, token):
        if job_id not in self._active:
            self.start(job_id)
        entry = self._active[job_id]
        entry["tokens"].append(token)

        if self.bridge:
            self.bridge.write_response({
                "type": "stream_token",
                "job_id": job_id,
                "token": token,
                "index": len(entry["tokens"]) - 1,
            })

    def finish(self, job_id, full_output=None):
        if job_id not in self._active:
            return None
        entry = self._active[job_id]
        entry["status"] = "completed"
        entry["finished_at"] = time.time()
        entry["full_output"] = full_output or "".join(entry["tokens"])

        if self.bridge:
            self.bridge.write_response({
                "type": "stream_end",
                "job_id": job_id,
                "total_tokens": len(entry["tokens"]),
            })

        result = dict(entry)
        del self._active[job_id]
        return result

    def simulate_stream(self, job_id, text, bridge=None, delay=0.02):
        words = text.split(" ")
        accumulated = ""
        self.start(job_id)

        target_bridge = bridge or self.bridge

        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            accumulated += token
            entry = self._active.get(job_id)
            if entry:
                entry["tokens"].append(token)

            if target_bridge:
                target_bridge.write_response({
                    "type": "stream_token",
                    "job_id": job_id,
                    "token": token,
                    "index": i,
                })

        self.finish(job_id, full_output=accumulated)
        return accumulated

    def active_streams(self):
        return {
            jid: {"tokens": len(e["tokens"]), "status": e["status"]}
            for jid, e in self._active.items()
        }
