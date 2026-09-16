import hashlib
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update, text
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal
from .main import require_authenticated_user, require_teacher
from .models import Attendance, AuditLog, ClassSession, CourseClass, Enrollment, Student
from .models import DemoChallenge, DemoRelay

router = APIRouter(prefix="/api/demo")


def get_db():
    db = SessionLocal()
    try:
        if db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def now_ms():
    return int(time.time() * 1000)


def enrolled(db, student_id, class_id):
    student = db.get(Student, student_id)
    return bool(student and (student.class_id == class_id or db.scalar(select(Enrollment.enrollment_id).where(
        Enrollment.student_id == student_id, Enrollment.class_id == class_id))))


def session_for(db, session_id, user, active=False):
    session = db.get(ClassSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if user["role"] == "student":
        if not enrolled(db, user["sub"], session.class_id):
            raise HTTPException(403, "Not enrolled in this class")
    elif user["role"] != "admin" and session.teacher_id != user["sub"]:
        raise HTTPException(403, "Session belongs to another teacher")
    if active and (session.status != "ACTIVE" or session.expiration_time <= now_ms()):
        raise HTTPException(409, "Session is closed or expired")
    return session


def log(db, user, event, detail):
    db.add(AuditLog(log_id=uuid.uuid4().hex, timestamp=now_ms(), event_type=event,
                    operator_id=user["sub"], details=detail))


def session_data(s):
    return {"session_id": s.session_id, "class_id": s.class_id, "subject": s.subject,
            "teacher_id": s.teacher_id, "status": "EXPIRED" if s.status == "ACTIVE" and s.expiration_time <= now_ms() else s.status,
            "expiration_time": s.expiration_time, "mode": "SIMULATION"}


class StartIn(BaseModel):
    class_id: str = Field(min_length=1, max_length=32)
    duration_seconds: int = Field(default=600, ge=10, le=3600)


class ChallengeIn(BaseModel):
    position: str = Field(pattern="^(near|back|outside)$")
    relay_student_id: str | None = Field(default=None, max_length=32)


class ProofIn(BaseModel):
    challenge_id: str = Field(min_length=32, max_length=32)
    response: str = Field(min_length=64, max_length=64)


class RelayIn(BaseModel):
    enabled: bool
    position: str = Field(default="near", pattern="^(near|back|outside)$")


@router.get("/profile")
def profile(user=Depends(require_authenticated_user), db=Depends(get_db)):
    result = {"user_id": user["sub"], "role": user["role"], "mode": "SIMULATION"}
    if user["role"] == "student":
        student = db.get(Student, user["sub"])
        if not student:
            raise HTTPException(401, "Account no longer exists")
        result.update(name=student.name, device_id=student.registered_device_id)
    return result


@router.get("/classes")
def classes(user=Depends(require_authenticated_user), db=Depends(get_db)):
    rows = db.scalars(select(CourseClass)).all()
    return [{"class_id": c.class_id, "class_name": c.class_name, "subject": c.subject,
             "class_code": c.class_code or c.class_id} for c in rows
            if user["role"] == "admin" or
            (user["role"] == "teacher" and c.teacher_id == user["sub"]) or
            (user["role"] == "student" and enrolled(db, user["sub"], c.class_id))]


@router.get("/sessions")
def sessions(user=Depends(require_authenticated_user), db=Depends(get_db)):
    rows = db.scalars(select(ClassSession).where(ClassSession.session_id.like("demo_%")).order_by(ClassSession.start_time.desc())).all()
    return [session_data(s) for s in rows if user["role"] == "admin" or
            (user["role"] == "teacher" and s.teacher_id == user["sub"]) or
            (user["role"] == "student" and enrolled(db, user["sub"], s.class_id))]


@router.post("/sessions")
def start(item: StartIn, user=Depends(require_teacher), db=Depends(get_db)):
    course = db.get(CourseClass, item.class_id.strip().upper())
    if not course:
        raise HTTPException(404, "Class not found")
    if user["role"] != "admin" and course.teacher_id != user["sub"]:
        raise HTTPException(403, "Class belongs to another teacher")
    if db.scalar(select(ClassSession.session_id).where(ClassSession.class_id == course.class_id,
            ClassSession.status == "ACTIVE", ClassSession.expiration_time > now_ms())):
        raise HTTPException(409, "Class already has an active session")
    stamp = now_ms()
    session = ClassSession(session_id="demo_" + uuid.uuid4().hex, class_id=course.class_id,
        teacher_id=course.teacher_id, subject=course.subject, start_time=stamp,
        expiration_time=stamp + item.duration_seconds * 1000, random_nonce=secrets.token_hex(16), status="ACTIVE")
    db.add(session)
    log(db, user, "DEMO_SESSION_START", session.session_id)
    db.commit()
    return session_data(session)


@router.get("/sessions/{session_id}/attendance")
def attendance(session_id: str, user=Depends(require_authenticated_user), db=Depends(get_db)):
    session = session_for(db, session_id, user)
    students = db.scalars(select(Student).order_by(Student.student_id)).all()
    records = {a.student_id: a for a in db.scalars(select(Attendance).where(Attendance.session_id == session_id)).all()}
    return [{"student_id": s.student_id, "name": s.name,
             "status": records[s.student_id].verification_status if s.student_id in records else "NOT_VERIFIED",
             "route": records[s.student_id].route_type if s.student_id in records else None,
             "rssi": records[s.student_id].rssi_evidence if s.student_id in records else None}
            for s in students if enrolled(db, s.student_id, session.class_id)
            and (user["role"] != "student" or s.student_id == user["sub"])]


@router.post("/sessions/{session_id}/relay")
def relay(session_id: str, item: RelayIn, user=Depends(require_authenticated_user), db=Depends(get_db)):
    session_for(db, session_id, user, active=True)
    if user["role"] != "student":
        raise HTTPException(403, "Student role required")
    key = session_id + ":" + user["sub"]
    row = db.get(DemoRelay, key)
    if not row:
        row = DemoRelay(relay_id=key, session_id=session_id, student_id=user["sub"])
        db.add(row)
    row.enabled = item.enabled
    row.position = item.position
    db.commit()
    return {"enabled": row.enabled, "mode": "SIMULATION"}


@router.get("/sessions/{session_id}/relays")
def relays(session_id: str, user=Depends(require_authenticated_user), db=Depends(get_db)):
    session_for(db, session_id, user, active=True)
    return [r.student_id for r in db.scalars(select(DemoRelay).where(DemoRelay.session_id == session_id,
        DemoRelay.enabled.is_(True), DemoRelay.position != "outside")).all() if r.student_id != user["sub"]]


@router.post("/sessions/{session_id}/challenge")
def challenge(session_id: str, item: ChallengeIn, user=Depends(require_authenticated_user), db=Depends(get_db)):
    session = session_for(db, session_id, user, active=True)
    if user["role"] != "student":
        raise HTTPException(403, "Student role required")
    if db.scalar(select(Attendance.attendance_id).where(Attendance.session_id == session_id, Attendance.student_id == user["sub"])):
        raise HTTPException(409, "Attendance already recorded")
    if item.relay_student_id:
        r = db.get(DemoRelay, session_id + ":" + item.relay_student_id)
        if not r or not r.enabled or r.position == "outside" or r.student_id == user["sub"] or not enrolled(db, r.student_id, session.class_id):
            raise HTTPException(409, "Selected relay is unavailable")
    elif item.position == "outside":
        raise HTTPException(409, "Simulated direct signal is below threshold; enable a classmate relay")
    db.execute(update(DemoChallenge).where(DemoChallenge.session_id == session_id,
        DemoChallenge.student_id == user["sub"]).values(used=True))
    nonce = secrets.token_hex(32)
    row = DemoChallenge(challenge_id=uuid.uuid4().hex, session_id=session_id, student_id=user["sub"],
        expected_hash=hashlib.sha256(nonce.encode()).hexdigest(), expires_at=min(now_ms() + 30000, session.expiration_time),
        used=False, relay_student_id=item.relay_student_id, rssi=-74 if item.relay_student_id or item.position == "back" else -56)
    db.add(row)
    db.commit()
    return {"challenge_id": row.challenge_id, "nonce": nonce, "expires_at": row.expires_at,
            "mode": "SIMULATION", "proof": "SHA256(nonce); demonstrates challenge lifecycle, not hardware attestation"}


@router.post("/sessions/{session_id}/verify")
def verify(session_id: str, item: ProofIn, user=Depends(require_authenticated_user), db=Depends(get_db)):
    session_for(db, session_id, user, active=True)
    if user["role"] != "student":
        raise HTTPException(403, "Student role required")
    row = db.get(DemoChallenge, item.challenge_id)
    if not row or row.session_id != session_id or row.student_id != user["sub"]:
        raise HTTPException(400, "Challenge does not match this student and session")
    if row.used or row.expires_at <= now_ms():
        raise HTTPException(409, "Challenge is used or expired")
    if not secrets.compare_digest(row.expected_hash, item.response):
        row.used = True
        db.commit()
        raise HTTPException(400, "Invalid response; request a new challenge")
    if row.relay_student_id:
        relay_row = db.get(DemoRelay, session_id + ":" + row.relay_student_id)
        if not relay_row or not relay_row.enabled or relay_row.position == "outside":
            raise HTTPException(409, "Relay is no longer available")
    consumed = db.execute(update(DemoChallenge).where(DemoChallenge.challenge_id == row.challenge_id,
        DemoChallenge.used.is_(False), DemoChallenge.expires_at > now_ms()).values(used=True)).rowcount
    if consumed != 1:
        db.rollback()
        raise HTTPException(409, "Challenge already consumed")
    record = Attendance(attendance_id="demo_" + hashlib.sha256((session_id + ":" + user["sub"]).encode()).hexdigest()[:48],
        session_id=session_id, student_id=user["sub"], timestamp=now_ms(), verification_status="ELIGIBLE",
        route_type="RELAY" if row.relay_student_id else "DIRECT", rssi_evidence=row.rssi,
        hop_count=2 if row.relay_student_id else 0, via_student=row.relay_student_id, synced=True)
    db.add(record)
    log(db, user, "DEMO_ELIGIBLE", session_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Attendance already recorded")
    return {"status": "ELIGIBLE", "mode": "SIMULATION", "attendance_id": record.attendance_id}


@router.post("/sessions/{session_id}/finalize")
def finalize(session_id: str, user=Depends(require_teacher), db=Depends(get_db)):
    session = session_for(db, session_id, user)
    if session.status == "FINALIZED":
        return {"status": "FINALIZED", "updated": 0}
    changed = db.execute(update(Attendance).where(Attendance.session_id == session_id,
        Attendance.verification_status == "ELIGIBLE").values(verification_status="PRESENT", synced=True)).rowcount
    session.status = "FINALIZED"
    db.execute(update(DemoChallenge).where(DemoChallenge.session_id == session_id).values(used=True))
    db.execute(update(DemoRelay).where(DemoRelay.session_id == session_id).values(enabled=False))
    log(db, user, "DEMO_FINALIZED", session_id)
    db.commit()
    return {"status": "FINALIZED", "updated": changed}
