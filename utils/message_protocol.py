"""
Message protocol definitions for inter-agent communication.
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import time


class MessageType(Enum):
    REQUEST = "REQUEST"
    PROPOSAL = "PROPOSAL"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CONFLICT = "CONFLICT"
    CONFIRM = "CONFIRM"
    STATUS = "STATUS"
    QUERY = "QUERY"


@dataclass
class Message:
    msg_type: MessageType
    sender_id: str
    receiver_id: str
    content: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    msg_id: Optional[str] = None

    def __post_init__(self):
        if self.msg_id is None:
            self.msg_id = f"{self.sender_id}-{self.receiver_id}-{int(self.timestamp * 1000)}"

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "content": self.content,
            "timestamp": self.timestamp,
        }


class MessageBus:
    """Simple in-process message bus for agent communication."""

    def __init__(self):
        self._queues: dict[str, list[Message]] = {}
        self._log: list[dict] = []
        self._total_messages = 0

    def register(self, agent_id: str):
        if agent_id not in self._queues:
            self._queues[agent_id] = []

    def send(self, message: Message):
        if message.receiver_id not in self._queues:
            self._queues[message.receiver_id] = []
        self._queues[message.receiver_id].append(message)
        self._log.append(message.to_dict())
        self._total_messages += 1

    def receive(self, agent_id: str) -> list[Message]:
        msgs = self._queues.get(agent_id, [])
        self._queues[agent_id] = []
        return msgs

    def peek(self, agent_id: str) -> list[Message]:
        return list(self._queues.get(agent_id, []))

    def get_log(self) -> list[dict]:
        return list(self._log)

    def get_total_messages(self) -> int:
        return self._total_messages

    def clear_log(self):
        self._log.clear()
