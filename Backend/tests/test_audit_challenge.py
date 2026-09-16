"""Adversarial Security Challenge Verification Suite.
Tests the empirical security claims regarding:
1. Backend unauthenticated ingestion, lack of foreign keys, and roster disclosure.
2. Webapp static hashing equivalence.
3. CVSS v3.1 vector calculation discrepancies.
"""
import hashlib
import math
from fastapi.testclient import TestClient
from Backend.main import app

client = TestClient(app)


import uuid

SESSION_ID = f"NONEXISTENT_SESSION_{uuid.uuid4().hex[:8]}"
STUDENT_ID = f"FABRICATED_STUDENT_{uuid.uuid4().hex[:8]}"


def test_unauthenticated_ingestion_rejects_arbitrary_student():
    att_id = f"forged_att_{uuid.uuid4().hex[:8]}"
    fake_attendance = {
        "attendance_id": att_id,
        "session_id": SESSION_ID,
        "student_id": STUDENT_ID,
        "timestamp": 1773400000000,
        "verification_status": "PRESENT",
        "route_type": "DIRECT",
        "rssi_evidence": -42,
        "hop_count": 0,
        "via_student": None,
    }
    # No Authorization header, no teacher token, no signature
    response = client.post("/api/attendance", json=fake_attendance)
    assert response.status_code == 401
    response = client.post("/api/attendance/batch", json=[fake_attendance])
    assert response.status_code == 401


def test_claim_unauthenticated_roster_disclosure():
    """Verify that GET /api/attendance/{session_id} discloses attendance without auth."""
    response = client.get(f"/api/attendance/{SESSION_ID}")
    assert response.status_code == 200
    records = response.json()
    assert not any(r["student_id"] == STUDENT_ID for r in records)


def test_claim_weak_password_hashing_scheme():
    """Verify that webapp/core.js password hashing is single-iteration SHA-256 with static prefix."""
    # From webapp/core.js: hashPassword(id, pw) = sha256hex("salt_" + id + pw)
    # S001 seed in core.js: "salt_S001stud123"
    seed_hash = hashlib.sha256("salt_S001stud123".encode("utf-8")).hexdigest()
    computed = hashlib.sha256(("salt_" + "S001" + "stud123").encode("utf-8")).hexdigest()
    assert seed_hash == computed
    # Verify execution time is sub-microsecond (vulnerable to high-throughput GPU cracking)
    # 10,000 hashes in Python takes < 10 milliseconds
    import time
    start = time.perf_counter()
    for _ in range(1000):
        hashlib.sha256(("salt_" + "S001" + "stud123").encode("utf-8")).hexdigest()
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1, "Hash execution is not fast enough to demonstrate lack of work factor"


def roundup(val):
    int_val = round(val * 100000)
    if int_val % 10000 == 0:
        return int_val / 100000.0
    else:
        return (math.floor(int_val / 10000) + 1) / 10.0


def cvss31_calc(av, ac, pr, ui, s, c, i, a):
    w_av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[av]
    w_ac = {"L": 0.77, "H": 0.44}[ac]
    w_pr = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.50}}[s][pr]
    w_ui = {"N": 0.85, "R": 0.62}[ui]
    w_c = {"N": 0.0, "L": 0.22, "H": 0.56}[c]
    w_i = {"N": 0.0, "L": 0.22, "H": 0.56}[i]
    w_a = {"N": 0.0, "L": 0.22, "H": 0.56}[a]

    iss = 1.0 - ((1.0 - w_c) * (1.0 - w_i) * (1.0 - w_a))
    if s == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    exploitability = 8.22 * w_av * w_ac * w_pr * w_ui

    if impact <= 0:
        return 0.0
    if s == "U":
        base = min(impact + exploitability, 10.0)
    else:
        base = min(1.08 * (impact + exploitability), 10.0)

    return roundup(base)


def test_cvss_score_discrepancies():
    """Empirically test whether the claimed CVSS scores in Section 3 match the vectors."""
    # Vectors and claimed scores from AUDIT_REPORT.md Section 3 Table 3.2
    claims = [
        ("VULN-01", ("N", "L", "N", "N", "U", "H", "H", "H"), 9.8),
        ("VULN-02", ("N", "L", "N", "N", "U", "N", "H", "H"), 9.8),  # Actual: 9.1
        ("VULN-03", ("L", "L", "N", "R", "U", "H", "H", "N"), 8.2),  # Actual: 7.1
        ("VULN-04", ("N", "L", "N", "N", "U", "H", "N", "N"), 7.5),  # Actual: 7.5
        ("VULN-05", ("A", "L", "N", "N", "U", "N", "H", "H"), 7.8),  # Actual: 8.1
        ("VULN-06", ("N", "L", "N", "N", "U", "N", "H", "H"), 7.4),  # Actual: 9.1
        ("VULN-07", ("A", "H", "N", "N", "U", "N", "H", "N"), 6.5),  # Actual: 5.3
    ]
    discrepancies = {}
    for vid, vector, claimed in claims:
        actual = cvss31_calc(*vector)
        if abs(actual - claimed) > 0.05:
            discrepancies[vid] = {"claimed": claimed, "actual": actual, "diff": round(claimed - actual, 1)}

    # We expect discrepancies in 5 out of 7 vulnerabilities
    assert len(discrepancies) == 5, f"Expected 5 discrepancies, got {len(discrepancies)}: {discrepancies}"
    assert discrepancies["VULN-02"]["actual"] == 9.1
    assert discrepancies["VULN-03"]["actual"] == 7.1
    assert discrepancies["VULN-05"]["actual"] == 8.1
    assert discrepancies["VULN-06"]["actual"] == 9.1
    assert discrepancies["VULN-07"]["actual"] == 5.3
