import json
import time
import uuid
import os
from engine.errors import JobError


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CRASHED = "crashed"


class Job:
    def __init__(self, task, model="qwen"):
        self.id = str(uuid.uuid4())[:12]
        self.task = task
        self.model = model
        self.status = JobStatus.PENDING
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.result = None
        self.error = None
        self.transitions = [{"status": JobStatus.PENDING, "at": time.time()}]

    def to_dict(self):
        return {
            "id": self.id,
            "task": self.task[:100],
            "model": self.model,
            "status": self.status,
            "created_at": self.created_at,
            "duration_ms": int((self.finished_at or time.time()) - (self.started_at or self.created_at)) * 1000
            if self.started_at else None,
            "error": self.error,
            "transitions": self.transitions[-10:],
        }

    def to_jsonl(self):
        d = self.to_dict()
        d["_type"] = "job"
        return json.dumps(d, default=str)


class JobStore:
    def __init__(self, path=None):
        self.path = path
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._inflight = {}

    def append(self, job):
        if self.path:
            try:
                with open(self.path, "a") as f:
                    f.write(job.to_jsonl() + "\n")
            except Exception:
                pass

    def load_all(self, limit=500):
        if not self.path or not os.path.exists(self.path):
            return []
        jobs = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("_type") == "job":
                            jobs.append(d)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return jobs[-limit:]

    def update(self, job):
        if self.path:
            try:
                with open(self.path, "a") as f:
                    d = job.to_dict()
                    d["_type"] = "job_update"
                    d["updated_at"] = time.time()
                    f.write(json.dumps(d, default=str) + "\n")
            except Exception:
                pass

    def find_incomplete(self):
        all_records = self.load_all(limit=2000)
        latest = {}
        for r in all_records:
            jid = r.get("id")
            if jid:
                latest[jid] = r

        for r in list(self._load_updates().values()):
            jid = r.get("id")
            if jid:
                existing = latest.get(jid, {})
                existing.update(r)
                latest[jid] = existing

        incomplete = []
        for jid, record in latest.items():
            status = record.get("status", "")
            if status in (JobStatus.PENDING, JobStatus.RUNNING):
                record["status"] = JobStatus.CRASHED
                incomplete.append(record)

        return incomplete

    def _load_updates(self, limit=2000):
        if not self.path or not os.path.exists(self.path):
            return {}
        updates = {}
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("_type") == "job_update":
                            jid = d.get("id")
                            if jid:
                                updates[jid] = d
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return updates

    def mark_crashed(self, job_id):
        if self.path:
            try:
                with open(self.path, "a") as f:
                    f.write(json.dumps({
                        "_type": "job_update",
                        "id": job_id,
                        "status": JobStatus.CRASHED,
                        "updated_at": time.time(),
                        "error": "engine crashed during execution",
                    }) + "\n")
            except Exception:
                pass


class JobPipeline:
    def __init__(self, store=None, event_bus=None):
        self.jobs = []
        self._completed = 0
        self.store = store or JobStore()
        self._event_bus = event_bus

    def submit(self, task, model="qwen"):
        job = Job(task, model)
        self.jobs.append(job)
        self.store.append(job)
        return job

    def execute(self, job, model_client):
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.transitions.append({"status": JobStatus.RUNNING, "at": time.time()})
        self.store.update(job)

        try:
            response = model_client.call(
                job.model,
                [{"role": "user", "content": job.task}],
            )

            if "error" in response and not response.get("stub"):
                job.status = JobStatus.FAILED
                job.error = response["error"]
                job.finished_at = time.time()
                job.transitions.append({"status": JobStatus.FAILED, "at": time.time()})
                self.store.update(job)
                return job

            job.result = response
            job.status = JobStatus.COMPLETED
            self._completed += 1
            job.transitions.append({"status": JobStatus.COMPLETED, "at": time.time()})

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.transitions.append({"status": JobStatus.FAILED, "at": time.time(), "error": str(e)})

        job.finished_at = time.time()
        self.store.update(job)
        return job

    def recover(self):
        incomplete = self.store.find_incomplete()
        recovered = []
        for record in incomplete:
            jid = record.get("id")
            self.store.mark_crashed(jid)
            recovered.append({
                "id": jid,
                "task": record.get("task", ""),
                "model": record.get("model", "qwen"),
                "previous_status": record.get("status"),
                "recovered_as": JobStatus.CRASHED,
            })
            if self._event_bus:
                self._event_bus.emit("job_recovered", {
                    "job_id": jid,
                    "previous_status": record.get("status"),
                    "recovered_as": JobStatus.CRASHED,
                })
        return recovered

    def recent_jobs(self, limit=10):
        return [j.to_dict() for j in self.jobs[-limit:]]

    def load_history(self, limit=50):
        return self.store.load_all(limit=limit)

    def replay(self, job_id=None):
        records = self.load_history(limit=1000)
        if job_id:
            return [r for r in records if r.get("id") == job_id]
        return records

    def stats(self):
        return {
            "total": len(self.jobs),
            "completed": self._completed,
            "failed": sum(1 for j in self.jobs if j.status == JobStatus.FAILED),
            "pending": sum(1 for j in self.jobs if j.status == JobStatus.PENDING),
            "crashed": sum(1 for j in self.jobs if j.status == JobStatus.CRASHED),
        }
