import json
import time
import uuid
import hashlib
from engine.errors import EngineRuntimeError


NETWORK_PROTOCOL_VERSION = 1

TRANSPORT_LOCAL = "local"
TRANSPORT_HTTP = "http"
TRANSPORT_WEBSOCKET = "websocket"
TRANSPORT_GRPC = "grpc"


class RPCMessage:
    def __init__(self, method, params=None, msg_id=None, source=None,
                 target=None, msg_type="request", result=None, error=None,
                 meta=None):
        self.id = msg_id or str(uuid.uuid4())[:10]
        self.method = method
        self.params = params or {}
        self.source = source
        self.target = target
        self.type = msg_type
        self.result = result
        self.error = error
        self.meta = meta or {}
        self.timestamp = time.time()
        self.protocol_version = NETWORK_PROTOCOL_VERSION

    def to_dict(self):
        d = {
            "id": self.id,
            "method": self.method,
            "type": self.type,
            "timestamp": self.timestamp,
            "protocol_version": self.protocol_version,
        }
        if self.params:
            d["params"] = self.params
        if self.source:
            d["source"] = self.source
        if self.target:
            d["target"] = self.target
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.meta:
            d["meta"] = self.meta
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d):
        msg = cls(
            method=d.get("method", ""),
            params=d.get("params", {}),
            msg_id=d.get("id"),
            source=d.get("source"),
            target=d.get("target"),
            msg_type=d.get("type", "request"),
            result=d.get("result"),
            error=d.get("error"),
            meta=d.get("meta", {}),
        )
        msg.timestamp = d.get("timestamp", time.time())
        msg.protocol_version = d.get("protocol_version", NETWORK_PROTOCOL_VERSION)
        return msg

    @classmethod
    def response(cls, request, result=None, error=None):
        return cls(
            method=request.method,
            msg_id=request.id,
            source=request.target,
            target=request.source,
            msg_type="response",
            result=result,
            error=error,
        )


class TransportLayer:
    def __init__(self, transport_type=TRANSPORT_LOCAL, event_bus=None):
        self.transport_type = transport_type
        self._event_bus = event_bus
        self._connections = {}
        self._message_handlers = {}
        self._pending = {}
        self._stats = {
            "sent": 0,
            "received": 0,
            "retries": 0,
            "timeouts": 0,
            "errors": 0,
        }

    def register_handler(self, method, handler_fn):
        self._message_handlers[method] = handler_fn

    def send(self, message, timeout_s=30, max_retries=3):
        self._stats["sent"] += 1

        if self.transport_type == TRANSPORT_LOCAL:
            return self._send_local(message, timeout_s, max_retries)

        self._emit_network("message_sent", {
            "msg_id": message.id,
            "method": message.method,
            "target": message.target,
            "transport": self.transport_type,
        })
        return self._send_local(message, timeout_s, max_retries)

    def _send_local(self, message, timeout_s, max_retries):
        handler = self._message_handlers.get(message.method)
        if not handler:
            self._stats["errors"] += 1
            return RPCMessage.response(message, error=f"no handler for method: {message.method}")

        retries = 0
        last_error = None
        while retries <= max_retries:
            try:
                result = handler(message)
                self._stats["received"] += 1
                return RPCMessage.response(message, result=result)
            except Exception as e:
                last_error = str(e)
                retries += 1
                if retries <= max_retries:
                    self._stats["retries"] += 1
                    self._emit_network("message_retry", {
                        "msg_id": message.id,
                        "attempt": retries,
                        "error": last_error,
                    })

        self._stats["errors"] += 1
        return RPCMessage.response(message, error=f"failed after {retries} retries: {last_error}")

    def receive(self, raw_data):
        try:
            d = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            message = RPCMessage.from_dict(d)
            self._stats["received"] += 1
            return message
        except Exception as e:
            self._stats["errors"] += 1
            return None

    def stats(self):
        return dict(self._stats)

    def _emit_network(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"network_{event_name}", data)


class WorkerHandshake:
    def __init__(self, transport, event_bus=None):
        self._transport = transport
        self._event_bus = event_bus
        self._registered = {}

    def initiate(self, worker_id, capabilities=None, metadata=None):
        msg = RPCMessage(
            method="handshake.init",
            params={
                "worker_id": worker_id,
                "capabilities": capabilities or ["execute"],
                "metadata": metadata or {},
                "protocol_version": NETWORK_PROTOCOL_VERSION,
            },
            source=worker_id,
        )

        response = self._transport.send(msg)
        accepted = response.result.get("accepted", False) if response and response.result else False

        if accepted:
            self._registered[worker_id] = {
                "worker_id": worker_id,
                "capabilities": capabilities or ["execute"],
                "registered_at": time.time(),
                "protocol_version": NETWORK_PROTOCOL_VERSION,
            }
            self._emit_network("worker_registered", {"worker_id": worker_id})

        return {
            "accepted": accepted,
            "worker_id": worker_id,
            "assigned_id": response.result.get("assigned_id", worker_id) if response and response.result else None,
        }

    def respond(self, message):
        worker_id = message.params.get("worker_id", message.source)
        self._registered[worker_id] = {
            "worker_id": worker_id,
            "capabilities": message.params.get("capabilities", ["execute"]),
            "registered_at": time.time(),
            "protocol_version": message.params.get("protocol_version", NETWORK_PROTOCOL_VERSION),
        }
        self._emit_network("handshake_accepted", {"worker_id": worker_id})
        return {
            "accepted": True,
            "assigned_id": worker_id,
            "coordinator_version": NETWORK_PROTOCOL_VERSION,
        }

    def is_registered(self, worker_id):
        return worker_id in self._registered

    def list_registered(self):
        return dict(self._registered)

    def _emit_network(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"network_{event_name}", data)


class TaskProtocol:
    def __init__(self, transport, event_bus=None):
        self._transport = transport
        self._event_bus = event_bus
        self._tasks = {}

    def submit(self, task_id, task_data, target_worker=None, priority=0):
        msg = RPCMessage(
            method="task.submit",
            params={
                "task_id": task_id,
                "task_data": task_data,
                "priority": priority,
                "submitted_at": time.time(),
            },
            target=target_worker,
        )

        self._tasks[task_id] = {
            "task_id": task_id,
            "status": "submitted",
            "target": target_worker,
            "submitted_at": time.time(),
        }

        self._emit_network("task_submitted", {
            "task_id": task_id,
            "target": target_worker,
        })

        response = self._transport.send(msg)
        if response and response.error:
            self._tasks[task_id]["status"] = "submit_failed"
            self._tasks[task_id]["error"] = response.error

        return response

    def return_result(self, task_id, worker_id, result):
        msg = RPCMessage(
            method="task.result",
            params={
                "task_id": task_id,
                "worker_id": worker_id,
                "result": result,
                "completed_at": time.time(),
            },
            source=worker_id,
        )

        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "completed"
            self._tasks[task_id]["completed_at"] = time.time()
            self._tasks[task_id]["worker_id"] = worker_id

        self._emit_network("task_result", {
            "task_id": task_id,
            "worker_id": worker_id,
        })

        return self._transport.send(msg)

    def fail_task(self, task_id, worker_id, error):
        msg = RPCMessage(
            method="task.fail",
            params={
                "task_id": task_id,
                "worker_id": worker_id,
                "error": str(error)[:500],
                "failed_at": time.time(),
            },
            source=worker_id,
        )

        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "failed"
            self._tasks[task_id]["error"] = str(error)[:500]

        self._emit_network("task_failed", {
            "task_id": task_id,
            "worker_id": worker_id,
            "error": str(error)[:200],
        })

        return self._transport.send(msg)

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def stats(self):
        by_status = {}
        for t in self._tasks.values():
            s = t.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total_tasks": len(self._tasks),
            "by_status": by_status,
        }

    def _emit_network(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"network_{event_name}", data)


class NodeRegistry:
    def __init__(self, event_bus=None):
        self._event_bus = event_bus
        self._nodes = {}

    def register(self, node_id, host="localhost", port=None,
                 capabilities=None, transport_type=TRANSPORT_LOCAL, metadata=None):
        self._nodes[node_id] = {
            "node_id": node_id,
            "host": host,
            "port": port,
            "capabilities": capabilities or ["execute"],
            "transport": transport_type,
            "status": "online",
            "registered_at": time.time(),
            "last_seen": time.time(),
            "metadata": metadata or {},
        }
        self._emit_network("node_registered", {"node_id": node_id, "host": host})
        return self._nodes[node_id]

    def unregister(self, node_id):
        if node_id in self._nodes:
            del self._nodes[node_id]
            self._emit_network("node_unregistered", {"node_id": node_id})
            return True
        return False

    def get(self, node_id):
        return self._nodes.get(node_id)

    def heartbeat(self, node_id):
        if node_id in self._nodes:
            self._nodes[node_id]["last_seen"] = time.time()
            return True
        return False

    def list_all(self):
        return dict(self._nodes)

    def find_by_capability(self, capability):
        return {
            nid: n for nid, n in self._nodes.items()
            if capability in n.get("capabilities", []) and n.get("status") == "online"
        }

    def stats(self):
        by_status = {}
        for n in self._nodes.values():
            s = n.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total_nodes": len(self._nodes),
            "by_status": by_status,
        }

    def _emit_network(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"network_{event_name}", data)


class NetworkLayer:
    def __init__(self, event_bus=None, transport_type=TRANSPORT_LOCAL):
        self._event_bus = event_bus
        self.transport = TransportLayer(transport_type=transport_type, event_bus=event_bus)
        self.handshake = WorkerHandshake(self.transport, event_bus=event_bus)
        self.task_protocol = TaskProtocol(self.transport, event_bus=event_bus)
        self.node_registry = NodeRegistry(event_bus=event_bus)
        self._initialized = False

    def initialize(self, node_id="coordinator-0", host="localhost"):
        self.node_registry.register(node_id, host=host, capabilities=["coordinator", "execute"])
        self._initialized = True
        self._emit_network("network_initialized", {
            "node_id": node_id,
            "transport": self.transport.transport_type,
        })

    def register_worker(self, worker_id, capabilities=None, host="localhost"):
        result = self.handshake.initiate(worker_id, capabilities=capabilities)
        if result.get("accepted"):
            self.node_registry.register(
                worker_id, host=host,
                capabilities=capabilities or ["execute"],
            )
        return result

    def submit_task(self, task_id, task_data, target_worker=None, priority=0):
        return self.task_protocol.submit(task_id, task_data,
                                         target_worker=target_worker, priority=priority)

    def complete_task(self, task_id, worker_id, result):
        return self.task_protocol.return_result(task_id, worker_id, result)

    def fail_task(self, task_id, worker_id, error):
        return self.task_protocol.fail_task(task_id, worker_id, error)

    def stats(self):
        return {
            "transport": self.transport.stats(),
            "nodes": self.node_registry.stats(),
            "tasks": self.task_protocol.stats(),
            "initialized": self._initialized,
        }

    def _emit_network(self, event_name, data):
        if self._event_bus:
            self._event_bus.emit(f"network_{event_name}", data)
