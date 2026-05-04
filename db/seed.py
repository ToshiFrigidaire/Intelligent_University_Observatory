"""
Seed the SQLite database with randomised university data.
Each call produces a different scenario: teacher availability, group sizes,
course assignments, and classroom layout are all varied.
"""
import json
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.models import init_db, get_session, Teacher, StudentGroup, Classroom, Course, Schedule

DAYS  = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SLOTS = ["08:00", "10:00", "12:00", "14:00", "16:00"]

# ── Name pools ────────────────────────────────────────────────────────────────
_FIRST = [
    "Alice", "Bob", "Clara", "David", "Eva", "Frank", "Grace", "Henry",
    "Irene", "James", "Karen", "Leo", "Maria", "Nour", "Omar", "Priya",
    "Quinn", "Rafael", "Sara", "Tariq",
]
_LAST = [
    "Martin", "Chen", "Diaz", "Kim", "Rossi", "Müller", "Okafor", "Patel",
    "Nakamura", "Osei", "Singh", "Dubois", "Santos", "Yilmaz", "Petrov",
    "Andersen", "Nguyen", "Kowalski", "Ferreira", "Hassan",
]
_TITLES = ["Dr.", "Prof.", "Assoc. Prof.", "Dr."]

_PROGRAMS = [
    "Computer Science", "Electrical Engineering", "Mathematics",
    "Data Science", "Mechanical Engineering", "Physics",
    "Information Systems", "Cybersecurity",
]

_COURSE_TEMPLATES = [
    # (name_template, preferred_type)
    ("Introduction to {subject}",          "lecture"),
    ("Advanced {subject}",                 "lecture"),
    ("{subject} Fundamentals",             "lecture"),
    ("{subject} Lab",                      "lab"),
    ("{subject} Workshop",                 "lab"),
    ("{subject} Seminar",                  "tutorial"),
    ("Applied {subject}",                  "lecture"),
    ("{subject} Project",                  "tutorial"),
]

_SUBJECTS = [
    "Programming", "Data Structures", "Algorithms", "Databases",
    "Operating Systems", "Networks", "Machine Learning", "AI",
    "Web Development", "Cloud Computing", "Cybersecurity", "Signal Processing",
    "Circuit Theory", "Electronics", "Calculus", "Linear Algebra",
    "Statistics", "Discrete Mathematics", "Numerical Methods", "Data Analysis",
    "Deep Learning", "Embedded Systems", "Software Engineering", "Big Data",
    "Computer Vision", "Natural Language Processing", "Robotics", "Cryptography",
]


def _random_teacher_name(used: set) -> str:
    for _ in range(100):
        name = f"{random.choice(_TITLES)} {random.choice(_FIRST)} {random.choice(_LAST)}"
        if name not in used:
            used.add(name)
            return name
    return f"Dr. Teacher{len(used)}"


def _random_availability() -> tuple[list, list]:
    """Return (available_days, preferred_slots) with meaningful variation."""
    n_days = random.randint(3, 5)
    avail  = sorted(random.sample(DAYS, n_days), key=DAYS.index)
    n_slots = random.randint(1, 3)
    prefs  = sorted(random.sample(SLOTS, n_slots), key=SLOTS.index)
    return avail, prefs


def _build_teachers(n: int) -> list[dict]:
    used_names: set = set()
    teachers = []
    for _ in range(n):
        avail, prefs = _random_availability()
        teachers.append({
            "name":           _random_teacher_name(used_names),
            "available_days": avail,
            "preferred_slots": prefs,
            "max_hours":      random.choice([12, 14, 16, 18, 20]),
        })
    return teachers


def _build_groups(n: int) -> list[dict]:
    groups = []
    programs = random.sample(_PROGRAMS, min(n, len(_PROGRAMS)))
    # ensure we have enough by cycling
    while len(programs) < n:
        programs.append(random.choice(_PROGRAMS))
    random.shuffle(programs)
    year_counter: dict = {}
    for prog in programs[:n]:
        year_counter[prog] = year_counter.get(prog, 0) + 1
        groups.append({
            "program": prog,
            "year":    year_counter[prog],
            "size":    random.randint(25, 140),
        })
    return groups


def _build_classrooms(n: int) -> list[dict]:
    rooms = []
    # guarantee a spread of capacities
    caps = [150, 120, 100, 80, 80, 60, 60, 50, 40, 30]
    for i in range(n):
        cap = caps[i] if i < len(caps) else random.randint(20, 160)
        # randomise equipment
        base = ["projector", "whiteboard"]
        if random.random() < 0.45:
            base += ["computers", "lab"]
        if random.random() < 0.2:
            base += ["electronics"]
        rooms.append({"capacity": cap, "equipment": list(set(base))})
    return rooms


def _build_courses(n: int, n_teachers: int, n_groups: int) -> list[tuple]:
    """Return list of (name, teacher_idx, group_idx, room_type, duration)."""
    used_names: set = set()
    courses = []
    subjects = list(_SUBJECTS)
    random.shuffle(subjects)

    for i in range(n):
        subj    = subjects[i % len(subjects)]
        tmpl, preferred_type = random.choice(_COURSE_TEMPLATES)
        name    = tmpl.format(subject=subj)
        # avoid exact duplicates
        if name in used_names:
            name = f"{name} {random.randint(2, 4)}"
        used_names.add(name)

        t_idx   = random.randint(0, n_teachers - 1)
        g_idx   = random.randint(0, n_groups - 1)
        rtype   = preferred_type
        dur     = random.choice([1, 2, 2, 2])  # mostly 2h
        courses.append((name, t_idx, g_idx, rtype, dur))
    return courses


def seed(
    n_teachers: int  = None,
    n_groups: int    = None,
    n_classrooms: int = None,
    n_courses: int   = None,
):
    """
    Seed the DB with a randomised scenario.
    Pass explicit counts to override the random defaults.
    """
    rng_teachers   = n_teachers   or random.randint(8, 14)
    rng_groups     = n_groups     or random.randint(6, 10)
    rng_classrooms = n_classrooms or random.randint(12, 18)
    rng_courses    = n_courses    or random.randint(24, 36)

    teachers   = _build_teachers(rng_teachers)
    groups     = _build_groups(rng_groups)
    classrooms = _build_classrooms(rng_classrooms)
    courses    = _build_courses(rng_courses, rng_teachers, rng_groups)

    init_db()
    session = get_session()

    session.query(Schedule).delete()
    session.query(Course).delete()
    session.query(Teacher).delete()
    session.query(StudentGroup).delete()
    session.query(Classroom).delete()
    session.commit()

    for i, t in enumerate(teachers, start=1):
        session.add(Teacher(
            teacher_id=i,
            name=t["name"],
            available_days=json.dumps(t["available_days"]),
            preferred_slots=json.dumps(t["preferred_slots"]),
            max_hours_per_week=t["max_hours"],
        ))

    for i, g in enumerate(groups, start=1):
        session.add(StudentGroup(
            group_id=i, program=g["program"], year=g["year"], group_size=g["size"]
        ))

    for i, r in enumerate(classrooms, start=1):
        session.add(Classroom(
            room_id=i, capacity=r["capacity"], equipment=json.dumps(r["equipment"])
        ))

    session.commit()

    for i, (name, t_idx, g_idx, rtype, dur) in enumerate(courses, start=1):
        session.add(Course(
            course_id=i,
            course_name=name,
            teacher_id=t_idx + 1,
            group_id=g_idx + 1,
            required_room_type=rtype,
            duration_hours=dur,
        ))

    session.commit()
    session.close()
    print(
        f"Seeded (randomised): {rng_teachers} teachers, {rng_groups} groups, "
        f"{rng_classrooms} classrooms, {rng_courses} courses."
    )


if __name__ == "__main__":
    seed()
