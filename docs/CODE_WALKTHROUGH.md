# Code walkthrough (`app/main.py`)

Read `main.py` top to bottom once; this guide maps sections to responsibilities.

## 1. Configuration

- `load_dotenv()` loads `.env` only for variables **not** already set in the OS.
- `MongoClient(..., tz_aware=True)` so punch times stay consistent when converting to IST.

## 2. Time and rules helpers

| Function | Rule | Idea in plain words |
|----------|------|---------------------|
| `truncate_second` | R1 | Drop sub-second precision before store/return |
| `attendance_date_for_punch` | R1 | Which calendar `date` label a punch belongs to (overnight shifts) |
| `compute_late_minutes` | R2 | 10-minute grace; then floor minutes since shift start |
| `compute_work_hours` | R4 | Duration in hours, half-up to 2 decimals |
| `compute_overtime_minutes` | R3 | Minutes after shift end; 0 unless ≥ 30 |
| `compute_half_day` | R5 | True if work hours &lt; 4.50 |
| `working_days_in_month` | R7 | Weekdays in month from `joined_on` |
| `round_half_up` | R8 | Decimal-based rounding (avoids float surprises) |

## 3. Serialization

- **API outward:** instants → epoch **milliseconds** (`dt_to_ms`).
- **API inward:** ms → UTC `datetime` (`ms_to_dt`).
- `serialize_attendance` never exposes Mongo `_id`; records are keyed by `(emp_code, date)`.

## 4. Pydantic models

Request bodies validate formats (e.g. `EMP0001` pattern, shift `HH:MM`, epoch ms bounds).

## 5. Startup indexes

`ensure_indexes()` runs on app start:

- Unique `emp_code`
- Unique `(emp_code, date)` on logs
- Sort/support indexes for list and punch-out queries

## 6. Query builders

`attendance_list_pipeline`, `department_summary_pipeline`, `employee_monthly_log_pipeline` are shared with `/admin/explain` so the explain plan matches real traffic.

## 7. Endpoints (patterns)

| Endpoint | Pattern |
|----------|---------|
| Punch-in | `insert_one` + unique index → 409 on duplicate |
| Punch-out | `find_one` open record, then `find_one_and_update` with `punch_out: None` guard |
| PATCH | Compare old vs new snapshot, build `changes`, update only if `history` length unchanged (409 on clash) |
| Analytics | Aggregation pipelines; leaderboard ranking done in Python after `$group` |
| Trend | Groups logs by day in MongoDB; fills calendar days and moving average in Python (see `EXTENDING.md` for `$densify` upgrade) |

## 8. Error codes (typical)

| Code | When |
|------|------|
| 404 | Unknown employee or missing attendance row |
| 409 | Duplicate punch-in/out or concurrent PATCH |
| 422 | Validation / business rule (dates, punch order, no-op PATCH) |
| 503 | `/health` when Mongo ping fails |
