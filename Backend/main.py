"""FastAPI cloud sync endpoint (spec §20). Idempotent on attendance_id with JWT authentication & role enforcement."""
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
import jwt

from .database import SessionLocal, init_db
from .models import Administrator, Attendance, Teacher, Student, CourseClass, ClassSession, AuditLog, RelayEvent, Enrollment
from .security import hash_password, verify_password

init_db()

JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 3600 * 24  # 24 hours
ENFORCE_AUTH = os.getenv("ENFORCE_AUTH", "true").lower() in ("true", "1")

ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500").split(",") if o.strip()
]

MAX_BATCH_SIZE = 500
ATTENDANCE_ID_MAX = 64
SESSION_ID_MAX = 64
STUDENT_ID_MAX = 32
TIMESTAMP_MIN = 0
TIMESTAMP_MAX = 4102444800000  # 2100-01-01
RSSI_MIN, RSSI_MAX = -127, 0
HOP_MAX = 2


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BLE Attendance Cloud Sync", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
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
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "iat", "sub", "role"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if claims.get("role") not in ("student", "teacher", "admin"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return claims


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
    attendance_id: str = Field(min_length=1, max_length=ATTENDANCE_ID_MAX)
    session_id: str = Field(min_length=1, max_length=SESSION_ID_MAX)
    student_id: str = Field(min_length=1, max_length=STUDENT_ID_MAX)
    timestamp: int = Field(ge=TIMESTAMP_MIN, le=TIMESTAMP_MAX)
    verification_status: str
    route_type: str = "DIRECT"
    rssi_evidence: int | None = Field(default=None, ge=RSSI_MIN, le=RSSI_MAX)
    hop_count: int = Field(default=0, ge=0, le=HOP_MAX)
    via_student: str | None = Field(default=None, max_length=128)
    teacher_signature: str | None = Field(default=None, max_length=256)


class ClassCreate(BaseModel):
    class_id: str
    class_name: str
    subject: str
    teacher_id: Optional[str] = None
    class_code: Optional[str] = None


class JoinClassRequest(BaseModel):
    student_id: Optional[str] = None
    class_code: str


@app.get("/health")
def health():
    return {"ok": True, "auth_enforced": ENFORCE_AUTH}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    u = req.username.strip().upper()
    p = req.password

    admin = db.get(Administrator, u)
    if admin and verify_password(p, admin.password_hash):
        token = create_access_token({"sub": u, "role": "admin"})
        return LoginResponse(access_token=token, user_id=u, role="admin")

    t = db.get(Teacher, u)
    if t and verify_password(p, t.password_hash):
        token = create_access_token({"sub": u, "role": "teacher"})
        return LoginResponse(access_token=token, user_id=u, role="teacher")

    s = db.get(Student, u)
    if s and verify_password(p, s.password_hash):
        token = create_access_token({"sub": u, "role": "student"})
        return LoginResponse(access_token=token, user_id=u, role="student")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")


@app.post("/api/attendance")
def sync_attendance(
    item: AttendanceIn,
    auth: dict = Depends(require_teacher),
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
    auth: dict = Depends(require_teacher),
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
        db.flush()
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
        db.flush()
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
    event_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=SESSION_ID_MAX)
    message_id: str = Field(min_length=1, max_length=64)
    source_student_id: str = Field(min_length=1, max_length=STUDENT_ID_MAX)
    relay_student_id: str = Field(min_length=1, max_length=STUDENT_ID_MAX)
    hop_count: int = Field(default=1, ge=0, le=HOP_MAX)
    timestamp: int = Field(ge=TIMESTAMP_MIN, le=TIMESTAMP_MAX)
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
            "class_code": c.class_code or c.class_id,
        }
        for c in rows
    ]


@app.post("/api/classes")
def create_class(
    item: ClassCreate,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    if auth:
        role = auth.get("role")
        if role not in ("teacher", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only teachers or administrators are authorized to create classes"
            )
    elif ENFORCE_AUTH:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cid = item.class_id.strip().upper() if item.class_id else ""
    if not cid:
        raise HTTPException(status_code=400, detail="Class ID cannot be empty")
    if len(cid) > 32:
        raise HTTPException(status_code=400, detail="Class ID cannot exceed 32 characters")

    cname = item.class_name.strip() if item.class_name else ""
    if not cname:
        raise HTTPException(status_code=400, detail="Class name cannot be empty")
    if len(cname) > 128:
        raise HTTPException(status_code=400, detail="Class name cannot exceed 128 characters")

    subj = item.subject.strip() if item.subject else ""
    if not subj:
        raise HTTPException(status_code=400, detail="Subject cannot be empty")
    if len(subj) > 128:
        raise HTTPException(status_code=400, detail="Subject cannot exceed 128 characters")

    tid = item.teacher_id.strip().upper() if item.teacher_id and item.teacher_id.strip() else None
    if tid:
        if len(tid) > 32:
            raise HTTPException(status_code=400, detail="Teacher ID cannot exceed 32 characters")
        teacher = db.get(Teacher, tid)
        if not teacher:
            raise HTTPException(status_code=400, detail=f"Teacher ID '{tid}' not found in registry")

    code = (item.class_code.strip().upper() if item.class_code and item.class_code.strip() else cid)
    if len(code) > 32:
        raise HTTPException(status_code=400, detail="Class code cannot exceed 32 characters")

    existing = db.get(CourseClass, cid)
    if existing:
        raise HTTPException(status_code=400, detail=f"Class ID '{cid}' already exists")

    # Check if class_code already in use
    code_exists = db.scalars(
        select(CourseClass).where((CourseClass.class_code.ilike(code)) | (CourseClass.class_id.ilike(code)))
    ).first()
    if code_exists:
        raise HTTPException(status_code=400, detail=f"Class code '{code}' is already in use by class '{code_exists.class_id}'")

    new_class = CourseClass(
        class_id=cid,
        class_name=cname,
        subject=subj,
        teacher_id=tid,
        class_code=code,
    )
    db.add(new_class)
    db.commit()
    return {
        "class_id": new_class.class_id,
        "class_name": new_class.class_name,
        "subject": new_class.subject,
        "teacher_id": new_class.teacher_id,
        "class_code": new_class.class_code,
    }


@app.get("/api/classes/code/{class_code}")
def get_class_by_code(class_code: str, db: Session = Depends(get_db)):
    code = class_code.strip().upper() if class_code else ""
    if not code:
        raise HTTPException(status_code=400, detail="Class code cannot be empty")
    course = db.scalars(
        select(CourseClass).where((CourseClass.class_code.ilike(code)) | (CourseClass.class_id.ilike(code)))
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"No class found with code '{code}'")
    return {
        "class_id": course.class_id,
        "class_name": course.class_name,
        "subject": course.subject,
        "teacher_id": course.teacher_id,
        "class_code": course.class_code or course.class_id,
    }


@app.post("/api/classes/join")
def join_class_by_code(
    req: JoinClassRequest,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    student_id = (auth.get("sub") if auth else None) or (req.student_id.strip().upper() if req.student_id and req.student_id.strip() else None)
    if not student_id:
        raise HTTPException(status_code=400, detail="Student identification required (Bearer token or student_id in body)")

    code = req.class_code.strip().upper() if req.class_code and req.class_code.strip() else ""
    if not code:
        raise HTTPException(status_code=400, detail="Class code cannot be empty")

    course = db.scalars(
        select(CourseClass).where((CourseClass.class_code.ilike(code)) | (CourseClass.class_id.ilike(code)))
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Invalid class code '{code}'. Class not found.")

    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail=f"Student ID '{student_id}' not found in registry")

    # If student previously had an enrolled class, ensure it is recorded in Enrollment
    if student.class_id and student.class_id != course.class_id:
        prior_enr = db.scalars(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.class_id == student.class_id
            )
        ).first()
        if not prior_enr:
            db.add(Enrollment(
                enrollment_id=f"enr_{uuid.uuid4().hex[:12]}",
                student_id=student_id,
                class_id=student.class_id
            ))

    # Add enrollment record for target course if not exists
    existing_enr = db.scalars(
        select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.class_id == course.class_id)
    ).first()
    if not existing_enr:
        db.add(Enrollment(
            enrollment_id=f"enr_{uuid.uuid4().hex[:12]}",
            student_id=student_id,
            class_id=course.class_id
        ))

    student.class_id = course.class_id
    db.commit()

    return {
        "success": True,
        "student_id": student_id,
        "class_id": course.class_id,
        "class_name": course.class_name,
        "subject": course.subject,
        "class_code": course.class_code or course.class_id,
        "message": f"Successfully joined {course.class_name} ({course.subject})"
    }


@app.post("/api/v2/classes/join")
def join_class_v2(
    req: JoinClassRequest,
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    if user.get("role") == "student":
        student_id = user["sub"]
    elif req.student_id and req.student_id.strip():
        student_id = req.student_id.strip().upper()
    else:
        student_id = user["sub"]

    code = req.class_code.strip().upper() if req.class_code and req.class_code.strip() else ""
    if not code:
        raise HTTPException(status_code=400, detail="Class code cannot be empty")

    course = db.scalars(
        select(CourseClass).where((CourseClass.class_code.ilike(code)) | (CourseClass.class_id.ilike(code)))
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Invalid class code '{code}'. Class not found.")

    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail=f"Student ID '{student_id}' not found in registry")

    import uuid
    if student.class_id and student.class_id != course.class_id:
        prior_enr = db.scalars(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.class_id == student.class_id
            )
        ).first()
        if not prior_enr:
            db.add(Enrollment(
                enrollment_id=f"enr_{uuid.uuid4().hex[:12]}",
                student_id=student_id,
                class_id=student.class_id
            ))

    existing_enr = db.scalars(
        select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.class_id == course.class_id)
    ).first()
    if not existing_enr:
        db.add(Enrollment(
            enrollment_id=f"enr_{uuid.uuid4().hex[:12]}",
            student_id=student_id,
            class_id=course.class_id
        ))

    student.class_id = course.class_id
    db.commit()

    return {
        "success": True,
        "student_id": student_id,
        "class_id": course.class_id,
        "class_name": course.class_name,
        "subject": course.subject,
        "class_code": course.class_code or course.class_id,
        "message": f"Successfully joined {course.class_name} ({course.subject})"
    }


@app.get("/api/classes/{class_id}/roster")
def get_class_roster(class_id: str, db: Session = Depends(get_db)):
    cid = class_id.strip().upper()
    enrolled_sids = db.scalars(
        select(Enrollment.student_id).where(Enrollment.class_id == cid)
    ).all()
    rows = db.scalars(
        select(Student).where(
            (Student.class_id == cid) | (Student.student_id.in_(enrolled_sids))
        ).distinct()
    ).all()
    return [
        {
            "student_id": s.student_id,
            "name": s.name,
            "email": s.email,
            "registered_device_id": s.registered_device_id,
            "class_id": cid,
        }
        for s in rows
    ]


@app.get("/api/students/{student_id}/classes")
def get_student_classes(
    student_id: str,
    auth: Optional[dict] = Depends(get_auth_context),
    db: Session = Depends(get_db)
):
    sid = student_id.strip().upper()
    student = db.get(Student, sid)
    if not student:
        raise HTTPException(status_code=404, detail=f"Student '{sid}' not found in registry")

    enrolled_cids = set(db.scalars(
        select(Enrollment.class_id).where(Enrollment.student_id == sid)
    ).all())
    if student.class_id:
        enrolled_cids.add(student.class_id)

    classes = db.scalars(
        select(CourseClass).where(CourseClass.class_id.in_(enrolled_cids))
    ).all()
    return [
        {
            "class_id": c.class_id,
            "class_name": c.class_name,
            "subject": c.subject,
            "teacher_id": c.teacher_id,
            "class_code": c.class_code or c.class_id,
        }
        for c in classes
    ]


@app.get("/api/v2/students/me/classes")
def get_my_classes_v2(
    user: dict = Depends(require_authenticated_user),
    db: Session = Depends(get_db)
):
    sid = user["sub"]
    student = db.get(Student, sid)
    if not student:
        raise HTTPException(status_code=404, detail=f"Student '{sid}' not found in registry")

    enrolled_cids = set(db.scalars(
        select(Enrollment.class_id).where(Enrollment.student_id == sid)
    ).all())
    if student.class_id:
        enrolled_cids.add(student.class_id)

    classes = db.scalars(
        select(CourseClass).where(CourseClass.class_id.in_(enrolled_cids))
    ).all()
    return [
        {
            "class_id": c.class_id,
            "class_name": c.class_name,
            "subject": c.subject,
            "teacher_id": c.teacher_id,
            "class_code": c.class_code or c.class_id,
        }
        for c in classes
    ]



