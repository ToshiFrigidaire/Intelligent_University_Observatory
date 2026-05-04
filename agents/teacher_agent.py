"""
TeacherAgent — represents one teacher.
Manages availability, preferred slots, and weekly load tracking.
"""
import json
from mesa import Agent
from utils.message_protocol import Message, MessageType, MessageBus


class TeacherAgent(Agent):
    def __init__(self, unique_id: int, model, teacher_data: dict, bus: MessageBus):
        super().__init__(unique_id, model)
        self.agent_id = f"teacher_{teacher_data['teacher_id']}"
        self.teacher_id = teacher_data["teacher_id"]
        self.name = teacher_data["name"]
        self.available_days: list[str] = json.loads(teacher_data["available_days"])
        self.preferred_slots: list[str] = json.loads(teacher_data["preferred_slots"])
        self.max_hours_per_week: int = teacher_data["max_hours_per_week"]
        self.bus = bus
        self.bus.register(self.agent_id)

        # Runtime state
        self.assigned_slots: list[tuple] = []   # (day, time_slot)
        self.hours_assigned: int = 0
        self.status: str = "idle"
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_action: str = "initialized"

    def is_available(self, day: str, time_slot: str) -> bool:
        if day not in self.available_days:
            return False
        if self.hours_assigned >= self.max_hours_per_week:
            return False
        if (day, time_slot) in self.assigned_slots:
            return False
        return True

    def preference_score(self, day: str, time_slot: str) -> float:
        """Returns 1.0 for preferred slot, 0.5 otherwise."""
        score = 0.0
        if day in self.available_days:
            score += 0.5
        if time_slot in self.preferred_slots:
            score += 0.5
        return score

    def assign(self, day: str, time_slot: str, duration: int = 2):
        self.assigned_slots.append((day, time_slot))
        self.hours_assigned += duration
        self.last_action = f"assigned {day} {time_slot}"

    def unassign(self, day: str, time_slot: str, duration: int = 2):
        if (day, time_slot) in self.assigned_slots:
            self.assigned_slots.remove((day, time_slot))
            self.hours_assigned = max(0, self.hours_assigned - duration)
            self.last_action = f"unassigned {day} {time_slot}"

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
            duration = msg.content.get("duration", 2)

            if self.is_available(day, time_slot):
                score = self.preference_score(day, time_slot)
                reply = Message(
                    msg_type=MessageType.PROPOSAL,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={
                        "course_id": course_id,
                        "day": day,
                        "time_slot": time_slot,
                        "preference_score": score,
                        "teacher_id": self.teacher_id,
                    },
                )
            else:
                # Propose alternatives
                alternatives = [
                    (d, s)
                    for d in self.available_days
                    for s in ["08:00", "10:00", "12:00", "14:00", "16:00"]
                    if self.is_available(d, s)
                ][:3]
                reply = Message(
                    msg_type=MessageType.REJECT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={
                        "course_id": course_id,
                        "reason": "unavailable",
                        "alternatives": [{"day": d, "time_slot": s} for d, s in alternatives],
                    },
                )
            self.bus.send(reply)
            self.messages_sent += 1

        elif msg.msg_type == MessageType.CONFIRM:
            day = msg.content.get("day")
            time_slot = msg.content.get("time_slot")
            duration = msg.content.get("duration", 2)
            self.assign(day, time_slot, duration)
            self.status = "confirmed"

        elif msg.msg_type == MessageType.REJECT:
            self.status = "idle"
