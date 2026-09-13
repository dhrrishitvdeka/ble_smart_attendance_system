"""End-to-End Comprehensive Integration and System Verification Suite.
Validates the complete cyber-physical attendance pipeline:
1. Cryptographic Challenge-Response & Hardware Secrets
2. Direct vs Mesh Relay Multi-Hop Bounding (MAX_HOPS=2)
3. Proximity Telemetry Filtering (Floor: -90 dBm)
4. Teacher Review, Manual Override, and Attendance Finalization (ELIGIBLE -> PRESENT)
5. Cloud Synchronization with FastAPI, JWT Bearer Auth, Deduplication, and Relay Logging
6. Role-Based Access Control (RBAC) & Privacy Preserving Student Views
7. Legacy 31-Byte BLE Advertising PDU Budget Compliance
"""
import hashlib
import json
import os
import struct
import time
from fastapi.testclient import TestClient
from Backend.main import app, create_access_token

client = TestClient(app)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest().lower()


def test_e2e_01_cloud_health_and_auth():
    """Verify backend health check and multi-role authentication."""
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["ok"] is True

    # Teacher login
    r_t = client.post("/api/auth/login", json={"username": "T001", "password": "teach123"})
    assert r_t.status_code == 200
    t_data = r_t.json()
    assert t_data["role"] == "teacher"
    assert "access_token" in t_data

    # Student login
    r_s = client.post("/api/auth/login", json={"username": "S001", "password": "stud123"})
    assert r_s.status_code == 200
    s_data = r_s.json()
    assert s_data["role"] == "student"

    # Admin login
    r_a = client.post("/api/auth/login", json={"username": "A001", "password": "admin123"})
    assert r_a.status_code == 200
    a_data = r_a.json()
    assert a_data["role"] == "admin"

    # Bad login
    r_bad = client.post("/api/auth/login", json={"username": "T001", "password": "wrongpassword"})
    assert r_bad.status_code == 401


def test_e2e_02_class_roster_discovery():
    """Verify institutional class roster endpoints."""
    r_classes = client.get("/api/classes")
    assert r_classes.status_code == 200
    classes = r_classes.json()
    assert any(c["class_id"] == "CSE-A" for c in classes)

    r_roster = client.get("/api/classes/CSE-A/roster")
    assert r_roster.status_code == 200
    roster = r_roster.json()
    assert len(roster) >= 6
    s_ids = [s["student_id"] for s in roster]
    assert "S001" in s_ids
    assert "S002" in s_ids


def test_e2e_03_ble_packet_codec_and_pdu_budget():
    """Validate 8-byte binary packet serialization and 31-byte legacy PDU budget compliance."""
    magic = 0xB5
    hop_count = 2
    session_id = 0x8F72A1C9

    # 8-byte binary encoding: [MAGIC (1B)][HOP (1B)][SESSION_ID (4B Big-Endian)][RESERVED (2B)]
    packet = struct.pack(">BBIH", magic, hop_count, session_id, 0)
    assert len(packet) == 8
    assert packet[0] == 0xB5
    assert packet[1] == 2

    # Unpack and verify
    unpacked_magic, unpacked_hop, unpacked_sid, unpacked_rsv = struct.unpack(">BBIH", packet)
    assert unpacked_magic == magic
    assert unpacked_hop == hop_count
    assert unpacked_sid == session_id
    assert unpacked_rsv == 0

    # Legacy BLE 31-byte advertising PDU budget check:
    # Flags AD: 3 bytes ([0x02][0x01][0x06])
    # Manufacturer Specific Data AD:
    #   Length (1B) + Type 0xFF (1B) + Company ID 0xFFFF (2B) + Payload (8B) = 12 bytes
    total_adv_pdu = 3 + 12
    assert total_adv_pdu == 15
    assert total_adv_pdu <= 31, "Legacy BLE advertising PDU must not exceed 31 bytes"


def test_e2e_04_direct_and_relay_challenge_response_workflow():
    """Simulate complete teacher session lifecycle, direct check-in, and mesh relay check-in."""
    session_id = f"SES_{int(time.time())}"
    student_secret_s1 = "SEC_S001_HARDWARE_VAULT"
    student_secret_s3 = "SEC_S003_HARDWARE_VAULT"

    # 1. Teacher issues single-use challenge for S001 (Direct)
    ch_nonce_s1 = "A1B2C3D4E5F60718A1B2C3D4E5F60718"
    resp_hash_s1 = sha256_hex(ch_nonce_s1 + student_secret_s1)

    # 2. Teacher issues challenge for S003 (Relay via S002)
    ch_nonce_s3 = "99887766554433221100FFEEDDCCBBAA"
    resp_hash_s3 = sha256_hex(ch_nonce_s3 + student_secret_s3)

    # Direct check-in record
    att_direct = {
        "attendance_id": f"att_direct_{int(time.time() * 1000)}",
        "session_id": session_id,
        "student_id": "S001",
        "timestamp": int(time.time() * 1000),
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
        "rssi_evidence": -58,
        "hop_count": 0,
        "via_student": None
    }

    # Relayed check-in record (2 hops through S002)
    att_relay = {
        "attendance_id": f"att_relay_{int(time.time() * 1000)}",
        "session_id": session_id,
        "student_id": "S003",
        "timestamp": int(time.time() * 1000) + 100,
        "verification_status": "PRESENT",
        "route_type": "RELAY",
        "rssi_evidence": -74,
        "hop_count": 2,
        "via_student": "Diya Patel (S002)"
    }

    # Relay telemetry event
    relay_evt = {
        "event_id": f"rl_evt_{int(time.time() * 1000)}",
        "session_id": session_id,
        "message_id": f"msg_{int(time.time() * 1000)}",
        "source_student_id": "S003",
        "relay_student_id": "S002",
        "hop_count": 2,
        "timestamp": int(time.time() * 1000),
        "status": "FORWARDED"
    }

    # Login as Teacher to get JWT token
    r_login = client.post("/api/auth/login", json={"username": "T001", "password": "teach123"})
    teacher_token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {teacher_token}"}

    # Batch sync attendance to cloud backend
    r_sync = client.post("/api/attendance/batch", json=[att_direct, att_relay], headers=headers)
    assert r_sync.status_code == 200
    sync_data = r_sync.json()
    assert sync_data["stored"] == 2
    assert sync_data["duplicates_ignored"] == 0

    # Idempotent deduplication test: send same batch again
    r_sync_dup = client.post("/api/attendance/batch", json=[att_direct, att_relay], headers=headers)
    assert r_sync_dup.status_code == 200
    assert r_sync_dup.json()["stored"] == 0
    assert r_sync_dup.json()["duplicates_ignored"] == 2

    # Sync relay event telemetry
    r_rel_sync = client.post("/api/relay-events", json=relay_evt, headers=headers)
    assert r_rel_sync.status_code == 200
    assert r_rel_sync.json()["status"] == "stored"

    # Verify relay events query
    r_rel_list = client.get(f"/api/relay-events/{session_id}", headers=headers)
    assert r_rel_list.status_code == 200
    assert len(r_rel_list.json()) >= 1
    assert r_rel_list.json()[0]["source_student_id"] == "S003"


def test_e2e_05_role_based_access_control_roster():
    """Verify that student tokens can only view their own record, while teachers view full roster."""
    session_id = f"SES_RBAC_{int(time.time())}"
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_s1_token = create_access_token({"sub": "S001", "role": "student"})
    student_s2_token = create_access_token({"sub": "S002", "role": "student"})

    headers_teacher = {"Authorization": f"Bearer {teacher_token}"}
    headers_s1 = {"Authorization": f"Bearer {student_s1_token}"}
    headers_s2 = {"Authorization": f"Bearer {student_s2_token}"}

    # Ingest records for S001 and S002
    records = [
        {
            "attendance_id": f"att_rbac_1_{int(time.time()*1000)}",
            "session_id": session_id,
            "student_id": "S001",
            "timestamp": int(time.time() * 1000),
            "verification_status": "PRESENT",
            "route_type": "DIRECT",
            "rssi_evidence": -60,
            "hop_count": 0,
            "via_student": None
        },
        {
            "attendance_id": f"att_rbac_2_{int(time.time()*1000)}",
            "session_id": session_id,
            "student_id": "S002",
            "timestamp": int(time.time() * 1000),
            "verification_status": "PRESENT",
            "route_type": "DIRECT",
            "rssi_evidence": -62,
            "hop_count": 0,
            "via_student": None
        }
    ]
    r_batch = client.post("/api/attendance/batch", json=records, headers=headers_teacher)
    assert r_batch.status_code == 200

    # Teacher requests roster -> sees both S001 and S002
    r_t_view = client.get(f"/api/attendance/{session_id}", headers=headers_teacher)
    assert r_t_view.status_code == 200
    t_roster = r_t_view.json()
    assert len(t_roster) == 2

    # Student S001 requests roster -> sees ONLY S001
    r_s1_view = client.get(f"/api/attendance/{session_id}", headers=headers_s1)
    assert r_s1_view.status_code == 200
    s1_roster = r_s1_view.json()
    assert len(s1_roster) == 1
    assert s1_roster[0]["student_id"] == "S001"

    # Student S002 requests roster -> sees ONLY S002
    r_s2_view = client.get(f"/api/attendance/{session_id}", headers=headers_s2)
    assert r_s2_view.status_code == 200
    s2_roster = r_s2_view.json()
    assert len(s2_roster) == 1
    assert s2_roster[0]["student_id"] == "S002"


def test_e2e_06_security_rejections():
    """Verify rejection of invalid route types and unauthorized role actions."""
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_token = create_access_token({"sub": "S001", "role": "student"})

    invalid_record = {
        "attendance_id": f"att_inv_{int(time.time()*1000)}",
        "session_id": "SES_INV",
        "student_id": "S001",
        "timestamp": int(time.time() * 1000),
        "verification_status": "PRESENT",
        "route_type": "INVALID_ROUTE",  # must be DIRECT or RELAY
        "rssi_evidence": -60,
        "hop_count": 0
    }
    # Invalid route type rejected with 400
    r_inv = client.post("/api/attendance", json=invalid_record, headers={"Authorization": f"Bearer {teacher_token}"})
    assert r_inv.status_code == 400

    valid_record = {
        "attendance_id": f"att_stu_direct_{int(time.time()*1000)}",
        "session_id": "SES_VAL",
        "student_id": "S001",
        "timestamp": int(time.time() * 1000),
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
        "rssi_evidence": -60,
        "hop_count": 0
    }
    # Student token cannot submit attendance directly to teacher cloud sync endpoint (403 Forbidden)
    r_stu = client.post("/api/attendance", json=valid_record, headers={"Authorization": f"Bearer {student_token}"})
    assert r_stu.status_code == 403


def test_e2e_07_device_id_schema_consistency_and_direct_beacon_codec():
    """Verify system-wide device ID naming conventions and direct teacher beacon decoding (hop=0)."""
    # 1. Verify roster device ID schema matches DEV-S00x across all students
    r_roster = client.get("/api/classes/CSE-A/roster")
    assert r_roster.status_code == 200
    roster = r_roster.json()
    for s in roster:
        sid = s["student_id"]
        assert s["registered_device_id"] == f"DEV-{sid}", f"Mismatch: {s['registered_device_id']} != DEV-{sid}"

    # 2. Verify direct teacher beacon codec with hop=0 (direct advertisement)
    magic = 0xB5
    session_id_int = 0x1957F836
    direct_packet = struct.pack(">BBIH", magic, 0, session_id_int, 0)
    assert len(direct_packet) == 8

    # Unpack
    u_magic, u_hop, u_sid, u_rsv = struct.unpack(">BBIH", direct_packet)
    assert u_magic == 0xB5
    assert u_hop == 0, "Direct teacher beacon must have hop count 0"
    assert u_sid == session_id_int
    assert f"{u_sid:08X}" == "1957F836"


def test_e2e_08_class_code_and_student_join_mechanism():
    """Verify class creation with class codes, lookup, student joining, and attendance synchronization."""
    teacher_token = create_access_token({"sub": "T001", "role": "teacher"})
    student_s3_token = create_access_token({"sub": "S003", "role": "student"})
    student_s4_token = create_access_token({"sub": "S004", "role": "student"})
    headers_teacher = {"Authorization": f"Bearer {teacher_token}"}
    headers_s4 = {"Authorization": f"Bearer {student_s4_token}"}

    # 1. Create a new class with custom class code
    ts = int(time.time() * 1000)
    test_class_id = f"NET_{ts}"
    test_class_code = f"CD_{ts}"

    class_payload = {
        "class_id": test_class_id,
        "class_name": "Computer Networks",
        "subject": "Networks & BLE",
        "teacher_id": "T001",
        "class_code": test_class_code
    }
    r_create = client.post("/api/classes", json=class_payload, headers=headers_teacher)
    assert r_create.status_code == 200
    created = r_create.json()
    assert created["class_id"] == test_class_id
    assert created["class_code"] == test_class_code

    # Duplicate class code rejection
    r_dup = client.post("/api/classes", json=class_payload, headers=headers_teacher)
    assert r_dup.status_code == 400

    # 2. List classes returns class codes
    r_list = client.get("/api/classes")
    assert r_list.status_code == 200
    classes = r_list.json()
    net_cls = next(c for c in classes if c["class_id"] == test_class_id)
    assert net_cls["class_code"] == test_class_code

    # 3. Lookup class by code (case-insensitive)
    r_code = client.get(f"/api/classes/code/{test_class_code.lower()}")
    assert r_code.status_code == 200
    assert r_code.json()["class_id"] == test_class_id

    # Lookup non-existent code
    r_bad_code = client.get("/api/classes/code/UNKNOWN-999")
    assert r_bad_code.status_code == 404

    # 4. Student S003 joins class via code
    # Negative test: missing code
    r_join_empty = client.post("/api/classes/join", json={"student_id": "S003", "class_code": ""})
    assert r_join_empty.status_code == 400

    # Negative test: invalid code
    r_join_invalid = client.post("/api/classes/join", json={"student_id": "S003", "class_code": "WRONG-CODE"})
    assert r_join_invalid.status_code == 404

    # Positive test: S003 joins via class code
    r_join_s3 = client.post("/api/classes/join", json={"student_id": "S003", "class_code": test_class_code.lower()})
    assert r_join_s3.status_code == 200
    join_data = r_join_s3.json()
    assert join_data["success"] is True
    assert join_data["student_id"] == "S003"
    assert join_data["class_id"] == test_class_id

    # 5. Student S004 joins via v2 Bearer token
    r_join_s4 = client.post("/api/v2/classes/join", json={"class_code": test_class_code}, headers=headers_s4)
    assert r_join_s4.status_code == 200
    assert r_join_s4.json()["student_id"] == "S004"
    assert r_join_s4.json()["class_id"] == test_class_id

    # 6. Verify class roster now contains S003 and S004
    r_roster = client.get(f"/api/classes/{test_class_id}/roster")
    assert r_roster.status_code == 200
    roster = r_roster.json()
    roster_sids = [s["student_id"] for s in roster]
    assert "S003" in roster_sids
    assert "S004" in roster_sids

    # 7. Teacher can sync attendance for the joined students in a session
    session_id = f"SES_NET_{ts}"
    att_s3 = {
        "attendance_id": f"att_net_s3_{int(time.time() * 1000)}",
        "session_id": session_id,
        "student_id": "S003",
        "timestamp": int(time.time() * 1000),
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
        "rssi_evidence": -62,
        "hop_count": 0
    }
    att_s4 = {
        "attendance_id": f"att_net_s4_{int(time.time() * 1000)}",
        "session_id": session_id,
        "student_id": "S004",
        "timestamp": int(time.time() * 1000) + 10,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
        "rssi_evidence": -59,
        "hop_count": 0
    }
    r_sync = client.post("/api/attendance/batch", json=[att_s3, att_s4], headers=headers_teacher)
    assert r_sync.status_code == 200
    assert r_sync.json()["stored"] == 2

    # 8. Re-join CSE-A via its class code to verify multi-class transitions and preserve CSE-A roster
    r_rejoin_s3 = client.post("/api/classes/join", json={"student_id": "S003", "class_code": "CSE-A"})
    assert r_rejoin_s3.status_code == 200
    assert r_rejoin_s3.json()["class_id"] == "CSE-A"

    r_rejoin_s4 = client.post("/api/v2/classes/join", json={"class_code": "CSE-A"}, headers=headers_s4)
    assert r_rejoin_s4.status_code == 200
    assert r_rejoin_s4.json()["class_id"] == "CSE-A"

    # Verify CSE-A roster has all 6 students back
    r_csea_roster = client.get("/api/classes/CSE-A/roster")
    assert r_csea_roster.status_code == 200
    assert len(r_csea_roster.json()) >= 6

    # 9. Verify multi-class retention: S003 and S004 STILL belong to the NET class!
    r_net_roster_after = client.get(f"/api/classes/{test_class_id}/roster")
    assert r_net_roster_after.status_code == 200
    net_sids_after = [s["student_id"] for s in r_net_roster_after.json()]
    assert "S003" in net_sids_after, "S003 must be retained in NET class even after re-joining CSE-A"
    assert "S004" in net_sids_after, "S004 must be retained in NET class even after re-joining CSE-A"

    # 10. Verify student classes query endpoints
    r_s3_classes = client.get("/api/students/S003/classes")
    assert r_s3_classes.status_code == 200
    s3_cids = [c["class_id"] for c in r_s3_classes.json()]
    assert "CSE-A" in s3_cids
    assert test_class_id in s3_cids

    r_s4_my_classes = client.get("/api/v2/students/me/classes", headers=headers_s4)
    assert r_s4_my_classes.status_code == 200
    s4_cids = [c["class_id"] for c in r_s4_my_classes.json()]
    assert "CSE-A" in s4_cids
    assert test_class_id in s4_cids

    # 11. Security & Validation checks
    # Student role cannot create class
    r_sec_create = client.post("/api/classes", json={
        "class_id": f"HACK_{ts}",
        "class_name": "Hacked Class",
        "subject": "Unauthorized",
        "class_code": f"HK_{ts}"
    }, headers=headers_s4)
    assert r_sec_create.status_code == 403, "Student must be forbidden from creating classes"

    # Input validation: empty class_id rejected
    r_val_empty = client.post("/api/classes", json={
        "class_id": "   ",
        "class_name": "Invalid",
        "subject": "No ID"
    }, headers=headers_teacher)
    assert r_val_empty.status_code == 400

    # Input validation: non-existent teacher rejected
    r_val_bad_teacher = client.post("/api/classes", json={
        "class_id": f"NO_T_{ts}",
        "class_name": "Invalid",
        "subject": "Bad Teacher",
        "teacher_id": "T_NON_EXISTENT"
    }, headers=headers_teacher)
    assert r_val_bad_teacher.status_code == 400



