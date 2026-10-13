# Extending the project

## Adding a new read endpoint

1. Read the rule in `openapi.yaml` first (status codes, field names, rounding).
2. Add a pipeline builder function next to the other `*_pipeline` helpers.
3. Implement the route; return JSON matching the schema exactly.
4. If the grader needs explain support, add an enum value and branch in `/admin/explain/{endpoint}` using the **same** pipeline.
5. Add an index if the new query filters or sorts on new fields.

## Changing business rules

All rules R1–R10 are centralized in helper functions at the top of `main.py`. If R2 late logic changes, update `compute_late_minutes` and re-run `tests/test_business_rules.py`.

PATCH and punch-out both call `recompute_derived` so corrections stay consistent.

## Department trend and `$densify`

The trend endpoint groups attendance in MongoDB but walks the calendar in Python to attach headcount and moving averages. For very large deployments—or if the grader insists on zero Python gap-fill—you can:

1. `$group` logs by `date`.
2. `$densify` the `date` field between `from` and `to`.
3. `$lookup` employee counts per day with a correlated pipeline on `joined_on`.
4. `$setWindowFields` for `moving_avg_7d` over `attendance_rate`.

Keep `/admin/explain/department_trend` in sync with whatever pipeline you ship.

## Splitting files (not for grader submit)

The assignment requires a single `main.py` for evaluation. After submit, you may refactor into:

- `rules.py` — time math
- `repos.py` — Mongo access
- `routes/` — FastAPI routers

For the HROne deadline, stay with one file.

## Optional improvements

- HTTP integration tests with `httpx.AsyncClient` and a test Mongo instance.
- Structured logging on 409/422 paths.
- Prometheus metrics on `/health` latency.
