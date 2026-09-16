# Local demonstration implementation plan

Implement and verify each numbered increment, then commit its intended files. Do not treat simulated radio evidence as real physical presence. Existing documentation is not audit evidence.

1. **Attendance write authorization and batch idempotency**: require teacher/admin authentication on `/api/attendance` and `/api/attendance/batch`; flush inserts before checking repeated IDs in both batch versions. Verify anonymous/student rejection, authenticated submission, and repeated IDs in one batch. Commit immediately.
2. **Backend identity and integrity**: remove password bypasses and nonexistent-student login; hash passwords; replace the public fallback JWT key; validate token claims, input bounds, session ownership, enrollment and attendance transitions. Protect rosters and relay operations, restrict CORS, use exact class-code matching, and handle concurrent duplicate writes transactionally. Add regression tests and commit.
3. **Authoritative local demo workflow**: provide a coherent backend-backed login, class management, enrollment, session creation, challenge, verification, finalization and history workflow. Serve the UI and API together locally. Keep browser simulation explicitly identified and separate from real BLE. Verify independent teacher/student clients share authoritative state and commit.
4. **Web state and sync correctness**: fix challenge issuance for multiple enrollments, stale object writes after reload, relay opt-in persistence, teacher session ownership, finalization dirty flags and cloud status updates, and relay-only retry. Remove silent real-BLE-to-success simulation fallback. Add executable regression coverage and commit.
5. **Native teacher correctness**: enforce persisted session status and expiry, atomic challenge consumption, strict RSSI/route parsing and connection-scoped results; avoid attendance replacement and preserve finalized updates during sync. Make manual override validate enrollment and audit accurately. Verify with .NET tests and commit.
6. **Android and protocol integration**: align credential provisioning, wire payloads and session metadata with the teacher; prevent synthetic handshakes from producing real attendance; validate BLE operation failures, cancellation, resource cleanup and relay semantics. Build and test where SDK/hardware availability permits, documenting limitations in the completion response. Commit.
7. **Reproducible end-to-end demonstration**: provide a loopback-only launcher and automated happy-path/negative-path tests for login, enrollment, direct and simulated relay verification, duplicate/replay rejection, finalization and retry. Run available Python, JavaScript, .NET and Android checks; resolve failures and commit each coherent repair.

## Completion gates

- No anonymous attendance writes or student self-finalization.
- Replayed requests cannot create duplicate attendance or downgrade PRESENT.
- Closed/expired sessions reject verification; unrelated teachers cannot mutate sessions.
- Demonstration mode is visible and never claims hardware proximity was proven.
- Startup and test commands work from the project directory without modifying existing user databases during tests.
- Every implemented increment has a verification result and a Git commit; unavailable toolchains and hardware remain explicit limitations rather than claimed passes.
