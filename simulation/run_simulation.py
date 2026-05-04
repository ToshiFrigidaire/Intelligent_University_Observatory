"""
Main simulation runner.
Loads data from DB, builds Mesa model, runs scheduling, persists results.
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from mesa import Model
from mesa.time import RandomActivation

from db.models import init_db, get_session, Teacher, StudentGroup, Classroom, Course, Schedule
from db.seed import seed as seed_db
from utils.message_protocol import MessageBus
from agents.teacher_agent import TeacherAgent
from agents.group_agent import GroupAgent
from agents.room_agent import RoomAgent
from agents.constraint_agent import ConstraintAgent
from agents.scheduler_agent import SchedulerAgent


class UniversityModel(Model):
    """Mesa model that hosts all university scheduling agents."""

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.bus = MessageBus()
        self.schedule_mesa = RandomActivation(self)
        self._agent_counter = 0

        self._load_agents()

    def _next_id(self) -> int:
        self._agent_counter += 1
        return self._agent_counter

    def _load_agents(self):
        session = self.session

        # Load data via Pandas for preprocessing
        teachers_df = pd.read_sql("SELECT * FROM teachers", session.bind)
        groups_df = pd.read_sql("SELECT * FROM student_groups", session.bind)
        rooms_df = pd.read_sql("SELECT * FROM classrooms", session.bind)
        courses_df = pd.read_sql("SELECT * FROM courses", session.bind)

        # Build teacher agents
        self.teacher_agents = []
        for _, row in teachers_df.iterrows():
            a = TeacherAgent(self._next_id(), self, row.to_dict(), self.bus)
            self.teacher_agents.append(a)
            self.schedule_mesa.add(a)

        # Build group agents
        self.group_agents = []
        for _, row in groups_df.iterrows():
            a = GroupAgent(self._next_id(), self, row.to_dict(), self.bus)
            self.group_agents.append(a)
            self.schedule_mesa.add(a)

        # Build room agents
        self.room_agents = []
        for _, row in rooms_df.iterrows():
            a = RoomAgent(self._next_id(), self, row.to_dict(), self.bus)
            self.room_agents.append(a)
            self.schedule_mesa.add(a)

        # Constraint agent
        self.constraint_agent = ConstraintAgent(self._next_id(), self, self.bus)
        self.schedule_mesa.add(self.constraint_agent)

        # Courses as plain dicts
        courses = courses_df.to_dict(orient="records")

        # Scheduler agent
        self.scheduler = SchedulerAgent(
            self._next_id(), self, self.bus,
            self.teacher_agents, self.group_agents, self.room_agents,
            self.constraint_agent, courses,
        )
        self.schedule_mesa.add(self.scheduler)

    def run(self) -> dict:
        """Execute the scheduling simulation and return results."""
        result_schedule = self.scheduler.run_scheduling()

        # Let all agents process their CONFIRM messages
        self.schedule_mesa.step()

        return {
            "schedule": result_schedule,
            "conflicts": self.scheduler.conflicts,
            "unscheduled": self.scheduler.unscheduled,
            "stats": {
                "total_courses": len(self.scheduler.courses),
                "scheduled": len(result_schedule),
                "unscheduled": len(self.scheduler.unscheduled),
                "conflicts_detected": len(self.scheduler.conflicts),
                "negotiation_rounds": self.scheduler.negotiation_rounds,
                "total_messages": self.bus.get_total_messages(),
                "duration_seconds": round(self.scheduler.end_time - self.scheduler.start_time, 3),
            },
            "agent_statuses": self._collect_agent_statuses(),
        }

    def _collect_agent_statuses(self) -> list[dict]:
        statuses = []
        for a in self.teacher_agents:
            statuses.append({
                "agent_id": a.agent_id,
                "type": "TeacherAgent",
                "name": a.name,
                "status": a.status,
                "messages_sent": a.messages_sent,
                "messages_received": a.messages_received,
                "last_action": a.last_action,
            })
        for a in self.group_agents:
            statuses.append({
                "agent_id": a.agent_id,
                "type": "GroupAgent",
                "name": f"{a.program} Y{a.year}",
                "status": a.status,
                "messages_sent": a.messages_sent,
                "messages_received": a.messages_received,
                "last_action": a.last_action,
            })
        for a in self.room_agents:
            statuses.append({
                "agent_id": a.agent_id,
                "type": "RoomAgent",
                "name": f"Room {a.room_id} (cap {a.capacity})",
                "status": a.status,
                "messages_sent": a.messages_sent,
                "messages_received": a.messages_received,
                "last_action": a.last_action,
            })
        statuses.append({
            "agent_id": self.constraint_agent.agent_id,
            "type": "ConstraintAgent",
            "name": "Constraint Validator",
            "status": self.constraint_agent.status,
            "messages_sent": self.constraint_agent.messages_sent,
            "messages_received": self.constraint_agent.messages_received,
            "last_action": self.constraint_agent.last_action,
        })
        statuses.append({
            "agent_id": self.scheduler.agent_id,
            "type": "SchedulerAgent",
            "name": "Central Scheduler",
            "status": self.scheduler.status,
            "messages_sent": self.scheduler.messages_sent,
            "messages_received": self.scheduler.messages_received,
            "last_action": self.scheduler.last_action,
        })
        return statuses


def persist_schedule(session, schedule: list[dict]):
    """Write finalized schedule to the DB."""
    session.query(Schedule).delete()
    session.commit()
    for s in schedule:
        obj = Schedule(
            course_id=s["course_id"],
            room_id=s["room_id"],
            day=s["day"],
            time_slot=s["time_slot"],
            status=s["status"],
        )
        session.add(obj)
    session.commit()


def run_simulation(reseed: bool = False) -> dict:
    init_db()
    if reseed:
        seed_db()

    session = get_session()
    model = UniversityModel(session)
    results = model.run()
    persist_schedule(session, results["schedule"])
    session.close()
    return results


if __name__ == "__main__":
    results = run_simulation(reseed=True)
    stats = results["stats"]
    print(f"\n=== Scheduling Complete ===")
    print(f"Scheduled:   {stats['scheduled']}/{stats['total_courses']} courses")
    print(f"Conflicts:   {stats['conflicts_detected']}")
    print(f"Messages:    {stats['total_messages']}")
    print(f"Duration:    {stats['duration_seconds']}s")
