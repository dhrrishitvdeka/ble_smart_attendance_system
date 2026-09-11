# Project Architecture, Feature Inventory & Milestone Plan
**BLE Smart Classroom Attendance System**

---

## 1. System Vision & Architecture Summary

The **BLE Smart Classroom Attendance System** is an offline-first, cyber-physical attendance verification platform designed for higher education environments. Its foundational principle is that the instructor's device serves as the **trusted root authority** and the sole decider of attendance. Physical proximity to the instructor is verified via Bluetooth Low Energy (BLE), assisted by an ephemeral cryptographic challenge-response exchange. In large lecture halls where direct line-of-sight RF signals cannot reach the back rows, student devices operate as intermediate multi-hop relays (up to 2 hops) to extend the reach of the attendance session without compromising verification integrity.

$$\text{Attendance Verified} \iff \text{Auth(Student)} \land \text{Device(Bound)} \land \text{Session(Active)} \land \text{Proximity(BLE)} \land \text{Response(Signed)} \land \text{Teacher(Finalized)}$$

```
 +───────────────────────────────────────────────────────────────────────────────────────────+
 │                                     TEACHER ROOT HOST                                     │
 │  TeacherApp/ (C# / .NET 8)                                                                │
 │  - Session Authority & Nonce Generator                                                    │
 │  - Local SQLite Relational Store (7 tables)                                               │
 │  - BLE GATT Server (Primary Service: a5e8c0de-0001-4b7d-9c11-000000000001)                │
 │  - Offline Verification Engine & Live Roster UI                                           │
 +──────────────────────────────┬────────────────────────────┬───────────────────────────────+
                                │                            │
                Direct BLE GATT │            Direct BLE GATT │
                (Hop Count = 0) │            (Hop Count = 0) │
                                ▼                            ▼
  +───────────────────────────────+            +───────────────────────────────+
  │      STUDENT A (DIRECT)       │            │      STUDENT C (DIRECT)       │
  │  StudentApp/ (Android Kotlin) │            │  StudentApp/ (Android Kotlin) │
  │  - Enrolled: Single Class     │            │  - Enrolled: Single Class     │
  │  - Bound Device Secret        │            │  - Bound Device Secret        │
  │  - Direct GATT Client         │            │  - Direct GATT Client         │
  +───────────────┬───────────────+            +───────────────────────────────+
                  │
  Relayed Beacon  │  Uplink GATT Proxy
  (Hop Count = 1) │  (Multi-hop return)
                  ▼
  +───────────────────────────────+
  │      STUDENT B (RELAYED)      │
  │  StudentApp/ (Android Kotlin) │
  │  - Beyond direct RF range     │
  │  - Verified via Student A     │
  │  - Preserves end-to-end auth  │
  +───────────────────────────────+
                                │
                                │ Idempotent Batch HTTPS Sync
                                ▼
 +───────────────────────────────────────────────────────────────────────────────────────────+
 │                                   CENTRAL CLOUD BACKEND                                   │
 │  Backend/ (Python FastAPI / SQLAlchemy / SQLite)                                          │
 │  - Institutional Relational Store & Teacher JWT Authentication                            │
 │  - POST /api/attendance & POST /api/attendance/batch                                      │
 │  - Cross-Session Audit Trails & Campus LMS Export                                         │
 +───────────────────────────────────────────────────────────────────────────────────────────+
```

### Module Boundaries & Responsibilities

1. **Teacher Host (`TeacherApp/`)**:
   - **Boundary**: Runs locally on instructor workstation/laptop (Windows 10/11 .NET 8 runtime).
   - **Responsibilities**: Creates ephemeral session keys (`session_id`, `nonce`), hosts GATT server, evaluates student proximity telemetry, validates challenge responses against registered student secrets, prevents duplicates, stores records in local SQLite, and provides live teacher review and finalization.
2. **Student Client (`StudentApp/`)**:
   - **Boundary**: Runs on student mobile devices (Android 8.0+ / API 26+).
   - **Responsibilities**: Enforces student login, binds identity to registered device hardware, scans for teacher BLE sessions, connects via GATT, signs challenges using hardware-protected device secrets, and displays verification status and personal history.
3. **BLE Relay Engine (`android-relay-ble/`)**:
   - **Boundary**: Low-level cross-platform BLE protocol and state machine components.
   - **Responsibilities**: Binary packet serialization (`PayloadCodec.kt`), beacon advertisement emission (`BleTeacherBroadcaster.cs`), and multi-hop forwarding state machine (`AttendanceRelayStateMachine.kt`) enforcing `MAX_HOPS = 2`.
4. **Interactive Browser Simulation (`webapp/`)**:
   - **Boundary**: Standalone client-side web application (HTML5, Vanilla JS, CSS3).
   - **Responsibilities**: Zero-install interactive demonstration of the system workflows (Admin, Teacher, Student) using simulated radio propagation and browser `localStorage`.
5. **Central Synchronization Backend (`Backend/`)**:
   - **Boundary**: Cloud-hosted REST API service (FastAPI, SQLite/PostgreSQL).
   - **Responsibilities**: Secure ingestion of finalized attendance rosters, deduplication, and persistence for university-wide reporting.

---

## 2. Comprehensive Feature Inventory & Implementation Audit

This inventory maps every capability defined across `New Text Document.txt` (System Specification), `README.md`, and the three specialized explorer audit reports.

| Subsystem | Feature / Capability | Spec Ref | Codebase Location | Actual Status | Architectural Gap / Deviation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TeacherApp** | Teacher Authentication | §2.1 | `TeacherApp/Program.cs` | **MISSING** | No login, credential store, or role validation. |
| **TeacherApp** | Class & Schedule Selection | §2.2 | `TeacherApp/Program.cs` | **MISSING** | Hardcoded console run; no class selection. |
| **TeacherApp** | Session Generation & Nonce | §2.3, §2.4 | `TeacherApp/Program.cs:6-7` | **PARTIAL STUB** | Generates 4-byte ID and 8-byte nonce, but exits immediately. |
| **TeacherApp** | BLE GATT Server (`GattServiceProvider`) | §2.5, §3 | `TeacherApp/BLE/` | **MISSING** | No GATT server instantiated; file `BleGattServer.cs` missing. |
| **TeacherApp** | BLE Service Advertising | §2.6, §4 | `android-relay-ble/BleTeacherBroadcaster.cs:34` | **NON-WORKING** | Uses `GeneralUnconnectableMode` beacon publisher instead of connectable GATT. |
| **TeacherApp** | Student BLE Connection Acceptance | §2.7 | `TeacherApp/Program.cs` | **MISSING** | Rejects Link Layer connections due to non-connectable beacon PDU. |
| **TeacherApp** | Attendance Request Ingestion | §2.8 | `TeacherApp/Program.cs` | **MISSING** | No GATT characteristic write handlers. |
| **TeacherApp** | Student Identity & Session Validation | §2.9, §2.10 | `TeacherApp/Program.cs` | **MISSING** | No database lookups or session state machine. |
| **TeacherApp** | Cryptographic Challenge-Response Verification | §2.11, §8 | `TeacherApp/Program.cs` | **MISSING** | No challenge issuance or response verification. |
| **TeacherApp** | RSSI Proximity Evidence Filtering | §2.12, §9 | `TeacherApp/Program.cs` | **MISSING** | No RSSI capture or threshold logic in native host. |
| **TeacherApp** | Direct & Relayed Request Routing | §2.13, §2.14 | `TeacherApp/Program.cs` | **MISSING** | No routing discrimination or hop decrement validation. |
| **TeacherApp** | Anti-Duplicate Enforcement | §2.15 | `TeacherApp/Program.cs` | **MISSING** | No deduplication table or in-memory cache. |
| **TeacherApp** | Local SQLite Relational Persistence | §2.16, §16 | `TeacherApp/TeacherApp.csproj` | **STUB ONLY** | Nuget `Microsoft.Data.Sqlite` referenced; zero database code written. |
| **TeacherApp** | Live Attendance Roster Dashboard | §2.17 | `TeacherApp/Program.cs` | **MISSING** | No GUI or interactive terminal UI. |
| **TeacherApp** | Teacher Review & Manual Override | §2.18 | `TeacherApp/Program.cs` | **MISSING** | No teacher controls to edit eligibility. |
| **TeacherApp** | Attendance Finalization Routine | §2.19 | `TeacherApp/Program.cs` | **MISSING** | No state transition from `ELIGIBLE` to `PRESENT`. |
| **TeacherApp** | HTTPS Cloud Sync Client | §2.20, §20 | `TeacherApp/Program.cs` | **MISSING** | No HTTP client (`HttpClient`) or sync scheduler. |
| **TeacherApp** | Radio Hardware Capability Probing | §2, §4 | `TeacherApp/Program.cs:10` | **STUB ONLY** | Prints static string warning; does not invoke `IsPeripheralRoleSupported`. |
| **StudentApp** | Gradle Build Tooling & Environment | §26 | `StudentApp/` | **MISSING** | Lacks `settings.gradle.kts`, root `build.gradle.kts`, and `app/build.gradle.kts`. |
| **StudentApp** | UI Resource Declarations | §26 | `StudentApp/app/src/main/res/` | **MISSING** | Zero XML layouts, drawables, strings, or themes. |
| **StudentApp** | Android Runtime BLE Permissions | §22 | `StudentApp/app/src/main/AndroidManifest.xml:4` | **DEFECTIVE** | Uses `neverForLocation` which strips beacon scan results on Android 12+. |
| **StudentApp** | Protocol Constants Specification | §26 | `StudentApp/.../Protocol.kt:6-12` | **COMPLETE** | Defines `SERVICE_UUID`, `MAGIC (0xB5)`, `MAX_HOPS (2)`, `RSSI_THRESHOLD (-85)`. |
| **StudentApp** | Student Authentication & Profile | §5.1, §5.2 | `StudentApp/` | **MISSING** | `LoginActivity.kt` and `MainActivity.kt` missing. |
| **StudentApp** | BLE Scanner & GATT Central Client | §5.3, §7 | `StudentApp/` | **MISSING** | `BleManager.kt` missing; no `BluetoothGattCallback`. |
| **StudentApp** | Device Hardware Binding & Keystore | §6, §21 | `StudentApp/` | **MISSING** | No asymmetric key generation or hardware binding. |
| **StudentApp** | Student Relay Forwarding Service | §5.4, §10 | `StudentApp/` | **MISSING** | `RelayManager.kt` missing in mobile app bundle. |
| **StudentApp** | Attendance State & History Store | §5.6, §5.7 | `StudentApp/` | **MISSING** | No local Room or SQLite database for student history. |
| **Relay Engine** | Binary Advertisement Codec | §1, §12 | `android-relay-ble/PayloadCodec.kt:56-78` | **COMPLETE** | 8-byte serialization: `[MAGIC][HOP][SESSION_ID][RESERVED]`. |
| **Relay Engine** | Windows BLE Broadcaster | §4 | `android-relay-ble/BleTeacherBroadcaster.cs` | **NON-WORKING** | Configured as unconnectable beacon (`GeneralUnconnectableMode`). |
| **Relay Engine** | Android Relay State Machine | §10-§14 | `android-relay-ble/AttendanceRelayStateMachine.kt` | **DEFECTIVE** | Relays downlink beacons only; zero uplink path; 33-byte payload overflow. |
| **Relay Engine** | Legacy 31-Byte PDU Compliance | §12 | `android-relay-ble/AttendanceRelayStateMachine.kt:281` | **CRASHING** | Flags (3B) + UUID (18B) + Mfg (12B) = 33B > 31B; triggers `ADVERTISE_FAILED_DATA_TOO_LARGE`. |
| **Relay Engine** | State Machine Watchdog Safety | §14 | `android-relay-ble/AttendanceRelayStateMachine.kt:277` | **DEFECTIVE** | `setTimeout(180_000)` has no callback; causes permanent state freeze. |
| **WebApp** | Multi-Role Admin Console | §17 | `webapp/admin.js:1-154` | **FUNCTIONAL** | Creates teachers, classes, schedules, and student enrollments in `localStorage`. |
| **WebApp** | Teacher Console & Live Monitoring | §17 | `webapp/teacher.js:107-138` | **FUNCTIONAL** | 10-minute session countdown, live roster polling, manual override, finalization. |
| **WebApp** | Student Presence Verification Workflow | §17 | `webapp/student.js:275-376` | **INVERTED** | Student browser tab issues challenge, self-verifies, and writes DB. |
| **WebApp** | Real Web Bluetooth Probing | §17 | `webapp/student.js:155-183` | **FUNCTIONAL** | Probes `navigator.bluetooth.requestDevice`; gracefully falls back to simulation. |
| **WebApp** | Password Hashing & Secret Storage | §21 | `webapp/core.js:68, 77-82` | **INSECURE** | Single-iteration SHA-256 with static salt; secrets stored in plaintext `localStorage`. |
| **WebApp** | Cloud Sync Push Routine | §20 | `webapp/teacher.js:298-311` | **MOCKED** | Logs string to DOM and flips boolean; never performs network `fetch()`. |
| **Backend** | Health Check Endpoint | §25 | `Backend/main.py:44` | **FUNCTIONAL** | Returns `{"ok": True}`. |
| **Backend** | Single Record Ingestion | §20 | `Backend/main.py:48-58` | **INSECURE** | Idempotent on `attendance_id`, but completely unauthenticated. |
| **Backend** | Batch Record Ingestion | §20 | `Backend/main.py:60-70` | **INSECURE** | Ingests arrays of attendance records; unauthenticated. |
| **Backend** | Session Roster Disclosure | §25 | `Backend/main.py:73-84` | **INSECURE** | Publicly dumps all student IDs and attendance for any session. |
| **Backend** | Relational Database Models | §19 | `Backend/models.py:10-21` | **INCOMPLETE** | Only 1 table (`Attendance`) out of 7 specified tables implemented. |
| **Backend** | Unit Test Suite | §25 | `Backend/tests/test_sync.py:1-37` | **PASSING** | 3 tests passing (idempotency, batch deduplication, route validation). |

---

### 2.1 Calibrated Vulnerability & Architectural Defect Scorecard (FIRST CVSS v3.1)

All security vulnerabilities and structural defects identified during the audit are cataloged below with scores mathematically calibrated to the FIRST CVSS v3.1 specification, accounting for host-isolated storage boundaries and separating exploitable flaws from architectural non-conformances:

| ID | Title | Severity | Calibrated CVSS v3.1 Vector | Calibrated Score | Classification & Trust Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VULN-01** | Client-Side Self-Verification & Direct Store Mutation | **HIGH / MEDIUM**<br>*(Dual-Context)* | **Networked**: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N`<br>**Local Demo**: `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N` | **7.5** (Net)<br>**5.5** (Demo) | Inverts trust root; client validates own challenge. Upper bound: 9.8 (if full host compromise). |
| **VULN-02** | Unauthenticated Cloud Ingestion on `/api/attendance` | **CRITICAL** | `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H` | **9.1** | Open REST ingestion accepts arbitrary forged attendance without authentication or signatures. |
| **VULN-03** | Plaintext Secret Storage & Weak Password Hashing | **HIGH** | `CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:N` | **7.1** | Plaintext `device_secret` in `localStorage`; single-iteration SHA-256 with static `"salt_" + id`. |
| **VULN-04** | Unauthenticated Public Disclosure of Student Roster | **HIGH** | `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N` | **7.5** | Public `GET /api/attendance/{session_id}` discloses complete student rosters and attendance timestamps. |
| **VULN-05** | Unauthenticated Downlink Broadcast & Replay in BLE | **HIGH** | `CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H` | **8.1** | Unsigned 8-byte beacon replayed across campus; triggers naive relay proximity verification. |
| **DEFECT-01** *(VULN-06)* | Architectural Inconsistency & System Disconnection Defect | **CRITICAL DEFECT**<br>*(Non-Exploitable)* | `N/A — Non-Exploitable Architectural Defect (Incomplete Stubs)` | **N/A**<br>*(Engineering Defect)* | Incomplete stubs (`Program.cs`, `StudentApp/`), unconnectable beacon vs GATT, missing relay uplink. |
| **VULN-07** | Proximity Telemetry Tampering & Lack of Distance Bounding | **MEDIUM** | `CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:N` | **5.3** | UI-controlled simulated RSSI; absence of RF distance bounding allows wormhole/amplification spoofing. |

---

## 3. Milestone Tracking & Remediation Roadmap

```
+───────────────────────────────────────────────────────────────────────────────────────────+
│                                MILESTONE EXECUTION ROADMAP                                │
+───────────────────────────────────────────────────────────────────────────────────────────+
│ M1: Complete Audit & Documentation (CURRENT)                                              │
│     [X] Codebase Audit Matrix  [X] Calibrated CVSS & Threat Models  [X] BLE Mesh Deep Dive│
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ M2: Cryptographic Decoupling & Storage Hardening                                          │
│     [ ] Remove Client-Side Self-Verification  [ ] Keystore Secret Storage                 │
│     [ ] FastAPI JWT Authentication             [ ] Enforce 7 Backend Relational Models     │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ M3: Connectable BLE GATT Server & Native Client                                           │
│     [ ] Windows GattServiceProvider           [ ] Android BluetoothGatt Client Callback  │
│     [ ] Hardware Capability Fallback Mode      [ ] BLE Service & Characteristic Binding    │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ M4: Uplink Relay Architecture & RF Optimization                                           │
│     [ ] Resolve 31-byte Advertising Overflow   [ ] Implement Bidirectional GATT Proxy      │
│     [ ] State Machine Watchdog Recovery        [ ] Correct Android Location Permissions   │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ M5: Production Hardening, Dynamic Factors & Rollout                                       │
│     [ ] Dynamic Rolling QR Visual Challenge    [ ] Tamper-Evident Hash-Chained Audit Log   │
│     [ ] Cloud HTTPS Batch Push in Web/Host     [ ] Classroom Pilot Verification           │
+───────────────────────────────────────────────────────────────────────────────────────────+
```

| Milestone | Target Scope | Key Deliverables | Status | Gate Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **M1: Comprehensive System Audit & Synthesis** | All 5 sub-systems, security boundaries, and BLE protocol. | - `PROJECT.md` (architecture, calibrated vulnerability scorecard)<br>- `AUDIT_REPORT.md` (calibrated CVSS & qualified threat models)<br>- `README.md` update<br>- `webapp/index.html` badge | **IN PROGRESS** | Independent peer review and verification pass on `Backend/tests`. |
| **M2: Cryptographic Decoupling & Ingestion Hardening** | `webapp/`, `Backend/`, `shared/` | - Decoupled client-server verification<br>- JWT Bearer auth on FastAPI<br>- Complete 7-table schema with foreign keys<br>- Hardware-backed key management | **PLANNED** | Zero unauthenticated writes; student client cannot self-verify. |
| **M3: Connectable BLE GATT Server & Android Client** | `TeacherApp/`, `StudentApp/` | - Windows `GattServiceProvider` in C#<br>- Full GATT client in Android Kotlin<br>- 7 characteristic read/write handlers<br>- Gradle build scaffolding | **PLANNED** | Student Android client connects to Teacher GATT server and exchanges packets. |
| **M4: Uplink Relay Architecture & RF Optimization** | `android-relay-ble/`, `StudentApp/` | - Fix 33-byte advertising overflow<br>- Store-and-forward GATT proxy relay<br>- State machine watchdog recovery<br>- Android 12+ location permission fix | **PLANNED** | Downstream student transmits request via relay to teacher with verified result. |
| **M5: Production Hardening & Multi-Factor Rollout** | Whole System | - Dynamic visual QR / audio factor<br>- Hash-chained append-only audit log<br>- Real HTTPS sync client in Web & C#<br>- Pilot trial in 100-student classroom | **PLANNED** | Zero false-positive proxy check-ins in physical classroom trial. |

---

## 4. Interface Contracts & Protocol Specifications

### 4.1 Bluetooth Low Energy (BLE) GATT Contract

The system standardizes on a 128-bit custom Service UUID and seven characteristic handles declared in `shared/ble_config.json`:

- **Primary Service UUID**: `a5e8c0de-0001-4b7d-9c11-000000000001`

| Characteristic Name | UUID | Permissions | Properties | Payload Format / Schema |
| :--- | :--- | :--- | :--- | :--- |
| **Session** | `...0002` | Read-Only | Read, Notify | `[SESSION_ID (4B)][NONCE (8B)][EXPIRES_AT (8B Unix ms)]` |
| **Attendance Request** | `...0003` | Write-Only | Write, Write Without Response | `[STUDENT_ID (4B)][SESSION_ID (4B)][REQ_NONCE (8B)]` |
| **Challenge** | `...0004` | Read / Indicate | Read, Indicate | `[CHALLENGE_NONCE (16B)][TTL_MS (2B)]` |
| **Response** | `...0005` | Write-Only | Write | `[STUDENT_ID (4B)][HMAC_SHA256 (32B)]` |
| **Attendance Result** | `...0006` | Read / Notify | Read, Notify | `[STATUS_BYTE (1B: 0x01=ELIGIBLE, 0x02=REJECTED)][REASON_CODE (1B)]` |
| **Relay Message** | `...0007` | Write / Indicate | Write, Indicate | `[ENCRYPTED_ENVELOPE (VarLen)][ORIG_STUDENT_ID (4B)][HOP_COUNT (1B)]` |

### 4.2 Binary Advertising Packet Format (Downlink Beacon)

The binary manufacturer-specific data structure serialized by `PayloadCodec.kt`:

$$\begin{array}{|c|c|c|c|c|}
\hline
\textbf{Byte 0} & \textbf{Byte 1} & \textbf{Bytes 2–5} & \textbf{Bytes 6–7} \\
\hline
\text{Magic Byte } (\texttt{0xB5}) & \text{Hop Count } (0 \le h \le 2) & \text{Session ID } (\text{32-bit Big-Endian}) & \text{Reserved } (\texttt{0x0000}) \\
\hline
\end{array}$$

- **Total Payload Size**: 8 bytes.
- **Legacy Advertising Footprint**:
  - Flags: 3 bytes (`[0x02][0x01][0x06]`)
  - Manufacturer Data: 12 bytes (`[0x0B][0xFF][CompanyID=0xFFFF][8B Payload]`)
  - **Total**: 15 bytes $\le$ 31 bytes (Compliant **only** when Service UUID is omitted from advertising data).

### 4.3 Cloud Ingestion REST API Contract

Target hardened API contracts between Teacher Host and Central Backend:

#### `POST /api/attendance` & `POST /api/attendance/batch`
- **Headers**:
  - `Authorization: Bearer <Teacher_JWT>`
  - `Content-Type: application/json`
  - `X-Signature-Ed25519: <Hex_Signature_Over_Payload>`
- **Request Body Schema**:
  ```json
  {
    "attendance_id": "string (UUIDv4)",
    "session_id": "string (Hex 8)",
    "student_id": "string (Alphanumeric 4-10)",
    "timestamp": 1773400000000,
    "verification_status": "PRESENT | ELIGIBLE | NOT_VERIFIED",
    "route_type": "DIRECT | RELAY",
    "rssi_evidence": -65,
    "hop_count": 0,
    "relay_student_id": "string (Nullable)",
    "teacher_id": "string (Instructor ID)"
  }
  ```
- **Response**:
  - `200 OK`: `{"status": "stored", "attendance_id": "..."}`
  - `200 OK`: `{"status": "duplicate_ignored", "attendance_id": "..."}`
  - `401 Unauthorized`: Token missing, expired, or invalid role.
  - `422 Unprocessable Entity`: Student ID not enrolled in class.

---

## 5. Repository Code Layout

```
ble_smart_attendance_system-master/
├── AUDIT_REPORT.md             # Authoritative publication-grade comprehensive audit report
├── PROJECT.md                  # System architecture, feature inventory, contracts, & roadmap
├── README.md                   # Operational guide, live demo credentials, and audit index
├── New Text Document.txt       # Original 30-section authoritative engineering specification
│
├── TeacherApp/                 # C# .NET 8 Desktop Host (.NET 8 Windows 10/11)
│   ├── TeacherApp.csproj       # Project configuration (references Microsoft.Data.Sqlite)
│   ├── Program.cs              # Host entrypoint (currently 12-line stub)
│   └── BLE/
│       └── BleProtocol.cs      # GATT UUID constants and protocol limits
│
├── StudentApp/                 # Native Android Client (Kotlin / Gradle skeleton)
│   └── app/
│       └── src/main/
│           ├── AndroidManifest.xml   # BLE and location permission declarations
│           └── java/com/example/attendance/
│               └── Protocol.kt       # Android protocol constants
│
├── android-relay-ble/          # Low-Level Bluetooth Engines & State Machines
│   ├── BleTeacherBroadcaster.cs        # Windows advertisement publisher (C#)
│   ├── PayloadCodec.kt                 # 8-byte binary serialization codec (Kotlin)
│   └── AttendanceRelayStateMachine.kt  # Android Central/Peripheral relay state machine
│
├── webapp/                     # Standalone Interactive Web Simulation
│   ├── index.html              # Single-page multi-portal UI (Admin, Teacher, Student)
│   ├── styles.css              # Custom styling for mobile and desktop screens
│   ├── core.js                 # Shared in-memory DB, cryptographic helpers, seed data
│   ├── admin.js                # Administration, class scheduling, student enrollment
│   ├── teacher.js              # Session orchestration, live roster, review, finalization
│   └── student.js              # Student simulation, radio modeling, challenge-response
│
├── Backend/                    # Cloud Synchronization Service (Python / FastAPI)
│   ├── main.py                 # FastAPI application, routing, and endpoints
│   ├── database.py             # SQLAlchemy session factory and SQLite engine
│   ├── models.py               # ORM entity models (Attendance table)
│   ├── requirements.txt        # Runtime dependencies (FastAPI, Uvicorn, SQLAlchemy, Pytest)
│   └── tests/
│       └── test_sync.py        # Automated test suite (idempotency, batching, route filter)
│
└── shared/                     # Canonical Shared Protocol Configuration
    └── ble_config.json         # Master UUIDs, company IDs, thresholds, and hop limits
```
