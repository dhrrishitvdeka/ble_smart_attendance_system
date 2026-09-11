# BLE Smart Classroom Attendance System

A BLE-assisted attendance verification system for classrooms. The teacher's
device is the trusted root and the **final attendance authority** — students
can never mark themselves present, and detecting a Bluetooth signal alone is
never treated as presence.

**Live demo (no install):**
https://dhrrishitvdeka.github.io/ble_smart_attendance_system/

Use Chrome or Edge on a laptop/desktop for the full experience.

---

## 1. Log in

Pick your portal on the home page and sign in with a demo account:

| Portal  | ID          | Password   |
|---------|-------------|------------|
| Admin   | `A001`      | `admin123` |
| Teacher | `T001`      | `teach123` |
| Student | `S001`–`S006` | `stud123`  |

> Tip: the credentials are also listed under **Spotlight** on the home page —
> click any of them to copy it.

---

## 2. Admin — first-time setup

Only the admin can create teachers, classes, schedules and student enrollments.
Do them **in this order**:

1. **Add Teacher** — enter an ID (e.g. `T002`), name and password.
2. **Add Class** — enter a class ID (e.g. `CSE-B`), a subject, and assign it to
   a teacher.
3. **Schedule a Class to a Teacher** — pick the class and teacher, add day/time.
   A teacher only ever sees classes assigned or scheduled to them.
4. **Enroll Student** — enter the student details and choose **one** class.
   Every student belongs to exactly one class and can only attend that
   class's sessions. The device ID (`DEV-<student_id>`) is registered
   automatically.

The tables at the bottom always show the current teachers, classes, schedules
and enrollments.

## 3. Teacher — run attendance

1. Log in and pick your class, then press **Start Attendance**. This creates a
   random temporary session ID + nonce. The session **expires automatically
   after 10 minutes**.
2. Watch the **live roster**: each student shows `NOT VERIFIED`, `ELIGIBLE`
   (passed all checks, awaiting you) or `PRESENT`, plus their route
   (`DIRECT` or `VIA <classmate>`) and RSSI proximity evidence.
3. Optionally use **Mark Present** on individual rows for manual review.
4. Press **Finalize Attendance** to confirm everyone eligible. Students who
   never verified stay `NOT VERIFIED` — nobody is auto-marked absent.
5. **End Session** when the class is over.
6. Connectivity: use **Toggle Internet** + **Sync to Cloud** to push records to
   the backend. Syncing is idempotent — re-syncing never creates duplicates.

## 4. Student — verify your presence

1. Log in. Your attendance is bound to your **registered device** and your
   login session — you can't type in someone else's ID.
2. Set your **simulated position** on the home screen:
   - `Near` — strong signal, direct verification works.
   - `Back of classroom` — moderate signal, direct verification works.
   - `Outside classroom` — no direct link; you must use the relay path.
3. Press **Scan for Class Session**, then **Verify My Presence**. You'll see
   each check pass: identity → device → session → challenge → proximity.
4. The result is `VERIFICATION COMPLETE` (now `ELIGIBLE`, waiting for the
   teacher to finalize) or `NOT VERIFIED` with the reason. Check
   **Attendance History** anytime for your past records.

### Can't reach the teacher? Use a relay

1. Ask a classmate with a working connection to tick
   **"Act as BLE relay for classmates"** on their home screen
   (relay mode only works during an active session).
2. On your phone, scan and press **Verify via Relay** (or **Try Relay Path**).
   Your request travels Teacher → classmate → you (2 hops max) and still goes
   through every verification check. Relays only forward messages — they prove
   connectivity, not presence, and can never mark attendance.

### Real Bluetooth vs simulation

The badge on the student home/scan screens always tells you the active mode:

- **Real BLE available** (Chrome/Edge over `https://` or `http://localhost`):
  verification attempts a real Web Bluetooth device connection.
- **Simulation in use** (any other setup): the position-based radio simulation
  is used instead. This is why you should open the app via `http://localhost`
  (see below), never as a downloaded file.

---

## 5. Run it on your own machine

```bat
start-webapp.bat
```

or manually:

```bash
python -m http.server 8080 --directory webapp
# open http://localhost:8080/index.html in Chrome/Edge
```

> Opening `index.html` directly as a file (`file://`) works for clicks but
> disables real Web Bluetooth — always serve over localhost.

### Optional: cloud-sync backend

```bash
pip install -r Backend/requirements.txt
uvicorn Backend.main:app --reload   # sync API on http://localhost:8000
pytest Backend/tests -q             # 3 tests, all passing
```

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| "No active classroom session found" | The teacher hasn't pressed Start Attendance (or it expired after 10 min). |
| "You are enrolled in X" | That session belongs to another class — log in as a student of that class. |
| Direct verify fails but you're "near" | Check the BLE badge; outside/localhost or permissions may force simulation — set position to Near. |
| "No relay available" | No classmate has relay mode on for this session, or you're not in the same class. |
| Page looks outdated after an update | Hard-refresh: `Ctrl+Shift+R` (or incognito). |
| Start over completely | Clear the site's local storage in your browser (the demo database lives there), then reload to re-seed demo data. |

## 7. How verification works (the short version)

Authentication → registered device → current session → BLE communication →
proximity evidence (RSSI, never exact distance) → single-use challenge-response
→ duplicate check → `ELIGIBLE` → **teacher finalizes** → `PRESENT`.
Anything failing means `NOT VERIFIED`, never automatic absence.

## 8. For developers

- `webapp/` — the full working simulation (no build step): `core.js` (DB,
  crypto, seed), `admin.js`, `teacher.js`, `student.js`.
- `Backend/` — FastAPI sync API + tests.
- `TeacherApp/` — .NET 8 teacher stub; `StudentApp/` — Android BLE
  permission manifest + protocol constants (native apps are stubs; the web
  simulation is the complete implementation).
- `android-relay-ble/` — BLE beacon codec + relay state machine (Kotlin) and
  Windows broadcaster (C#). `shared/ble_config.json` is the single source of
  truth for UUIDs, `MAX_HOPS = 2` and radio thresholds.
- Full spec: `New Text Document.txt`. Known honest limits of BLE/RSSI,
  background scanning and relay security are documented there (§29) — this
  system assists verification; it does not mathematically prove physical
  presence.
