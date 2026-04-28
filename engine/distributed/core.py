import time
import uuid
from engine.errors import EngineRuntimeError


class WorkerState:
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"
    FAILED = "failed"


class Worker:
    def __init__(self, worker_id=None, capabilities=None, host="local"):
        self.id = worker_id or str(uuid.uuid4())[:8]
        self.capabilities = capabilities or ["execute"]
        self.host = host
        self.state = WorkerState.IDLE
        self.last_heartbeat = time.time()
        self.jobs_completed = 0
        self.jobs_failed = 0
        self._assigned_job = None

    def to_dict(self):
        return {
            "id": self.id,
            "host": self.host,
            "state": self.state,
            "capabilities": self.capabilities,
            "last_heartbeat": self.last_heartbeat,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
            "assigned_job": self._assigned_job,
        }


class WorkerRegistry:
    def __init__(self):
        self._workers = {}

    def register(self, worker_id=None, capabilities=None, host="local"):
        wid = worker_id or str(uuid.uuid4())[:8]
        worker = Worker(worker_id=wid, capabilities=capabilities, host=host)
        self._workers[wid] = worker
        return worker

    def unregister(self, worker_id):
        if worker_id in self._workers:
            del self._workers[worker_id]
            return True
        return False

    def get(self, worker_id):
        return self._workers.get(worker_id)

    def available(self):
        return [w for w in self._workers.values() if w.state == WorkerState.IDLE]

    def list_all(self):
        return [w.to_dict() for w in self._workers.values()]

    def stats(self):
        by_state = {}
        for w in self._workers.values():
            by_state[w.state] = by_state.get(w.state, 0) + 1
        return {
            "total": len(self._workers),
            "by_state": by_state,
            "total_completed": sum(w.jobs_completed for w in self._workers.values()),
            "total_failed": sum(w.jobs_failed for w in self._workers.values()),
        }


class HeartbeatMonitor:
    def __init__(self, registry, timeout_s=30):
        self.registry = registry
        self.timeout_s = timeout_s

    def check(self):
        now = time.time()
        stale = []
        for worker in self.registry._workers.values():
            if worker.state in (WorkerState.IDLE, WorkerState.BUSY):
                if now - worker.last_heartbeat > self.timeout_s:
                    worker.state = WorkerState.FAILED
                    stale.append(worker.id)
        return stale

    def ping(self, worker_id):
        worker = self.registry.get(worker_id)
        if worker:
            worker.last_heartbeat = time.time()
            if worker.state == WorkerState.FAILED:
                worker.state = WorkerState.IDLE
            return True
        return False


class RemoteExecution:
    def __init__(self, registry, event_bus=None):
        self.registry = registry
        self.event_bus = event_bus

    def delegate(self, task, model="qwen", preferred_worker=None):
        workers = self.registry.available()
        if not workers:
            self._ensure_local()
            workers = self.registry.available()

        worker = None
        if preferred_worker:
            worker = self.registry.get(preferred_worker)
            if worker and worker.state != WorkerState.IDLE:
                worker = None

        if not worker and workers:
            worker = workers[0]

        if not worker:
            raise EngineRuntimeError("no workers available", component="remote_execution")

        worker.state = WorkerState.BUSY
        worker._assigned_job = task[:100]
        if self.event_bus:
            self.event_bus.emit("worker_assigned", {
                "worker_id": worker.id,
                "task": task[:100],
                "model": model,
            })

        return worker

    def complete(self, worker_id, result):
        worker = self.registry.get(worker_id)
        if worker:
            worker.state = WorkerState.IDLE
            worker.jobs_completed += 1
            worker._assigned_job = None
            if self.event_bus:
                self.event_bus.emit("worker_completed", {
                    "worker_id": worker_id,
                    "status": "completed",
                })
        return worker

    def fail(self, worker_id, error):
        worker = self.registry.get(worker_id)
        if worker:
            worker.state = WorkerState.IDLE
            worker.jobs_failed += 1
            worker._assigned_job = None
            if self.event_bus:
                self.event_bus.emit("worker_failed", {
                    "worker_id": worker_id,
                    "error": str(error)[:200],
                })
        return worker

    def _ensure_local(self):
        if not self.registry._workers:
            self.registry.register(worker_id="local-0", capabilities=["execute", "stream"], host="localhost")


class ResultAggregator:
    def __init__(self):
        self._results = {}

    def collect(self, task_id, worker_id, result):
        if task_id not in self._results:
            self._results[task_id] = []
        self._results[task_id].append({
            "worker_id": worker_id,
            "result": result,
            "timestamp": time.time(),
        })

    def aggregate(self, task_id):
        entries = self._results.get(task_id, [])
        if not entries:
            return None

        if len(entries) == 1:
            return entries[0]["result"]

        return {
            "task_id": task_id,
            "workers": len(entries),
            "results": entries,
            "status": "aggregated",
        }

    def stats(self):
        return {
            "tasks_tracked": len(self._results),
            "total_results": sum(len(v) for v in self._results.values()),
        }


class SwarmFoundation:
    def __init__(self, event_bus=None):
        self.registry = WorkerRegistry()
        self.heartbeat = HeartbeatMonitor(self.registry)
        self.execution = RemoteExecution(self.registry, event_bus=event_bus)
        self.aggregator = ResultAggregator()
        self._event_bus = event_bus
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        self._initialized = True
        self.registry.register(worker_id="local-0", capabilities=["execute", "stream"], host="localhost")
        self.registry.register(worker_id="local-1", capabilities=["execute"], host="localhost")
        self.registry.register(worker_id="local-2", capabilities=["execute"], host="localhost")
        if self._event_bus:
            self._event_bus.emit("swarm_initialized", {
                "workers": len(self.registry._workers),
            })

    def stats(self):
        return {
            "registry": self.registry.stats(),
            "aggregator": self.aggregator.stats(),
            "initialized": self._initialized,
        }
