# Test report

## Environment where this file was written

- **Office laptop:** no `pip install`, no MongoDB, no `uvicorn` run (per your request).
- **Evidence:** static review of code against `openapi.yaml` and `DATA_MODEL.md`; unit tests authored but not executed here unless noted below.

## Tests included

| Suite | File | Needs MongoDB? | Purpose |
|-------|------|----------------|---------|
| Business rules | `tests/test_business_rules.py` | No | R1–R5 style helpers (late grace, OT floor, half-day, overnight date) |

## How to run (personal laptop)

```bash
pip install -r requirements.txt
pytest -v
```

Optional API smoke test after seed:

```bash
python sample_seed.py
uvicorn app.main:app --port 8000
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/analytics/employees/EMP0001/monthly?month=2026-07"
```

## Results on office laptop

| Command | Result |
|---------|--------|
| `pytest` | **Not run** — dependencies not installed in this environment |
| Manual API calls | **Not run** — MongoDB/server not started |

## What you should verify before submit

1. All `pytest` tests pass.
2. `GET /health` returns 200 with Mongo up; 503 with Mongo down.
3. Sample seed + monthly analytics for `EMP0001` / `2026-07` look reasonable.
4. `GET /admin/explain/attendance_list` shows `IXSCAN` (not `COLLSCAN`) once indexes exist and data volume is large enough for the grader.

Update this file with your local pytest output after you run it.
