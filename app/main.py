"""
Employee Attendance & Analytics API.

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (optional .env; real env vars take precedence)
"""
from __future__ import annotations

import calendar
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

load_dotenv()  # does not override variables already set in the environment

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "attendance_db")

IST = timezone(timedelta(hours=5, minutes=30))
PRESENCE_STATUSES = frozenset({"PRESENT", "WFH", "ON_DUTY"})
ALL_STATUSES = frozenset({"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"})
EPOCH_MIN = 100_000_000_000
EPOCH_MAX = 4_102_444_800_000
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMP_CODE_RE = re.compile(r"^EMP\d{4,6}$")

client = MongoClient(MONGO_URI, tz_aware=True)
db = client[MONGO_DB]

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Time / rounding helpers (R1–R5, R8)
# --------------------------------------------------------------------------- #
def round_half_up(value: float, places: int) -> float:
    if places == 0:
        quant = Decimal("1")
    else:
        quant = Decimal("0." + "0" * (places - 1) + "1")
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def truncate_second(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0)


def ms_to_dt(ms: int) -> datetime:
    return truncate_second(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def dt_to_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(truncate_second(dt).timestamp() * 1000)


def parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def is_overnight(shift_start: str, shift_end: str) -> bool:
    return shift_end <= shift_start


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def attendance_date_for_punch(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    """R1: IST calendar date of the attendance day."""
    punch_ist = to_ist(truncate_second(punch_in))
    if is_overnight(shift_start, shift_end):
        h_end, m_end = parse_hhmm(shift_end)
        punch_mins = punch_ist.hour * 60 + punch_ist.minute
        end_mins = h_end * 60 + m_end
        if punch_mins < end_mins:
            return (punch_ist.date() - timedelta(days=1)).isoformat()
    return punch_ist.date().isoformat()


def shift_start_on_date(date_str: str, shift_start: str) -> datetime:
    y, mo, d = map(int, date_str.split("-"))
    h, m = parse_hhmm(shift_start)
    return datetime(y, mo, d, h, m, 0, tzinfo=IST)


def shift_end_on_date(date_str: str, shift_start: str, shift_end: str) -> datetime:
    y, mo, d = map(int, date_str.split("-"))
    h, m = parse_hhmm(shift_end)
    if is_overnight(shift_start, shift_end):
        base = datetime(y, mo, d, tzinfo=IST) + timedelta(days=1)
        return base.replace(hour=h, minute=m, second=0, microsecond=0)
    return datetime(y, mo, d, h, m, 0, tzinfo=IST)


def compute_late_minutes(punch_in: datetime, date_str: str, shift_start: str) -> int:
    """R2: grace is 10 minutes; late = floor minutes since shift start when > 10."""
    pin = to_ist(truncate_second(punch_in))
    start = shift_start_on_date(date_str, shift_start)
    elapsed = int((pin - start).total_seconds() // 60)
    return elapsed if elapsed > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    """R4: seconds / 3600, half-up to 2 decimals."""
    secs = (truncate_second(punch_out) - truncate_second(punch_in)).total_seconds()
    return round_half_up(secs / 3600.0, 2)


def compute_overtime_minutes(
    punch_out: datetime, date_str: str, shift_start: str, shift_end: str
) -> int:
    """R3: floor minutes after shift end; 0 unless >= 30."""
    pout = to_ist(truncate_second(punch_out))
    end = shift_end_on_date(date_str, shift_start, shift_end)
    mins = int((pout - end).total_seconds() // 60)
    return mins if mins >= 30 else 0


def compute_half_day(work_hours: Optional[float]) -> bool:
    """R5: true when rounded work_hours < 4.50."""
    if work_hours is None:
        return False
    return work_hours < 4.50


def month_range(month: str) -> tuple[str, str]:
    y, mo = map(int, month.split("-"))
    last = calendar.monthrange(y, mo)[1]
    return f"{y:04d}-{mo:02d}-01", f"{y:04d}-{mo:02d}-{last:02d}"


def working_days_in_month(month: str, joined_on: str) -> int:
    """R7: Mon–Fri between month start (or joined_on) and month end."""
    start, end = month_range(month)
    if joined_on > end:
        return 0
    eff = max(start, joined_on)
    y1, m1, d1 = map(int, eff.split("-"))
    y2, m2, d2 = map(int, end.split("-"))
    cur = date(y1, m1, d1)
    last = date(y2, m2, d2)
    count = 0
    while cur <= last:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


def recompute_derived(
    status: str,
    date_str: str,
    shift_start: str,
    shift_end: str,
    punch_in: Optional[datetime],
    punch_out: Optional[datetime],
) -> dict[str, Any]:
    if status in ("ABSENT", "LEAVE"):
        return {
            "punch_in": None,
            "punch_out": None,
            "work_hours": None,
            "late_minutes": 0,
            "overtime_minutes": 0,
            "half_day": False,
        }
    if punch_in is None:
        raise ValueError("presence status needs punch_in")
    pin = truncate_second(punch_in)
    late = compute_late_minutes(pin, date_str, shift_start)
    if punch_out is None:
        return {
            "punch_in": pin,
            "punch_out": None,
            "work_hours": None,
            "late_minutes": late,
            "overtime_minutes": 0,
            "half_day": False,
        }
    pout = truncate_second(punch_out)
    wh = compute_work_hours(pin, pout)
    return {
        "punch_in": pin,
        "punch_out": pout,
        "work_hours": wh,
        "late_minutes": late,
        "overtime_minutes": compute_overtime_minutes(pout, date_str, shift_start, shift_end),
        "half_day": compute_half_day(wh),
    }


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def serialize_employee(doc: dict) -> dict:
    return {
        "emp_code": doc["emp_code"],
        "name": doc["name"],
        "email": doc["email"],
        "department": doc["department"],
        "shift_start": doc["shift_start"],
        "shift_end": doc["shift_end"],
        "joined_on": doc["joined_on"],
        "created_at": dt_to_ms(doc["created_at"]),
    }


def serialize_history_entry(entry: dict) -> dict:
    changes_out = {}
    for key, pair in entry.get("changes", {}).items():
        if key in ("punch_in", "punch_out"):
            changes_out[key] = {
                "from": dt_to_ms(pair.get("from")),
                "to": dt_to_ms(pair.get("to")),
            }
        else:
            changes_out[key] = {"from": pair.get("from"), "to": pair.get("to")}
    return {
        "at": dt_to_ms(entry["at"]),
        "by": entry["by"],
        "reason": entry["reason"],
        "changes": changes_out,
    }


def serialize_attendance(doc: dict) -> dict:
    history = doc.get("history") or []
    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": dt_to_ms(doc.get("punch_in")),
        "punch_out": dt_to_ms(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": int(doc.get("late_minutes") or 0),
        "overtime_minutes": int(doc.get("overtime_minutes") or 0),
        "half_day": bool(doc.get("half_day", False)),
        "history": [serialize_history_entry(h) for h in history],
    }


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
def validate_epoch_ms(v: Optional[int], field_name: str) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{field_name} must be an integer millisecond timestamp")
    if v < EPOCH_MIN or v > EPOCH_MAX:
        raise ValueError(f"{field_name} out of allowed range")
    return v


class EmployeeIn(BaseModel):
    emp_code: str
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120)
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code")
    @classmethod
    def emp_code_format(cls, v: str) -> str:
        if not EMP_CODE_RE.match(v):
            raise ValueError("emp_code must match EMP####")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid email")
        return v

    @field_validator("shift_start", "shift_end")
    @classmethod
    def shift_format(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("shift time must be HH:MM")
        return v

    @model_validator(mode="after")
    def shifts_differ(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at")
    @classmethod
    def punched_at_ms(cls, v):
        return validate_epoch_ms(v, "punched_at")

    @field_validator("status")
    @classmethod
    def status_allowed(cls, v: str) -> str:
        if v not in PRESENCE_STATUSES:
            raise ValueError("invalid punch-in status")
        return v


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at")
    @classmethod
    def punched_at_ms(cls, v):
        return validate_epoch_ms(v, "punched_at")


class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("punch_in", "punch_out")
    @classmethod
    def epoch_fields(cls, v, info):
        return validate_epoch_ms(v, info.field_name)

    @field_validator("status")
    @classmethod
    def status_val(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALL_STATUSES:
            raise ValueError("invalid status")
        return v


# --------------------------------------------------------------------------- #
# Startup: indexes (idempotent)
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def ensure_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="ux_emp_code")
    db.employees.create_index(
        [("department", ASCENDING), ("joined_on", ASCENDING)], name="ix_dept_joined"
    )
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="ux_emp_date"
    )
    db.attendance_logs.create_index(
        [("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_date_emp"
    )
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="ix_emp_punch_in"
    )
    db.attendance_logs.create_index([("date", ASCENDING)], name="ix_date")


# --------------------------------------------------------------------------- #
# Query builders (shared with /admin/explain)
# --------------------------------------------------------------------------- #
def attendance_list_pipeline(
    emp_code: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    status: Optional[str],
    page: int,
    page_size: int,
    count_only: bool = False,
) -> list[dict]:
    match: dict[str, Any] = {}
    if emp_code:
        match["emp_code"] = emp_code
    if status:
        match["status"] = status
    if date_from or date_to:
        match["date"] = {}
        if date_from:
            match["date"]["$gte"] = date_from
        if date_to:
            match["date"]["$lte"] = date_to
    pipeline: list[dict] = []
    if match:
        pipeline.append({"$match": match})
    if count_only:
        pipeline.append({"$count": "total"})
        return pipeline
    pipeline.extend(
        [
            {"$sort": {"date": -1, "emp_code": 1}},
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
        ]
    )
    return pipeline


def employee_monthly_pipeline(emp_code: str, month: str) -> list[dict]:
    start, end = month_range(month)
    return employee_monthly_log_pipeline(emp_code, start, end)


def _weekday_present_expr(root: Optional[str] = None) -> dict:
    """Mongo expression: present-day credit (0, 0.5, or 1) from one log document."""
    if root:
        status = f"${root}.status"
        date_f = f"${root}.date"
        half = f"${root}.half_day"
    else:
        status, date_f, half = "$status", "$date", "$half_day"
    dow = {"$dayOfWeek": {"$dateFromString": {"dateString": date_f, "timezone": "+05:30"}}}
    weekday = {"$and": [{"$gte": [dow, 2]}, {"$lte": [dow, 6]}]}
    return {
        "$cond": [
            {"$in": [status, list(PRESENCE_STATUSES)]},
            {
                "$cond": [
                    weekday,
                    {"$cond": [{"$eq": [{"$ifNull": [half, False]}, True]}, 0.5, 1.0]},
                    0,
                ]
            },
            0,
        ]
    }


def department_summary_pipeline(month: str, department: Optional[str]) -> list[dict]:
    _, month_end = month_range(month)
    start, end = month_range(month)
    match: dict[str, Any] = {"joined_on": {"$lte": month_end}}
    if department:
        match["department"] = department
    return [
        {"$match": match},
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "emp_codes": {"$push": "$emp_code"},
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"codes": "$emp_codes"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$in": ["$emp_code", "$$codes"]},
                                    {"$gte": ["$date", start]},
                                    {"$lte": ["$date", end]},
                                ]
                            }
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$_id",
                "headcount": {"$first": "$headcount"},
                "present_days": {"$sum": _weekday_present_expr("logs")},
                "avg_work_hours": {
                    "$avg": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$logs", None]},
                                    {"$in": ["$logs.status", list(PRESENCE_STATUSES)]},
                                    {"$ne": ["$logs.work_hours", None]},
                                ]
                            },
                            "$logs.work_hours",
                            "$$REMOVE",
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$logs", None]},
                                    {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {
                        "$cond": [
                            {"$ne": ["$logs", None]},
                            {"$ifNull": ["$logs.late_minutes", 0]},
                            0,
                        ]
                    }
                },
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]


def run_department_summary(month: str, department: Optional[str]) -> dict:
    rows = list(db.employees.aggregate(department_summary_pipeline(month, department)))
    items = []
    for row in rows:
        avg = row.get("avg_work_hours")
        items.append(
            {
                "department": row["_id"],
                "headcount": int(row["headcount"]),
                "present_days": float(row.get("present_days") or 0),
                "avg_work_hours": round_half_up(avg, 2) if avg is not None else None,
                "late_count": int(row.get("late_count") or 0),
                "total_late_minutes": int(row.get("total_late_minutes") or 0),
                "leave_count": int(row.get("leave_count") or 0),
                "on_duty_count": int(row.get("on_duty_count") or 0),
            }
        )
    return {"month": month, "items": items}


def employee_monthly_log_pipeline(emp_code: str, start: str, end: str) -> list[dict]:
    return [
        {"$match": {"emp_code": emp_code, "date": {"$gte": start, "$lte": end}}},
        {
            "$group": {
                "_id": None,
                "present_days": {"$sum": _weekday_present_expr()},
                "leave_days": {
                    "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
            }
        },
    ]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    return serialize_employee(doc)


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q: dict[str, Any] = {}
    if department:
        q["department"] = department
    total = db.employees.count_documents(q)
    skip = (page - 1) * page_size
    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", ASCENDING)
        .skip(skip)
        .limit(page_size)
    )
    return {
        "items": [serialize_employee(d) for d in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = ms_to_dt(body.punched_at) if body.punched_at else truncate_second(datetime.now(timezone.utc))
    d = attendance_date_for_punch(ts, emp["shift_start"], emp["shift_end"])
    late = compute_late_minutes(ts, d, emp["shift_start"])
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")
    return serialize_attendance(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = ms_to_dt(body.punched_at) if body.punched_at else truncate_second(datetime.now(timezone.utc))

    candidate = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts},
            "punch_out": None,
        },
        sort=[("punch_in", DESCENDING)],
    )
    if not candidate:
        raise HTTPException(404, "no open punch-in found")

    pin = candidate["punch_in"]
    if ts <= pin:
        raise HTTPException(422, "punch_out must be after punch_in")
    if (ts - pin).total_seconds() > 24 * 3600:
        raise HTTPException(422, "punch_out too far after punch_in")

    derived = recompute_derived(
        candidate["status"],
        candidate["date"],
        emp["shift_start"],
        emp["shift_end"],
        pin,
        ts,
    )
    updated = db.attendance_logs.find_one_and_update(
        {"_id": candidate["_id"], "punch_out": None},
        {"$set": derived},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(409, "already punched out")
    return serialize_attendance(updated)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be <= date_to")

    match: dict[str, Any] = {}
    if emp_code:
        match["emp_code"] = emp_code
    if status:
        match["status"] = status
    if date_from or date_to:
        match["date"] = {}
        if date_from:
            match["date"]["$gte"] = date_from
        if date_to:
            match["date"]["$lte"] = date_to

    total = db.attendance_logs.count_documents(match)
    pipeline = attendance_list_pipeline(
        emp_code, date_from, date_to, status, page, page_size, count_only=False
    )
    items = [serialize_attendance(d) for d in db.attendance_logs.aggregate(pipeline)]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _values_differ(a, b) -> bool:
    if isinstance(a, datetime) and isinstance(b, datetime):
        return truncate_second(a) != truncate_second(b)
    return a != b


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    rec = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not rec:
        raise HTTPException(404, "attendance record not found")

    if body.status in ("ABSENT", "LEAVE") and (body.punch_in is not None or body.punch_out is not None):
        raise HTTPException(422, "cannot set punch times with ABSENT or LEAVE")

    new_status = body.status if body.status is not None else rec["status"]
    new_pin = ms_to_dt(body.punch_in) if body.punch_in is not None else rec.get("punch_in")
    new_pout = ms_to_dt(body.punch_out) if body.punch_out is not None else rec.get("punch_out")

    if new_status in PRESENCE_STATUSES and new_pin is None:
        raise HTTPException(422, "presence status requires punch_in")

    if new_pin is not None and new_status in PRESENCE_STATUSES:
        if attendance_date_for_punch(new_pin, emp["shift_start"], emp["shift_end"]) != date:
            raise HTTPException(422, "punch_in must fall on the record attendance date")

    if new_pin and new_pout:
        if new_pout <= new_pin:
            raise HTTPException(422, "punch_out must be after punch_in")
        if (new_pout - new_pin).total_seconds() > 24 * 3600:
            raise HTTPException(422, "punch_out too far after punch_in")

    old_snapshot = {
        "status": rec["status"],
        "punch_in": rec.get("punch_in"),
        "punch_out": rec.get("punch_out"),
        "work_hours": rec.get("work_hours"),
        "late_minutes": int(rec.get("late_minutes") or 0),
        "overtime_minutes": int(rec.get("overtime_minutes") or 0),
        "half_day": bool(rec.get("half_day", False)),
    }

    derived = recompute_derived(
        new_status, date, emp["shift_start"], emp["shift_end"], new_pin, new_pout
    )
    new_snapshot = {
        "status": new_status,
        **derived,
    }

    changes: dict[str, dict] = {}
    for field in (
        "status",
        "punch_in",
        "punch_out",
        "work_hours",
        "late_minutes",
        "overtime_minutes",
        "half_day",
    ):
        if _values_differ(old_snapshot[field], new_snapshot[field]):
            fr = old_snapshot[field]
            to = new_snapshot[field]
            if field in ("punch_in", "punch_out"):
                changes[field] = {"from": fr, "to": to}
            else:
                changes[field] = {"from": fr, "to": to}

    if not changes:
        raise HTTPException(422, "no changes")

    hist_len = len(rec.get("history") or [])
    entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }
    update_set = {
        "status": new_status,
        **derived,
    }
    updated = db.attendance_logs.find_one_and_update(
        {"_id": rec["_id"], "$expr": {"$eq": [{"$size": {"$ifNull": ["$history", []]}}, hist_len]}},
        {"$set": update_set, "$push": {"history": entry}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(409, "concurrent correction conflict")
    return serialize_attendance(updated)


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(...)):
    if not MONTH_RE.match(month):
        raise HTTPException(422, "invalid month")
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")

    start, end = month_range(month)
    wd = working_days_in_month(month, emp["joined_on"])
    agg = list(db.attendance_logs.aggregate(employee_monthly_log_pipeline(emp_code, start, end)))
    if agg:
        row = agg[0]
        present = float(row.get("present_days") or 0)
        leave_days = int(row.get("leave_days") or 0)
        late_count = int(row.get("late_count") or 0)
        total_late = int(row.get("total_late_minutes") or 0)
        total_ot = int(row.get("total_overtime_minutes") or 0)
    else:
        present = leave_days = late_count = total_late = total_ot = 0

    pct = None
    if wd > 0:
        pct = round_half_up((present / wd) * 100.0, 2)

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": wd,
        "present_days": present,
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late,
        "total_overtime_minutes": total_ot,
        "attendance_pct": pct,
    }


@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(...), department: Optional[str] = None):
    if not MONTH_RE.match(month):
        raise HTTPException(422, "invalid month")
    return run_department_summary(month, department)


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    if not MONTH_RE.match(month):
        raise HTTPException(422, "invalid month")
    start, end = month_range(month)

    emp_q: dict[str, Any] = {}
    if department:
        emp_q["department"] = department
    emp_map = {e["emp_code"]: e for e in db.employees.find(emp_q)}

    pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}}},
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]
                    }
                },
            }
        },
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
    ]
    rows = list(db.attendance_logs.aggregate(pipeline))

    ranked: list[dict] = []
    rank = 0
    prev_total = None
    position = 0
    for row in rows:
        code = row["_id"]
        if code not in emp_map:
            continue
        position += 1
        total = int(row["total_late_minutes"])
        if prev_total is None or total != prev_total:
            rank = position
            prev_total = total
        ranked.append(
            {
                "rank": rank,
                "emp_code": code,
                "name": emp_map[code]["name"],
                "department": emp_map[code]["department"],
                "total_late_minutes": total,
                "late_count": int(row["late_count"]),
            }
        )

    items = [r for r in ranked if r["rank"] <= limit]
    return {"month": month, "items": items}


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    if to_date < from_date:
        raise HTTPException(422, "to must be >= from")
    d0 = date.fromisoformat(from_date)
    d1 = date.fromisoformat(to_date)
    if (d1 - d0).days > 91:
        raise HTTPException(422, "date range exceeds 92 days")

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(404, "department not found")

    codes = [
        e["emp_code"]
        for e in db.employees.find({"department": department}, {"emp_code": 1})
    ]

    log_rows = list(
        db.attendance_logs.aggregate(
            [
                {
                    "$match": {
                        "emp_code": {"$in": codes},
                        "date": {"$gte": from_date, "$lte": to_date},
                    }
                },
                {
                    "$group": {
                        "_id": "$date",
                        "present_count": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", list(PRESENCE_STATUSES)]},
                                    {"$cond": ["$half_day", 0.5, 1.0]},
                                    0,
                                ]
                            }
                        },
                        "late_count": {
                            "$sum": {
                                "$cond": [
                                    {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                                    1,
                                    0,
                                ]
                            }
                        },
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    )
    by_date = {r["_id"]: r for r in log_rows}

    employees = list(
        db.employees.find({"department": department}, {"emp_code": 1, "joined_on": 1})
    )

    def headcount_on(day_str: str) -> int:
        return sum(1 for e in employees if e["joined_on"] <= day_str)

    items: list[dict] = []
    cur = d0
    while cur <= d1:
        ds = cur.isoformat()
        working = cur.weekday() < 5
        hc = headcount_on(ds)
        agg = by_date.get(ds, {})
        present = float(agg.get("present_count", 0))
        late = int(agg.get("late_count", 0))
        rate = None
        if working and hc > 0:
            rate = round_half_up(present / hc, 4)
        items.append(
            {
                "date": ds,
                "is_working_day": working,
                "headcount": hc,
                "present_count": present,
                "late_count": late,
                "attendance_rate": rate,
                "moving_avg_7d": None,
            }
        )
        cur += timedelta(days=1)

    for i, row in enumerate(items):
        rates = []
        for j in range(max(0, i - 6), i + 1):
            if items[j]["attendance_rate"] is not None:
                rates.append(items[j]["attendance_rate"])
        if rates:
            row["moving_avg_7d"] = round_half_up(sum(rates) / len(rates), 4)

    return {"department": department, "items": items}


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: Literal[
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    ],
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if endpoint == "attendance_list":
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must be <= date_to")
        pipeline = attendance_list_pipeline(
            emp_code, date_from, date_to, status, page, page_size, count_only=False
        )
        coll = db.attendance_logs
        explain = coll.aggregate(pipeline).explain()
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explain}

    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month required")
        pipeline = employee_monthly_pipeline(emp_code, month)
        explain = db.attendance_logs.aggregate(pipeline).explain()
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explain}

    if endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "month required")
        pipeline = department_summary_pipeline(month, department)
        explain = db.employees.aggregate(pipeline).explain()
        return {"endpoint": endpoint, "collection": "employees", "explain": explain}

    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "month required")
        start, end = month_range(month)
        pipeline = [
            {"$match": {"date": {"$gte": start, "$lte": end}}},
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                }
            },
            {"$match": {"total_late_minutes": {"$gt": 0}}},
            {"$sort": {"total_late_minutes": -1, "_id": 1}},
        ]
        explain = db.attendance_logs.aggregate(pipeline).explain()
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explain}

    if endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(422, "department, from and to required")
        codes = [
            e["emp_code"]
            for e in db.employees.find({"department": department}, {"emp_code": 1})
        ]
        pipeline = [
            {
                "$match": {
                    "emp_code": {"$in": codes},
                    "date": {"$gte": from_date, "$lte": to_date},
                }
            },
            {"$group": {"_id": "$date", "present_count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        explain = db.attendance_logs.aggregate(pipeline).explain()
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": explain}

    raise HTTPException(422, "unknown endpoint")
