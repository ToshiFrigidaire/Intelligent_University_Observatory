"""
GroupAgent — represents one student group.
Ensures no two sessions overlap for the same group.
"""
from mesa import Agent
from utils.message_protocol import Message, MessageType, MessageBus


class GroupAgent(Agent):
    def __init__(self, unique_id: int, model, group_data: dict, bus: MessageBus):
        super().__init__(unique_id, model)
        self.agent_id = f"group_{group_data['group_id']}"
        self.group_id = group_data["group_id"]
        self.program = group_data["program"]
        self.year = group_data["year"]
        self.group_size = group_data["group_size"]
        self.bus = bus
        self.bus.register(self.agent_id)

        self.assigned_slots: list[tuple] = []   # (day, time_slot)
        self.assigned_courses: list[int] = []
        self.status: str = "idle"
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_action: str = "initialized"

    def is_available(self, day: str, time_slot: str) -> bool:
        return (day, time_slot) not in self.assigned_slots

    def assign(self, day: str, time_slot: str, course_id: int):
        self.assigned_slots.append((day, time_slot))
        self.assigned_courses.append(course_id)
        self.last_action = f"assigned course {course_id} at {day} {time_slot}"

    def unassign(self, day: str, time_slot: str, course_id: int):
        if (day, time_slot) in self.assigned_slots:
            self.assigned_slots.remove((day, time_slot))
        if course_id in self.assigned_courses:
            self.assigned_courses.remove(course_id)
        self.last_action = f"unassigned course {course_id}"

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

            if self.is_available(day, time_slot):
                reply = Message(
                    msg_type=MessageType.ACCEPT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={"course_id": course_id, "day": day, "time_slot": time_slot},
                )
            else:
                reply = Message(
                    msg_type=MessageType.CONFLICT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={
                        "course_id": course_id,
                        "day": day,
                        "time_slot": time_slot,
                        "reason": "group_overlap",
                    },
                )
            self.bus.send(reply)
            self.messages_sent += 1
            self.status = "idle"

        elif msg.msg_type == MessageType.CONFIRM:
            day = msg.content.get("day")
            time_slot = msg.content.get("time_slot")
            course_id = msg.content.get("course_id")
            self.assign(day, time_slot, course_id)
            self.status = "confirmed"
