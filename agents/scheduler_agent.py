"""
SchedulerAgent — central coordinator.
Implements a backtracking constraint-satisfaction scheduling loop.
"""
import json
import time
from mesa import Agent
from utils.message_protocol import Message, MessageType, MessageBus


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SLOTS = ["08:00", "10:00", "12:00", "14:00", "16:00"]


class SchedulerAgent(Agent):
    def __init__(self, unique_id: int, model, bus: MessageBus,
                 teacher_agents, group_agents, room_agents, constraint_agent,
                 courses: list[dict]):
        super().__init__(unique_id, model)
        self.agent_id = "scheduler"
        self.bus = bus
        self.bus.register(self.agent_id)

        self.teacher_agents = {a.teacher_id: a for a in teacher_agents}
        self.group_agents = {a.group_id: a for a in group_agents}
        self.room_agents = {a.room_id: a for a in room_agents}
        self.constraint_agent = constraint_agent
        self.courses = courses

        self.schedule: list[dict] = []
        self.conflicts: list[dict] = []
        self.unscheduled: list[dict] = []
        self.status: str = "idle"
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_action: str = "initialized"
        self.negotiation_rounds: int = 0
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    # ------------------------------------------------------------------
    # Main scheduling entry point
    # ------------------------------------------------------------------
    def run_scheduling(self):
        self.status = "scheduling"
        self.start_time = time.time()
        self.schedule.clear()
        self.conflicts.clear()
        self.unscheduled.clear()

        # Reset all agent states
        for ta in self.teacher_agents.values():
            ta.assigned_slots.clear()
            ta.hours_assigned = 0
            ta.status = "idle"
        for ga in self.group_agents.values():
            ga.assigned_slots.clear()
            ga.assigned_courses.clear()
            ga.status = "idle"
        for ra in self.room_agents.values():
            ra.bookings.clear()
            ra.status = "idle"
        self.constraint_agent.group_day_slots.clear()
        self.constraint_agent.teacher_day_slots.clear()
        self.constraint_agent.violations.clear()
        # Reset constraint agent counters so the UI shows real activity
        self.constraint_agent.messages_sent = 0
        self.constraint_agent.messages_received = 0

        # Sort courses: larger groups first (harder to place)
        sorted_courses = sorted(
            self.courses,
            key=lambda c: self.group_agents[c["group_id"]].group_size,
            reverse=True,
        )

        for course in sorted_courses:
            placed = self._place_course(course, backtrack_limit=50)
            if not placed:
                self.unscheduled.append(course)
                self.last_action = f"failed to schedule course {course['course_id']}"

        self.end_time = time.time()
        self.status = "done"
        self.last_action = (
            f"scheduled {len(self.schedule)}/{len(self.courses)} courses "
            f"in {self.end_time - self.start_time:.2f}s"
        )
        return self.schedule

    # ------------------------------------------------------------------
    # Place a single course using backtracking
    # ------------------------------------------------------------------
    def _place_course(self, course: dict, backtrack_limit: int = 50) -> bool:
        teacher = self.teacher_agents[course["teacher_id"]]
        group = self.group_agents[course["group_id"]]
        required_type = course["required_room_type"]
        group_size = group.group_size
        duration = course["duration_hours"]
        course_id = course["course_id"]

        candidates = self._generate_candidates(teacher, group, required_type, group_size)

        # Base info shared by every conflict entry for this course
        _base = {
            "course_id":       course_id,
            "course_name":     course["course_name"],
            "teacher_id":      teacher.teacher_id,
            "teacher_name":    teacher.name,
            "group_id":        group.group_id,
            "group_name":      f"{group.program} Y{group.year}",
            "group_size":      group_size,
            "required_type":   required_type,
            "duration_hours":  duration,
            "total_candidates": len(candidates),
        }

        if not candidates:
            self.conflicts.append({
                **_base,
                "day": None, "time_slot": None,
                "room_id": None, "room_capacity": None,
                "attempt": 0,
                "reason": "no_valid_candidate_found",
                "resolved": False,
                "resolved_day": None, "resolved_slot": None, "resolved_room": None,
            })
            return False

        local_rejections: list[dict] = []

        attempts = 0
        for day, slot, room in candidates:
            if attempts >= backtrack_limit:
                break
            attempts += 1

            self.constraint_agent.messages_received += 1
            valid, reason = self.constraint_agent.validate(
                group.group_id, teacher.teacher_id, day, slot
            )
            self.constraint_agent.messages_sent += 1
            self.negotiation_rounds += 1

            if not valid:
                local_rejections.append({
                    **_base,
                    "day":           day,
                    "time_slot":     slot,
                    "room_id":       room.room_id,
                    "room_capacity": room.capacity,
                    "attempt":       attempts,
                    "reason":        reason,
                    "resolved":      False,
                    "resolved_day":  None,
                    "resolved_slot": None,
                    "resolved_room": None,
                })
                continue

            # All checks passed — commit
            teacher.assign(day, slot, duration)
            group.assign(day, slot, course_id)
            room.book(day, slot)
            self.constraint_agent.record(group.group_id, teacher.teacher_id, day, slot)

            # Mark every rejection for this course as resolved
            for r in local_rejections:
                r["resolved"]      = True
                r["resolved_day"]  = day
                r["resolved_slot"] = slot
                r["resolved_room"] = room.room_id
            self.conflicts.extend(local_rejections)

            self.schedule.append({
                "course_id": course_id,
                "course_name": course["course_name"],
                "teacher_id": teacher.teacher_id,
                "teacher_name": teacher.name,
                "group_id": group.group_id,
                "group_name": f"{group.program} Y{group.year}",
                "room_id": room.room_id,
                "day": day,
                "time_slot": slot,
                "duration": duration,
                "room_type": required_type,
                "status": "confirmed",
            })

            self._send_confirm(teacher.agent_id, day, slot, course_id, duration)
            self._send_confirm(group.agent_id, day, slot, course_id, duration)
            self._send_confirm(room.agent_id, day, slot, course_id, duration)
            return True

        # Exhausted all candidates without success — all rejections stay unresolved
        self.conflicts.extend(local_rejections)
        return False

    def _generate_candidates(self, teacher, group, required_type, group_size):
        """Generate (day, slot, room) triples ordered by preference score."""
        candidates = []
        for day in DAYS:
            for slot in SLOTS:
                if not teacher.is_available(day, slot):
                    continue
                if not group.is_available(day, slot):
                    continue
                for room in self.room_agents.values():
                    if not room.is_available(day, slot):
                        continue
                    if not room.can_fit(group_size):
                        continue
                    if not room.matches_type(required_type):
                        continue
                    score = teacher.preference_score(day, slot)
                    candidates.append((day, slot, room, score))

        # Sort: preferred slots first, then tightest-fit room
        candidates.sort(key=lambda x: (-x[3], x[2].capacity))
        return [(d, s, r) for d, s, r, _ in candidates]

    def _send_confirm(self, agent_id: str, day: str, time_slot: str,
                      course_id: int, duration: int):
        msg = Message(
            msg_type=MessageType.CONFIRM,
            sender_id=self.agent_id,
            receiver_id=agent_id,
            content={"day": day, "time_slot": time_slot,
                     "course_id": course_id, "duration": duration},
        )
        self.bus.send(msg)
        self.messages_sent += 1

    def step(self):
        messages = self.bus.receive(self.agent_id)
        self.messages_received += len(messages)

