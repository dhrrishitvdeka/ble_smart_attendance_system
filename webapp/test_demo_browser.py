import os
import uuid
from playwright.sync_api import sync_playwright, expect


def test_browser_demo():
    url = os.environ.get("DEMO_URL", "http://127.0.0.1:8765")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        errors = []
        pages = {}
        for user, password in (("A001", "admin123"), ("T001", "teach123"), ("S001", "stud123"), ("S002", "stud123"), ("S003", "stud123")):
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator("#username").fill(user)
            page.locator("#password").fill(password)
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator("#message")).to_contain_text("Signed in")
            pages[user] = page
        admin, teacher, student, relay, outside = [pages[u] for u in ("A001", "T001", "S001", "S002", "S003")]
        code = "BROWSER-" + uuid.uuid4().hex[:8].upper()
        for element, value in (("class-id", code), ("class-name", "Browser demo"), ("subject", "Acceptance"), ("class-code", code)):
            admin.locator("#" + element).fill(value)
        admin.get_by_role("button", name="Create class", exact=True).click()
        expect(admin.locator("#message")).to_have_text("Class created.")
        for page in (student, relay, outside):
            page.locator("#join-code").fill(code)
            page.get_by_role("button", name="Join class", exact=True).click()
            expect(page.locator("#message")).to_have_text("Class joined.")
        teacher.locator("#refresh").click()
        expect(teacher.locator("#message")).to_have_text("Updated.")
        teacher.locator("#class-select").select_option(code)
        teacher.locator("#start").click()
        expect(teacher.locator("#message")).to_contain_text("Session started")
        session = teacher.locator("#session-select").input_value()
        for page in (student, relay, outside):
            page.locator("#refresh").click()
            expect(page.locator("#message")).to_have_text("Updated.")
            page.locator("#session-select").select_option(session)
            expect(page.locator("#message")).to_have_text("Updated.")
        student.locator("#verify").click()
        expect(student.locator("#message")).to_contain_text("ELIGIBLE")
        student.locator("#verify").click()
        expect(student.locator("#message")).to_contain_text("already recorded")
        outside.locator("#position").select_option("outside")
        outside.locator("#verify").click()
        expect(outside.locator("#message")).to_contain_text("below threshold")
        relay.locator("#relay-on").click()
        expect(relay.locator("#message")).to_contain_text("relay enabled")
        outside.locator("#refresh").click()
        expect(outside.locator("#message")).to_have_text("Updated.")
        outside.locator("#relay").select_option("S002")
        outside.locator("#verify").click()
        expect(outside.locator("#message")).to_contain_text("ELIGIBLE")
        teacher.locator("#finalize").click()
        expect(teacher.locator("#message")).to_contain_text("Finalized 2")
        expect(teacher.locator("#attendance")).to_contain_text("PRESENT")
        for page in (student, outside):
            page.locator("#refresh").click()
            expect(page.locator("#message")).to_have_text("Updated.")
            expect(page.locator("#attendance")).to_contain_text("PRESENT")
            assert page.locator("#attendance tr").count() == 1
        assert not errors, errors
        browser.close()
