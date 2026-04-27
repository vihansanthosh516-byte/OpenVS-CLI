"""
Actor Protocol — message passing protocol for swarm agent communication.

Every agent in the swarm communicates through typed messages.
No shared state. No direct function calls between agents.
Everything is a message on the bus.

Message types:
- TASK_ASSIGN: coordinator → worker (here's your subtask)
- TASK_RESULT: worker → coordinator (here's what I did)
- TASK_FAILED: worker → coordinator (I couldn't do it)
- CONSENSUS_REQUEST: coordinator → agents (vote on this)
- CONSENSUS_VOTE: agent → coordinator (here's my vote)
- POLICY_CHECK: any → policy engine (can I do this?)
- POLICY_RESULT: policy engine → any (yes/no + reason)
- HEARTBEAT: worker → fabric (I'm alive)
- DELEGATE: planner → coordinator (break this into subtasks)
- MERGE_REQUEST: coordinator → merge engine (merge these patches)
"""

import time
import uuid
from enum import Enum
from typing import Optional
from core.event_bus import bus


class MessageType(Enum):
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_FAILED = "task_failed"
    CONSENSUS_REQUEST = "consensus_request"
    CONSENSUS_VOTE = "consensus_vote"
    POLICY_CHECK = "policy_check"
    POLICY_RESULT = "policy_result"
    HEARTBEAT = "heartbeat"
    DELEGATE = "delegate"
    MERGE_REQUEST = "merge_request"
    MERGE_RESULT = "merge_result"
    CANCEL = "cancel"
    RETRY = "retry"


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class ActorMessage:
    """A typed message between swarm actors.

    All inter-agent communication flows through these messages.
    No direct method calls between agents — only messages.
    """

    def __init__(
        self,
        msg_type: MessageType,
        sender: str,
        recipient: str,
        payload: dict,
        priority: MessagePriority = MessagePriority.NORMAL,
        reply_to: str = None,
        correlation_id: str = None,
    ):
        self.id = f"msg_{uuid.uuid4().hex[:8]}"
        self.type = msg_type
        self.sender = sender
        self.recipient = recipient
        self.payload = payload
        self.priority = priority
        self.reply_to = reply_to
        self.correlation_id = correlation_id or self.id
        self.timestamp = time.time()
        self.delivered = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "priority": self.priority.value,
            "reply_to": self.reply_to,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "delivered": self.delivered,
        }


class ActorProtocol:
    """The message passing protocol for swarm communication.

    Usage:
        protocol = ActorProtocol()

        # Send a task assignment
        protocol.send(ActorMessage(
            msg_type=MessageType.TASK_ASSIGN,
            sender="coordinator",
            recipient="worker_1",
            payload={"task": "Fix auth bug", "role": "coder"},
        ))

        # Subscribe to results
        protocol.on(MessageType.TASK_RESULT, handler=my_result_handler)
    """

    def __init__(self):
        self._handlers: dict[MessageType, list] = {}
        self._message_log: list[ActorMessage] = []
        self._pending_replies: dict[str, list[ActorMessage]] = {}

    def send(self, message: ActorMessage) -> dict:
        """Send a message to a recipient via the event bus."""
        self._message_log.append(message)

        bus.emit(f"actor.{message.type.value}", {
            "msg_id": message.id,
            "sender": message.sender,
            "recipient": message.recipient,
            "correlation_id": message.correlation_id,
            "payload_keys": list(message.payload.keys()),
        })

        # Deliver to handlers
        handlers = self._handlers.get(message.type, [])
        for handler in handlers:
            try:
                handler(message)
            except Exception as e:
                bus.emit("actor.handler_error", {
                    "msg_id": message.id,
                    "error": str(e)[:100],
                })

        # Track for reply correlation
        if message.correlation_id not in self._pending_replies:
            self._pending_replies[message.correlation_id] = []
        self._pending_replies[message.correlation_id].append(message)

        message.delivered = True
        return {"status": "sent", "msg_id": message.id}

    def reply(self, original: ActorMessage, msg_type: MessageType, payload: dict) -> dict:
        """Reply to a message, preserving correlation."""
        response = ActorMessage(
            msg_type=msg_type,
            sender=original.recipient,
            recipient=original.sender,
            payload=payload,
            reply_to=original.id,
            correlation_id=original.correlation_id,
        )
        return self.send(response)

    def on(self, msg_type: MessageType, handler):
        """Register a handler for a message type."""
        self._handlers.setdefault(msg_type, []).append(handler)

    def off(self, msg_type: MessageType, handler):
        """Remove a handler for a message type."""
        handlers = self._handlers.get(msg_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def get_conversation(self, correlation_id: str) -> list[dict]:
        """Get all messages in a conversation thread."""
        messages = self._pending_replies.get(correlation_id, [])
        return [m.to_dict() for m in messages]

    def message_log(self, limit: int = 100, msg_type: MessageType = None) -> list[dict]:
        """Return recent messages, optionally filtered by type."""
        messages = self._message_log
        if msg_type:
            messages = [m for m in messages if m.type == msg_type]
        return [m.to_dict() for m in messages[-limit:]]

    def stats(self) -> dict:
        type_counts = {}
        for msg in self._message_log:
            key = msg.type.value
            type_counts[key] = type_counts.get(key, 0) + 1

        return {
            "total_messages": len(self._message_log),
            "conversations": len(self._pending_replies),
            "handlers_registered": sum(len(h) for h in self._handlers.values()),
            "type_counts": type_counts,
        }


# Global singleton
protocol = ActorProtocol()
