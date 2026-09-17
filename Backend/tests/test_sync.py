"""Idempotency: re-POSTing the same attendance_id must not duplicate."""
from fastapi.testclient import TestClient
from Backend.main import app, create_access_token
import uuid

client = TestClient(app)
client.headers["Authorization"] = "Bearer " + create_access_token({"sub": "T001", "role": "teacher"})

PAYLOAD = {
    "attendance_id": "att_test123",
    "session_id": "SESS1",
    "student_id": "S001",
    "timestamp": 1700000000000,
    "verification_status": "PRESENT",
    "route_type": "DIRECT",
    "rssi_evidence": -60,
    "hop_count": 0,
}


def test_sync_is_idempotent():
    r1 = client.post("/api/attendance", json=PAYLOAD)
    assert r1.status_code == 200
    r2 = client.post("/api/attendance", json=PAYLOAD)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"


def test_batch_dedupes():
    for path in ("/api/attendance/batch", "/api/v2/attendance/batch"):
        payload = dict(PAYLOAD, attendance_id=uuid.uuid4().hex)
        r = client.post(path, json=[payload, payload])
        assert r.status_code == 200
        assert r.json()["stored"] == 1
        assert r.json()["duplicates_ignored"] == 1


def test_rejects_bad_route():
    bad = dict(PAYLOAD, attendance_id="att_bad", route_type="WORMHOLE")
    r = client.post("/api/attendance", json=bad)
    assert r.status_code == 400


def test_single_and_batch_validation_are_consistent():
    bad_status = dict(PAYLOAD, attendance_id="att_vstat", verification_status="MAYBE")
    assert client.post("/api/attendance", json=bad_status).status_code == 400
    assert client.post("/api/attendance/batch", json=[bad_status]).status_code == 400
    assert client.post("/api/v2/attendance", json=bad_status).status_code == 400
    assert client.post("/api/v2/attendance/batch", json=[bad_status]).status_code == 400
    manual = dict(PAYLOAD, attendance_id="att_manual_ok", route_type="MANUAL", verification_status="ELIGIBLE")
    assert client.post("/api/attendance", json=manual).status_code == 200


def test_unknown_native_session_is_accepted_for_teacher_sync():
    att = dict(PAYLOAD, attendance_id="att_native_untracked", session_id="NATIVE-UNKNOWN-SESS")
    assert client.post("/api/attendance", json=att).status_code == 200
    assert client.post("/api/v2/attendance", json=dict(att, attendance_id="att_native_v2")).status_code == 200


def test_batch_rejects_oversized_and_demo_sessions():
    big = [dict(PAYLOAD, attendance_id=f"att_big_{i}") for i in range(501)]
    assert client.post("/api/attendance/batch", json=big).status_code == 413
    demo = [dict(PAYLOAD, attendance_id="att_demo_probe", session_id="demo_x")]
    assert client.post("/api/attendance/batch", json=demo).status_code == 409


def test_teacher_can_create_and_use_own_class_without_teacher_id():
    import time
    ts = str(time.time_ns())
    r = client.post("/api/classes", json={"class_id": "OWN" + ts, "class_name": "Own Class", "subject": "Testing"})
    assert r.status_code == 200
    assert r.json()["teacher_id"] == "T001"
    assert r.json()["class_code"] == "OWN" + ts
    r_sess = client.post("/api/demo/sessions", json={"class_id": "OWN" + ts})
    assert r_sess.status_code == 200


def test_teacher_cannot_create_class_for_other_teacher():
    import time
    from Backend.database import SessionLocal
    from Backend.models import Teacher
    from Backend.security import hash_password
    with SessionLocal() as db:
        if not db.get(Teacher, "T002"):
            db.add(Teacher(teacher_id="T002", name="Second Teacher", password_hash=hash_password("teach456")))
            db.commit()
    ts = str(time.time_ns())
    r = client.post("/api/classes", json={"class_id": "OTH" + ts, "class_name": "Other", "subject": "X", "teacher_id": "T002"})
    assert r.status_code == 403
    r = client.post("/api/classes", json={"class_id": "NOT" + ts, "class_name": "Other", "subject": "X", "teacher_id": "T_NOPE"})
    assert r.status_code == 400
