"""FastAPI cloud sync endpoint (spec §20). Idempotent on attendance_id."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from .database import SessionLocal, init_db
from .models import Attendance

init_db()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BLE Attendance Cloud Sync", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AttendanceIn(BaseModel):
    attendance_id: str
    session_id: str
    student_id: str
    timestamp: int
    verification_status: str
    route_type: str = "DIRECT"
    rssi_evidence: int | None = None
    hop_count: int = 0
    via_student: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/attendance")
def sync_attendance(item: AttendanceIn, db: Session = Depends(get_db)):
    if item.route_type not in ("DIRECT", "RELAY"):
        raise HTTPException(400, "route_type must be DIRECT or RELAY")
    existing = db.get(Attendance, item.attendance_id)
    if existing:
        return {"status": "duplicate_ignored", "attendance_id": item.attendance_id}
    db.add(Attendance(**item.model_dump(), synced=True))
    db.commit()
    return {"status": "stored", "attendance_id": item.attendance_id}


@app.post("/api/attendance/batch")
def sync_batch(items: list[AttendanceIn], db: Session = Depends(get_db)):
    stored, ignored = 0, 0
    for item in items:
        if db.get(Attendance, item.attendance_id):
            ignored += 1
            continue
        db.add(Attendance(**item.model_dump(), synced=True))
        stored += 1
    db.commit()
    return {"stored": stored, "duplicates_ignored": ignored}


@app.get("/api/attendance/{session_id}")
def list_session(session_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(Attendance).where(Attendance.session_id == session_id)).all()
    return [
        {
            "attendance_id": r.attendance_id,
            "student_id": r.student_id,
            "verification_status": r.verification_status,
            "route_type": r.route_type,
        }
        for r in rows
    ]
