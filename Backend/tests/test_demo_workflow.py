import hashlib
import uuid

from fastapi.testclient import TestClient
from Backend.main import app
from Backend.database import SessionLocal
from Backend.models import ClassSession, DemoChallenge


def login(user):
    client = TestClient(app)
    password = "admin123" if user == "A001" else "teach123" if user == "T001" else "stud123"
    response = client.post("/api/auth/login", json={"username": user, "password": password})
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    return client


def new_session(teacher):
    code = "DEMO-" + uuid.uuid4().hex[:8]
    response = teacher.post("/api/classes", json={"class_id": code, "class_name": code,
        "subject": "Demo", "teacher_id": "T001", "class_code": code})
    assert response.status_code == 200
    for user in ("S001", "S002", "S003"):
        assert login(user).post("/api/v2/classes/join", json={"class_code": code}).status_code == 200
    response = teacher.post("/api/demo/sessions", json={"class_id": code})
    assert response.status_code == 200
    return "/api/demo/sessions/" + response.json()["session_id"]


def solve(client, path, **kwargs):
    challenge = client.post(path + "/challenge", json={"position": "near", **kwargs})
    assert challenge.status_code == 200, challenge.text
    data = challenge.json()
    proof = {"challenge_id": data["challenge_id"], "response": hashlib.sha256(data["nonce"].encode()).hexdigest()}
    response = client.post(path + "/verify", json=proof)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ELIGIBLE"
    return proof


def test_demo_direct_relay_finalization_history():
    teacher, student, relay, outside = [login(u) for u in ("T001", "S001", "S002", "S003")]
    path = new_session(teacher)
    assert len(student.get(path + "/attendance").json()) == 1
    proof = solve(student, path)
    assert student.post(path + "/verify", json=proof).status_code == 409
    assert outside.post(path + "/challenge", json={"position": "outside"}).status_code == 409
    assert relay.post(path + "/relay", json={"enabled": True}).status_code == 200
    assert "S002" in outside.get(path + "/relays").json()
    solve(outside, path, position="outside", relay_student_id="S002")
    assert student.post(path + "/finalize", json={}).status_code == 403
    result = teacher.post(path + "/finalize", json={})
    assert result.status_code == 200
    assert result.json()["updated"] == 2
    assert teacher.post(path + "/finalize", json={}).json()["updated"] == 0
    rows = teacher.get(path + "/attendance").json()
    assert {r["student_id"]: r["status"] for r in rows} == {"S001": "PRESENT", "S002": "NOT_VERIFIED", "S003": "PRESENT"}
    assert outside.get(path + "/attendance").json()[0]["route"] == "RELAY"
    assert relay.post(path + "/challenge", json={"position": "near"}).status_code == 409
    assert login("S001").get(path + "/attendance").json()[0]["status"] == "PRESENT"


def test_demo_expired_challenge_and_session():
    teacher, student = login("T001"), login("S001")
    path = new_session(teacher)
    challenge = student.post(path + "/challenge", json={"position": "near"}).json()
    with SessionLocal() as db:
        db.get(DemoChallenge, challenge["challenge_id"]).expires_at = 1
        db.commit()
    proof = {"challenge_id": challenge["challenge_id"], "response": hashlib.sha256(challenge["nonce"].encode()).hexdigest()}
    assert student.post(path + "/verify", json=proof).status_code == 409
    with SessionLocal() as db:
        db.get(ClassSession, path.rsplit("/", 1)[1]).expiration_time = 1
        db.commit()
    assert student.post(path + "/challenge", json={"position": "near"}).status_code == 409


def test_demo_invalid_proof_and_relay_withdrawal():
    teacher, student, relay = login("T001"), login("S001"), login("S002")
    path = new_session(teacher)
    data = student.post(path + "/challenge", json={"position": "near"}).json()
    assert student.post(path + "/verify", json={"challenge_id": data["challenge_id"], "response": "0" * 64}).status_code == 400
    assert student.post(path + "/verify", json={"challenge_id": data["challenge_id"], "response": "0" * 64}).status_code == 409
    relay.post(path + "/relay", json={"enabled": True})
    data = student.post(path + "/challenge", json={"position": "outside", "relay_student_id": "S002"}).json()
    relay.post(path + "/relay", json={"enabled": False})
    proof = {"challenge_id": data["challenge_id"], "response": hashlib.sha256(data["nonce"].encode()).hexdigest()}
    assert student.post(path + "/verify", json=proof).status_code == 409


def test_demo_ui_served_and_auth_required():
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert "SIMULATION ONLY" in client.get("/").text
    assert client.get("/webapp/demo.js").status_code == 200
    assert client.get("/api/demo/sessions").status_code == 401
    assert client.post("/api/demo/sessions", json={"class_id": "CSE-A"}).status_code == 401


def test_demo_expired_session_can_finalize_verified_students():
    teacher, student = login("T001"), login("S001")
    path = new_session(teacher)
    solve(student, path, position="back")
    with SessionLocal() as db:
        db.get(ClassSession, path.rsplit("/", 1)[1]).expiration_time = 1
        db.commit()
    result = teacher.post(path + "/finalize", json={})
    assert result.status_code == 200
    assert result.json() == {"status": "FINALIZED", "updated": 1}
    assert student.get(path + "/attendance").json()[0]["status"] == "PRESENT"


def test_seed_repairs_partial_database_without_overwriting_accounts(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from Backend import database
    from Backend.models import Base, Teacher, Student, CourseClass, Enrollment
    from Backend.security import hash_password, verify_password

    engine = create_engine("sqlite:///" + (tmp_path / "partial.db").as_posix())
    sessions = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    try:
        Base.metadata.create_all(engine)
        with sessions.begin() as db:
            db.add(Teacher(teacher_id="T001", name="Existing teacher", password_hash=hash_password("existing")))
        database.init_db()
        database.init_db()
        with sessions() as db:
            teacher = db.get(Teacher, "T001")
            assert teacher.name == "Existing teacher"
            assert verify_password("existing", teacher.password_hash)
            assert db.get(CourseClass, "CSE-A") is not None
            assert len(db.scalars(select(Student)).all()) == 6
            assert len(db.scalars(select(Enrollment)).all()) == 6
    finally:
        engine.dispose()
