"""
SQLAlchemy ORM models for the university timetabling system.
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os

Base = declarative_base()

DB_PATH = os.path.join(os.path.dirname(__file__), "university.db")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Teacher(Base):
    __tablename__ = "teachers"
    teacher_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    available_days = Column(Text, nullable=False)   # JSON list e.g. '["Mon","Tue"]'
    preferred_slots = Column(Text, nullable=False)  # JSON list e.g. '["08:00","10:00"]'
    max_hours_per_week = Column(Integer, default=20)
    courses = relationship("Course", back_populates="teacher")


class StudentGroup(Base):
    __tablename__ = "student_groups"
    group_id = Column(Integer, primary_key=True)
    program = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    group_size = Column(Integer, nullable=False)
    courses = relationship("Course", back_populates="group")


class Classroom(Base):
    __tablename__ = "classrooms"
    room_id = Column(Integer, primary_key=True)
    capacity = Column(Integer, nullable=False)
    equipment = Column(Text, nullable=False)  # JSON list e.g. '["projector","whiteboard"]'
    sessions = relationship("Schedule", back_populates="room")


class Course(Base):
    __tablename__ = "courses"
    course_id = Column(Integer, primary_key=True)
    course_name = Column(String(150), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.teacher_id"), nullable=False)
    group_id = Column(Integer, ForeignKey("student_groups.group_id"), nullable=False)
    required_room_type = Column(String(50), default="lecture")  # lecture | lab | tutorial
    duration_hours = Column(Integer, default=2)
    teacher = relationship("Teacher", back_populates="courses")
    group = relationship("StudentGroup", back_populates="courses")
    sessions = relationship("Schedule", back_populates="course")


class Schedule(Base):
    __tablename__ = "schedule"
    session_id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("courses.course_id"), nullable=False)
    room_id = Column(Integer, ForeignKey("classrooms.room_id"), nullable=False)
    day = Column(String(10), nullable=False)
    time_slot = Column(String(10), nullable=False)
    status = Column(String(20), default="confirmed")  # confirmed | conflict | pending
    course = relationship("Course", back_populates="sessions")
    room = relationship("Classroom", back_populates="sessions")


def init_db():
    Base.metadata.create_all(ENGINE)


def get_session():
    Session = sessionmaker(bind=ENGINE)
    return Session()
