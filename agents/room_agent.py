"""
RoomAgent — manages one classroom.
Handles capacity checks, equipment matching, and booking state.
"""
import json
from mesa import Agent
from utils.message_protocol import Message, MessageType, MessageBus


class RoomAgent(Agent):
    def __init__(self, unique_id: int, model, room_data: dict, bus: MessageBus):
        super().__init__(unique_id, model)
        self.agent_id = f"room_{room_data['room_id']}"
        self.room_id = room_data["room_id"]
        self.capacity: int = room_data["capacity"]
        self.equipment: list[str] = json.loads(room_data["equipment"])
        self.bus = bus
        self.bus.register(self.agent_id)

        self.bookings: list[tuple] = []   # (day, time_slot)
        self.status: str = "idle"
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_action: str = "initialized"

    def is_available(self, day: str, time_slot: str) -> bool:
        return (day, time_slot) not in self.bookings

    def matches_type(self, required_room_type: str) -> bool:
        """Check if room equipment matches the required session type."""
        if required_room_type == "lab":
            return "lab" in self.equipment or "computers" in self.equipment
        # lecture / tutorial — any room with projector or whiteboard
        return True

    def can_fit(self, group_size: int) -> bool:
        return self.capacity >= group_size

    def book(self, day: str, time_slot: str):
        self.bookings.append((day, time_slot))
        self.last_action = f"booked {day} {time_slot}"

    def unbook(self, day: str, time_slot: str):
        if (day, time_slot) in self.bookings:
            self.bookings.remove((day, time_slot))
            self.last_action = f"unbooked {day} {time_slot}"

    def step(self):
        messages = self.bus.receive(self.agent_id)
        for msg in messages:
            self.messages_received += 1
            self._handle_message(msg)

    def _handle_message(self, msg: Message):
        if msg.msg_type == MessageType.REQUEST:
            self.status = "negotiating"
            day = msg.content.get("day")
            time_slot = msg.content.get("time_slot")
            course_id = msg.content.get("course_id")
            group_size = msg.content.get("group_size", 0)
            required_type = msg.content.get("required_room_type", "lecture")

            ok = (
                self.is_available(day, time_slot)
                and self.can_fit(group_size)
                and self.matches_type(required_type)
            )

            if ok:
                reply = Message(
                    msg_type=MessageType.ACCEPT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={
                        "course_id": course_id,
                        "room_id": self.room_id,
                        "day": day,
                        "time_slot": time_slot,
                        "capacity": self.capacity,
                    },
                )
            else:
                reasons = []
                if not self.is_available(day, time_slot):
                    reasons.append("room_booked")
                if not self.can_fit(group_size):
                    reasons.append("capacity_exceeded")
                if not self.matches_type(required_type):
                    reasons.append("equipment_mismatch")
                reply = Message(
                    msg_type=MessageType.REJECT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={"course_id": course_id, "reasons": reasons},
                )
            self.bus.send(reply)
            self.messages_sent += 1
            self.status = "idle"

        elif msg.msg_type == MessageType.CONFIRM:
            day = msg.content.get("day")
            time_slot = msg.content.get("time_slot")
            self.book(day, time_slot)
            self.status = "confirmed"
