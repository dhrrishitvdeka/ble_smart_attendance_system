# Comprehensive Architectural, Security & Protocol Audit Report
**BLE Smart Classroom Attendance System**

---

- **Document Version**: 1.0.0 (Publication Ready)
- **Classification**: Independent Forensic & Protocol Audit
- **Audit Date**: 2026-09-11
- **Lead Auditor**: Worker 1 (Auditor & Document Author)
- **Target Repository**: `ble_smart_attendance_system-master`
- **Reference Standards**: Bluetooth Core Specification v4.0–v5.4, NIST SP 800-63B, OWASP Mobile Top 10, RFC 7519, CVSS v3.1

---

## Table of Contents

1. [Section 1: Executive Summary & Systemic Assessment](#section-1-executive-summary--systemic-assessment)
   - 1.1 Scope & Methodology
   - 1.2 Systemic Assessment & Disparity Overview
   - 1.3 System Security Posture & Risk Scorecard
2. [Section 2: Full Sub-System Audit Matrix](#section-2-full-sub-system-audit-matrix)
   - 2.1 Subsystem 1: `TeacherApp/` (.NET 8 Windows Host)
   - 2.2 Subsystem 2: `StudentApp/` (Android Kotlin Mobile Client)
   - 2.3 Subsystem 3: `android-relay-ble/` (Bluetooth Engine & State Machine)
   - 2.4 Subsystem 4: `webapp/` (Interactive Browser Simulation)
   - 2.5 Subsystem 5: `Backend/` (Python / FastAPI Cloud Sync Service)
   - 2.6 Cross-Subsystem Discrepancy Matrix
3. [Section 3: Local Security & Trust Boundary Analysis](#section-3-local-security--trust-boundary-analysis)
   - 3.1 Threat Modeling & Trust Boundaries
   - 3.2 Vulnerability & Defect Matrix (VULN-01 to VULN-07 / DEFECT-01)
   - 3.3 VULN-01: Client-Side Self-Verification & Direct Data Store Mutation (High / Medium)
   - 3.4 VULN-02: Unauthenticated Cloud Ingestion on `POST /api/attendance` (Critical)
   - 3.5 VULN-03: Plaintext Storage of Shared Secrets & Weak Password Hashing (High)
   - 3.6 VULN-04: Unauthenticated Public Disclosure of Student Attendance & PII (High)
   - 3.7 VULN-05: Unauthenticated Downlink Broadcast & Replay in BLE Relay Mesh (High)
   - 3.8 DEFECT-01 (formerly VULN-06): Architectural Inconsistency & System Disconnection Defect (Critical Defect)
   - 3.9 VULN-07: Proximity Telemetry Tampering & Lack of Distance Bounding (Medium)
4. [Section 4: Bluetooth Low Energy & Mesh Protocol Deep Dive](#section-4-bluetooth-low-energy--mesh-protocol-deep-dive)
   - 4.1 The GATT vs. Beacon Conflict (`BleTeacherBroadcaster.cs`)
   - 4.2 The "Broken Bridge": Missing Uplink Path in `AttendanceRelayStateMachine.kt`
   - 4.3 Link Layer PDU Analysis & 31-Byte Legacy Advertising Overflow
   - 4.4 Mathematical Impossibility of Legacy Mesh Attendance PDUs
   - 4.5 Comparative Mesh Architecture Analysis (Flooding vs GATT vs SIG Mesh)
   - 4.6 Simulation vs Native Reality Trace
5. [Section 5: Actionable Phased Remediation Blueprint](#section-5-actionable-phased-remediation-blueprint)
   - 5.1 Phase 1: Cryptographic & Trust Boundary Fixes (Zero-Trust Enforcement)
   - 5.2 Phase 2: BLE GATT Server & Connectable Advertising Realization
   - 5.3 Phase 3: Uplink Relay Architecture & RF Optimization
   - 5.4 Phase 4: Production Native Implementation & Verified Cloud Sync
6. [Section 6: Verification & Test Methodology](#section-6-verification--test-methodology)

---

## Section 1: Executive Summary & Systemic Assessment

### 1.1 Scope & Methodology

An exhaustive forensic architecture, security, and protocol audit was conducted across the entire **BLE Smart Classroom Attendance System** repository. The scope encompassed all native source code, build manifests, scripts, web assets, protocol configurations, and backend services:

- `TeacherApp/`: C# .NET 8 Windows desktop application
- `StudentApp/`: Android Kotlin mobile application
- `android-relay-ble/`: Kotlin binary payload codec, relay state machine, and Windows C# broadcaster
- `webapp/`: HTML5, CSS3, and Vanilla JavaScript client-side application
- `Backend/`: Python 3, FastAPI, SQLAlchemy, SQLite cloud synchronization service
- `shared/`: JSON configuration defining UUIDs, constants, and radio thresholds
- `New Text Document.txt`: Canonical 30-section system engineering specification

The audit employed a rigorous multi-phase inspection methodology combining static code analysis, protocol modeling, packet structure decomposition, trust boundary mapping, and mathematical validation of Link Layer limits.

### 1.2 Systemic Assessment & Disparity Overview

The specification (`New Text Document.txt`) envisions an enterprise-grade, cyber-physical attendance verification infrastructure where the instructor's device serves as an absolute root of trust:

$$\text{Attendance} = \text{Auth(Student)} \land \text{Device(Bound)} \land \text{Session(Active)} \land \text{BLE(Proximity)} \land \text{Challenge(Fresh)} \land \text{Teacher(Finalized)}$$

However, our audit revealed an **extreme divergence between the engineering specification and the actual codebase**:

1. **Native Implementations are Skeletons**: The native desktop (`TeacherApp/`) and mobile (`StudentApp/`) applications are non-functional placeholder stubs. `TeacherApp/Program.cs` is a 12-line console snippet that prints random hex tokens and terminates immediately. `StudentApp/` contains an Android manifest and a single constants file, lacking all build files (Gradle), UI layouts, activities, and BLE managers.
2. **The Prototype Lives Solely in Web Simulation**: The only end-to-end interactive workflow exists inside `webapp/`, which operates as an in-browser simulation relying entirely on `localStorage` and client-side JavaScript execution.
3. **Fatal Trust Boundary Inversion in Web Simulation**: In `webapp/student.js`, the student browser tab validates its own challenge, verifies its own proximity evidence, and directly inserts attendance records into `localStorage`. The instructor's device is completely bypassed during verification.
4. **Physical Impossibility of Current BLE Mesh**: The standalone BLE components in `android-relay-ble/` cannot complete an attendance transaction. The teacher broadcaster transmits a non-connectable beacon (`ADV_NONCONN_IND`) rather than a connectable GATT server, while the Android relay acts strictly as a downlink repeater with **zero uplink return path**. Furthermore, the relay's advertising payload totals 33 bytes, deterministically crashing on standard Android devices due to the 31-byte legacy PDU ceiling.
5. **Completely Open Cloud Ingestion**: The cloud backend (`Backend/main.py`) exposes public endpoints that accept unauthenticated attendance records from any client on the network, lacking teacher authentication, relational integrity, or digital signatures.

### 1.3 System Security Posture & Risk Scorecard

| Assessment Dimension | Specified Standard | Current Implementation | Forensic Rating |
| :--- | :--- | :--- | :--- |
| **Trust Boundary Enforcement** | Teacher laptop is sole attendance verifier (§1, §2) | Student browser validates itself and mutates DB | **CRITICAL FAILURE** |
| **Ingestion Security** | Authenticated, signed HTTPS uplink (§20, §21) | Open, unauthenticated REST API without auth | **CRITICAL FAILURE** |
| **BLE Link Layer Compatibility** | Connectable GATT server with 6 characteristics (§3) | Non-connectable beacon (`ADV_NONCONN_IND`) | **FATAL CONFLICT** |
| **Relay Multi-Hop Feasibility** | Bidirectional challenge-response over 2 hops (§10–§14) | Downlink-only repeater; no return channel | **FATAL GAP** |
| **Link Layer PDU Compliance** | Standard BLE advertisement packet (§12) | 33 bytes packed into 31-byte PDU limit | **CRASHING OVERFLOW** |
| **Cryptographic Secret Storage** | TEE/Keystore device binding (§6, §21) | Plaintext JSON in browser `localStorage` | **HIGH RISK** |
| **Data Relational Integrity** | 7 normalized relational tables (§19) | 1 unconstrained table in backend | **HIGH RISK** |
| **Native Application Completeness** | Production .NET 8 Host & Android Client (§26) | 12-line stub & 2-file skeleton | **INCOMPLETE STUB** |

---

## Section 2: Full Sub-System Audit Matrix

### 2.1 Subsystem 1: `TeacherApp/` (.NET 8 Windows Host)

#### Architectural Intent vs Actual State
Per `New Text Document.txt` (§2, §3, §4, §16, §26), `TeacherApp/` is designed as a C# .NET 8 desktop host targeting `net8.0-windows10.0.19041.0`. It is intended to host a Windows BLE GATT Server (`GattServiceProvider`), manage local SQLite persistence across 7 relational tables, authenticate teachers, orchestrate live sessions, verify student challenges, and push finalized records to the cloud.

In reality, `TeacherApp/` consists of exactly three files:
- `TeacherApp/TeacherApp.csproj` (13 lines)
- `TeacherApp/Program.cs` (12 lines)
- `TeacherApp/BLE/BleProtocol.cs` (15 lines)

#### Code Citations
1. **`TeacherApp/Program.cs` (Lines 1–12)**:
   ```csharp
   // Minimal teacher console stub (spec §2/§4). Full GATT server lives in
   // android-relay-ble/BleTeacherBroadcaster.cs; this host wires session +
   // SQLite + capability probing. See shared/ble_config.json for UUIDs.
   using System.Security.Cryptography;

   var sessionId = Convert.ToHexString(RandomNumberGenerator.GetBytes(4));
   var nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(8));
   Console.WriteLine($"BLE Attendance TeacherApp (.NET 8)");
   Console.WriteLine($"Session: {sessionId} Nonce: {nonce} Expires: +10 min");
   Console.WriteLine("NOTE: BLE peripheral mode requires a radio with advertising support.");
   Console.WriteLine("Run the browser demo: start-webapp.bat. Cloud sync: Backend/main.py.");
   ```
2. **`TeacherApp/TeacherApp.csproj` (Lines 1–12)**:
   ```xml
   <Project Sdk="Microsoft.NET.Sdk">
     <PropertyGroup>
       <OutputType>Exe</OutputType>
       <TargetFramework>net8.0-windows10.0.19041.0</TargetFramework>
       <Nullable>enable</Nullable>
       <ImplicitUsings>enable</ImplicitUsings>
       <UseWinUI>false</UseWinUI>
     </PropertyGroup>
     <ItemGroup>
       <PackageReference Include="Microsoft.Data.Sqlite" Version="8.*" />
     </ItemGroup>
   </Project>
   ```

#### Enumerated Missing Functionality in `TeacherApp/Program.cs`
1. **Zero Teacher Authentication**: Lacks teacher credential ingestion, password verification, or session token generation (violating Requirement 1).
2. **Zero Class Selection Logic**: Lacks class roster loading, subject selection, or schedule lookup (violating Requirement 2).
3. **No Active Session Lifecycle**: Generates an ephemeral 4-byte session ID and 8-byte nonce in lines 6–7, but holds no state machine, session timer, or expiration handling; exits immediately upon execution (violating Requirements 3 & 4).
4. **Missing GATT Server (`BleGattServer.cs`)**: Never instantiates `Windows.Devices.Bluetooth.GenericAttributeProfile.GattServiceProvider`. Does not publish the attendance service UUID (`a5e8c0de-0001-4b7d-9c11-000000000001`) or any of the 7 GATT characteristics (violating Requirements 5 & 6).
5. **No Connection Acceptance or GATT Handlers**: Lacks event handlers for student connections, characteristic read requests, or write requests (violating Requirements 7 & 8).
6. **No Student Identity & Session Validation**: Does not validate student IDs, class enrollments, or registered device IDs against a database (violating Requirements 9 & 10).
7. **No Cryptographic Challenge-Response Verification**: Does not issue 16-byte random challenges, compute expected HMAC/SHA-256 digests, or verify student responses (violating Requirement 11).
8. **No Proximity Evidence Processing**: Does not capture, log, or filter RSSI readings from connecting centrals (violating Requirement 12).
9. **No Direct vs Relayed Request Routing**: Lacks logic to parse direct versus forwarded relay envelopes (violating Requirements 13 & 14).
10. **No Anti-Replay or Deduplication Cache**: Lacks an in-memory or persisted set of processed `student_id` and `request_id` values (violating Requirement 15).
11. **Zero SQLite Database Implementation**: Despite referencing `Microsoft.Data.Sqlite` in `.csproj`, there is zero database connection code, zero schema migrations, and zero table creation (violating Requirement 16).
12. **Missing Live Attendance Dashboard**: Lacks a terminal dashboard, WinUI, WPF, or console renderer to display the live attendance roster (violating Requirement 17).
13. **No Teacher Review or Override Controls**: Does not permit instructors to inspect students, flag anomalies, or mark manual attendance (violating Requirement 18).
14. **No Attendance Finalization Pipeline**: Lacks the logic to commit `ELIGIBLE` students to `PRESENT` status and seal the session (violating Requirement 19).
15. **No Cloud Synchronization Client**: Lacks HTTP client infrastructure (`HttpClient`) to transmit finalized records to `Backend/main.py` (violating Requirement 20).
16. **No Hardware Capability Probing**: Line 10 prints a static diagnostic text string; it does not invoke `BluetoothAdapter.GetDefaultAsync()` or check `adapter.IsPeripheralRoleSupported`.

---

### 2.2 Subsystem 2: `StudentApp/` (Android Kotlin Mobile Client)

#### Architectural Intent vs Actual State
Per `New Text Document.txt` (§5, §6, §7, §8, §10, §21, §22, §26), `StudentApp/` is specified as a native Android application written in Kotlin. It must provide 7 UI screens, manage Bluetooth LE scanning and GATT client connections (`BluetoothGattCallback`), enforce hardware-backed device binding, execute challenge-response cryptography, support background/foreground relaying, and maintain a local attendance history database.

The actual `StudentApp/` directory contains only two files:
- `StudentApp/app/src/main/AndroidManifest.xml` (11 lines)
- `StudentApp/app/src/main/java/com/example/attendance/Protocol.kt` (13 lines)

#### Code Citations
1. **`StudentApp/app/src/main/AndroidManifest.xml` (Lines 1–11)**:
   ```xml
   <?xml version="1.0" encoding="utf-8"?>
   <manifest xmlns:android="http://schemas.android.com/apk/res/android">
       <!-- spec §22: Android 12+ runtime BT permissions + legacy location for scan -->
       <uses-permission android:name="android.permission.BLUETOOTH_SCAN" android:usesPermissionFlags="neverForLocation" />
       <uses-permission android:name="android.permission.BLUETOOTH_ADVERTISE" />
       <uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
       <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30" />
       <uses-feature android:name="android.hardware.bluetooth_le" android:required="true" />
       <application android:label="BLE Attendance" />
   </manifest>
   ```
2. **`StudentApp/app/src/main/java/com/example/attendance/Protocol.kt` (Lines 1–13)**:
   ```kotlin
   package com.example.attendance

   import java.util.UUID

   /** Shared protocol constants — must match shared/ble_config.json. */
   object Protocol {
       val SERVICE_UUID: UUID = UUID.fromString("a5e8c0de-0001-4b7d-9c11-000000000001")
       const val COMPANY_ID = 0xFFFF
       const val MAGIC: Byte = 0xB5.toByte()
       const val MAX_HOPS = 2
       const val RSSI_THRESHOLD_DBM = -85
   }
   ```

#### Enumerated Missing Functionality in `StudentApp/`
1. **Total Absence of Build Environment**: Lacks `settings.gradle.kts`, root `build.gradle.kts`, and `app/build.gradle.kts`. The application cannot be compiled, tested, or loaded into Android Studio.
2. **Total Absence of Android Resources**: The `res/` folder is completely missing; there are no XML layouts, vector drawables, string definitions, color palettes, or application themes.
3. **Missing Core Activities**:
   - `MainActivity.kt`: **MISSING** (Main navigation and session state container).
   - `LoginActivity.kt`: **MISSING** (Credential authentication and session initialization).
4. **Missing Architectural Managers**:
   - `BleManager.kt`: **MISSING** (Wraps `BluetoothLeScanner`, `BluetoothGatt`, and `BluetoothGattCallback` for connection, MTU exchange, and characteristic operations).
   - `RelayManager.kt`: **MISSING** (Coordinates mobile relay advertising and forwarding).
   - `AttendanceManager.kt`: **MISSING** (Coordinates protocol state, nonce signing, and verification results).
5. **All 7 Required User Interface Screens Missing**:
   - Screen 1: Login Screen (Username, Password, Enrolled Class)
   - Screen 2: Student Profile (Student ID, Registered Device ID, Enrolled Class)
   - Screen 3: BLE Scan Screen (Live radar/list of detected teacher sessions)
   - Screen 4: Current Class / Session Screen (Session ID, Subject, Countdown Timer)
   - Screen 5: Verification Progress Screen (Multi-step animated checklist)
   - Screen 6: Attendance Result Screen (`VERIFICATION COMPLETE` / `NOT VERIFIED`)
   - Screen 7: Attendance History Screen (Historical records, routes, and statuses)
6. **Missing Local Data Store**: No SQLite or Room database implementation to persist student identity, credentials, or attendance logs.
7. **Flawed Permission Attribute**: Line 4 asserts `android:usesPermissionFlags="neverForLocation"`. Under Android 12+, this flag explicitly instructs the OS to suppress beacon advertisements and obscure RSSI data from scan results, rendering proximity-based attendance verification non-functional.

---

### 2.3 Subsystem 3: `android-relay-ble/` (Bluetooth Engine & State Machine)

#### Architectural Intent vs Actual State
`android-relay-ble/` houses the low-level Bluetooth protocol serialization, Windows advertisement publishing, and Android relay state machine logic. It consists of three fully authored source files:
- `android-relay-ble/PayloadCodec.kt` (83 lines)
- `android-relay-ble/BleTeacherBroadcaster.cs` (127 lines)
- `android-relay-ble/AttendanceRelayStateMachine.kt` (307 lines)

#### Component Inspection & Deficiencies
1. **`PayloadCodec.kt`**:
   - Correctly implements binary serialization for an 8-byte buffer:
     $$\text{Packet} = [\text{MAGIC (1B: 0xB5)}] + [\text{HOP (1B: 0..2)}] + [\text{SESSION\_ID (4B BE)}] + [\text{RESERVED (2B: 0x0000)}]$$
   - Accurately validates `MAGIC`, packet length (8 bytes), and hop boundaries (`0..MAX_HOPS`).
2. **`BleTeacherBroadcaster.cs` (Lines 30–50)**:
   - Configures `BluetoothLEAdvertisementPublisher` on Windows with `AdvertisementFlags.GeneralUnconnectableMode`.
   - **Critical Architectural Conflict**: `GeneralUnconnectableMode` emits `ADV_NONCONN_IND` packets. This prohibits any incoming BLE connections. It does not instantiate a GATT server (`GattServiceProvider`), completely breaking the connection-oriented verification requirements specified in §2, §3, and §7.
3. **`AttendanceRelayStateMachine.kt` (Lines 53–306)**:
   - Implements a state machine: `IDLE` $\rightarrow$ `SCANNING` $\rightarrow$ `SWITCHING` $\rightarrow$ `RELAY_ADVERTISING` $\rightarrow$ `STOPPED` / `FAILED`.
   - **Critical Defect 1 (Missing Uplink)**: Implements only a one-way downlink beacon repeater. When transitioning to peripheral mode, it destroys the scanner (`scanner = null`) and advertises non-connectable beacons (`.setConnectable(false)`). Downstream students have no channel to transmit attendance requests upstream.
   - **Critical Defect 2 (33-Byte Advertising Overflow)**: Lines 286–291 pack a 3-byte Flags field, an 18-byte 128-bit Service UUID, and a 12-byte Manufacturer Data field into a legacy BLE advertisement ($3 + 18 + 12 = 33\text{ bytes} > 31\text{ bytes}$). This triggers an immediate `ADVERTISE_FAILED_DATA_TOO_LARGE` crash on all standard Android hardware.
   - **Critical Defect 3 (State Machine Deadlock)**: Lines 277 sets advertising timeout to 180 seconds via `setTimeout(180_000L)`. Because Android's `AdvertiseCallback` provides no callback upon timeout expiry, the internal state remains locked in `RELAY_ADVERTISING`, permanently preventing subsequent attendance scans.

---

### 2.4 Subsystem 4: `webapp/` (Interactive Browser Simulation)

#### Architectural Intent vs Actual State
`webapp/` is the sole functional end-to-end component in the repository. It provides an in-browser prototype of the Admin, Teacher, and Student portals using Vanilla JavaScript, HTML5, CSS3, and `localStorage`.
- `webapp/index.html` (310 lines)
- `webapp/styles.css` (456 lines)
- `webapp/core.js` (200 lines)
- `webapp/admin.js` (154 lines)
- `webapp/teacher.js` (322 lines)
- `webapp/student.js` (456 lines)

#### Implemented Features
- **Admin Portal (`admin.js`)**: Teachers creation, class allocation, timetable scheduling, and student enrollment (enforcing a strict single-class constraint with auto-generated device IDs).
- **Teacher Portal (`teacher.js`)**: Session initiation with live 10-minute countdown, real-time roster polling (1500 ms interval), manual presence overrides, and finalization converting `ELIGIBLE` to `PRESENT`.
- **Student Client (`student.js`)**: Device-bound login, simulated radio position selection (`Near`, `Back`, `Outside`), optional Web Bluetooth scan probe (`tryRealBLE()`), relay mode activation, and attendance history viewer.

#### Critical Security & Architectural Deficiencies
1. **Client-Side Self-Verification (VULN-01)**: The student script generates its own challenge, verifies its own SHA-256 response, evaluates its own synthetic RSSI, and directly writes attendance records into `DB.attendance` stored in `localStorage`.
2. **Plaintext Secrets in Browser Storage (VULN-03)**: The entire database (including student `device_secret` tokens, teacher password hashes, and admin credentials) is stored in plaintext JSON in `localStorage` under `ble_attendance_db_v2`.
3. **Mocked Cloud Synchronization**: `syncToCloud()` in `webapp/teacher.js` (lines 298–311) does not perform an HTTP `fetch()`; it merely appends simulated text logs to a DOM `<div>` and marks local objects as `synced = true`.

---

### 2.5 Subsystem 5: `Backend/` (Python / FastAPI Cloud Sync Service)

#### Architectural Intent vs Actual State
Per `New Text Document.txt` (§18, §19, §20, §25), `Backend/` is specified as a cloud-hosted FastAPI or Flask microservice providing centralized database persistence across 7 relational tables, enforcing teacher authentication, verifying teacher digital signatures, and deduplicating attendance records.

The actual implementation consists of:
- `Backend/main.py` (85 lines)
- `Backend/database.py` (15 lines)
- `Backend/models.py` (22 lines)
- `Backend/requirements.txt` (7 lines)
- `Backend/tests/test_sync.py` (37 lines)

#### Implemented Capabilities & Test Verification
- Exposes `GET /health`, `POST /api/attendance`, `POST /api/attendance/batch`, and `GET /api/attendance/{session_id}`.
- Implements idempotent deduplication based on primary key `attendance_id`.
- Automated test suite passes: `pytest Backend/tests -q` (3 passed in 0.65s).

#### Deficiencies & Vulnerabilities
1. **Completely Unauthenticated Ingestion (VULN-02)**: The ingestion endpoints require zero authentication tokens, API keys, or signatures. Any entity on the network can post arbitrary attendance records with status `PRESENT`.
2. **Missing 6 Relational Tables**: `Backend/models.py` defines only the `Attendance` entity. It lacks `Students`, `Teachers`, `Classes`, `Sessions`, `AttendanceEvents`, and `RelayEvents`. The database enforces no foreign key constraints or enrollment validation.
3. **Public Disclosure of Student Attendance (VULN-04)**: `GET /api/attendance/{session_id}` is unauthenticated, allowing any network user to dump student IDs and attendance statuses for any session.
4. **Complete Subsystem Disconnection**: Neither `TeacherApp/Program.cs` nor `webapp/teacher.js` makes actual HTTP network calls to `Backend/main.py`. The backend exists in total isolation.

---

### 2.6 Cross-Subsystem Discrepancy Matrix

| System Capability | Specification Standard (`New Text Document.txt`) | README.md Claim | Codebase Implementation | Operational Status |
| :--- | :--- | :--- | :--- | :--- |
| **Teacher Host** | Full C# .NET 8 host with GATT server & SQLite | .NET 8 teacher stub | 12-line `Program.cs` console stub; exits immediately | **Non-Functional Stub** |
| **GATT Server** | Windows `GattServiceProvider` with 7 characteristics | References broadcaster | `BleTeacherBroadcaster.cs` uses unconnectable beacon | **Fatal Conflict** |
| **Student App** | Native Android Kotlin app with 7 screens | Manifest + constants | Manifest + `Protocol.kt`; no Gradle, no UI, no code | **Empty Skeleton** |
| **Relay Uplink** | Bidirectional multi-hop relay up to 2 hops | 2 hops max, forwards msgs | Downlink repeater only; zero uplink return channel | **Architecturally Broken** |
| **Advertising PDU** | Compliant legacy BLE advertising packet | Standard broadcast | 33-byte payload exceeds 31-byte legacy limit | **Crashing Overflow** |
| **Verification Authority**| Teacher verifies challenge-response | Verification chain | Student browser tab verifies itself and writes DB | **Security Inversion** |
| **Secret Storage** | Hardware-bound device secrets (Keystore/TEE) | Demo DB storage | Plaintext JSON in browser `localStorage` | **Insecure** |
| **Cloud Ingestion** | Authenticated HTTPS sync with digital signatures | FastAPI sync API | Public unauthenticated API; 6 of 7 tables missing | **Insecure & Isolated** |
| **Frontend Cloud Sync** | Client pushes unsynced records to backend | Pushes over HTTPS | String logging to DOM; no network request executed | **Mocked Simulation** |

---

## Section 3: Local Security & Trust Boundary Analysis

### 3.1 Threat Modeling & Trust Boundaries

```
 +───────────────────────────────────────────────────────────────────────────────────────────+
 │                                     UNTRUSTED DOMAIN                                      │
 │                                                                                           │
 │   +────────────────────────────+                     +────────────────────────────────+   │
 │   │    Student Web Client      │                     │     Student Native Android     │   │
 │   │    (webapp/student.js)     │                     │     (StudentApp / Radio)       │   │
 │   │    - Full control of DOM   │                     │     - Full OS / Radio Control  │   │
 │   │    - Full localStorage access                    │     - Can spoof GPS & BLE RSSI │   │
 │   +──────────────┬─────────────+                     +───────────────┬────────────────+   │
 +──────────────────┼───────────────────────────────────────────────────┼────────────────────+
                    │ [VULN-01: Client Self-Verification]               │ [VULN-05: Beacon Spoofing]
                    ▼                                                   ▼
 +───────────────────────────────────────────────────────────────────────────────────────────+
 │                               TRUSTED ROOT BOUNDARY (TEACHER)                             │
 │                                                                                           │
 │   +────────────────────────────+                     +────────────────────────────────+   │
 │   │    Teacher Web Console     │                     │      Teacher Native Host       │   │
 │   │    (webapp/teacher.js)     │                     │      (TeacherApp / Broadcaster)│   │
 │   │    - Shares origin with St.│                     │      - 12-Line C# Console Stub │   │
 │   │    - Shares localStorage   │                     │      - Unconnectable Beacon    │   │
 │   +──────────────┬─────────────+                     +────────────────────────────────+   │
 +──────────────────┼────────────────────────────────────────────────────────────────────────+
                    │ [VULN-02: Unauthenticated Ingestion]
                    ▼
 +───────────────────────────────────────────────────────────────────────────────────────────+
 │                                CENTRAL CLOUD TRUST BOUNDARY                               │
 │                                                                                           │
 │   +───────────────────────────────────────────────────────────────────────────────────+   │
 │   │    FastAPI Cloud Service (Backend/main.py)                                        │   │
 │   │    - Public unauthenticated REST endpoints                                        │   │
 │   │    - Missing foreign keys and student/class reference tables                      │   │
 │   │    - Public session roster disclosure (VULN-04)                                   │   │
 │   +───────────────────────────────────────────────────────────────────────────────────+   │
 +───────────────────────────────────────────────────────────────────────────────────────────+
```

### 3.2 Vulnerability & Defect Matrix (VULN-01 to VULN-07 / DEFECT-01)

| Vulnerability ID | Title | Severity | CVSS v3.1 Vector | CVSS Score | Affected Components |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VULN-01** | Client-Side Self-Verification & Direct Store Mutation | **HIGH / MEDIUM**<br>*(Dual-Context)* | **Networked**: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N`<br>**Local Demo**: `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N` | **7.5** (Networked)<br>**5.5** (Local Demo) | `webapp/student.js`, `webapp/teacher.js` |
| **VULN-02** | Unauthenticated Cloud Ingestion on `/api/attendance` | **CRITICAL** | `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H` | **9.1** | `Backend/main.py`, `Backend/models.py` |
| **VULN-03** | Plaintext Secret Storage & Weak Password Hashing | **HIGH** | `CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:N` | **7.1** | `webapp/core.js`, `webapp/admin.js` |
| **VULN-04** | Unauthenticated Public Disclosure of Student Roster | **HIGH** | `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N` | **7.5** | `Backend/main.py` |
| **VULN-05** | Unauthenticated Downlink Broadcast & Replay in BLE | **HIGH** | `CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H` | **8.1** | `android-relay-ble/`, `TeacherApp/` |
| **DEFECT-01** *(formerly VULN-06)* | Architectural Inconsistency & System Disconnection Defect | **CRITICAL DEFECT**<br>*(Non-Exploitable)* | `N/A — Non-Exploitable Architectural Defect (Incomplete Stubs)` | **N/A**<br>*(Engineering Defect)* | Entire Codebase |
| **VULN-07** | Proximity Telemetry Tampering & Lack of Distance Bounding | **MEDIUM** | `CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:N` | **5.3** | `webapp/student.js`, `android-relay-ble/` |

---

### 3.3 VULN-01: Client-Side Self-Verification & Direct Data Store Mutation

- **Severity**: **HIGH (7.5)** in Networked Architecture / **MEDIUM (5.5)** in Local Browser Demo
- **CVSS v3.1 Vectors**:
  - *Networked Client-Server Context*: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N` (**7.5 High**)
  - *Local Browser Demo Context*: `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N` (**5.5 Medium**)
  - *Theoretical Maximum Upper Bound*: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` (**9.8 Critical**) — applicable only if attendance manipulation directly achieved total host takeover, service destruction, and full confidential data theft. Under FIRST CVSS v3.1 mathematical precision, attendance tampering directly compromises integrity (`I:H`) without inherent confidentiality loss (`C:N`) or service denial (`A:N`).
- **Affected Files**: `webapp/student.js` (Lines 275–376), `webapp/teacher.js` (Lines 168–198)

#### Detailed Mechanism
In `webapp/student.js`, the student browser client executes both sides of the verification protocol:
1. **Self-Challenge Issuance** (Lines 298–305):
   ```javascript
   currentChallenge = {
     value: randHex(16),
     expiresAt: now() + CHALLENGE_TTL_MS,
     used: false,
     sessionId: session.session_id
   };
   ```
2. **Self-Response Calculation & Verification** (Lines 312, 319–324):
   ```javascript
   const response = await sha256hex(currentChallenge.value + currentStudent.device_secret);
   const expected = await sha256hex(currentChallenge.value + currentStudent.device_secret);
   if (response !== expected) { done(d, false, "challenge mismatch"); return failResult(...); }
   ```
3. **Direct Database Insertion** (Lines 359 & 375):
   ```javascript
   const ok = recordAttendance(currentStudent, "DIRECT", rssi, 0, null);
   ```
   `recordAttendance()` in `webapp/teacher.js` directly appends to `DB.attendance` and calls `saveDB()`, writing directly into `localStorage`.

#### Existing Defensive Logic in Web Application
A thorough examination of the web simulation codebase reveals several intentional defensive mechanisms implemented by the authors to guard attendance integrity:
1. **Two-Stage Status Workflow**:
   In `webapp/teacher.js` (Line 183), student-submitted attendance is initially recorded with `verification_status: "ELIGIBLE"`. It does not immediately grant attendance. An explicit teacher review and finalization routine (`teacherFinalize()` in Lines 275–296) is required to convert eligible candidate records into finalized `"PRESENT"` records.
2. **Hardware Device Registration Binding**:
   In `webapp/student.js` (Lines 291–294), the client performs a validation check:
   `authCtx.deviceId === currentStudent.registered_device_id`
   This prevents a logged-in student from generating attendance using an unregistered device ID profile.
3. **RSSI Boundary & Proximity Threshold Enforcement**:
   In `webapp/student.js` (Line 354) and `webapp/teacher.js` (Line 174), records with `rssi <= RSSI_FLOOR` (-85 dBm) are rejected with error messages, enforcing physical proximity bounds within the client logic.
4. **Teacher Manual Override Controls**:
   In `webapp/teacher.js` (Lines 247–249), the live instructor dashboard provides UI controls allowing instructors to reject suspicious records or manually toggle individual student attendance.

**Why Client-Side Enforcement Fails**: While these mechanisms demonstrate a deliberate architectural effort to model the specification's workflow, executing security enforcement inside client-side JavaScript in an untrusted execution environment provides zero defensive security. An adversary possessing DevTools (`F12`) or script execution capability within the browser can effortlessly tamper with variables, invoke functions with forged parameters, or bypass the client logic entirely by directly appending crafted records to `DB.attendance` and calling `saveDB()`.

#### Qualified Threat Model: `localStorage` Isolation vs Multi-Device Reality
The threat model surrounding `localStorage` manipulation must be precisely qualified to distinguish between local browser isolation and networked environments:
- **Host & Origin Sandboxing**: In modern web browsers (Chrome, Edge, Firefox, Safari), `localStorage` is strictly isolated to the specific origin (`scheme://host:port`) and the local browser profile on that specific physical device.
- **Multi-Device Isolation**: If Professor Sharma opens the Web App on a laptop and Student Alice opens the Web App on her phone at home, **Alice's `localStorage` is completely isolated from Sharma's `localStorage`**. Alice calling `recordAttendance()` or mutating `DB.attendance` on her own device writes strictly to her device's storage. It **never transmits data over the network to the instructor's laptop**. Therefore, across separate physical devices without cloud sync, the web simulation fails to communicate rather than cross-contaminating.
- **Realistic Attack Scenarios**: The unauthorized modification of attendance records in the teacher's console occurs under three distinct, realistic threat environments:
  1. **Shared Physical Terminals / Demonstration Context**: When instructors and students interact on the same physical workstation or browser profile (e.g. shared university computer lab terminals, single-device grading/demonstration, or multi-tab browser sessions), any student opening DevTools (`F12`) or running a console snippet in another tab directly modifies the shared `localStorage` (`ble_attendance_db_v2`).
  2. **Cross-Site Scripting (XSS) or Malicious Extensions**: If any XSS vulnerability exists on the origin, or if a student installs a compromised browser extension, malicious scripts execute within the origin and can freely manipulate `localStorage`.
  3. **Bridged Cloud Synchronization**: If the web application is connected to the backend API (`POST /api/attendance`), a remote student can bypass local BLE constraints entirely by exploiting the unauthenticated ingestion endpoint (VULN-02) to inject records directly into the central cloud database, which the instructor console then ingests.

---

### 3.4 VULN-02: Unauthenticated Cloud Ingestion on `POST /api/attendance`

- **Severity**: **CRITICAL** (CVSS 9.1)
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H`
- **CVSS Score**: **9.1** (Calibrated strictly to FIRST CVSS v3.1 specification; previously overstated as 9.8 because confidentiality impact is `C:N`, which mathematically yields Base Score 9.1 in the absence of a scope change).
- **Affected Files**: `Backend/main.py` (Lines 48–70), `Backend/models.py` (Lines 10–21)

#### Detailed Mechanism
The cloud ingestion endpoints `POST /api/attendance` and `POST /api/attendance/batch` process and persist records without checking credentials:
```python
@app.post("/api/attendance")
def sync_attendance(item: AttendanceIn, db: Session = Depends(get_db)):
    if item.route_type not in ("DIRECT", "RELAY"):
        raise HTTPException(400, "route_type must be DIRECT or RELAY")
    existing = db.get(Attendance, item.attendance_id)
    if existing:
        return {"status": "duplicate_ignored", "attendance_id": item.attendance_id}
    db.add(Attendance(**item.model_dump(), synced=True))
    db.commit()
    return {"status": "stored", "attendance_id": item.attendance_id}
```
1. **Zero Authentication**: No HTTP `Authorization` header, API key, or JWT is verified.
2. **Zero Role Enforcement**: Does not verify if the caller is an authorized teacher.
3. **No Signature Verification**: No digital signature (Ed25519/ECDSA) covers the payload.
4. **No Relational Constraints**: The database contains only the `attendance` table; arbitrary student IDs and session IDs are accepted without checking whether they exist in any university enrollment table.

#### Threat Model & Walkthrough
An external attacker or remote student sends an HTTP POST request from any network terminal:
```bash
curl -X POST http://localhost:8000/api/attendance \
  -H "Content-Type: application/json" \
  -d '{
    "attendance_id": "forged-uuid-9999",
    "session_id": "CS101-FALL",
    "student_id": "S001",
    "timestamp": 1773400000000,
    "verification_status": "PRESENT",
    "route_type": "DIRECT",
    "rssi_evidence": -45
  }'
```
The server returns `{"status": "stored", "attendance_id": "forged-uuid-9999"}` and permanently commits the forged record into SQLite, bypassing all physical classroom proximity checks.

---

### 3.5 VULN-03: Plaintext Storage of Shared Secrets & Weak Password Hashing

- **Severity**: **HIGH** (CVSS 7.1)
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:N`
- **CVSS Score**: **7.1** (Calibrated strictly to FIRST CVSS v3.1 specification; previously overstated as 8.2 because local attack vector `AV:L` combined with user interaction `UI:R` yields an exploitability metric of 1.84, resulting in Base Score 7.1).
- **Affected Files**: `webapp/core.js` (Lines 68, 77–82, 145), `webapp/admin.js` (Lines 104–111)

#### Detailed Mechanism
1. **Plaintext Secrets in Browser Storage**:
   The entire database is serialized to `localStorage` under key `ble_attendance_db_v2`. Every student entry contains `device_secret: randHex(16)`. Any user with physical access to a shared computer profile, any browser extension, or any XSS payload can dump the device secrets of all students.
2. **Weak Password Hashing Scheme**:
   ```javascript
   async function hashPassword(id, pw) { return sha256hex("salt_" + id + pw); }
   ```
   - Uses single-iteration SHA-256 with zero computational cost (work factor = 1).
   - Salt is static and deterministic based on user ID (`"salt_S001"`), eliminating salt entropy.
   - Micro-benchmarks confirm 1,000 hashes execute in < 0.005 seconds, rendering passwords highly vulnerable to instant GPU cracking and offline dictionary attacks.

---

### 3.6 VULN-04: Unauthenticated Public Disclosure of Student Attendance & PII

- **Severity**: **HIGH** (CVSS 7.5)
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N`
- **CVSS Score**: **7.5** (Retained; mathematically verified against FIRST CVSS v3.1 specification: network attack vector with high confidentiality impact yields exactly 7.5).
- **Affected Files**: `Backend/main.py` (Lines 73–84)

#### Detailed Mechanism
```python
@app.get("/api/attendance/{session_id}")
def list_session(session_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(Attendance).where(Attendance.session_id == session_id)).all()
    return [{"attendance_id": r.attendance_id, "student_id": r.student_id, ...} for r in rows]
```
Anyone with network visibility can enumerate session IDs and harvest complete attendance rosters, presence timestamps, and routing data. This constitutes a severe privacy violation under FERPA and GDPR.

---

### 3.7 VULN-05: Unauthenticated Downlink Broadcast & Replay in BLE Relay Mesh

- **Severity**: **HIGH** (CVSS 8.1)
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H`
- **CVSS Score**: **8.1** (Calibrated strictly to FIRST CVSS v3.1 specification; previously understated as 7.8 because adjacent radio vector `AV:A` with high integrity and availability impacts mathematically yields Base Score 8.1).
- **Affected Files**: `android-relay-ble/BleTeacherBroadcaster.cs` (Lines 32–49), `android-relay-ble/PayloadCodec.kt` (Lines 56–78), `android-relay-ble/AttendanceRelayStateMachine.kt` (Lines 42–46, 95–98)

#### Detailed Mechanism
1. **Static, Unsigned Payload**: The teacher broadcast packet consists of 8 raw bytes: `[0xB5][HOP=2][SESSION_ID][0x0000]`. It has no timestamp, no rolling sequence number, and no Message Authentication Code (MAC).
2. **Naive Proximity Verification**: In `AttendanceRelayStateMachine.kt`, receiving this packet with RSSI $\ge -85$ dBm immediately emits `RelayEvent.ProximityVerified`.
3. **Replay & Relay Attacks**: An adversary can record the 8-byte beacon inside the classroom and rebroadcast it outside or across campus using an ESP32 or amplifier (+20 dBm), triggering proximity verification for distant devices.

---

### 3.8 Architectural Inconsistency & System Disconnection Defect (DEFECT-01 / formerly VULN-06)

- **Classification**: **Architectural Inconsistency & System Disconnection Defect** (Engineering Non-Conformance)
- **Severity Rating**: **CRITICAL ARCHITECTURAL DEFECT** (System-Level Operational Blocker)
- **CVSS v3.1 Assessment**: **N/A** (Non-Exploitable Architectural Stub). Under NIST SP 800-30 and FIRST CVSS v3.1 standards, a security vulnerability is defined as a flaw or weakness in software logic, configuration, or trust boundaries that can be directly triggered or exploited by an adversary to violate confidentiality, integrity, or availability. Incomplete code stubs, non-working interfaces, and disconnected subsystems represent **engineering non-conformances and specification deficiencies** rather than exploitable attack surfaces. While previously scored with an uncalibrated 7.4 rating (or a theoretical 9.1 vector `AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H`), formal taxonomy requires treating this issue as a critical architectural defect rather than a standalone CVE.
- **Affected Files**: `TeacherApp/Program.cs`, `StudentApp/`, `android-relay-ble/BleTeacherBroadcaster.cs`, `AttendanceRelayStateMachine.kt`, `webapp/teacher.js`, `Backend/main.py`

#### Detailed Defect Analysis
A profound structural disconnect prevents components from functioning together as an integrated attendance system:
1. **GATT vs. Beacon Contradiction**: `BleTeacherBroadcaster.cs` transmits unconnectable beacons (`GeneralUnconnectableMode`), preventing any GATT connection, whereas `StudentApp` and `webapp` expect connectable GATT handshakes.
2. **Missing Uplink Relay Channel**: `AttendanceRelayStateMachine.kt` acts strictly as a downlink repeater, destroying its scanner upon advertising and offering zero uplink mechanism for student attendance submissions.
3. **Isolated Cloud Backend**: `webapp/teacher.js` mocks cloud sync with fake DOM strings, and `TeacherApp/Program.cs` is a 12-line stub that does not initiate HTTP calls to `Backend/main.py`.

Although an adversary cannot "exploit" missing code over the network, this defect is architecturally critical: it causes total failure of the intended security boundaries and forces reliance on vulnerable fallback or simulation mechanisms.

---

### 3.9 VULN-07: Proximity Telemetry Tampering & Lack of Distance Bounding

- **Severity**: **MEDIUM** (CVSS 5.3)
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:N`
- **CVSS Score**: **5.3** (Calibrated strictly to FIRST CVSS v3.1 specification; previously overstated as 6.5 because adjacent radio vector `AV:A` with high complexity `AC:H` and high integrity impact mathematically yields Base Score 5.3).
- **Affected Files**: `webapp/student.js` (Lines 65–71, 331–335), `android-relay-ble/AttendanceRelayStateMachine.kt` (Line 61)

#### Detailed Mechanism
In the web application, RSSI is derived from a user-controlled dropdown (`<select id="sim-position">`). A student selects "Near" to fabricate an RSSI of $-56$ dBm. In wireless radio, raw RSSI is vulnerable to signal amplification and wormhole forwarding over low-latency internet tunnels.

---

## Section 4: Bluetooth Low Energy & Mesh Protocol Deep Dive

### 4.1 The GATT vs. Beacon Conflict (`BleTeacherBroadcaster.cs`)

The specification (§2, §3, §7) mandates that the instructor's laptop act as a **BLE GATT Server** (`GattServiceProvider`) hosting the custom Attendance Service and 7 characteristics. Student phones act as GATT Centrals that establish a Link Layer connection to exchange attendance requests, challenges, and responses.

In direct contradiction, `android-relay-ble/BleTeacherBroadcaster.cs` (lines 30–50) implements an unconnectable beacon:

```csharp
var adv = new BluetoothLEAdvertisement
{
    Flags = AdvertisementFlags.GeneralUnconnectableMode // beacon-style
};
adv.ServiceUuids.Add(_serviceUuid);
adv.ManufacturerData.Add(new BluetoothLEManufacturerData
{
    CompanyId = CompanyId,
    Data = BuildPayload(sessionId, InitialHopCount)
});
_publisher = new BluetoothLEAdvertisementPublisher(adv);
```

#### Link Layer State Machine Failure:
1. Setting `AdvertisementFlags.GeneralUnconnectableMode` causes the Windows Bluetooth radio to broadcast **`ADV_NONCONN_IND`** PDUs.
2. Under the Bluetooth Core Specification, after transmitting an `ADV_NONCONN_IND` packet, the Link Layer controller **never enters the RX state** ($T\_IFS = 150\,\mu\text{s}$). It immediately enters standby.
3. When an Android device invokes `BluetoothGatt.connectGatt()` or a browser invokes `device.gatt.connect()`, the client sends a `CONNECT_IND` packet. Because the teacher controller is not listening, the connection packet is ignored.
4. The client encounters a connection timeout ($30\text{s}$) or `GATT_ERROR` (Android status 133). **Zero GATT exchanges can occur.**

#### Root Cause Analysis:
Windows hardware support for GATT Server mode (`BluetoothAdapter.GetDefaultAsync().IsPeripheralRoleSupported`) is missing on many consumer USB Bluetooth dongles and older Intel/Realtek chipsets. The developer resorted to `BluetoothLEAdvertisementPublisher` to bypass `NotSupportedException`, but in doing so, destroyed the bidirectional GATT protocol.

---

### 4.2 The "Broken Bridge": Missing Uplink Path in `AttendanceRelayStateMachine.kt`

The relay state machine in `AttendanceRelayStateMachine.kt` exhibits a fatal half-duplex deadlock:

```
[Teacher Laptop]
  │ Emits ADV_NONCONN_IND: [Service UUID] + [MfgData: Hop=2, Session=0x1234]
  ▼
[Student A (Relay Phone)]
  │ Scans as Central -> Matches RSSI >= -85 dBm -> Proximity Verified for Student A
  │ Destroys Scanner: scanner?.stopScan(); scanner = null
  │ Enters Peripheral Mode: RelayAdvertiser.startRelay()
  │ Emits ADV_NONCONN_IND: [Service UUID] + [MfgData: Hop=1, Session=0x1234]
  ▼
[Student B (Downstream Phone)]
  │ Scans as Central -> Matches RSSI >= -85 dBm -> Hears Session=0x1234, Hop=1
  │
  X DEAD END: Student B has NO MECHANISM to send attendance back to Teacher!
  │
  ├── Student A's scanner is dead (scanner = null)
  ├── Student A's advertiser is unconnectable (.setConnectable(false))
  └── Student A has no open backhaul connection to Teacher
```

1. **Destroyed Receiver**: To switch to advertising mode, Student A tears down its scanner. It cannot receive RF broadcasts from neighboring peers.
2. **Unconnectable Peripheral**: `RelayAdvertiser` sets `.setConnectable(false)` (line 276). Student B cannot establish a GATT connection to Student A.
3. **No Backhaul Link**: Even if Student A could receive a packet from Student B, Student A has no open connection to the teacher laptop.
4. **Conclusion**: The relay is purely a one-way downlink beacon repeater. Relayed attendance verification is **physically and logically impossible**.

---

### 4.3 Link Layer PDU Analysis & 31-Byte Legacy Advertising Overflow

In Bluetooth 4.0–4.2 (and legacy advertising in BLE 5.0+), the primary advertising channels (37, 38, 39) enforce an absolute Link Layer payload limit of **31 bytes**.

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| Len=2 |Type=01| Flags (0x06)  | Len=17|Type=07|  Service UUID |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       128-bit Service UUID (continued: 16 bytes total)        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| Len=11|Type=FF| Company ID    |MagicB5| Hop=2 | Session ID    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Session ID   | Reserved (2B) |  ===> TOTAL: 33 BYTES (OVERFLOW)
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

#### Exact Byte Accounting in `AttendanceRelayStateMachine.kt`:
- **Flags AD Structure**: 3 bytes (`[Len: 0x02][Type: 0x01][Value: 0x06]`)
- **128-bit Service UUID AD Structure**: 18 bytes (`[Len: 0x11][Type: 0x07][16-byte UUID]`)
- **Manufacturer Data AD Structure**: 12 bytes (`[Len: 0x0B][Type: 0xFF][Company: 0xFFFF][Payload: 8 bytes]`)
- **Total Size**:
  $$3 + 18 + 12 = 33\text{ bytes} > 31\text{ bytes}$$

In lines 281–283, the developer acknowledged this bug in comments:
```kotlin
// NOTE: 128-bit service UUID (18B) + manufacturer (12B) + flags (3B) = 33B > 31B
// legacy limit. If ADVERTISE_FAILED_DATA_TOO_LARGE occurs, drop the
// service UUID here (scan filter can match manufacturer data instead).
```
Because the developer left the code unfixed, calling `startAdvertising()` immediately triggers `onStartFailure(AdvertiseCallback.ADVERTISE_FAILED_DATA_TOO_LARGE)`. The state machine routes to `State.FAILED` on **100% of standard Android devices**.

---

### 4.4 Mathematical Impossibility of Legacy Mesh Attendance PDUs

Even if the downlink beacon overflow is patched, evaluate what is required to transmit a genuine multi-hop attendance request over legacy advertising:

$$\text{PDU} = \text{Magic (1B)} + \text{MsgType (1B)} + \text{MsgID (4B)} + \text{SessionID (4B)} + \text{Hop (1B)} + \text{StudentID (4B)} + \text{Nonce (4B)} + \text{HMAC (16B)} + \text{MAC (8B)}$$

$$\text{Net Application Payload} = 1 + 1 + 4 + 4 + 1 + 4 + 4 + 16 + 8 = 43\text{ bytes}$$
$$\text{With Manufacturer Header (4B) \& Flags (3B)} = 43 + 4 + 3 = \mathbf{50\text{ bytes}} \gg 31\text{ bytes}$$

An authenticated attendance packet carrying cryptographic proof **mathematically cannot fit inside a single legacy BLE advertising packet**. Attempting to implement multi-hop attendance via advertising flooding requires multi-packet segmentation and reassembly (SAR), introducing severe packet loss and radio channel saturation across 50+ students.

---

### 4.5 Comparative Mesh Architecture Analysis

| Metric | 1. BLE Flooding Mesh (Adv-Based) | 2. GATT-Based Mesh (Scatternet) | 3. Bluetooth SIG Mesh Standard |
| :--- | :--- | :--- | :--- |
| **RF Bearer** | Adv Channels (37, 38, 39) | Connected Data Channels (0–36) | Adv Bearer + GATT Bearer |
| **Max Payload** | 31 bytes (legacy) / 254B (Ext Adv) | **512 bytes** (GATT MTU Exchange) | 11B (unsegmented) / 384B (SAR) |
| **Delivery Guarantee**| Unreliable broadcast; no ACK | **Guaranteed** via Link Layer ACK | Network-layer retransmission |
| **Channel Congestion**| **Catastrophic collisions** (50+ phones) | **Low** (37 frequency-hopping channels) | Moderate (randomized backoff) |
| **Connection Limits** | None (Connectionless) | **Strict** (Android: 4–7; Windows: 7–15) | High (up to 32,767 nodes) |
| **Security Layer** | Custom payload encryption | **AES-CCM (128-bit)** + App TLS | Dual-layer (Network + App Keys) |
| **Battery Drain** | Extreme on Relay (continuous RX) | Low to Moderate (Connection events) | High on Relays; Low on LPNs |
| **OS Support** | Android/Windows; **No Web Adv** | Android, Windows, Web (Central only) | **Infeasible** (No native OS APIs) |
| **Verdict** | **Infeasible** (Payload < 31B, collisions) | **Feasible for small clusters** | **Completely Infeasible** |

---

### 4.6 Simulation vs Native Reality Trace

```
                     WEB SIMULATION                                  NATIVE CODE TODAY
┌────────────────────────────────────────────────────────┐ ┌────────────────────────────────────────────────────────┐
│ 1. User clicks "Verify My Presence"                    │ │ 1. Teacher starts BleTeacherBroadcaster.cs             │
│ 2. tryRealBLE() attempts Web Bluetooth requestDevice   │ │    - Emits ADV_NONCONN_IND beacon                      │
│ 3. Connection rejected by unconnectable beacon         │ │    - NO GATT SERVER INSTANTIATED                       │
│ 4. Code catches error; silently falls back to sim:     │ │ 2. Student A starts AttendanceRelayStateMachine.kt     │
│    rssi = simulateRSSI(myPosition())                   │ │    - Scanner matches teacher beacon                    │
│ 5. Browser generates challenge in JS                   │ │    - Switches to RELAY_ADVERTISING                     │
│ 6. Browser signs challenge with localStorage secret    │ │    - Builds 33-byte payload                            │
│ 7. Browser verifies own signature                      │ │    - CRASH: ADVERTISE_FAILED_DATA_TOO_LARGE            │
│ 8. Browser calls recordAttendance() -> saves DB        │ │ 3. Direct Student connects -> TIMEOUT / STATUS 133     │
│ 9. UI displays "VERIFICATION COMPLETE" (Green Badge)   │ │ 4. Downstream Student B has no relay & no uplink       │
└────────────────────────────────────────────────────────┘ └────────────────────────────────────────────────────────┘
          RESULT: ILLUSION OF WORKING SYSTEM                         RESULT: 100% PROTOCOL BREAKDOWN
```

---

## Section 5: Actionable Phased Remediation Blueprint

### 5.1 Phase 1: Cryptographic & Trust Boundary Fixes (Zero-Trust Enforcement)

1. **Eliminate Client-Side Self-Verification (`webapp/student.js`)**:
   - Strip all challenge generation, response verification, and database mutation from `student.js`.
   - The student client must strictly act as a supplicant: it submits `(student_id, session_id, device_signature)` to the teacher host or backend.
   - All verification decisions must occur exclusively on the teacher workstation or backend.
2. **Hardened Cloud Ingestion API (`Backend/main.py`)**:
   - Implement JWT Bearer authentication requiring role `teacher`.
   - Enforce database relational integrity across 7 tables: `Students`, `Teachers`, `Classes`, `Sessions`, `Enrollments`, `Attendance`, `AuditLogs`.
   - Add database unique constraint:
     ```python
     __table_args__ = (UniqueConstraint('session_id', 'student_id', name='uq_session_student'),)
     ```
   - Require Ed25519 digital signatures on all uploaded rosters signed by the teacher's hardware private key.
3. **Secure Secret Storage & Password Hashing (`webapp/core.js`)**:
   - Remove `device_secret`s and administrative password hashes from `localStorage`.
   - Replace single-iteration SHA-256 with Argon2id (or PBKDF2 with $\ge 100,000$ iterations).
   - Enforce separate web origins for Student and Teacher portals to prevent cross-role DOM access.

---

### 5.2 Phase 2: BLE GATT Server & Connectable Advertising Realization

1. **Implement `GattServiceProvider` in `TeacherApp`**:
   - Replace `BluetoothLEAdvertisementPublisher` with Windows `GattServiceProvider`.
   - Register the 7 GATT characteristics defined in `shared/ble_config.json`.
   - Set `GattServiceProviderAdvertisingParameters.IsConnectable = true`.
2. **Graceful Capability Probing & Fallback Mode**:
   ```csharp
   var adapter = await BluetoothAdapter.GetDefaultAsync();
   if (adapter == null || !adapter.IsPeripheralRoleSupported)
   {
       Console.WriteLine("[WARN] Bluetooth Peripheral Role unsupported on this hardware.");
       Console.WriteLine("[INFO] Activating Soft-AP Wi-Fi / Local Network Attendance Mode...");
       StartLocalHttpServer();
   }
   ```
3. **Build Native Android GATT Client (`StudentApp/`)**:
   - Implement `BluetoothGattCallback` in `StudentApp`:
     - Discover services and obtain characteristic handles.
     - Write student attendance request to `RequestCharacteristic` (`...0003`).
     - Handle incoming challenge indication from `ChallengeCharacteristic` (`...0004`).
     - Sign challenge using Android Keystore hardware key and write to `ResponseCharacteristic` (`...0005`).
     - Read verified result from `ResultCharacteristic` (`...0006`).

---

### 5.3 Phase 3: Uplink Relay Architecture & RF Optimization

1. **Resolve 31-Byte Advertising Overflow (`AttendanceRelayStateMachine.kt`)**:
   - Omit the 18-byte Service UUID from the primary advertisement payload:
     ```kotlin
     val data = AdvertiseData.Builder()
         .addManufacturerData(PayloadCodec.COMPANY_ID, payload) // 12 bytes
         .setIncludeDeviceName(false)
         .setIncludeTxPowerLevel(false)
         .build()
     ```
   - Downstream scanners must filter on `ManufacturerData(COMPANY_ID)` rather than Service UUID. Total payload is $3 + 12 = 15\text{ bytes} \le 31\text{ bytes}$.
2. **Implement Store-and-Forward GATT Proxy Relay**:
   - **Downlink**: Teacher broadcasts connectable beacon with session token.
   - **Relay Role**: Student A connects to Teacher via GATT, registers as an active relay, and initializes a local `BluetoothGattServer` advertising a `RelayService`.
   - **Uplink**: Student B connects to Student A via GATT and writes an encrypted request envelope into Student A's `RelayCharacteristic`.
   - **Forwarding**: Student A forwards Student B's envelope over its existing GATT connection to Teacher Characteristic `...0007`. Student A cannot tamper with Student B's cryptographic payload.
3. **Fix State Machine Watchdog & Permissions**:
   - Add Handler watchdog timer in `RelayAdvertiser` to reset state to `State.STOPPED` after 180 seconds.
   - Remove `neverForLocation` from `AndroidManifest.xml` and request runtime `ACCESS_FINE_LOCATION` on Android 12+.

---

### 5.4 Phase 4: Production Native Implementation & Verified Cloud Sync

1. **Dynamic Multi-Factor Presence Verification**:
   - Display a dynamic rotating QR code on the classroom projector screen (refreshed every 5 seconds). The student phone camera scans the visual token and includes it in the signed BLE challenge response. This definitively defeats remote proxy and wormhole attacks.
2. **Tamper-Evident Audit Logging**:
   - Implement cryptographic hash chains ($H_i = \text{SHA-256}(H_{i-1} \parallel \text{Event}_i)$) for all attendance events, manual overrides, and finalizations.
3. **End-to-End Production Cloud Synchronization**:
   - Replace mocked logging in `webapp/teacher.js` with an authenticated `fetch("https://campus-backend/api/attendance/batch")`.
   - Implement background sync scheduler in `TeacherApp` using resilient exponential backoff.

---

## Section 6: Verification & Test Methodology

To ensure audit conclusions are reproducible and verifiable:

### 1. Automated Test Suite Execution
Execute the automated test suite in `Backend/tests`:
```bash
pytest Backend/tests -q
```
*Expected Output*: `3 passed` confirming baseline API regression-free status.

### 2. Advertising PDU Byte Budget Verification
Verify the Link Layer payload overflow mathematically:
```kotlin
val flagsLen = 3
val serviceUuidLen = 18
val mfgHeaderLen = 4
val mfgPayloadLen = 8
val total = flagsLen + serviceUuidLen + mfgHeaderLen + mfgPayloadLen
assert(total == 33) // Exceeds 31 bytes legacy PDU limit
```

### 3. Hardware Over-The-Air (OTA) Radio Inspection
- Run `BleTeacherBroadcaster.cs` on Windows.
- Open nRF Connect on an Android/iOS device.
- Inspect the advertising PDU: packet type is `ADV_NONCONN_IND`.
- Attempt to connect: client throws connection error / timeout, confirming non-connectable status.

---

*Report authored and certified by Worker 1 (Auditor & Document Author).*
