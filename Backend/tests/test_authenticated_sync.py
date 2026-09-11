"""Tests for Authenticated Attendance Sync & Security Hardening (VULN-02 & VULN-04 remediations)."""
import uuid
from fastapi.testclient import TestClient
from Backend.main import app, create_access_token

client = TestClient(app)

SESSION_ID = f"AUTH_TEST_SESS_{uuid.uuid4().hex[:8]}"
STUDENT_A = "S001"
STUDENT_B = "S002"


def test_auth_login_teacher():
    resp = client.post("/api/auth/login", json={"username": "T001", "password": "teach123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["role"] == "teacher"


def test_auth_login_student():
    resp = client.post("/api/auth/login", json={"username": "S001", "password": "stud123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["role"] == "student"


def test_auth_login_invalid():
    resp = client.post("/api/auth/login", json={"username": "T001", "password": "wrongpass"})
    assert resp.status_code == 401


def test_v2_endpoint_strictly_requires_token():
    payload = {
        "attendance_id": f"att_auth_{uuid.uuid4().hex[:8]}",
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    # No Authorization header
    resp = client.post("/api/v2/attendance", json=payload)
    assert resp.status_code == 401


def test_v2_endpoint_rejects_student_role():
    token = create_access_token({"sub": STUDENT_A, "role": "student"})
    payload = {
        "attendance_id": f"att_auth_{uuid.uuid4().hex[:8]}",
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    resp = client.post(
        "/api/v2/attendance",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_v2_endpoint_accepts_teacher():
    token = create_access_token({"sub": "T001", "role": "teacher"})
    att_id = f"att_auth_{uuid.uuid4().hex[:8]}"
    payload = {
        "attendance_id": att_id,
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    resp = client.post(
        "/api/v2/attendance",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stored"
    assert data["verified_by"] == "T001"


def test_pii_roster_disclosure_protection():
    pii_sess = f"PII_SESS_{uuid.uuid4().hex[:8]}"
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_a_token = create_access_token({"sub": STUDENT_A, "role": "student"})
    student_b_token = create_access_token({"sub": STUDENT_B, "role": "student"})

    # Add records for Student A and Student B
    for sid in [STUDENT_A, STUDENT_B]:
        client.post(
            "/api/v2/attendance",
            json={
                "attendance_id": f"att_{sid}_{uuid.uuid4().hex[:8]}",
                "session_id": pii_sess,
                "student_id": sid,
                "timestamp": 1700000000000,
                "verification_status": "PRESENT",
                "route_type": "DIRECT",
            },
            headers={"Authorization": f"Bearer {teacher_token}"},
        )

    # Teacher should see all students in session
    resp_teacher = client.get(
        f"/api/v2/attendance/{pii_sess}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp_teacher.status_code == 200
    records = resp_teacher.json()
    assert len(records) == 2
    student_ids = [r["student_id"] for r in records]
    assert STUDENT_A in student_ids
    assert STUDENT_B in student_ids

    # Student A must ONLY see their own record (preventing PII harvesting)
    resp_a = client.get(
        f"/api/v2/attendance/{pii_sess}",
        headers={"Authorization": f"Bearer {student_a_token}"},
    )
    assert resp_a.status_code == 200
    records_a = resp_a.json()
    assert len(records_a) == 1
    assert records_a[0]["student_id"] == STUDENT_A


def test_enforce_auth_protects_primary_endpoints(monkeypatch):
    """Verify that when ENFORCE_AUTH is enabled, /api/attendance, batch, and session GET are strictly secured."""
    import Backend.main as main_mod
    monkeypatch.setattr(main_mod, "ENFORCE_AUTH", True)

    payload = {
        "attendance_id": f"att_enf_{uuid.uuid4().hex[:8]}",
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_token = create_access_token({"sub": STUDENT_A, "role": "student"})

    # 1. Unauthenticated single POST -> 401
    r_unauth = client.post("/api/attendance", json=payload)
    assert r_unauth.status_code == 401

    # 2. Student role single POST -> 403
    r_stud = client.post("/api/attendance", json=payload, headers={"Authorization": f"Bearer {student_token}"})
    assert r_stud.status_code == 403

    # 3. Teacher single POST -> 200
    r_teach = client.post("/api/attendance", json=payload, headers={"Authorization": f"Bearer {teacher_token}"})
    assert r_teach.status_code == 200

    # 4. Unauthenticated batch POST -> 401
    r_batch_unauth = client.post("/api/attendance/batch", json=[payload])
    assert r_batch_unauth.status_code == 401

    # 5. Student batch POST -> 403
    r_batch_stud = client.post("/api/attendance/batch", json=[payload], headers={"Authorization": f"Bearer {student_token}"})
    assert r_batch_stud.status_code == 403

    # 6. Teacher batch POST -> 200
    r_batch_teach = client.post("/api/attendance/batch", json=[payload], headers={"Authorization": f"Bearer {teacher_token}"})
    assert r_batch_teach.status_code == 200

    # 7. Unauthenticated GET session -> 401
    r_get_unauth = client.get(f"/api/attendance/{SESSION_ID}")
    assert r_get_unauth.status_code == 401

    # 8. Student GET session -> only own record
    r_get_stud = client.get(f"/api/attendance/{SESSION_ID}", headers={"Authorization": f"Bearer {student_token}"})
    assert r_get_stud.status_code == 200
    assert all(rec["student_id"] == STUDENT_A for rec in r_get_stud.json())


def test_malformed_and_expired_tokens():
    """Verify that malformed and expired JWT tokens return 401."""
    # Malformed token string
    r1 = client.post("/api/v2/attendance", json={}, headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert r1.status_code == 401
    assert "Invalid token" in r1.json()["detail"]

    # Wrong authorization scheme
    r2 = client.post("/api/v2/attendance", json={}, headers={"Authorization": "Basic dGVzdDp0ZXN0"})
    assert r2.status_code == 401
    assert "Invalid authorization scheme" in r2.json()["detail"]

    # Expired token
    expired_token = create_access_token({"sub": "T001", "role": "teacher"}, expires_in=-10)
    r3 = client.post("/api/v2/attendance", json={}, headers={"Authorization": f"Bearer {expired_token}"})
    assert r3.status_code == 401
    assert "Token has expired" in r3.json()["detail"]


def test_admin_role_authorized_for_sync():
    """Verify administrator role can execute teacher sync operations."""
    admin_token = create_access_token({"sub": "A001", "role": "admin"})
    payload = {
        "attendance_id": f"att_admin_{uuid.uuid4().hex[:8]}",
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    r = client.post("/api/v2/attendance", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["status"] == "stored"
    assert r.json()["verified_by"] == "A001"


def test_authenticated_replay_deduplication():
    """Verify that re-posting an existing attendance record under auth does not duplicate."""
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    att_id = f"att_dedup_{uuid.uuid4().hex[:8]}"
    payload = {
        "attendance_id": att_id,
        "session_id": SESSION_ID,
        "student_id": STUDENT_A,
        "timestamp": 1700000000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }
    r1 = client.post("/api/v2/attendance", json=payload, headers={"Authorization": f"Bearer {teacher_token}"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "stored"

    # Replay
    r2 = client.post("/api/v2/attendance", json=payload, headers={"Authorization": f"Bearer {teacher_token}"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"



