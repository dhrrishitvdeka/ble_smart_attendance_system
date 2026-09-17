# BLE Smart Classroom Attendance System

A BLE-assisted attendance verification system for classrooms. The teacher's
device is the trusted root and the **final attendance authority** — students
can never mark themselves present, and a Bluetooth signal alone is never
treated as presence.

> **This is an educational demonstration.** The browser demo explicitly labels
> proximity and relay hops as simulated. The native BLE apps require physical
> teacher hardware and are not required for the local demo.

## Components

| Component | Directory | Technology | Status |
| :--- | :--- | :--- | :--- |
| Local demo (start here) | `Backend/` + `webapp/demo.html` | FastAPI + browser | Working, browser-tested |
| Legacy browser simulation | `webapp/index.html` | Vanilla JS | Working, syncs with backend |
| Cloud sync API | `Backend/` | FastAPI / SQLAlchemy | Authentication enforced; pytest coverage |
| Teacher desktop | `TeacherApp/` | C# / .NET 10 (Windows) | MSTest coverage; hardware validation required |
| Student mobile | `StudentApp/` | Android / Kotlin | Source only (see limitations) |
| BLE relay reference | `android-relay-ble/` | Kotlin / C# | Source only (see limitations) |

## Quick start (local demo)

Requires Python 3.10+ with `venv`. Run these commands from the repository root.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Backend/requirements.txt
.\start-webapp.bat
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r Backend/requirements.txt
chmod +x start-webapp.sh
./start-webapp.sh
```

Dependencies are downloaded during installation; after that the demo runs locally.
GitHub Pages cannot host this Python backend; no static deployment workflow is included.

Then open **http://127.0.0.1:8000** in Chrome/Edge. Use separate tabs for each
role; every tab signs in independently against the local backend.

Demo accounts (created on first run):

| Role | ID | Password |
| :--- | :--- | :--- |
| Admin | `A001` | `admin123` |
| Teacher | `T001` | `teach123` |
| Students | `S001`–`S006` | `stud123` |

Data persists in `local_demo.db`. Delete it to reset the demo.

### Demo workflow

1. **Admin** creates a class (ID, name, subject, join code).
2. **Students** join with the join code.
3. **Teacher** starts a 10-minute session for their class.
4. **Students** verify: choose a simulated position. `Outside` + direct is
   rejected; a classmate must enable **relay** first, then you select them as
   the relay route.
5. Each verification issues a single-use, expiring challenge from the backend;
   the browser answers it with SHA-256. This demonstrates the challenge
   lifecycle — it is **not** hardware attestation.
6. **Teacher** finalizes: `ELIGIBLE` becomes `PRESENT`, everyone else stays
   `NOT_VERIFIED` (never auto-absent).

## Legacy browser simulation

`webapp/index.html` is the original multi-screen localStorage simulation. It
now syncs to the backend with the same-origin API using authenticated teacher
and student tokens. Start the same server and open
`http://127.0.0.1:8000/webapp/index.html`.

## Cloud sync API

```bash
python -m pip install -r Backend/requirements.txt
python -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000
pytest Backend/tests tests_e2e_integration.py -q
```

Authentication is always enforced (`ENFORCE_AUTH`). Set `JWT_SECRET` in
production; otherwise a random secret is generated per process, invalidating
tokens on restart. Passwords are PBKDF2-HMAC-SHA256 (600k iterations).
CORS is limited to `CORS_ORIGINS` (localhost defaults).

## Native teacher app (Windows)

```powershell
dotnet test TeacherApp.Tests
dotnet run --project TeacherApp -- --auto-demo
```

Requires the .NET 10 SDK and Windows. The GATT server requires a Bluetooth
adapter with peripheral role support. Simulation is enabled explicitly with
`--auto-demo` or `--simulate`; missing hardware does not enable it automatically.

## Android apps

`StudentApp/` and `android-relay-ble/` are source-only references in this
repository. Building them requires the Android SDK and Gradle, which are not
bundled. The Android BLE client does not fabricate discovery or handshake
success when a teacher beacon is unreachable. These reference sources are not
validated for production attendance or hardware interoperability.

## Automated tests

| Suite | Command |
| :--- | :--- |
| Full test suite (Backend, e2e, browser acceptance) | `pytest -q` (auto-serves background test instance) |
| Backend API + demo workflow | `pytest Backend/tests tests_e2e_integration.py -q` |
| Webapp JS unit regression | `node --test webapp/regression.test.cjs` |
| Native teacher (.NET) | `dotnet test TeacherApp.Tests` |

Install development dependencies with `python -m pip install -r requirements-dev.txt`
and Chromium with `python -m playwright install chromium` before browser tests.
Browser tests automatically spin up an isolated background test server on a temporary database
when run via `pytest`. For manual isolated runs:

```powershell
$env:DATABASE_URL = "sqlite:///./browser_test.db"
.\.venv\Scripts\python.exe -m uvicorn Backend.main:app --host 127.0.0.1 --port 8017 --workers 1
```

In another PowerShell terminal:

```powershell
$env:DEMO_URL = "http://127.0.0.1:8017"
.\.venv\Scripts\python.exe -m pytest webapp/test_demo_browser.py webapp/test_legacy_browser.py -q
```

Stop the server before deleting `browser_test.db`. Backend pytest runs use a
temporary database unless `DATABASE_URL` is already set; unset it before running
backend tests. JavaScript syntax checks use `node --check webapp/<filename>.js`.

CI runs backend, JavaScript, and Windows teacher tests on pushes to `master` or
`main` and on pull requests (`.github/workflows/ci.yml`). Browser acceptance and
Android hardware checks are currently manual.

## How verification works

Authentication → registered device → active session → single-use
challenge-response → proximity evidence (RSSI, never exact distance) →
duplicate check → `ELIGIBLE` → **teacher finalizes** → `PRESENT`.
Any failure means `NOT VERIFIED`, never automatic absence.

## Honest limitations

- The browser demo is a simulation; it cannot prove physical presence.
- The Android apps are not buildable from this repository alone (no Gradle
  wrapper or SDK) and have not been verified on hardware in this state.
- Native credential provisioning and relay transport are incomplete. Android
  demo secrets are not provisioned from the teacher database; relay references
  do not provide a complete end-to-end forwarding implementation.
- Native credential storage, callback threading, and device-specific Bluetooth
  behavior require further engineering and review before real deployment.
- The legacy webapp keeps verification state in browser localStorage; the
  backend-backed demo is the authoritative workflow.
- RSSI is evidence, not distance. Relay forwarding proves connectivity, never
  presence.

## Contributing

Open an issue describing the problem or proposed change before a large rewrite.
Keep pull requests focused, include regression tests, and run the relevant suites
above. Document hardware and SDK versions for native changes. Do not commit local
databases, credentials, device keys, build outputs, or real student records.

## Security and privacy

This project is an educational prototype, not a production attendance service.
Demo accounts are seeded automatically with public passwords. Do not expose an
unmodified instance to the Internet or use it with real student data. A deployment
requires removal of demo accounts, HTTPS, a strong `JWT_SECRET`, restricted CORS,
and an independent review of authorization, retention, and consent requirements.

Older revisions used a public fallback JWT signing key. Rotate that key and
invalidate existing tokens if any deployment used it. Current versions generate
a runtime secret when `JWT_SECRET` is unset. Native sync trusts authenticated
teachers for unknown session IDs; it does not independently attest BLE proximity.

Report vulnerabilities privately through GitHub's private vulnerability reporting
feature if enabled. Do not post credentials, personal data, or sensitive details
in public issues; request a private contact channel instead.

## License

MIT — see [LICENSE](LICENSE).
