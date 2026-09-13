from fastapi.testclient import TestClient
from Backend.main import app, create_access_token

client = TestClient(app)


def test_cors_headers():
    response = client.options(
        "/api/attendance",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST"}
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in ("*", "http://localhost:8080")



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
    r_unauth = client.post("/api/v2/relay-events/batch", json=[e1, e2])
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
