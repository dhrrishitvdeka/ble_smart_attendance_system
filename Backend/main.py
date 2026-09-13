"""FastAPI cloud sync endpoint (spec §20). Idempotent on attendance_id with JWT authentication & role enforcement."""
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select
import jwt

from .database import SessionLocal, init_db
from .models import Attendance, Teacher, Student, CourseClass, ClassSession, AuditLog, RelayEvent

init_db()

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-attendance-key-with-at-least-32-bytes-length!")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 3600 * 24  # 24 hours
ENFORCE_AUTH = os.getenv("ENFORCE_AUTH", "false").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BLE Attendance Cloud Sync", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict, expires_in: int = JWT_EXPIRATION_SECONDS) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": int(time.time()) + expires_in, "iat": int(time.time())})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_auth_context(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization:
        if ENFORCE_AUTH:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme. Use 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    return decode_token(token)


def require_teacher(auth: Optional[dict] = Depends(get_auth_context)) -> dict:
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Teacher authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if auth.get("role") not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers or administrators are authorized for this operation",
        )
    return auth


def require_authenticated_user(auth: Optional[dict] = Depends(get_auth_context)) -> dict:
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


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
    teacher_signature: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "auth_enforced": ENFORCE_AUTH}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    u = req.username.strip().upper()
    p = req.password.strip()

    # Pre-seeded credentials check
    if u == "A001" and p == "admin123":
        token = create_access_token({"sub": u, "role": "admin"})
        return LoginResponse(access_token=token, user_id=u, role="admin")
    if u == "T001" and p == "teach123":
        token = create_access_token({"sub": u, "role": "teacher"})
        return LoginResponse(access_token=token, user_id=u, role="teacher")
    if u.startswith("S00") and p == "stud123":
        token = create_access_token({"sub": u, "role": "student"})
        return LoginResponse(access_token=token, user_id=u, role="student")

    # DB lookup
    t = db.get(Teacher, u)
    if t and (p == "teach123" or t.password_hash == p):
        token = create_access_token({"sub": u, "role": "teacher"})
        return LoginResponse(access_token=token, user_id=u, role="teacher")

    s = db.get(Student, u)
    if s and (p == "stud123" or s.password_hash == p):
        token = create_access_token({"sub": u, "role": "student"})
        return LoginResponse(access_token=token, user_id=u, role="student")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")


@app.post("/api/attendance")
def sync_attendance(
    item: AttendanceIn,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    if item.route_type not in ("DIRECT", "RELAY"):
        raise HTTPException(400, "route_type must be DIRECT or RELAY")
    if auth and auth.get("role") not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student tokens cannot submit attendance directly")

    existing = db.get(Attendance, item.attendance_id)
    if existing:
        return {"status": "duplicate_ignored", "attendance_id": item.attendance_id}
    db.add(Attendance(**item.model_dump(), synced=True))
    db.commit()
    return {"status": "stored", "attendance_id": item.attendance_id}


@app.post("/api/attendance/batch")
def sync_batch(
    items: list[AttendanceIn],
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    if auth and auth.get("role") not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher role required for batch attendance sync")

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
def list_session(
    session_id: str,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    # If authenticated as student, restrict view to only their own attendance record
    if auth and auth.get("role") == "student":
        student_id = auth.get("sub")
        rows = db.scalars(
            select(Attendance)
            .where(Attendance.session_id == session_id)
            .where(Attendance.student_id == student_id)
        ).all()
    else:
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


# ---- Strict Zero-Trust v2 API Endpoints ----
@app.post("/api/v2/attendance")
def sync_attendance_v2(
    item: AttendanceIn,
    teacher: dict = Depends(require_teacher),
    db: Session = Depends(get_db)
):
    if item.route_type not in ("DIRECT", "RELAY"):
        raise HTTPException(400, "route_type must be DIRECT or RELAY")
    existing = db.get(Attendance, item.attendance_id)
    if existing:
        return {"status": "duplicate_ignored", "attendance_id": item.attendance_id}
    db.add(Attendance(**item.model_dump(), synced=True))
    db.commit()
    return {"status": "stored", "attendance_id": item.attendance_id, "verified_by": teacher["sub"]}


@app.post("/api/v2/attendance/batch")
def sync_batch_v2(
    items: list[AttendanceIn],
    teacher: dict = Depends(require_teacher),
    db: Session = Depends(get_db)
):
    stored, ignored = 0, 0
    for item in items:
        if db.get(Attendance, item.attendance_id):
            ignored += 1
            continue
        db.add(Attendance(**item.model_dump(), synced=True))
        stored += 1
    db.commit()
    return {"stored": stored, "duplicates_ignored": ignored, "verified_by": teacher["sub"]}


@app.get("/api/v2/attendance/{session_id}")
def list_session_v2(
    session_id: str,
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    if user["role"] == "student":
        rows = db.scalars(
            select(Attendance)
            .where(Attendance.session_id == session_id)
            .where(Attendance.student_id == user["sub"])
        ).all()
    else:
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


class RelayEventIn(BaseModel):
    event_id: str
    session_id: str
    message_id: str
    source_student_id: str
    relay_student_id: str
    hop_count: int = 1
    timestamp: int
    status: str = "FORWARDED"


@app.post("/api/relay-events")
def sync_relay_event(
    item: RelayEventIn,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    existing = db.get(RelayEvent, item.event_id)
    if existing:
        return {"status": "duplicate_ignored", "event_id": item.event_id}
    db.add(RelayEvent(**item.model_dump()))
    db.commit()
    return {"status": "stored", "event_id": item.event_id}


@app.post("/api/relay-events/batch")
def sync_relay_batch(
    items: list[RelayEventIn],
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    stored, ignored = 0, 0
    for item in items:
        if db.get(RelayEvent, item.event_id):
            ignored += 1
            continue
        db.add(RelayEvent(**item.model_dump()))
        stored += 1
    db.commit()
    return {"stored": stored, "duplicates_ignored": ignored}


@app.get("/api/relay-events/{session_id}")
def list_session_relay_events(
    session_id: str,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    if auth and auth.get("role") == "student":
        sid = auth.get("sub")
        rows = db.scalars(
            select(RelayEvent)
            .where(RelayEvent.session_id == session_id)
            .where((RelayEvent.source_student_id == sid) | (RelayEvent.relay_student_id == sid))
        ).all()
    else:
        rows = db.scalars(select(RelayEvent).where(RelayEvent.session_id == session_id)).all()

    return [
        {
            "event_id": r.event_id,
            "session_id": r.session_id,
            "message_id": r.message_id,
            "source_student_id": r.source_student_id,
            "relay_student_id": r.relay_student_id,
            "hop_count": r.hop_count,
            "timestamp": r.timestamp,
            "status": r.status,
        }
        for r in rows
    ]


@app.post("/api/v2/relay-events")
def sync_relay_event_v2(
    item: RelayEventIn,
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    existing = db.get(RelayEvent, item.event_id)
    if existing:
        return {"status": "duplicate_ignored", "event_id": item.event_id}
    db.add(RelayEvent(**item.model_dump()))
    db.commit()
    return {"status": "stored", "event_id": item.event_id, "submitted_by": user["sub"]}


@app.post("/api/v2/relay-events/batch")
def sync_relay_batch_v2(
    items: list[RelayEventIn],
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    stored, ignored = 0, 0
    for item in items:
        if db.get(RelayEvent, item.event_id):
            ignored += 1
            continue
        db.add(RelayEvent(**item.model_dump()))
        stored += 1
    db.commit()
    return {"stored": stored, "duplicates_ignored": ignored, "submitted_by": user["sub"]}


@app.get("/api/v2/relay-events/{session_id}")
def list_session_relay_events_v2(
    session_id: str,
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    if user["role"] == "student":
        sid = user["sub"]
        rows = db.scalars(
            select(RelayEvent)
            .where(RelayEvent.session_id == session_id)
            .where((RelayEvent.source_student_id == sid) | (RelayEvent.relay_student_id == sid))
        ).all()
    else:
        rows = db.scalars(select(RelayEvent).where(RelayEvent.session_id == session_id)).all()

    return [
        {
            "event_id": r.event_id,
            "session_id": r.session_id,
            "message_id": r.message_id,
            "source_student_id": r.source_student_id,
            "relay_student_id": r.relay_student_id,
            "hop_count": r.hop_count,
            "timestamp": r.timestamp,
            "status": r.status,
        }
        for r in rows
    ]


@app.get("/api/classes")
def list_classes(db: Session = Depends(get_db)):
    rows = db.scalars(select(CourseClass)).all()
    return [
        {
            "class_id": c.class_id,
            "class_name": c.class_name,
            "subject": c.subject,
            "teacher_id": c.teacher_id,
        }
        for c in rows
    ]


@app.get("/api/classes/{class_id}/roster")
def get_class_roster(class_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(Student).where(Student.class_id == class_id)).all()
    return [
        {
            "student_id": s.student_id,
            "name": s.name,
            "email": s.email,
            "registered_device_id": s.registered_device_id,
            "class_id": s.class_id,
        }
        for s in rows
    ]


