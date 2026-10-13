# Project overview

## Purpose

This project is a small **HR attendance backend**: employees punch in and out, HR can correct mistakes, and managers can pull monthly analytics (lateness, department summaries, trends).

## Features (by area)

### Employees

- Create employee with shift times and `joined_on`.
- List employees with optional department filter and pagination.

### Attendance

- **Punch-in** — creates one record per (`emp_code`, attendance `date`); computes `late_minutes`.
- **Punch-out** — closes the latest open record; computes `work_hours`, `overtime_minutes`, `half_day`.
- **List** — filter by employee, date range, status; sorted by date desc.
- **PATCH regularize** — manual fix with `history` audit trail; recomputes derived fields.

### Analytics (MongoDB aggregations)

- Per-employee monthly summary.
- Per-department monthly summary (includes headcount with zero-log employees).
- Late leaderboard with competition ranking.
- Department daily trend (present/late counts, attendance rate, 7-day moving average).

### Admin

- `/admin/explain/{endpoint}` — returns MongoDB `explain` for the same pipeline the endpoint uses.

## Technology stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Database | MongoDB 6+ (BSON datetimes internally) |
| Driver | PyMongo |
| Validation | Pydantic v2 |

## Architecture (high level)

```
Client (curl / grader / Swagger)
        │
        ▼
   FastAPI (app/main.py)
        │
        ├── helpers: IST dates, R1–R5 math, serialization
        ├── indexes on startup
        └── PyMongo ──► MongoDB
              ├── employees
              └── attendance_logs
```

There is no separate service layer file—the assignment requires a single `main.py`, so functions are grouped by comment sections instead.

## Security notes (assignment scope)

- No authentication: `regularized_by` is free text.
- No secrets in the repo; connection string via `MONGO_URI`.
- Input validation via Pydantic (epoch ms range, email pattern, etc.).

For production you would add auth, rate limits, and TLS to MongoDB.
