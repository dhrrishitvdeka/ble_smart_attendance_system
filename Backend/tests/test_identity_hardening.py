"""Regression tests for identity hardening: no login bypasses, hashed credentials, JWT claim enforcement."""
import time
import uuid

import jwt as pyjwt
from fastapi.testclient import TestClient

from Backend.main import app, create_access_token
import Backend.main as main_mod

client = TestClient(app)


def test_seeded_teacher_login_with_hashed_password():
    resp = client.post("/api/auth/login", json={"username": "t001 ", "password": "teach123"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "teacher"


def test_seeded_student_login_with_hashed_password():
    resp = client.post("/api/auth/login", json={"username": "S003", "password": "stud123"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "student"


def test_admin_login_uses_database_record():
    resp = client.post("/api/auth/login", json={"username": "A001", "password": "admin123"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_unknown_admin_rejected_without_bypass():
    resp = client.post("/api/auth/login", json={"username": "A999", "password": "admin123"})
    assert resp.status_code == 401


def test_nonexistent_student_rejected_without_bypass():
    resp = client.post("/api/auth/login", json={"username": "S999", "password": "stud123"})
    assert resp.status_code == 401


def test_wrong_password_rejected():
    resp = client.post("/api/auth/login", json={"username": "T001", "password": "wrong"})
    assert resp.status_code == 401


def test_password_hash_is_not_plaintext_in_database():
    from Backend.database import SessionLocal
    from Backend.models import Teacher, Student
    db = SessionLocal()
    try:
        teacher = db.get(Teacher, "T001")
        student = db.get(Student, "S001")
        assert teacher and "$" in teacher.password_hash and "teach123" not in teacher.password_hash
        assert student and "$" in student.password_hash and "stud123" not in student.password_hash
    finally:
        db.close()


def test_token_missing_claims_rejected():
    for claims in ({"sub": "T001"}, {"role": "teacher"}, {}):
        forged = jwt_encode_without_required_claims(claims)
        resp = client.post(
            "/api/v2/attendance",
            json=valid_payload(),
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401


def test_token_with_invalid_role_rejected():
    token = jwt_encode_without_required_claims({"sub": "X001", "role": "superuser"})
    resp = client.post(
        "/api/attendance",
        json=valid_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_token_signed_with_stolen_default_secret_rejected():
    known_default = "super-secret-attendance-key-with-at-least-32-bytes-length!"
    forged = main_mod.jwt.encode(
        {"sub": "T001", "role": "teacher", "exp": int(time.time()) + 600, "iat": int(time.time())},
        known_default,
        algorithm="HS256",
    )
    resp = client.post("/api/attendance", json=valid_payload(), headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def valid_payload():
    return {
        "attendance_id": f"att_{uuid.uuid4().hex[:12]}",
        "session_id": f"SESS_{uuid.uuid4().hex[:8]}",
        "student_id": "S001",
        "timestamp": int(time.time() * 1000),
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
    }


def jwt_encode_without_required_claims(claims):
    return main_mod.jwt.encode(claims, main_mod.JWT_SECRET, algorithm=main_mod.JWT_ALGORITHM)
