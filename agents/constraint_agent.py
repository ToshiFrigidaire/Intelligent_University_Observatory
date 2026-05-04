"""
ConstraintAgent — validates proposed sessions against institutional rules.
Rules:
  - No group may have more than 4 hours of classes per day.
  - Mandatory lunch break: no sessions at 12:00 for more than 1 consecutive slot.
  - No teacher may teach more than 3 consecutive slots per day.
"""
from mesa import Agent
from utils.message_protocol import Message, MessageType, MessageBus


MAX_HOURS_PER_DAY_GROUP = 6   # max 6h (3 x 2h slots) per group per day
MAX_CONSECUTIVE_TEACHER = 3   # max 3 consecutive 2h slots per teacher per day


class ConstraintAgent(Agent):
    def __init__(self, unique_id: int, model, bus: MessageBus):
        super().__init__(unique_id, model)
        self.agent_id = "constraint_agent"
        self.bus = bus
        self.bus.register(self.agent_id)

        # group_id -> {day -> [time_slots]}
        self.group_day_slots: dict[int, dict[str, list]] = {}
        # teacher_id -> {day -> [time_slots]}
        self.teacher_day_slots: dict[int, dict[str, list]] = {}

        self.status: str = "idle"
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_action: str = "initialized"
        self.violations: list[dict] = []

    def validate(self, group_id: int, teacher_id: int, day: str, time_slot: str) -> tuple[bool, str]:
        """Returns (valid, reason)."""
        # Check group daily hours (each slot = 2h, max 3 slots = 6h)
        group_slots = self.group_day_slots.get(group_id, {}).get(day, [])
        if len(group_slots) >= MAX_HOURS_PER_DAY_GROUP // 2:
            return False, f"group_{group_id}_exceeds_{MAX_HOURS_PER_DAY_GROUP}h_on_{day}"

        # Check teacher consecutive slots
        teacher_slots = sorted(self.teacher_day_slots.get(teacher_id, {}).get(day, []))
        all_slots = ["08:00", "10:00", "12:00", "14:00", "16:00"]
        if time_slot in all_slots:
            idx = all_slots.index(time_slot)
            consecutive = 1
            for offset in [-1, -2]:
                check = idx + offset
                if 0 <= check < len(all_slots) and all_slots[check] in teacher_slots:
                    consecutive += 1
                else:
                    break
            if consecutive >= MAX_CONSECUTIVE_TEACHER:
                return False, f"teacher_{teacher_id}_too_many_consecutive_on_{day}"

        return True, "ok"

    def record(self, group_id: int, teacher_id: int, day: str, time_slot: str):
        self.group_day_slots.setdefault(group_id, {}).setdefault(day, []).append(time_slot)
        self.teacher_day_slots.setdefault(teacher_id, {}).setdefault(day, []).append(time_slot)

    def unrecord(self, group_id: int, teacher_id: int, day: str, time_slot: str):
        g = self.group_day_slots.get(group_id, {}).get(day, [])
        if time_slot in g:
            g.remove(time_slot)
        t = self.teacher_day_slots.get(teacher_id, {}).get(day, [])
        if time_slot in t:
            t.remove(time_slot)

    def step(self):
        messages = self.bus.receive(self.agent_id)
        for msg in messages:
            self.messages_received += 1
            self._handle_message(msg)

    def _handle_message(self, msg: Message):
        if msg.msg_type == MessageType.REQUEST:
            self.status = "negotiating"
            group_id = msg.content.get("group_id")
            teacher_id = msg.content.get("teacher_id")
            day = msg.content.get("day")
            time_slot = msg.content.get("time_slot")
            course_id = msg.content.get("course_id")

            valid, reason = self.validate(group_id, teacher_id, day, time_slot)
            if valid:
                reply = Message(
                    msg_type=MessageType.ACCEPT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={"course_id": course_id, "day": day, "time_slot": time_slot},
                )
            else:
                self.violations.append({
                    "course_id": course_id, "day": day,
                    "time_slot": time_slot, "reason": reason,
                })
                reply = Message(
                    msg_type=MessageType.REJECT,
                    sender_id=self.agent_id,
                    receiver_id=msg.sender_id,
                    content={"course_id": course_id, "reason": reason},
                )
            self.bus.send(reply)
            self.messages_sent += 1
            self.status = "idle"
            self.last_action = f"validated course {course_id}: {'ok' if valid else reason}"
