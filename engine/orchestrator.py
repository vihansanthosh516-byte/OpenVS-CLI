import time
import sys
import os

_engine_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_engine_dir)
sys.path.insert(0, _project_dir)
sys.path.insert(0, _engine_dir)

from model_client import ModelClient
from jobs import JobPipeline, JobStore
from events import EventBus
from hooks import HookSystem
from executor import Executor
from stream import StreamManager
from errors import EngineRuntimeError, ModelError

VERSION = "0.5.0"


class Orchestrator:
    def __init__(self, events=None, hooks=None, store_path=None):
        self.model = "qwen"
        self.config = {}
        self.model_client = ModelClient()
        self.events = events or EventBus()
        self.hooks = hooks or HookSystem(event_bus=self.events)
        self.store = JobStore(path=store_path)
        self.pipeline = JobPipeline(store=self.store, event_bus=self.events)
        self.executor = Executor()
        self.stream = StreamManager()
        self._start_time = time.time()
        self._plugin_runtime = None
        self._observability = None
        self._lifecycle = None
        self._sandbox = None
        self._event_store = None
        self._swarm = None
        self._coordinator = None
        self._network = None
        self._replay = None

    def attach_plugin_runtime(self, plugin_runtime):
        self._plugin_runtime = plugin_runtime

    def attach_observability(self, observability):
        self._observability = observability

    def attach_lifecycle(self, lifecycle):
        self._lifecycle = lifecycle

    def attach_sandbox(self, sandbox):
        self._sandbox = sandbox

    def attach_event_store(self, event_store):
        self._event_store = event_store

    def attach_swarm(self, swarm):
        self._swarm = swarm

    def attach_coordinator(self, coordinator):
        self._coordinator = coordinator

    def attach_network(self, network):
        self._network = network

    def attach_replay(self, replay_engine):
        self._replay = replay_engine

    def execute(self, task):
        self.events.emit("job_started", {"task": task[:200], "model": self.model})
        self.hooks._execute("job_started", {"task": task, "model": self.model})

        job = self.pipeline.submit(task, model=self.model)
        job = self.pipeline.execute(job, self.model_client)

        if job.status == "completed":
            self.events.emit("job_finished", {"job_id": job.id, "status": "completed"})
            self.hooks._execute("job_finished", {"job_id": job.id, "status": "completed"})

        resp = job.result or {}
        if resp.get("stub"):
            fix = resp.get("fix", "set API key in config")
            output = f"[{self.model}] (stub mode) Task: {task[:200]}\n {resp.get('error', 'API key missing')}.\n Fix: {fix}"
        elif resp.get("error"):
            output = f"[{self.model}] error: {resp.get('error', 'unknown')}"
        elif resp.get("content"):
            output = resp["content"]
        else:
            content = self._extract_content(resp)
            output = content or f"[{self.model}] completed (no text in response)"
            self.events.emit("error_occurred", {"job_id": job.id, "error": job.error})
            output = f"[{self.model}] job failed: {job.error}"

        return {
            "output": output,
            "trace": {
                "job_id": job.id,
                "task": task[:200],
                "model": self.model,
                "status": job.status,
                "mode": "single",
                "timestamp": time.time(),
            },
        }

    def execute_streaming(self, task, bridge=None):
        self.events.emit("job_started", {"task": task[:200], "model": self.model})

        job = self.pipeline.submit(task, model=self.model)
        job = self.pipeline.execute(job, self.model_client)

        if job.status == "completed":
            self.events.emit("job_finished", {"job_id": job.id, "status": "completed"})

            resp = job.result or {}
            if resp.get("stub"):
                full_text = f"[{self.model}] (stub) {task[:200]}"
            else:
                full_text = self._extract_content(resp) or f"[{self.model}] completed"

            self.stream.bridge = bridge
            self.stream.simulate_stream(job.id, full_text, bridge=bridge)

            self.events.emit("job_finished", {"job_id": job.id, "status": "completed", "streamed": True})

            return {
                "output": full_text,
                "streamed": True,
                "trace": {
                    "job_id": job.id,
                    "task": task[:200],
                    "model": self.model,
                    "status": job.status,
                    "mode": "single_streaming",
                    "timestamp": time.time(),
                },
            }
        else:
            self.events.emit("error_occurred", {"job_id": job.id, "error": job.error})
            return {
                "output": f"[{self.model}] job failed: {job.error}",
                "streamed": False,
                "trace": {"job_id": job.id, "status": "failed"},
            }

    def status(self):
        elapsed = time.time() - self._start_time
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"

        job_stats = self.pipeline.stats()

        return {
            "version": VERSION,
            "model": self.model,
            "jobs_completed": job_stats["completed"],
            "jobs_failed": job_stats["failed"],
            "jobs_total": job_stats["total"],
            "uptime": uptime,
            "mode": "single",
            "model_client": "connected" if self.model_client.available else "stub",
            "events": self.events.listeners(),
            "hooks": self.hooks.stats(),
            "executor": self.executor.stats(),
        }

    @staticmethod
    def _extract_content(response):
        if "choices" in response:
            try:
                return response["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                pass
        if "output" in response:
            try:
                content = response["output"][0].get("content", [])
                if isinstance(content, list) and content:
                    return content[0].get("text", "")
            except (KeyError, IndexError, TypeError):
                pass
        return None
