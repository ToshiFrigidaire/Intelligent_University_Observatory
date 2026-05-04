"""
Unit tests for all core agents.
Run with: pytest tests/test_agents.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from unittest.mock import MagicMock

from utils.message_protocol import MessageBus, Message, MessageType
from agents.teacher_agent import TeacherAgent
from agents.group_agent import GroupAgent
from agents.room_agent import RoomAgent
from agents.constraint_agent import ConstraintAgent


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def teacher(bus):
    data = {
        "teacher_id": 1,
        "name": "Dr. Test",
        "available_days": json.dumps(["Mon", "Tue", "Wed"]),
        "preferred_slots": json.dumps(["08:00", "10:00"]),
        "max_hours_per_week": 10,
    }
    model = MagicMock()
    return TeacherAgent(1, model, data, bus)


@pytest.fixture
def group(bus):
    data = {"group_id": 1, "program": "CS", "year": 1, "group_size": 50}
    model = MagicMock()
    return GroupAgent(2, model, data, bus)


@pytest.fixture
def room(bus):
    data = {"room_id": 1, "capacity": 60, "equipment": json.dumps(["projector", "whiteboard"])}
    model = MagicMock()
    return RoomAgent(3, model, data, bus)


@pytest.fixture
def lab_room(bus):
    data = {"room_id": 2, "capacity": 40, "equipment": json.dumps(["lab", "computers"])}
    model = MagicMock()
    return RoomAgent(4, model, data, bus)


@pytest.fixture
def constraint(bus):
    model = MagicMock()
    return ConstraintAgent(5, model, bus)


# ── TeacherAgent tests ─────────────────────────────────────────────────────────

class TestTeacherAgent:
    def test_available_on_valid_day_slot(self, teacher):
        assert teacher.is_available("Mon", "08:00") is True

    def test_unavailable_on_wrong_day(self, teacher):
        assert teacher.is_available("Sat", "08:00") is False

    def test_unavailable_after_max_hours(self, teacher):
        teacher.hours_assigned = 10
        assert teacher.is_available("Mon", "08:00") is False

    def test_unavailable_after_assignment(self, teacher):
        teacher.assign("Mon", "08:00")
        assert teacher.is_available("Mon", "08:00") is False

    def test_preference_score_preferred(self, teacher):
        score = teacher.preference_score("Mon", "08:00")
        assert score == 1.0

    def test_preference_score_partial(self, teacher):
        score = teacher.preference_score("Mon", "14:00")
        assert score == 0.5

    def test_preference_score_none(self, teacher):
        score = teacher.preference_score("Sat", "14:00")
        assert score == 0.0

    def test_assign_increments_hours(self, teacher):
        teacher.assign("Mon", "08:00", duration=2)
        assert teacher.hours_assigned == 2
        assert ("Mon", "08:00") in teacher.assigned_slots

    def test_unassign_decrements_hours(self, teacher):
        teacher.assign("Mon", "08:00", duration=2)
        teacher.unassign("Mon", "08:00", duration=2)
        assert teacher.hours_assigned == 0
        assert ("Mon", "08:00") not in teacher.assigned_slots

    def test_handles_request_message_available(self, teacher, bus):
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=teacher.agent_id,
            content={"day": "Mon", "time_slot": "08:00", "course_id": 1, "duration": 2},
        )
        bus.send(msg)
        teacher.step()
        replies = bus.receive("scheduler")
        assert len(replies) == 1
        assert replies[0].msg_type == MessageType.PROPOSAL

    def test_handles_request_message_unavailable(self, teacher, bus):
        teacher.assign("Mon", "08:00")
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=teacher.agent_id,
            content={"day": "Mon", "time_slot": "08:00", "course_id": 1, "duration": 2},
        )
        bus.send(msg)
        teacher.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.REJECT

    def test_confirm_message_assigns_slot(self, teacher, bus):
        msg = Message(
            msg_type=MessageType.CONFIRM,
            sender_id="scheduler",
            receiver_id=teacher.agent_id,
            content={"day": "Tue", "time_slot": "10:00", "course_id": 2, "duration": 2},
        )
        bus.send(msg)
        teacher.step()
        assert ("Tue", "10:00") in teacher.assigned_slots


# ── GroupAgent tests ───────────────────────────────────────────────────────────

class TestGroupAgent:
    def test_available_initially(self, group):
        assert group.is_available("Mon", "08:00") is True

    def test_unavailable_after_assign(self, group):
        group.assign("Mon", "08:00", course_id=1)
        assert group.is_available("Mon", "08:00") is False

    def test_available_different_slot(self, group):
        group.assign("Mon", "08:00", course_id=1)
        assert group.is_available("Mon", "10:00") is True

    def test_handles_request_accept(self, group, bus):
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=group.agent_id,
            content={"day": "Mon", "time_slot": "08:00", "course_id": 1},
        )
        bus.send(msg)
        group.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.ACCEPT

    def test_handles_request_conflict(self, group, bus):
        group.assign("Mon", "08:00", course_id=1)
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=group.agent_id,
            content={"day": "Mon", "time_slot": "08:00", "course_id": 2},
        )
        bus.send(msg)
        group.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.CONFLICT

    def test_unassign(self, group):
        group.assign("Mon", "08:00", course_id=1)
        group.unassign("Mon", "08:00", course_id=1)
        assert group.is_available("Mon", "08:00") is True


# ── RoomAgent tests ────────────────────────────────────────────────────────────

class TestRoomAgent:
    def test_available_initially(self, room):
        assert room.is_available("Mon", "08:00") is True

    def test_unavailable_after_booking(self, room):
        room.book("Mon", "08:00")
        assert room.is_available("Mon", "08:00") is False

    def test_capacity_check_pass(self, room):
        assert room.can_fit(50) is True

    def test_capacity_check_fail(self, room):
        assert room.can_fit(100) is False

    def test_matches_lecture_type(self, room):
        assert room.matches_type("lecture") is True

    def test_matches_lab_type(self, lab_room):
        assert lab_room.matches_type("lab") is True

    def test_non_lab_room_rejects_lab(self, room):
        # room has projector/whiteboard but no lab equipment
        assert room.matches_type("lab") is False

    def test_handles_request_accept(self, room, bus):
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=room.agent_id,
            content={
                "day": "Mon", "time_slot": "08:00", "course_id": 1,
                "group_size": 50, "required_room_type": "lecture",
            },
        )
        bus.send(msg)
        room.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.ACCEPT

    def test_handles_request_reject_capacity(self, room, bus):
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=room.agent_id,
            content={
                "day": "Mon", "time_slot": "08:00", "course_id": 1,
                "group_size": 200, "required_room_type": "lecture",
            },
        )
        bus.send(msg)
        room.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.REJECT
        assert "capacity_exceeded" in replies[0].content["reasons"]

    def test_unbook(self, room):
        room.book("Mon", "08:00")
        room.unbook("Mon", "08:00")
        assert room.is_available("Mon", "08:00") is True


# ── ConstraintAgent tests ──────────────────────────────────────────────────────

class TestConstraintAgent:
    def test_valid_initially(self, constraint):
        valid, reason = constraint.validate(1, 1, "Mon", "08:00")
        assert valid is True

    def test_rejects_group_exceeding_daily_hours(self, constraint):
        # Record 3 slots (= 6 hours) for group 1 on Mon — 4th should be rejected
        constraint.record(1, 1, "Mon", "08:00")
        constraint.record(1, 2, "Mon", "10:00")   # different teacher to avoid consecutive check
        constraint.record(1, 3, "Mon", "12:00")
        valid, reason = constraint.validate(1, 4, "Mon", "14:00")
        assert valid is False
        assert "exceeds" in reason

    def test_rejects_teacher_too_many_consecutive(self, constraint):
        constraint.record(1, 1, "Mon", "08:00")
        constraint.record(1, 1, "Mon", "10:00")
        # Third consecutive slot should be rejected
        valid, reason = constraint.validate(1, 1, "Mon", "12:00")
        # Either group or teacher constraint fires
        assert valid is False

    def test_unrecord_restores_availability(self, constraint):
        constraint.record(1, 1, "Mon", "08:00")
        constraint.record(1, 1, "Mon", "10:00")
        constraint.unrecord(1, 1, "Mon", "10:00")
        valid, _ = constraint.validate(1, 1, "Mon", "10:00")
        assert valid is True

    def test_handles_request_accept(self, constraint, bus):
        msg = Message(
            msg_type=MessageType.REQUEST,
            sender_id="scheduler",
            receiver_id=constraint.agent_id,
            content={"group_id": 1, "teacher_id": 1, "day": "Mon",
                     "time_slot": "08:00", "course_id": 1},
        )
        bus.send(msg)
        constraint.step()
        replies = bus.receive("scheduler")
        assert replies[0].msg_type == MessageType.ACCEPT


# ── MessageBus tests ───────────────────────────────────────────────────────────

class TestMessageBus:
    def test_register_and_send_receive(self, bus):
        bus.register("agent_a")
        msg = Message(MessageType.REQUEST, "sender", "agent_a", {})
        bus.send(msg)
        received = bus.receive("agent_a")
        assert len(received) == 1
        assert received[0].msg_type == MessageType.REQUEST

    def test_receive_clears_queue(self, bus):
        bus.register("agent_b")
        msg = Message(MessageType.REQUEST, "sender", "agent_b", {})
        bus.send(msg)
        bus.receive("agent_b")
        assert bus.receive("agent_b") == []

    def test_total_message_count(self, bus):
        bus.register("agent_c")
        for _ in range(5):
            bus.send(Message(MessageType.REQUEST, "s", "agent_c", {}))
        assert bus.get_total_messages() == 5

    def test_log_records_messages(self, bus):
        bus.register("agent_d")
        bus.send(Message(MessageType.CONFIRM, "s", "agent_d", {}))
        log = bus.get_log()
        assert len(log) == 1
        assert log[0]["msg_type"] == "CONFIRM"
