"""
Flask routes — REST API + page rendering.
"""
import io
import csv
import json
import threading
from flask import Blueprint, render_template, jsonify, request, Response, abort
from sqlalchemy.exc import IntegrityError

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.models import init_db, get_session, Schedule, Course, Teacher, StudentGroup, Classroom
from simulation.run_simulation import run_simulation

bp = Blueprint("main", __name__)

# Shared simulation state
_sim_lock = threading.Lock()
_sim_running = False
_last_results: dict = {}


# ── Pages ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def dashboard():
    return render_template("dashboard.html")


@bp.route("/timetable")
def timetable():
    return render_template("timetable.html")


@bp.route("/agents")
def agents():
    return render_template("agents.html")


@bp.route("/conflicts")
def conflicts():
    return render_template("conflicts.html")


# ── API ────────────────────────────────────────────────────────────────────────

@bp.route("/api/stats")
def api_stats():
    session = get_session()
    total_courses = session.query(Course).count()
    scheduled = session.query(Schedule).filter_by(status="confirmed").count()
    conflict_count = len(_last_results.get("conflicts", []))
    unscheduled = len(_last_results.get("unscheduled", []))
    session.close()

    stats = _last_results.get("stats", {})
    return jsonify({
        "total_courses": total_courses,
        "scheduled": scheduled,
        "unscheduled": unscheduled,
        "conflict_count": conflict_count,
        "completion_pct": round(scheduled / total_courses * 100, 1) if total_courses else 0,
        "total_messages": stats.get("total_messages", 0),
        "negotiation_rounds": stats.get("negotiation_rounds", 0),
        "duration_seconds": stats.get("duration_seconds", 0),
        "sim_running": _sim_running,
    })


@bp.route("/api/schedule")
def api_schedule():
    session = get_session()
    rows = (
        session.query(Schedule, Course, Teacher, StudentGroup, Classroom)
        .join(Course, Schedule.course_id == Course.course_id)
        .join(Teacher, Course.teacher_id == Teacher.teacher_id)
        .join(StudentGroup, Course.group_id == StudentGroup.group_id)
        .join(Classroom, Schedule.room_id == Classroom.room_id)
        .all()
    )
    data = []
    for sched, course, teacher, group, room in rows:
        data.append({
            "session_id": sched.session_id,
            "course_id": course.course_id,
            "course_name": course.course_name,
            "teacher_name": teacher.name,
            "group_name": f"{group.program} Y{group.year}",
            "room_id": room.room_id,
            "room_capacity": room.capacity,
            "day": sched.day,
            "time_slot": sched.time_slot,
            "room_type": course.required_room_type,
            "status": sched.status,
        })
    session.close()
    return jsonify(data)


@bp.route("/api/agents")
def api_agents():
    statuses = _last_results.get("agent_statuses", [])
    return jsonify(statuses)


@bp.route("/api/conflicts")
def api_conflicts():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    all_conflicts = _last_results.get("conflicts", [])
    total = len(all_conflicts)
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "conflicts": all_conflicts[start:end],
    })


@bp.route("/api/filters")
def api_filters():
    session = get_session()
    teachers = [{"id": t.teacher_id, "name": t.name}
                for t in session.query(Teacher).all()]
    groups = [{"id": g.group_id, "name": f"{g.program} Y{g.year}"}
              for g in session.query(StudentGroup).all()]
    rooms = [{"id": r.room_id, "name": f"Room {r.room_id} (cap {r.capacity})"}
             for r in session.query(Classroom).all()]
    session.close()
    return jsonify({"teachers": teachers, "groups": groups, "rooms": rooms})


@bp.route("/api/generate", methods=["POST"])
def api_generate():
    global _sim_running, _last_results

    if _sim_lock.locked():
        return jsonify({"error": "Simulation already running"}), 409

    body   = request.get_json(silent=True) or {}
    reseed = body.get("reseed", True)  # default: reseed for a fresh scenario

    def _run():
        global _sim_running, _last_results
        _sim_running = True
        try:
            _last_results = run_simulation(reseed=reseed)
        finally:
            _sim_running = False

    t = threading.Thread(target=_run, daemon=True)
    _sim_lock.acquire(blocking=False)
    try:
        t.start()
        t.join()
    finally:
        if _sim_lock.locked():
            _sim_lock.release()

    return jsonify({
        "message": "Scheduling complete",
        "stats": _last_results.get("stats", {}),
    })


@bp.route("/api/export/csv")
def export_csv():
    session = get_session()
    rows = (
        session.query(Schedule, Course, Teacher, StudentGroup, Classroom)
        .join(Course, Schedule.course_id == Course.course_id)
        .join(Teacher, Course.teacher_id == Teacher.teacher_id)
        .join(StudentGroup, Course.group_id == StudentGroup.group_id)
        .join(Classroom, Schedule.room_id == Classroom.room_id)
        .all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["session_id", "course", "teacher", "group", "room",
                     "day", "time_slot", "type", "status"])
    for sched, course, teacher, group, room in rows:
        writer.writerow([
            sched.session_id, course.course_name, teacher.name,
            f"{group.program} Y{group.year}", f"Room {room.room_id}",
            sched.day, sched.time_slot, course.required_room_type, sched.status,
        ])
    session.close()
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=timetable.csv"},
    )


@bp.route("/api/export/pdf")
def export_pdf():
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except ImportError:
        return jsonify({"error": "reportlab not installed"}), 500

    session = get_session()
    rows = (
        session.query(Schedule, Course, Teacher, StudentGroup, Classroom)
        .join(Course, Schedule.course_id == Course.course_id)
        .join(Teacher, Course.teacher_id == Teacher.teacher_id)
        .join(StudentGroup, Course.group_id == StudentGroup.group_id)
        .join(Classroom, Schedule.room_id == Classroom.room_id)
        .order_by(Schedule.day, Schedule.time_slot)
        .all()
    )
    session.close()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    elements = [Paragraph("University Timetable", styles["Title"]), Spacer(1, 12)]

    table_data = [["Course", "Teacher", "Group", "Room", "Day", "Time", "Type"]]
    for sched, course, teacher, group, room in rows:
        table_data.append([
            course.course_name, teacher.name,
            f"{group.program} Y{group.year}", f"Room {room.room_id}",
            sched.day, sched.time_slot, course.required_room_type,
        ])

    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4f46e5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=timetable.pdf"},
    )


# ── Reseed ────────────────────────────────────────────────────────────────────

@bp.route("/api/reseed", methods=["POST"])
def api_reseed():
    """Drop all data and seed a fresh randomised scenario."""
    from db.seed import seed as seed_db
    body = request.get_json(silent=True) or {}
    seed_db(
        n_teachers=body.get("n_teachers"),
        n_groups=body.get("n_groups"),
        n_classrooms=body.get("n_classrooms"),
        n_courses=body.get("n_courses"),
    )
    session = get_session()
    counts = {
        "teachers":   session.query(Teacher).count(),
        "groups":     session.query(StudentGroup).count(),
        "classrooms": session.query(Classroom).count(),
        "courses":    session.query(Course).count(),
    }
    session.close()
    return jsonify({"message": "Database reseeded with a new random scenario.", "counts": counts})


# ── CRUD: Teachers ────────────────────────────────────────────────────────────

@bp.route("/api/teachers", methods=["GET"])
def list_teachers():
    session = get_session()
    teachers = session.query(Teacher).order_by(Teacher.teacher_id).all()
    data = [{
        "teacher_id":       t.teacher_id,
        "name":             t.name,
        "available_days":   json.loads(t.available_days),
        "preferred_slots":  json.loads(t.preferred_slots),
        "max_hours_per_week": t.max_hours_per_week,
        "course_count":     len(t.courses),
    } for t in teachers]
    session.close()
    return jsonify(data)


@bp.route("/api/teachers/<int:tid>", methods=["GET"])
def get_teacher(tid):
    session = get_session()
    t = session.query(Teacher).get(tid)
    if not t:
        session.close()
        return jsonify({"error": "Teacher not found"}), 404
    data = {
        "teacher_id":       t.teacher_id,
        "name":             t.name,
        "available_days":   json.loads(t.available_days),
        "preferred_slots":  json.loads(t.preferred_slots),
        "max_hours_per_week": t.max_hours_per_week,
    }
    session.close()
    return jsonify(data)


@bp.route("/api/teachers", methods=["POST"])
def create_teacher():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    session = get_session()
    t = Teacher(
        name=name,
        available_days=json.dumps(body.get("available_days", ["Mon","Tue","Wed","Thu","Fri"])),
        preferred_slots=json.dumps(body.get("preferred_slots", ["08:00","10:00"])),
        max_hours_per_week=int(body.get("max_hours_per_week", 20)),
    )
    session.add(t)
    session.commit()
    tid = t.teacher_id
    session.close()
    return jsonify({"message": "Teacher created", "teacher_id": tid}), 201


@bp.route("/api/teachers/<int:tid>", methods=["PUT"])
def update_teacher(tid):
    body = request.get_json(silent=True) or {}
    session = get_session()
    t = session.query(Teacher).get(tid)
    if not t:
        session.close()
        return jsonify({"error": "Teacher not found"}), 404
    if "name" in body:
        t.name = body["name"].strip() or t.name
    if "available_days" in body:
        t.available_days = json.dumps(body["available_days"])
    if "preferred_slots" in body:
        t.preferred_slots = json.dumps(body["preferred_slots"])
    if "max_hours_per_week" in body:
        t.max_hours_per_week = int(body["max_hours_per_week"])
    session.commit()
    session.close()
    return jsonify({"message": "Teacher updated"})


@bp.route("/api/teachers/<int:tid>", methods=["DELETE"])
def delete_teacher(tid):
    session = get_session()
    t = session.query(Teacher).get(tid)
    if not t:
        session.close()
        return jsonify({"error": "Teacher not found"}), 404
    try:
        session.delete(t)
        session.commit()
    except IntegrityError:
        session.rollback()
        session.close()
        return jsonify({"error": "Cannot delete teacher with assigned courses"}), 409
    session.close()
    return jsonify({"message": "Teacher deleted"})


# ── CRUD: Student Groups ──────────────────────────────────────────────────────

@bp.route("/api/groups", methods=["GET"])
def list_groups():
    session = get_session()
    groups = session.query(StudentGroup).order_by(StudentGroup.group_id).all()
    data = [{
        "group_id":    g.group_id,
        "program":     g.program,
        "year":        g.year,
        "group_size":  g.group_size,
        "course_count": len(g.courses),
    } for g in groups]
    session.close()
    return jsonify(data)


@bp.route("/api/groups/<int:gid>", methods=["GET"])
def get_group(gid):
    session = get_session()
    g = session.query(StudentGroup).get(gid)
    if not g:
        session.close()
        return jsonify({"error": "Group not found"}), 404
    data = {"group_id": g.group_id, "program": g.program, "year": g.year, "group_size": g.group_size}
    session.close()
    return jsonify(data)


@bp.route("/api/groups", methods=["POST"])
def create_group():
    body = request.get_json(silent=True) or {}
    program = (body.get("program") or "").strip()
    if not program:
        return jsonify({"error": "program is required"}), 400
    session = get_session()
    g = StudentGroup(
        program=program,
        year=int(body.get("year", 1)),
        group_size=int(body.get("group_size", 30)),
    )
    session.add(g)
    session.commit()
    gid = g.group_id
    session.close()
    return jsonify({"message": "Group created", "group_id": gid}), 201


@bp.route("/api/groups/<int:gid>", methods=["PUT"])
def update_group(gid):
    body = request.get_json(silent=True) or {}
    session = get_session()
    g = session.query(StudentGroup).get(gid)
    if not g:
        session.close()
        return jsonify({"error": "Group not found"}), 404
    if "program" in body:
        g.program = body["program"].strip() or g.program
    if "year" in body:
        g.year = int(body["year"])
    if "group_size" in body:
        g.group_size = int(body["group_size"])
    session.commit()
    session.close()
    return jsonify({"message": "Group updated"})


@bp.route("/api/groups/<int:gid>", methods=["DELETE"])
def delete_group(gid):
    session = get_session()
    g = session.query(StudentGroup).get(gid)
    if not g:
        session.close()
        return jsonify({"error": "Group not found"}), 404
    try:
        session.delete(g)
        session.commit()
    except IntegrityError:
        session.rollback()
        session.close()
        return jsonify({"error": "Cannot delete group with assigned courses"}), 409
    session.close()
    return jsonify({"message": "Group deleted"})


# ── CRUD: Classrooms ──────────────────────────────────────────────────────────

@bp.route("/api/classrooms", methods=["GET"])
def list_classrooms():
    session = get_session()
    rooms = session.query(Classroom).order_by(Classroom.room_id).all()
    data = [{
        "room_id":    r.room_id,
        "capacity":   r.capacity,
        "equipment":  json.loads(r.equipment),
        "session_count": len(r.sessions),
    } for r in rooms]
    session.close()
    return jsonify(data)


@bp.route("/api/classrooms/<int:rid>", methods=["GET"])
def get_classroom(rid):
    session = get_session()
    r = session.query(Classroom).get(rid)
    if not r:
        session.close()
        return jsonify({"error": "Classroom not found"}), 404
    data = {"room_id": r.room_id, "capacity": r.capacity, "equipment": json.loads(r.equipment)}
    session.close()
    return jsonify(data)


@bp.route("/api/classrooms", methods=["POST"])
def create_classroom():
    body = request.get_json(silent=True) or {}
    capacity = body.get("capacity")
    if not capacity:
        return jsonify({"error": "capacity is required"}), 400
    session = get_session()
    r = Classroom(
        capacity=int(capacity),
        equipment=json.dumps(body.get("equipment", ["projector", "whiteboard"])),
    )
    session.add(r)
    session.commit()
    rid = r.room_id
    session.close()
    return jsonify({"message": "Classroom created", "room_id": rid}), 201


@bp.route("/api/classrooms/<int:rid>", methods=["PUT"])
def update_classroom(rid):
    body = request.get_json(silent=True) or {}
    session = get_session()
    r = session.query(Classroom).get(rid)
    if not r:
        session.close()
        return jsonify({"error": "Classroom not found"}), 404
    if "capacity" in body:
        r.capacity = int(body["capacity"])
    if "equipment" in body:
        r.equipment = json.dumps(body["equipment"])
    session.commit()
    session.close()
    return jsonify({"message": "Classroom updated"})


@bp.route("/api/classrooms/<int:rid>", methods=["DELETE"])
def delete_classroom(rid):
    session = get_session()
    r = session.query(Classroom).get(rid)
    if not r:
        session.close()
        return jsonify({"error": "Classroom not found"}), 404
    try:
        session.delete(r)
        session.commit()
    except IntegrityError:
        session.rollback()
        session.close()
        return jsonify({"error": "Cannot delete classroom with scheduled sessions"}), 409
    session.close()
    return jsonify({"message": "Classroom deleted"})


# ── CRUD: Courses ─────────────────────────────────────────────────────────────

@bp.route("/api/courses", methods=["GET"])
def list_courses():
    session = get_session()
    courses = (
        session.query(Course, Teacher, StudentGroup)
        .join(Teacher, Course.teacher_id == Teacher.teacher_id)
        .join(StudentGroup, Course.group_id == StudentGroup.group_id)
        .order_by(Course.course_id)
        .all()
    )
    data = [{
        "course_id":         c.course_id,
        "course_name":       c.course_name,
        "teacher_id":        c.teacher_id,
        "teacher_name":      t.name,
        "group_id":          c.group_id,
        "group_name":        f"{g.program} Y{g.year}",
        "required_room_type": c.required_room_type,
        "duration_hours":    c.duration_hours,
    } for c, t, g in courses]
    session.close()
    return jsonify(data)


@bp.route("/api/courses/<int:cid>", methods=["GET"])
def get_course(cid):
    session = get_session()
    c = session.query(Course).get(cid)
    if not c:
        session.close()
        return jsonify({"error": "Course not found"}), 404
    data = {
        "course_id":          c.course_id,
        "course_name":        c.course_name,
        "teacher_id":         c.teacher_id,
        "group_id":           c.group_id,
        "required_room_type": c.required_room_type,
        "duration_hours":     c.duration_hours,
    }
    session.close()
    return jsonify(data)


@bp.route("/api/courses", methods=["POST"])
def create_course():
    body = request.get_json(silent=True) or {}
    name = (body.get("course_name") or "").strip()
    if not name:
        return jsonify({"error": "course_name is required"}), 400
    if not body.get("teacher_id") or not body.get("group_id"):
        return jsonify({"error": "teacher_id and group_id are required"}), 400
    session = get_session()
    # validate FK existence
    if not session.query(Teacher).get(int(body["teacher_id"])):
        session.close()
        return jsonify({"error": "teacher_id does not exist"}), 400
    if not session.query(StudentGroup).get(int(body["group_id"])):
        session.close()
        return jsonify({"error": "group_id does not exist"}), 400
    rtype = body.get("required_room_type", "lecture")
    if rtype not in ("lecture", "lab", "tutorial"):
        session.close()
        return jsonify({"error": "required_room_type must be lecture, lab, or tutorial"}), 400
    c = Course(
        course_name=name,
        teacher_id=int(body["teacher_id"]),
        group_id=int(body["group_id"]),
        required_room_type=rtype,
        duration_hours=int(body.get("duration_hours", 2)),
    )
    session.add(c)
    session.commit()
    cid = c.course_id
    session.close()
    return jsonify({"message": "Course created", "course_id": cid}), 201


@bp.route("/api/courses/<int:cid>", methods=["PUT"])
def update_course(cid):
    body = request.get_json(silent=True) or {}
    session = get_session()
    c = session.query(Course).get(cid)
    if not c:
        session.close()
        return jsonify({"error": "Course not found"}), 404
    if "course_name" in body:
        c.course_name = body["course_name"].strip() or c.course_name
    if "teacher_id" in body:
        if not session.query(Teacher).get(int(body["teacher_id"])):
            session.close()
            return jsonify({"error": "teacher_id does not exist"}), 400
        c.teacher_id = int(body["teacher_id"])
    if "group_id" in body:
        if not session.query(StudentGroup).get(int(body["group_id"])):
            session.close()
            return jsonify({"error": "group_id does not exist"}), 400
        c.group_id = int(body["group_id"])
    if "required_room_type" in body:
        if body["required_room_type"] not in ("lecture", "lab", "tutorial"):
            session.close()
            return jsonify({"error": "required_room_type must be lecture, lab, or tutorial"}), 400
        c.required_room_type = body["required_room_type"]
    if "duration_hours" in body:
        c.duration_hours = int(body["duration_hours"])
    session.commit()
    session.close()
    return jsonify({"message": "Course updated"})


@bp.route("/api/courses/<int:cid>", methods=["DELETE"])
def delete_course(cid):
    session = get_session()
    c = session.query(Course).get(cid)
    if not c:
        session.close()
        return jsonify({"error": "Course not found"}), 404
    try:
        session.delete(c)
        session.commit()
    except IntegrityError:
        session.rollback()
        session.close()
        return jsonify({"error": "Cannot delete course with scheduled sessions"}), 409
    session.close()
    return jsonify({"message": "Course deleted"})


# ── Pages: data management ────────────────────────────────────────────────────

@bp.route("/data")
def data_management():
    return render_template("data.html")


# Initialize DB on first import
init_db()
