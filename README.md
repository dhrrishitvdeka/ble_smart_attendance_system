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
| Cloud sync API | `Backend/` | FastAPI / SQLAlchemy | Hardened, 44 pytest tests |
| Teacher desktop | `TeacherApp/` | C# / .NET (Windows) | Compiles; 40 MSTest tests pass |
| Student mobile | `StudentApp/` | Android / Kotlin | Source only (see limitations) |
| BLE relay reference | `android-relay-ble/` | Kotlin / C# | Source only (see limitations) |

## Quick start (local demo)

Requires Python 3.10+.

```bat
start-webapp.bat
```

This installs nothing by itself — install dependencies once first:

```bat
python -m pip install -r Backend/requirements.txt
```

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

The GATT server requires a Bluetooth adapter with peripheral role support; on
machines without one the app runs in simulated verification mode.

## Android apps

`StudentApp/` and `android-relay-ble/` are source-only references in this
repository. Building them requires the Android SDK and Gradle, which are not
bundled. The Android BLE client falls back to a simulated handshake when no
teacher beacon is reachable — treat its results as simulation, not proximity
proof.

## Automated tests

| Suite | Command |
| :--- | :--- |
| Backend API + demo workflow | `pytest Backend/tests tests_e2e_integration.py -q` |
| Browser acceptance (5 tabs) | `python -m pytest webapp/test_demo_browser.py -q` (needs `pip install playwright` + `python -m playwright install chromium`, server running) |
| Legacy browser sync | `python -m pytest webapp/test_legacy_browser.py -q` |
| Webapp JS unit regression | `node --test webapp/regression.test.cjs` |
| Native teacher | `dotnet test TeacherApp.Tests` |

CI runs the backend and webapp jobs on every push (`.github/workflows/ci.yml`).

## How verification works

Authentication → registered device → active session → single-use
challenge-response → proximity evidence (RSSI, never exact distance) →
duplicate check → `ELIGIBLE` → **teacher finalizes** → `PRESENT`.
Any failure means `NOT VERIFIED`, never automatic absence.

## Honest limitations

- The browser demo is a simulation; it cannot prove physical presence.
- The Android apps are not buildable from this repository alone (no Gradle
  wrapper or SDK) and have not been verified on hardware in this state.
- The legacy webapp keeps verification state in browser localStorage; the
  backend-backed demo is the authoritative workflow.
- RSSI is evidence, not distance. Relay forwarding proves connectivity, never
  presence.

## License

MIT — see [LICENSE](LICENSE).
