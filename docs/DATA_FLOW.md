# Data flow

## Punch-in

```
JSON body (emp_code, optional punched_at ms, status)
    → load employee shift times
    → ms_to_dt + truncate_second
    → attendance_date_for_punch (R1)
    → compute_late_minutes (R2)
    → insert attendance_logs document
    → serialize_attendance (ms out)
```

Mongo document stores BSON datetimes for `punch_in`; `punch_out` and `work_hours` start null.

## Punch-out

```
Find latest log for emp where punch_in <= punched_at AND punch_out is null
    → validate punched_at after punch_in and within 24h
    → recompute_derived (work_hours, OT, half_day, late again)
    → atomic update if still open
```

Overnight example: punch on `2026-07-06` with out on `2026-07-07` stays on one row keyed by `date=2026-07-06`.

## Regularize (PATCH)

```
Load employee + existing log by (emp_code, date)
    → merge optional status / punch_in / punch_out from body
    → validate ABSENT/LEAVE vs punch times, presence needs punch_in, R1 date match
    → recompute_derived
    → diff old vs new → history.changes (only changed fields)
    → update with history size check (concurrency)
```

History stores BSON datetimes inside `changes`; API returns ms for punch fields.

## Analytics

**Monthly employee**

1. `working_days` from employee `joined_on` + calendar (Python).
2. Log metrics from `$group` on `attendance_logs` (stored `late_minutes`, `half_day`, etc.—not recomputed from punches).

**Department summary**

1. Start from `employees` filtered by `joined_on <= month end` → headcount per department.
2. `$lookup` logs in month → sum present credit (weekday + half-day rules in aggregation).

**Leaderboard**

1. `$group` late minutes per `emp_code` in month.
2. Join names from `employees`; competition rank in Python; filter `rank <= limit`.

**Trend**

1. `$group` by `date` for department employees in range.
2. Walk each calendar day from `from` to `to` to attach headcount (from `joined_on`) and fill missing days.
3. Compute `attendance_rate` on working days; 7-day moving average over non-null rates in range.

## Explain endpoint

Runs `.explain()` on the **same** pipeline builder the list/analytics endpoint uses, so graders can confirm index use (`IXSCAN`).
