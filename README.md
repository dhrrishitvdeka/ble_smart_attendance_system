# BLE Smart Classroom Attendance System

A BLE-assisted attendance verification system (spec: `New Text Document.txt`).
The teacher laptop is the trusted root device and **final attendance authority**.
Students can never mark themselves PRESENT. BLE detection alone never equals presence.

## Repo layout

- `webapp/` — working browser simulation (no build step). Teacher + student + admin portals.
- `Backend/` — FastAPI cloud-sync API (idempotent on `attendance_id`). `pytest Backend/tests`.
- `TeacherApp/` — minimal .NET 8 teacher stub (`BleProtocol.cs` shares UUIDs with `shared/ble_config.json`).
- `StudentApp/` — Android manifest (BLE permissions) + `Protocol.kt` shared constants.
- `android-relay-ble/` — beacon payload codec + relay state machine (Kotlin) + Windows broadcaster (C#).
- `shared/ble_config.json` — single source of truth for UUIDs, `MAX_HOPS=2`, RSSI floors.
- `.github/workflows/` — `ci.yml` (JS syntax + backend tests) and Pages `deploy.yml`.

## Run the web simulation (recommended)

Serve over `http://localhost` so Web Bluetooth is available (file:// hides it):

```bat
start-webapp.bat
```

or manually: `python -m http.server 8080 --directory webapp`, then open
`http://localhost:8080/index.html` in Chrome/Edge.

## Run the backend

```bash
pip install -r Backend/requirements.txt
uvicorn Backend.main:app --reload
pytest Backend/tests -q
```

## Demo accounts

| Role    | ID     | Password  |
|---------|--------|-----------|
| Admin   | A001   | admin123  |
| Teacher | T001   | teach123  |
| Student | S001–S006 | stud123 |

## What is implemented (mapped to the spec)

- **Admin portal** — the only place teachers, classes, teacher schedules and
  student enrollments can be created. Each student is enrolled in exactly ONE
  selected class (never all classes) and can only attend that class's sessions.
  Teachers only see classes assigned/scheduled to them.
- **Real BLE** — in Chrome/Edge on HTTPS/localhost, DIRECT verification calls
  `navigator.bluetooth.requestDevice({ filters: [{ services: [attendance UUID] }] })`
  and records real RSSI when `watchAdvertisements` is permitted. Otherwise the
  position simulation is used. The BLE badge on the student home/scan screens
  always shows which mode is active.
- **Teacher portal** — login (salted SHA-256 password hashes), class select,
  START ATTENDANCE generating a cryptographically random temporary session ID,
  random nonce, and auto-expiration (10 min). Simulated GATT-peripheral
  capability check before starting.
- **Student portal** — login with registered-device binding; the attendance
  flow always uses the identity from the authenticated login session, never a
  typed-in ID. Screens: profile, BLE scan, verification, result, history.
- **BLE simulation** — RSSI per simulated position selected on the student
  home screen: near ≈ −56 dBm (STRONG), back ≈ −72 dBm (MODERATE),
  outside ≈ −95 dBm (fails `RSSI_FLOOR = −90`). Noise ±6 dBm.
  RSSI is treated strictly as *proximity evidence*, never exact distance.
- **Challenge-response** — random, single-use, session-bound challenge that
  expires in 30 s; response = SHA-256(challenge ‖ device_secret), verified
  teacher-side. Request IDs prevent replays; duplicates rejected per session.
- **Relay** — opt-in, session-only relay mode. Relay messages carry message ID,
  hop count (MAX_HOPS = 2), and are forwarded without modification. Relays
  never authorize attendance. Shortest reliable route preferred. If no relay:
  NOT VERIFIED (never auto-absent).
- **Decision chain** — authentication → registered device → current session →
  BLE communication → proximity evidence → valid challenge → no duplicate →
  ELIGIBLE → **teacher finalizes** → PRESENT.
- **Dashboard** — live roster with status, route (DIRECT / VIA student +
  hops), RSSI evidence, counts, manual review override, finalize button,
  audit log.
- **Offline-first storage + sync** — localStorage stands in for SQLite;
  toggle internet offline/online; sync pushes only unsynced records keyed by
  unique `attendance_id` (idempotent, no duplicates).

## Try these scenarios

1. Teacher login → START ATTENDANCE → note the session ID.
2. Log in as S001 (position: near) → Scan → VERIFY MY PRESENCE → watch the
   full challenge-response chain → ELIGIBLE on dashboard → FINALIZE.
3. Change S002's position to *back of classroom* → direct link is MODERATE but works.
4. Change S003's position to *outside classroom* → VERIFY fails (no direct link) →
   enable relay mode on S001 → S003 Scan → VERIFY VIA RELAY (or the TRY RELAY PATH
   button) → hop 2 via S001 — still requires full verification; relay never proves presence.
5. Wait for session expiry or toggle internet and use Sync to Cloud (idempotent
   `POST /api/attendance`, see `Backend/`).

## Limitations (per spec §29)

This is a **BLE-assisted attendance verification** demo, not proof of physical
presence:

- Browser JS cannot access real BLE advertising/GATT-server peripherals; all
  radio behaviour here is simulated.
- Real-world RSSI depends on walls, people, furniture, phone orientation,
  interference and hardware — it cannot measure distance.
- Android background scanning/advertisting restrictions, laptop peripheral-mode
  support variability, and phone handoff are documented concerns of the real
  system (C# `GattServiceProvider` + Kotlin `BluetoothLeScanner`) that this web
  simulation abstracts away.
- A successful relay chain proves connectivity through another student's
  device, not that the destination student is inside the classroom.

The production architecture (C# .NET 8 teacher app, Kotlin student app,
FastAPI backend) follows the phased plan in the spec document.
