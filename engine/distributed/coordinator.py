import time
import uuid
from engine.distributed.core import WorkerState, WorkerRegistry, HeartbeatMonitor, RemoteExecution, ResultAggregator
from engine.errors import EngineRuntimeError


class SelectionStrategy:
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CAPABILITY_FIRST = "capability_first"
    RANDOM = "random"

    @staticmethod
    def select(workers, strategy=None, required_capabilities=None):
        if strategy is None:
            strategy = SelectionStrategy.LEAST_LOADED
        available = [w for w in workers if w.state == WorkerState.IDLE]
        if not available:
            return None

        if required_capabilities:
            capable = [w for w in available
                       if all(c in w.capabilities for c in required_capabilities)]
            if capable:
                available = capable

        if strategy == SelectionStrategy.ROUND_ROBIN:
            return available[0]
        elif strategy == SelectionStrategy.LEAST_LOADED:
            return min(available, key=lambda w: w.jobs_completed + (0 if w.state == WorkerState.IDLE else 1000))
        elif strategy == SelectionStrategy.CAPABILITY_FIRST:
            return max(available, key=lambda w: len(w.capabilities))
        else:
            return available[0]


class TaskAssignment:
    def __init__(self, task_id=None, task_data=None, worker_id=None,
                 priority=0, required_capabilities=None, status="pending"):
        self.id = task_id or str(uuid.uuid4())[:10]
        self.task_data = task_data or {}
        self.worker_id = worker_id
        self.priority = priority
        self.required_capabilities = required_capabilities or ["execute"]
        self.status = status
        self.assigned_at = None
        self.completed_at = None
        self.result = None
        self.error = None
        self.retries = 0
        self.max_retries = 3

    def to_dict(self):
        return {
            "id": self.id,
            "task_data": self.task_data,
            "worker_id": self.worker_id,
            "priority": self.priority,
            "required_capabilities": self.required_capabilities,
            "status": self.status,
            "assigned_at": self.assigned_at,
            "completed_at": self.completed_at,
            "retries": self.retries,
        }


class SwarmCoordinator:
    def __init__(self, registry=None, event_bus=None, selection_strategy=SelectionStrategy.LEAST_LOADED):
        self.registry = registry or WorkerRegistry()
        self._event_bus = event_bus
        self._strategy = selection_strategy
        self._assignments = {}
        self._pending_queue = []
        self._completed = []
        self._failed_assignments = []
        self.heartbeat = HeartbeatMonitor(self.registry)
        self.execution = RemoteExecution(self.registry, event_bus=event_bus)
        self.aggregator = ResultAggregator()
        self._failure_callbacks = []
        self._recovery_queue = []

    def submit(self, task_data, priority=0, required_capabilities=None, task_id=None):
        assignment = TaskAssignment(
            task_id=task_id,
            task_data=task_data,
            priority=priority,
            required_capabilities=required_capabilities or ["execute"],
        )

        worker = SelectionStrategy.select(
            self.registry._workers.values(),
            strategy=self._strategy,
            required_capabilities=required_capabilities,
        )

        if worker:
            return self._assign(assignment, worker)
        else:
            self._pending_queue.append(assignment)
            self._emit("task_queued", {
                "task_id": assignment.id,
                "queue_size": len(self._pending_queue),
            })
            return {
                "status": "queued",
                "task_id": assignment.id,
                "reason": "no available workers",
            }

    def _assign(self, assignment, worker):
        assignment.worker_id = worker.id
        assignment.status = "assigned"
        assignment.assigned_at = time.time()
        self._assignments[assignment.id] = assignment

        worker.state = WorkerState.BUSY
        worker._assigned_job = str(assignment.task_data)[:100]

        self._emit("task_assigned", {
            "task_id": assignment.id,
            "worker_id": worker.id,
            "priority": assignment.priority,
        })

        return {
            "status": "assigned",
            "task_id": assignment.id,
            "worker_id": worker.id,
        }

    def complete(self, task_id, result):
        assignment = self._assignments.get(task_id)
        if not assignment:
            return {"status": "error", "error": f"task {task_id} not found"}

        assignment.status = "completed"
        assignment.completed_at = time.time()
        assignment.result = result

        if assignment.worker_id:
            self.execution.complete(assignment.worker_id, result)

        self.aggregator.collect(task_id, assignment.worker_id, result)
        self._completed.append(assignment)

        self._emit("task_completed", {
            "task_id": task_id,
            "worker_id": assignment.worker_id,
        })

        self._process_pending()
        return {"status": "ok", "task_id": task_id}

    def fail(self, task_id, error):
        assignment = self._assignments.get(task_id)
        if not assignment:
            return {"status": "error", "error": f"task {task_id} not found"}

        assignment.retries += 1
        if assignment.retries < assignment.max_retries:
            assignment.status = "retrying"
            if assignment.worker_id:
                self.execution.fail(assignment.worker_id, error)
            self._emit("task_retry", {
                "task_id": task_id,
                "attempt": assignment.retries,
            })
            worker = SelectionStrategy.select(
                self.registry._workers.values(),
                strategy=self._strategy,
                required_capabilities=assignment.required_capabilities,
            )
            if worker:
                return self._assign(assignment, worker)
            else:
                self._pending_queue.append(assignment)

        assignment.status = "failed"
        assignment.error = str(error)[:500]
        if assignment.worker_id:
            self.execution.fail(assignment.worker_id, error)
        self._failed_assignments.append(assignment)

        self._emit("task_failed_final", {
            "task_id": task_id,
            "error": str(error)[:200],
            "retries": assignment.retries,
        })

        for cb in self._failure_callbacks:
            try:
                cb(assignment, error)
            except Exception:
                pass

        self._process_pending()
        return {"status": "failed", "task_id": task_id, "error": str(error)[:200]}

    def on_worker_failure(self, callback):
        self._failure_callbacks.append(callback)

    def handle_dead_worker(self, worker_id):
        worker = self.registry.get(worker_id)
        if not worker:
            return

        worker.state = WorkerState.FAILED
        self._emit("worker_dead", {"worker_id": worker_id})

        affected = [
            a for a in self._assignments.values()
            if a.worker_id == worker_id and a.status in ("assigned", "retrying")
        ]

        for assignment in affected:
            assignment.status = "orphaned"
            assignment.worker_id = None
            self._recovery_queue.append(assignment)
            self._emit("task_orphaned", {
                "task_id": assignment.id,
                "dead_worker": worker_id,
            })

        self._recover_orphaned()

    def _recover_orphaned(self):
        while self._recovery_queue:
            assignment = self._recovery_queue.pop(0)
            worker = SelectionStrategy.select(
                self.registry._workers.values(),
                strategy=self._strategy,
                required_capabilities=assignment.required_capabilities,
            )
            if worker:
                self._assign(assignment, worker)
                self._emit("task_recovered", {
                    "task_id": assignment.id,
                    "new_worker": worker.id,
                })
            else:
                self._pending_queue.append(assignment)
                break

    def _process_pending(self):
        while self._pending_queue:
            assignment = self._pending_queue[0]
            worker = SelectionStrategy.select(
                self.registry._workers.values(),
                strategy=self._strategy,
                required_capabilities=assignment.required_capabilities,
            )
            if worker:
                self._pending_queue.pop(0)
                self._assign(assignment, worker)
            else:
                break

    def rebalance(self):
        moved = 0
        busy_workers = [w for w in self.registry._workers.values() if w.state == WorkerState.BUSY]
        idle_workers = [w for w in self.registry._workers.values() if w.state == WorkerState.IDLE]

        for busy_w in busy_workers:
            if not idle_workers:
                break
            load = busy_w.jobs_completed + busy_w.jobs_failed
            avg_load = sum(w.jobs_completed + w.jobs_failed for w in self.registry._workers.values()) / max(len(self.registry._workers), 1)
            if load > avg_load * 1.5 and idle_workers:
                target = idle_workers.pop(0)
                self._emit("rebalance_suggested", {
                    "from_worker": busy_w.id,
                    "to_worker": target.id,
                })
                moved += 1

        return {"status": "ok", "moved": moved}

    def status(self):
        return {
            "registry": self.registry.stats(),
            "assignments": {
                "active": len([a for a in self._assignments.values() if a.status in ("assigned", "retrying")]),
                "pending": len(self._pending_queue),
                "recovery": len(self._recovery_queue),
                "completed": len(self._completed),
                "failed": len(self._failed_assignments),
            },
            "strategy": self._strategy,
        }

    def list_assignments(self):
        return [a.to_dict() for a in self._assignments.values()]

    def _emit(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"coordinator_{event_name}", data)
