# Setup and troubleshooting

## Prerequisites

- Python **3.11+**
- MongoDB **6.0+** (local Docker or Atlas)
- Git (for submission)

## Step-by-step (personal laptop)

### 1. Unzip project

Place the folder anywhere, e.g. `~/projects/candidate_kit`.

### 2. Virtual environment

```bash
cd candidate_kit
python -m venv .venv
```

Activate:

- **Windows:** `.venv\Scripts\activate`
- **macOS/Linux:** `source .venv/bin/activate`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. MongoDB

**Docker (example):**

```bash
docker run -d --name mongo -p 27017:27017 mongo:7
```

**Atlas:** create free M0 cluster, copy connection string.

### 5. Environment file

```bash
cp .env.example .env
```

Edit `.env`:

```
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

For Atlas, use `mongodb+srv://...` and ensure IP allowlist includes your machine.

### 6. Seed sample data

```bash
python sample_seed.py
```

You should see two lines loading employees and attendance_logs.

### 7. Run API

```bash
uvicorn app.main:app --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs`.

### 8. Run tests

```bash
pytest -v
```

Paste output into `TEST_REPORT.md` for your records.

## Configuration reference

| Variable | Default | Meaning |
|----------|---------|---------|
| `MONGO_URI` | `mongodb://localhost:27017` | Mongo connection string |
| `MONGO_DB` | `attendance_db` | Database name |

## Common errors

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Connection refused` on health | Mongo not running | Start Docker/Atlas |
| `503` on `/health` | Wrong URI or auth | Check `.env` |
| `409` on punch-in | Second punch same day | Expected; one record per day |
| `422` on PATCH | No actual field changes | Change status or punch times |
| Import error `app` | Wrong working directory | Run uvicorn from project root |
| Tests fail on work hours | TZ assumptions | Run tests with project code as-is; report failure |

## ZIP tips

Exclude when zipping from a machine that already ran setup:

- `.venv/`
- `__pycache__/`
- `.env` (never share)

Include everything else, especially `app/main.py`, `docs/`, `tests/`, and `openapi.yaml`.

## Git submission

```bash
git init
git add app requirements.txt README.md REVIEW.md DECISIONS.md docs tests sample_data sample_seed.py openapi.yaml DATA_MODEL.md .env.example .gitignore
git commit -m "HROne attendance API submission"
# add remote and push to public GitHub
```

Do not add `.env` or Dockerfile.
