# REVIEW.md

Defects found in the starter `app/main.py` (helpers and endpoints):

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `list_employees` | `total` uses `count_documents({})` while `items` respect the `department` filter | `GET /employees?department=Sales` shows a `total` larger than matching rows | Count with the same `q` filter as the find |
| 2 | `list_employees` | `skip = page * page_size` | Page 1 skips the first page entirely; page 2 skips two pages | Use `(page - 1) * page_size` |
| 3 | `health` | Always returns ok without checking MongoDB | Service looks healthy when DB is down | `admin.command("ping")`, return 503 on failure |
| 4 | `compute_late_minutes` | Builds shift start by replacing clock on `punch_in` in local/naive time, grace is `> 10` minutes as integer compare on wrong delta | Late minutes disagree with R2 (e.g. 09:40:01 should be 10, not 0) | IST shift start on attendance `date`, floor minutes, late only if `> 10` |
| 5 | `compute_overtime` | Parses `date_str` with `fromisoformat` and ignores overnight shifts | Overnight and OT threshold (30 min) wrong | `shift_end_on_date` with next-day end for overnight; floor minutes; 0 unless ≥ 30 |
| 6 | `punch_in` | No check when `emp` is missing | Unknown `emp_code` causes `TypeError` on `emp["shift_start"]` | 404 when employee not found |
| 7 | `punch_in` / responses | Treats `punched_at` as seconds (`/ 1000` only) and returns extra `id` field | Grader sends epoch ms; response shape does not match OpenAPI | Validate ms range; serialize without Mongo `_id` / `id` |
| 8 | `create_employee` / `serialize` | `created_at` left as BSON datetime in JSON | Clients expect epoch milliseconds | Convert at API boundary |
| 9 | `list_attendance` | Loads all matching documents, sorts in Python | Slow or OOM on large collections; explain plan unlike production query | `count_documents` + aggregation with `$sort`, `$skip`, `$limit` and indexes |
| 10 | (missing) | No unique index on `(emp_code, date)`; check-then-insert punch-in | Duplicate punch-in under concurrency | Unique index + rely on `DuplicateKeyError` → 409 |
| 11 | (missing) | Punch-out, PATCH, analytics, `/admin/explain` not implemented | Contract tests fail | Implemented per `openapi.yaml` |

**Not treated as defects**

- Leaving all logic in `app/main.py` — required by the assignment.
- Using `load_dotenv()` — spec allows `.env` as long as real environment variables win (default `load_dotenv` behaviour).
