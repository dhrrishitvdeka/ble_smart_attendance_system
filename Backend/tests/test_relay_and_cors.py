import uuid

import pytest
from fastapi.testclient import TestClient
from Backend.database import SessionLocal
from Backend.main import app, create_access_token
from Backend.models import ClassSession, CourseClass, Enrollment, RelayEvent, Student, Teacher

client = TestClient(app)
client.headers["Authorization"] = "Bearer " + create_access_token({"sub": "T001", "role": "teacher"})


def test_cors_headers():
    response = client.options(
        "/api/attendance",
        headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8000"



import time

def test_relay_event_ingestion_and_deduplication():
    eid = f"rl_test_{time.time_ns()}"
    sid = f"SES_{time.time_ns()}"
    payload = {
        "event_id": eid,
        "session_id": sid,
        "message_id": "msg_001",
        "source_student_id": "S003",
        "relay_student_id": "S002",
        "hop_count": 2,
        "timestamp": 1773400000000,
        "status": "FORWARDED"
    }

    # First post -> stored
    r1 = client.post("/api/relay-events", json=payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "stored"

    # Duplicate post -> duplicate_ignored
    r2 = client.post("/api/relay-events", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

    # List session relay events
    r3 = client.get(f"/api/relay-events/{sid}")
    assert r3.status_code == 200
    events = r3.json()
    assert len(events) >= 1
    assert any(e["event_id"] == eid for e in events)



def test_classes_and_roster():
    # Classes endpoint
    r1 = client.get("/api/classes")
    assert r1.status_code == 200
    classes = r1.json()
    assert len(classes) >= 1
    assert any(c["class_id"] == "CSE-A" for c in classes)

    # Class roster endpoint
    r2 = client.get("/api/classes/CSE-A/roster")
    assert r2.status_code == 200
    roster = r2.json()
    assert len(roster) >= 6
    student_ids = [s["student_id"] for s in roster]
    assert "S001" in student_ids
    assert "S002" in student_ids


def test_relay_v2_authenticated_batch_and_privacy_filter():
    sid = f"SES_V2_RELAY_{time.time_ns()}"
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_token_s1 = create_access_token({"sub": "S001", "role": "student"})
    student_token_s5 = create_access_token({"sub": "S005", "role": "student"})

    e1 = {
        "event_id": f"rl_v2_1_{time.time_ns()}",
        "session_id": sid,
        "message_id": "msg_001",
        "source_student_id": "S001",
        "relay_student_id": "S002",
        "hop_count": 2,
        "timestamp": 1773400000000,
        "status": "FORWARDED"
    }
    e2 = {
        "event_id": f"rl_v2_2_{time.time_ns()}",
        "session_id": sid,
        "message_id": "msg_002",
        "source_student_id": "S003",
        "relay_student_id": "S004",
        "hop_count": 2,
        "timestamp": 1773400001000,
        "status": "FORWARDED"
    }

    # 1. Unauthenticated batch push rejected
    r_unauth = client.post("/api/v2/relay-events/batch", json=[e1, e2], headers={"Authorization": ""})
    assert r_unauth.status_code == 401

    # 2. Authenticated batch push succeeds
    r_auth = client.post(
        "/api/v2/relay-events/batch",
        json=[e1, e2],
        headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert r_auth.status_code == 200
    assert r_auth.json()["stored"] == 2

    # 3. Teacher queries -> sees both events
    r_teacher = client.get(
        f"/api/v2/relay-events/{sid}",
        headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert r_teacher.status_code == 200
    assert len(r_teacher.json()) == 2

    # 4. Student S001 queries -> sees ONLY e1 (involving S001)
    r_s1 = client.get(
        f"/api/v2/relay-events/{sid}",
        headers={"Authorization": f"Bearer {student_token_s1}"}
    )
    assert r_s1.status_code == 200
    s1_events = r_s1.json()
    assert len(s1_events) == 1
    assert s1_events[0]["event_id"] == e1["event_id"]

    # 5. Student S005 queries -> sees NO events (neither source nor relay)
    r_s5 = client.get(
        f"/api/v2/relay-events/{sid}",
        headers={"Authorization": f"Bearer {student_token_s5}"}
    )
    assert r_s5.status_code == 200
    assert len(r_s5.json()) == 0


def test_relay_batches_require_auth_enforce_limits_and_dedupe():
    for path in ("/api/relay-events/batch", "/api/v2/relay-events/batch"):
        sid = f"SES_RELAY_LIMITS_{path.count('/')}_{time.time_ns()}"
        ev = {
            "event_id": f"rl_lim_{time.time_ns()}_{path.count('/')}",
            "session_id": sid,
            "message_id": "msg_lim",
            "source_student_id": "S001",
            "relay_student_id": "S002",
            "hop_count": 1,
            "timestamp": 1773400000000,
            "status": "FORWARDED"
        }
        r_empty = client.post(path, json=[], headers={"Authorization": ""})
        assert r_empty.status_code == 401
        r_big = client.post(path, json=[dict(ev, event_id=f"e{i}") for i in range(501)])
        assert r_big.status_code == 413
        r1 = client.post(path, json=[ev, ev])
        assert r1.status_code == 200
        assert r1.json()["stored"] == 1
        assert r1.json()["duplicates_ignored"] == 1
        r2 = client.post(path, json=[ev])
        assert r2.status_code == 200
        assert r2.json()["duplicates_ignored"] == 1


def test_class_code_lookup_and_join_are_exact_not_wildcard():
    import time
    ts = str(time.time_ns())
    code = "EXACT" + ts
    r = client.post("/api/classes", json={"class_id": code, "class_name": "Exact", "subject": "X", "class_code": code})
    assert r.status_code == 200
    assert client.get(f"/api/classes/code/{code}").status_code == 200
    probe_code = code[:-1] + "_"
    assert client.get(f"/api/classes/code/{probe_code}").status_code == 404
    token = create_access_token({"sub": "S001", "role": "student"})
    r_join = client.post("/api/classes/join", json={"class_code": probe_code}, headers={"Authorization": f"Bearer {token}"})
    assert r_join.status_code == 404


def test_student_cannot_relay_events_for_classmates():
    sid = f"SES_RELAY_OWN_{time.time_ns()}"
    other = {
        "event_id": f"rl_other_{time.time_ns()}",
        "session_id": sid,
        "message_id": "msg_other",
        "source_student_id": "S002",
        "relay_student_id": "S003",
        "hop_count": 1,
        "timestamp": 1773400000000,
        "status": "FORWARDED"
    }
    token = create_access_token({"sub": "S001", "role": "student"})
    r = client.post("/api/relay-events", json=other, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    own = dict(other, event_id=f"rl_own_{time.time_ns()}", source_student_id="S001", relay_student_id="S001")
    r_own = client.post("/api/relay-events", json=own, headers={"Authorization": f"Bearer {token}"})
    assert r_own.status_code == 200
    assert r_own.json()["status"] == "stored"


def test_class_id_and_join_code_share_an_unambiguous_namespace():
    suffix = uuid.uuid4().hex[:16].upper()
    class_id, code = "CLASS_" + suffix, "CODE_" + suffix
    response = client.post("/api/classes", json={
        "class_id": class_id, "class_name": "Original", "subject": "Testing", "class_code": code,
    })
    assert response.status_code == 200
    duplicate = client.post("/api/classes", json={
        "class_id": code.lower(), "class_name": "Second", "subject": "Testing", "class_code": "NEW_" + suffix,
    })
    assert duplicate.status_code == 400
    for lookup in (class_id, code):
        result = client.get(f"/api/classes/code/{lookup}")
        assert result.status_code == 200
        assert result.json()["class_id"] == class_id


@pytest.fixture
def registered_relay_session():
    suffix = uuid.uuid4().hex[:16]
    class_id = "CLASS_" + suffix
    session_id = "SESSION_" + suffix
    other_teacher = "T_" + suffix
    students = {name: name + "_" + suffix for name in ("source", "relay", "peer", "outside")}
    with SessionLocal.begin() as db:
        password_hash = db.get(Teacher, "T001").password_hash
        db.add(Teacher(teacher_id=other_teacher, name="Other teacher", password_hash=password_hash))
        db.add(CourseClass(class_id=class_id, class_name="Relay class", subject="Testing", teacher_id="T001"))
        db.flush()
        for name, student_id in students.items():
            db.add(Student(student_id=student_id, name=name, password_hash=password_hash,
                registered_device_id="DEV_" + student_id,
                class_id=class_id if name in ("source", "peer") else None))
        db.flush()
        db.add(Enrollment(enrollment_id="ENR_" + suffix, student_id=students["relay"], class_id=class_id))
        db.add(ClassSession(session_id=session_id, class_id=class_id, teacher_id="T001",
            start_time=1773400000000, expiration_time=1773400600000, random_nonce=suffix))
        db.add(RelayEvent(event_id="EVENT_" + suffix, session_id=session_id, message_id="MSG_" + suffix,
            source_student_id=students["source"], relay_student_id=students["relay"],
            hop_count=1, timestamp=1773400000000, status="FORWARDED"))
    return session_id, other_teacher, students, "EVENT_" + suffix


@pytest.mark.parametrize("path", ["/api/relay-events", "/api/v2/relay-events"])
@pytest.mark.parametrize("identity,role,expected_status,visible", [
    ("T001", "teacher", 200, True),
    ("A001", "admin", 200, True),
    ("other_teacher", "teacher", 403, False),
    ("source", "student", 200, True),
    ("relay", "student", 200, True),
    ("peer", "student", 200, False),
    ("outside", "student", 403, False),
    (None, None, 401, False),
])
def test_registered_relay_session_access(registered_relay_session, path, identity, role, expected_status, visible):
    session_id, other_teacher, students, event_id = registered_relay_session
    subject = other_teacher if identity == "other_teacher" else students.get(identity, identity)
    authorization = "Bearer " + create_access_token({"sub": subject, "role": role}) if subject else ""
    response = client.get(f"{path}/{session_id}", headers={"Authorization": authorization})
    assert response.status_code == expected_status
    if expected_status == 200:
        assert [row["event_id"] for row in response.json()] == ([event_id] if visible else [])
    else:
        assert "detail" in response.json()
