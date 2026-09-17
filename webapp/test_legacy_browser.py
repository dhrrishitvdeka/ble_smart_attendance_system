import os
import uuid

BASE_URL = os.environ.get("DEMO_URL", "http://127.0.0.1:8000")
from playwright.sync_api import sync_playwright, expect


def test_legacy_same_origin_sync():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        requests = []
        page.on("request", lambda req: requests.append(req.url) if "/api/" in req.url else None)
        page.goto(BASE_URL + "/webapp/index.html")
        page.wait_for_function("typeof DB !== 'undefined' && DB && DB.teachers.length > 0")
        page.evaluate("document.getElementById('t-id').value='T001'; document.getElementById('t-pass').value='teach123'")
        page.evaluate("teacherLogin()")
        attendance_id = "legacy_" + uuid.uuid4().hex
        page.evaluate("""id => {
          DB.online = true;
          DB.attendance.push({ attendance_id: id, session_id: 'LEGACY_BROWSER', student_id: 'S001',
            timestamp: Date.now(), verification_status: 'PRESENT', route_type: 'DIRECT',
            rssi_evidence: -60, hop_count: 0, synced: false });
          saveDB();
        }""", attendance_id)
        page.evaluate("syncToCloud()")
        expect(page.locator("#sync-log")).to_contain_text("stored=1")
        assert page.evaluate("id => DB.attendance.find(a => a.attendance_id === id).synced", attendance_id)
        assert requests and all(url.startswith(BASE_URL + "/") for url in requests)
        browser.close()


def test_legacy_student_join_reaches_backend():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        auth = page.request.post(BASE_URL + "/api/auth/login", data={"username": "T001", "password": "teach123"}).json()
        code = "JOIN-" + uuid.uuid4().hex[:8].upper()
        created = page.request.post(BASE_URL + "/api/classes", headers={"Authorization": "Bearer " + auth["access_token"]},
            data={"class_id": code, "class_name": code, "subject": "Browser test", "teacher_id": "T001", "class_code": code})
        assert created.status == 200
        page.goto(BASE_URL + "/webapp/index.html")
        page.wait_for_function("typeof DB !== 'undefined' && DB && DB.students.length > 0")
        page.evaluate("document.getElementById('st-id').value='S001'; document.getElementById('st-pass').value='stud123'")
        page.evaluate("studentLogin()")
        page.locator("#st-join-code").fill(code)
        with page.expect_response(lambda r: r.url.endswith("/api/classes/join")) as pending:
            page.evaluate("joinClassByCode()")
        assert pending.value.status == 200, pending.value.text()
        expect(page.locator("#st-join-msg")).to_contain_text("locally and in the backend")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/classes/join", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Unavailable"}'))
        page.locator("#st-join-code").fill(code)
        page.evaluate("joinClassByCode()")
        expect(page.locator("#st-join-msg")).to_have_text(
            "Local simulation enrollment only. Backend enrollment failed: Backend rejected enrollment (HTTP 503)."
        )
        page.unroute("**/api/classes/join")
        page.locator("#st-join-code").fill(code)
        page.evaluate("joinClassByCode()")
        expect(page.locator("#st-join-msg")).to_contain_text("locally and in the backend")
        assert not errors, errors
        browser.close()
