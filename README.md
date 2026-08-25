# BLE Smart Classroom Attendance System — Web Simulation

A browser-based simulation of the BLE-assisted attendance system described in
`New Text Document.txt`. The teacher laptop is simulated in-browser as the
trusted root device and **final attendance authority**. Students can never
mark themselves PRESENT.

## Run

Open `webapp/index.html` in any modern browser (Chrome/Edge recommended).
No server or build step required.

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
- **Real BLE (online mode)** — with internet toggled ON in Chrome/Edge
  (HTTPS or localhost), verification attempts a real Web Bluetooth GATT
  connection to a nearby device and records its RSSI when available.
  Offline mode uses the radio simulation.
- **Teacher portal** — login (salted SHA-256 password hashes), class select,
  START ATTENDANCE generating a cryptographically random temporary session ID,
  random nonce, and auto-expiration (10 min). Simulated GATT-peripheral
  capability check before starting.
- **Student portal** — login with registered-device binding; the attendance
  flow always uses the identity from the authenticated login session, never a
  typed-in ID. Screens: profile, BLE scan, verification, result, history.
- **BLE simulation** — RSSI per simulated position (near / back of room /
  outside) with noise. RSSI is treated strictly as *proximity evidence*, never
  exact distance.
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
3. Set S002 to *back of classroom* → direct link may be weak/moderate but works.
4. Set S003 to *outside classroom* → no direct link → enable relay mode on an
   already-present student (e.g. S001) → S003 uses the RELAY path (hop 2) —
   still requires full verification; relay never proves presence.
5. Wait for session expiry or toggle internet and use Sync to Cloud.

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
