"""Idempotency: re-POSTing the same attendance_id must not duplicate."""
from fastapi.testclient import TestClient
from Backend.main import app

client = TestClient(app)

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
    r = client.post("/api/attendance/batch", json=[PAYLOAD, PAYLOAD])
    assert r.status_code == 200
    assert r.json()["duplicates_ignored"] >= 1


def test_rejects_bad_route():
    bad = dict(PAYLOAD, attendance_id="att_bad", route_type="WORMHOLE")
    r = client.post("/api/attendance", json=bad)
    assert r.status_code == 400
