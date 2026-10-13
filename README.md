# Employee Attendance & Analytics API (HROne assignment)

FastAPI service backed by MongoDB: punch-in/out, manual corrections with audit history, and monthly analytics. All application code lives in **`app/main.py`** as required by the grader.

## What you get in this folder

| Path | Purpose |
|------|---------|
| `app/main.py` | Full API implementation |
| `openapi.yaml` | HTTP contract + business rules R1–R10 |
| `DATA_MODEL.md` | MongoDB collections and field types |
| `sample_data/` + `sample_seed.py` | Nine sample documents for local smoke tests |
| `REVIEW.md` | Starter code review (submission template) |
| `DECISIONS.md` | Short design notes (submission template) |
| `docs/` | Beginner-friendly guides (read after this file) |
| `tests/` | Unit tests for date/math rules (no DB) |

There is **no web UI** in this assignment—only a REST API. FastAPI still serves interactive docs at `/docs` once the server is running.

## Transfer to your personal laptop (ZIP)

1. Zip the whole `candidate_kit` folder (exclude `.venv` if you create one later).
2. On the personal machine: install **Python 3.11+** and **MongoDB 6+** (Docker `mongo:7` or Atlas).
3. Follow [docs/SETUP.md](docs/SETUP.md) step by step.

Do **not** commit or share `.env` files (use `.env.example` as a template).

## Quick start (personal machine)

```bash
cd candidate_kit
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env    # or cp on Unix; edit MONGO_URI if needed
python sample_seed.py
uvicorn app.main:app --port 8000 --reload
```

- Health: `GET http://127.0.0.1:8000/health`
- Swagger UI: `http://127.0.0.1:8000/docs`

## Tests

```bash
pytest -q
```

See [TEST_REPORT.md](TEST_REPORT.md) for what was run on the office machine (if anything).

## Documentation map

1. [docs/OVERVIEW.md](docs/OVERVIEW.md) — features and architecture  
2. [docs/CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md) — how `main.py` is organised  
3. [docs/DATA_FLOW.md](docs/DATA_FLOW.md) — request → MongoDB → response  
4. [docs/SETUP.md](docs/SETUP.md) — setup, config, troubleshooting  
5. [docs/EXTENDING.md](docs/EXTENDING.md) — how to add endpoints safely  

## Submission checklist (HROne)

- [x] `app/main.py`, `requirements.txt`, `README.md`, `REVIEW.md`, `DECISIONS.md`
- [x] Public Git repo (you push from personal laptop)
- [ ] No `.env`, secrets, or Dockerfile in the repo
- [ ] Form submitted before **15 Oct 2026, 11:59 PM IST**

## Honest status

Implementation follows `openapi.yaml` to the best of manual review here. **Automated grader and MongoDB were not run on the office laptop** (no installs). Run `pytest`, seed data, and hit `/docs` on your personal machine before submitting.
