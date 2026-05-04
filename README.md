# Intelligent University Observatory (IUO)

A Multi-Agent System for automated university timetable generation, built with Mesa, Flask, SQLite, and Plotly.

## Architecture

```
intelligent_university_observatory/
├── agents/
│   ├── scheduler_agent.py    # Central coordinator (backtracking CSP)
│   ├── teacher_agent.py      # Availability + preference management
│   ├── group_agent.py        # Overlap detection for student groups
│   ├── room_agent.py         # Capacity + equipment matching
│   └── constraint_agent.py   # Institutional rule validation
├── db/
│   ├── models.py             # SQLAlchemy ORM models
│   ├── seed.py               # Realistic seed data (10T/8G/15R/30C)
│   └── university.db         # SQLite database (auto-created)
├── simulation/
│   └── run_simulation.py     # Mesa model + simulation runner
├── web/
│   ├── app.py                # Flask factory
│   ├── routes.py             # REST API + page routes
│   └── templates/            # Jinja2 HTML templates
├── utils/
│   └── message_protocol.py   # MessageBus + typed Message dataclass
├── tests/
│   └── test_agents.py        # pytest unit tests
└── requirements.txt
```

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed the database
python db/seed.py

# 4. Run the web server
python web/app.py
# Open http://localhost:5000
```

## Running the Simulation (CLI)

```bash
python simulation/run_simulation.py
```

## Running Tests

```bash
pytest tests/ -v
```

## REST API

| Method | Endpoint            | Description                        |
|--------|---------------------|------------------------------------|
| GET    | /api/stats          | Dashboard summary metrics          |
| GET    | /api/schedule       | Full schedule (JSON)               |
| GET    | /api/agents         | Agent statuses                     |
| GET    | /api/conflicts      | Paginated conflict log             |
| GET    | /api/filters        | Filter options (teachers/groups/rooms) |
| POST   | /api/generate       | Trigger a new scheduling run       |
| GET    | /api/export/csv     | Download timetable as CSV          |
| GET    | /api/export/pdf     | Download timetable as PDF          |

## Agent Communication Protocol

Agents communicate via a shared `MessageBus` using typed messages:

- `REQUEST` — Scheduler asks an agent to check availability
- `PROPOSAL` — Teacher proposes a slot with a preference score
- `ACCEPT` — Group/Room confirms a slot is free
- `REJECT` — Agent rejects a slot (with alternatives or reasons)
- `CONFLICT` — Group reports an overlap
- `CONFIRM` — Scheduler commits a final assignment

## Scheduling Algorithm

1. Sort courses by group size (largest first — hardest to place)
2. For each course, generate all valid `(day, slot, room)` candidates
3. Rank candidates by teacher preference score, then tightest room fit
4. Validate against `ConstraintAgent` (max 4h/day per group, max 3 consecutive teacher slots)
5. On conflict: skip candidate and try next (backtracking)
6. Persist confirmed sessions to SQLite

## Hard Constraints

- No teacher double-booked at the same time
- No student group has two sessions simultaneously
- No room double-booked at the same time
- Room capacity ≥ group size
- Room equipment matches session type (lab sessions need lab rooms)

## Soft Constraints

- Teacher preferred days and time slots (scored 0–1.0)
- Tightest-fit room selection (minimizes wasted capacity)
