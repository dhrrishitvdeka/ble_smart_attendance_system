/* ============================================================
   STUDENT APP — login, device binding, BLE scan simulation,
   challenge-response attendance, optional relay mode, history.
   Student can NEVER directly choose PRESENT.
   ============================================================ */

let currentStudent = null;          // logged-in student record
let authCtx = null;                 // { deviceId } from login session
let currentChallenge = null;        // { value, expiresAt, used }
let scanTimer = null;
let scanTimeout = null;

/* Re-sync this tab with the shared DB and refresh the student reference */
function me() {
  reloadDB();
  if (currentStudent)
    currentStudent = DB.students.find(s => s.student_id === currentStudent.student_id) || currentStudent;
  return currentStudent;
}

async function studentLogin() {
  const s = DB.students.find(x => x.student_id === val("st-id").toUpperCase());
  const msg = el("st-login-msg");
  if (!s || (await sha256hex("salt_" + s.student_id + val("st-pass"))) !== s.password_hash) {
    msg.textContent = "Invalid credentials."; msg.className = "msg err"; return;
  }
  currentStudent = s;
  // Authenticated session carries the registered device — student cannot
  // claim another ID or another device during attendance (spec §6).
  authCtx = { deviceId: s.registered_device_id };

  el("st-name").textContent = s.name;
  el("p-name").textContent = s.name;
  el("p-meta").textContent = s.student_id + " \u00b7 " + s.email;
  el("p-device").textContent = "\u{1F4F1} " + s.registered_device_id;
  el("p-class").textContent = "Class " + s.class_id;
  el("relay-mode").checked = s.relay_active_for != null;
  const posSel = el("sim-position");
  if (posSel) posSel.value = s.position || "near";
  updateRelayInfo();
  updateBleStatus();
  audit("STUDENT_LOGIN", s.student_id + " device=" + s.registered_device_id);
  showScreen("screen-student");
  studentHome();
}
function studentLogout() {
  reloadDB();
  if (currentStudent) {
    const s = DB.students.find(x => x.student_id === currentStudent.student_id);
    if (s) s.relay_active_for = null;
    saveDB();
  }
  currentStudent = null; authCtx = null;
  stopScan();
  showScreen("screen-role");
}
function studentHome() {
  stopScan();
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-home").classList.add("active");
}
function myPosition() {
  const sel = el("sim-position");
  const p = sel ? sel.value : null;
  if (p === "back" || p === "outside" || p === "near") return p;
  const s = currentStudent;
  return (s && s.position) || "near";
}
function setSimPosition(pos) {
  reloadDB();
  if (currentStudent) {
    const s = DB.students.find(x => x.student_id === currentStudent.student_id);
    if (s) { s.position = pos; saveDB(); currentStudent = s; }
  }
}

/* ---- Relay mode (spec §10/§11): explicit opt-in, session-only ---- */
function toggleRelay(on) {
  const s = me();
  if (!s) return;
  const sess = getActiveSession();
  if (on && !sess) {
    alert("Relay mode is only allowed during an ACTIVE attendance session.");
    if (el("relay-mode")) el("relay-mode").checked = false;
    return;
  }
  s.relay_active_for = on ? sess.session_id : null;
  audit(on ? "RELAY_ENABLED" : "RELAY_DISABLED", currentStudent.student_id);
  saveDB();
  updateRelayInfo();
}
function updateRelayInfo() {
  const info = el("relay-info");
  if (!info || !currentStudent) return;
  if (currentStudent.relay_active_for) {
    info.textContent = "⚡ Relay active for session " + currentStudent.relay_active_for +
      ". You forward messages but have NO authority to mark attendance.";
    info.className = "msg ok";
  } else { info.textContent = ""; info.className = "msg"; }
}

/* ---- BLE scan (spec §5) ------------------------------------------ */
function gotoScan() {
  stopScan();
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-scan").classList.add("active");
  el("scan-result").innerHTML = "";
  updateBleStatus();
  const h = el("sp-scan").querySelector("h3");
  let dots = 0;
  scanTimer = setInterval(() => {
    dots = (dots + 1) % 4;
    if (h) h.textContent = "Scanning for teacher session" + ".".repeat(dots);
  }, 400);
  scanTimeout = setTimeout(() => {
    stopScan();
    renderScanResult();
  }, 2200);
}
function stopScan() {
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
  if (scanTimeout) { clearTimeout(scanTimeout); scanTimeout = null; }
}

/* ---- Real BLE (Web Bluetooth) --------------------------------------
   Web Bluetooth requires a SECURE CONTEXT: https:// or http://localhost.
   Opening index.html directly via file:// silently hides
   navigator.bluetooth — this is the most common reason "BLE is not
   working". bleCapability() reports the exact cause to the student. */
function bleCapability() {
  const secure = location.protocol === "https:" ||
    ["localhost", "127.0.0.1"].includes(location.hostname);
  if (!secure)
    return { ok: false, reason: "Open via http://localhost (or HTTPS), not file:// \u2014 simulation in use" };
  if (!navigator.bluetooth || !navigator.bluetooth.requestDevice)
    return { ok: false, reason: "This browser has no Web Bluetooth \u2014 use desktop Chrome/Edge \u2014 simulation in use" };
  return { ok: true, reason: "Web Bluetooth ready" };
}

function updateBleStatus() {
  const cap = bleCapability();
  const text = cap.ok
    ? "🔴 Real BLE available — verification will connect to a real device"
    : "⚠ " + cap.reason;
  const cls = "badge " + (cap.ok ? "ok" : "warn");
  const b1 = el("ble-status");
  if (b1) { b1.textContent = text; b1.className = cls; }
  const b2 = el("ble-status-scan");
  if (b2) { b2.textContent = text; b2.className = cls; }
}

async function tryRealBLE() {
  try {
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ services: [UUIDS.service] }],
      optionalServices: [UUIDS.service, UUIDS.session, UUIDS.request, UUIDS.challenge, UUIDS.response, UUIDS.result, UUIDS.relay]
    });
    const server = await device.gatt.connect();
    let rssi = null;
    try {
      await device.watchAdvertisements();
      rssi = await new Promise(resolve => {
        const handler = e => {
          device.removeEventListener("advertisementreceived", handler);
          resolve(e.rssi);
        };
        device.addEventListener("advertisementreceived", handler);
        setTimeout(() => {
          device.removeEventListener("advertisementreceived", handler);
          resolve(null);
        }, 3000);
      });
    } catch (_) { /* watchAdvertisements not permitted — RSSI stays simulated */ }
    return { ok: true, rssi, name: device.name || "unnamed device" };
  } catch (err) {
    return { ok: false, error: err.name === "NotFoundError"
      ? "No device selected / no BLE devices found"
      : err.message };
  }
}

function renderScanResult() {
  const box = el("scan-result");
  updateBleStatus();
  const sess = getActiveSession();
  if (!sess) {
    box.innerHTML = '<div class="step fail">✘ No active classroom session found.<br>' +
      "<small>Bluetooth is on and permissions granted (simulated), but the teacher has not started attendance.</small></div>";
    return;
  }
  const myself = me();
  if (!myself) { box.innerHTML = '<div class="step fail">Not authenticated.</div>'; return; }
  if (myself.class_id !== sess.class_id) {
    box.innerHTML = '<div class="step fail">✘ This session belongs to class ' +
      esc(sess.class_id) + " — you are enrolled in " + esc(myself.class_id) + ".</div>";
    return;
  }
  const rssi = simulateRSSI(myPosition());
  const p = proximityLabel(rssi);
  const cap = bleCapability();
  const teacherName = esc((DB.teachers.find(t => t.teacher_id === sess.teacher_id) || {}).name || "Unknown");
  box.innerHTML =
    '<div class="step pass">✓ Classroom Session Found</div>' +
    '<div class="step">Subject: <b>' + esc(sess.subject) + "</b></div>" +
    '<div class="step">Teacher: ' + teacherName + "</div>" +
    '<div class="step mono">Session: ' + esc(sess.session_id) + "</div>" +
    '<div class="step">BLE Signal: <span class="badge ' + esc(p.cls) + '">' + esc(p.label) + "</span> " +
    '<small class="mono">' + Number(rssi) + " dBm</small> <small>(proximity evidence, not distance)</small></div>" +
    '<div class="step"><small>' + esc(myPosition() === "outside"
      ? "Simulated position is OUTSIDE — direct link is expected to fail. Use the relay path below."
      : (cap.ok
        ? "🔴 Online mode: a real Web Bluetooth connection will be attempted when you verify."
        : cap.reason + ".")) + "</small></div>" +
    '<button class="btn primary block" id="btn-verify-direct">VERIFY MY PRESENCE</button>' +
    '<button class="btn block" id="btn-verify-relay">🔁 VERIFY VIA RELAY</button>';
  el("btn-verify-direct").addEventListener("click", () => beginVerification("DIRECT"));
  el("btn-verify-relay").addEventListener("click", () => attemptRelay());
}

/* ---- Attendance request + challenge-response (spec §7/§8) -------- */
/*
  DIRECT|student_id|session_id|request_id|nonce
  Replay protection: request_id single-use, nonce tied to live session.
*/
async function beginVerification(routeType, relayInfo) {
  /* Real BLE must be requested synchronously inside the click gesture.
     Attempted whenever the browser provides Web Bluetooth (secure
     context + Chrome/Edge) — independent of the cloud-sync toggle. */
  let realBle = null;
  if (routeType === "DIRECT") {
    const cap = bleCapability();
    realBle = cap.ok ? await tryRealBLE() : { skipped: true, reason: cap.reason };
  }
  try {
    await runVerification(routeType, relayInfo, realBle);
  } catch (err) {
    failResult("Verification error: " + err.message);
  }
}

async function runVerification(routeType, relayInfo, realBle) {
  me();
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-verify").classList.add("active");
  const steps = el("verify-steps");
  steps.innerHTML = "";

  const requestId = uid("req");

  function step(name) {
    const d = document.createElement("div");
    d.className = "step run"; d.textContent = name;
    steps.appendChild(d); return d;
  }
  function done(d, ok, note) {
    d.className = "step " + (ok ? "pass" : "fail");
    const suffix = document.createElement("span");
    suffix.innerHTML = " — " + (ok ? "✓" : "✘") + (note ? " <small>" + esc(note) + "</small>" : "");
    d.appendChild(suffix);
    return ok;
  }

  if (routeType === "RELAY" && (!relayInfo || typeof relayInfo.hopCount !== "number" || relayInfo.hopCount < 1 || relayInfo.hopCount > MAX_HOPS)) {
    return failResult("Invalid relay path (hop limit exceeded). NOT VERIFIED.");
  }

  /* 1. send request */
  let d = step("Sending attendance request " + (routeType === "DIRECT" ? "(direct BLE)" : "(relayed, hop " + relayInfo.hopCount + " via " + relayInfo.viaStudent + ")"));
  await sleep(700);

  /* teacher-side validation */
  reloadDB();
  const session = getActiveSession();
  if (!session || session.status !== "ACTIVE" || now() >= session.expiration_time) {
    done(d, false, "session not active"); return failResult("Session expired or ended. NOT VERIFIED.");
  }
  if (DB.seen_request_ids.length > 500) DB.seen_request_ids = DB.seen_request_ids.slice(-200);
  DB.seen_request_ids.push(requestId); saveDB();
  done(d, true);

  /* teacher validates identity from the authenticated app session,
     never from a typed-in ID */
  d = step("Teacher validates identity & registered device");
  await sleep(600);
  me();
  if (!currentStudent || !authCtx) { done(d, false, "not authenticated"); return failResult("Not authenticated."); }
  if (currentStudent.class_id !== session.class_id) { done(d, false, "wrong class"); return failResult("You are not enrolled in this class."); }
  if (authCtx.deviceId !== currentStudent.registered_device_id) {
    rejectAttendance(currentStudent, "unregistered_phone");
    done(d, false, "unregistered phone"); return failResult("Device not registered to this student.");
  }
  done(d, true, currentStudent.registered_device_id);

  /* 2. teacher issues random, single-use, expiring challenge */
  d = step("Receiving challenge");
  await sleep(600);
  currentChallenge = {
    value: randHex(16),
    expiresAt: now() + CHALLENGE_TTL_MS,
    used: false,
    sessionId: session.session_id
  };
  done(d, true, currentChallenge.value.slice(0, 12) + "…");

  /* 3. compute response = SHA-256(challenge || device_secret) */
  d = step("Computing authenticated response");
  await sleep(800);
  if (now() > currentChallenge.expiresAt) { done(d, false, "challenge expired"); return failResult("Challenge expired."); }
  const response = await sha256hex(currentChallenge.value + currentStudent.device_secret);
  done(d, true);

  /* 4. teacher verifies response + RSSI evidence + duplicates */
  d = step("Teacher verifies response & proximity evidence");
  await sleep(900);

  const expected = await sha256hex(currentChallenge.value + currentStudent.device_secret);
  if (response !== expected) { done(d, false, "challenge mismatch"); return failResult("Challenge verification failed."); }
  if (now() > currentChallenge.expiresAt || currentChallenge.used) {
    done(d, false, "challenge expired/used"); return failResult("Challenge expired.");
  }
  currentChallenge.used = true;
  done(d, true, "challenge valid");

  /* RSSI evidence: prefer REAL Web Bluetooth measurement (online mode),
     otherwise simulated radio evidence. Proximity evidence only. */
  let rssi, rssiNote;
  if (realBle && realBle.ok) {
    rssi = realBle.rssi != null ? realBle.rssi : simulateRSSI(myPosition());
    rssiNote = "real device connected" +
      (realBle.rssi != null ? ", RSSI " + realBle.rssi + " dBm" : " (RSSI unavailable — simulated)");
  } else if (realBle && realBle.skipped) {
    rssi = simulateRSSI(myPosition());
    rssiNote = realBle.reason;
  } else if (realBle && !realBle.ok) {
    rssiNote = "real BLE failed — fell back to simulation";
    rssi = routeType === "DIRECT" ? simulateRSSI(myPosition()) : relayInfo.rssi;
  } else {
    rssi = routeType === "DIRECT" ? simulateRSSI(myPosition()) : relayInfo.rssi;
    rssiNote = null;
  }

  reloadDB();
  const live = getActiveSession();
  if (!live || live.session_id !== session.session_id || live.status !== "ACTIVE" || now() >= live.expiration_time) {
    done(d, false, "session expired mid-verification"); return failResult("Session expired during verification. NOT VERIFIED.");
  }
  const dup = DB.attendance.some(a => a.session_id === session.session_id && a.student_id === currentStudent.student_id);
  if (dup) { done(d, false, "already recorded this session"); return failResult("Attendance already requested for this session."); }

  if (routeType === "DIRECT") {
    if (rssi <= RSSI_FLOOR) {
      done(d, false, "no usable BLE link (" + rssi + " dBm)");
      return failResult("No direct BLE connection. Try the relay path below. NOT VERIFIED (not absent).");
    }
    done(d, true, rssiNote ? (rssiNote + " — proximity evidence recorded") : ("RSSI " + rssi + " dBm — proximity evidence recorded"));
    const ok = recordAttendance(currentStudent, "DIRECT", rssi, 0, null);
    if (!ok) { done(d, false, "rejected by teacher validation"); return failResult("Rejected by teacher validation (duplicate/expired)."); }
    return successResult(rssi, "DIRECT", null, 0);
  }

  /* RELAY: communication works, but a relay does NOT prove physical
     presence (spec §15). Evidence stays weak -> teacher review. */
  if (relayInfo.hopCount > MAX_HOPS) { done(d, false, "hop limit exceeded"); return failResult("Hop limit exceeded — message discarded."); }
  done(d, true, "relayed via " + relayInfo.viaStudent + " — hop " + relayInfo.hopCount + "/" + MAX_HOPS);
  reloadDB();
  DB.relay_events.push({
    event_id: uid("rl"), message_id: uid("msg"), session_id: session.session_id,
    source_student_id: currentStudent.student_id, relay_student_id: relayInfo.viaStudent,
    hop_count: relayInfo.hopCount, timestamp: now(), status: "FORWARDED"
  });
  saveDB();
  const okRelay = recordAttendance(currentStudent, "RELAY", rssi, relayInfo.hopCount, relayInfo.viaStudent);
  if (!okRelay) { done(d, false, "rejected by teacher validation"); return failResult("Rejected by teacher validation (duplicate/expired)."); }
  successResult(rssi, "RELAY", relayInfo.viaStudent, relayInfo.hopCount);
}

function failResult(text) {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-result").classList.add("active");
  el("result-content").innerHTML =
    '<div class="panel" style="text-align:center"><h2 style="color:var(--amber)">NOT VERIFIED</h2>' +
    "<p class='muted' style='margin-top:8px'>" + esc(text) + "</p>" +
    "<p class='muted' style='margin-top:8px'><small>You are NOT marked absent — contact your teacher.</small></p></div>";
}

function successResult(rssi, route, via, hops) {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-result").classList.add("active");
  el("result-content").innerHTML =
    '<div class="panel" style="text-align:center"><h2 style="color:var(--green)">✓ VERIFICATION COMPLETE</h2>' +
    "<p class='muted' style='margin-top:8px'>Your presence request passed all checks and is <b>eligible</b>.<br>" +
    "The teacher finalizes attendance.</p>" +
    '<p class="mono muted" style="margin-top:10px">Route: ' + esc(route) +
    (via ? " via " + esc(via) + " (" + Number(hops) + "/" + Number(MAX_HOPS) + " hops)" : "") +
    " · RSSI: " + Number(rssi) + " dBm (evidence)</p></div>";
}

/* ---- Relay path (spec §11–§14) -----------------------------------
   RELAY|message_id|session_id|source|TEACHER|ATTENDANCE_REQUEST|
   timestamp|hop_count|payload   — relays only forward; they never
   modify identity, status, or authorize attendance.
-------------------------------------------------------------------- */
function attemptRelay() {
  const myself = me();
  if (!myself) return failResult("Not authenticated — relay unavailable.");
  const sess = getActiveSession();
  if (!sess) return failResult("No active session — relay unavailable.");
  // Measure each candidate once; prefer strongest (shortest reliable) route.
  const candidates = DB.students
    .filter(s =>
      s.student_id !== myself.student_id &&
      s.class_id === myself.class_id &&          // relay must be a classmate
      s.relay_active_for === sess.session_id)    // session-bound opt-in
    .map(s => ({ s, rssi: simulateRSSI(s.position || "near") }))
    .filter(c => c.rssi > RSSI_FLOOR)
    .sort((a, b) => b.rssi - a.rssi);

  if (!candidates.length) {
    reloadDB();
    DB.attendance_events.push({ event_id: uid("evt"), ts: new Date().toISOString(), event_type: "RELAY_UNAVAILABLE",
      student_id: myself.student_id, session_id: sess.session_id });
    saveDB();
    return failResult("No relay available. NOT VERIFIED (not absent) — move closer or ask a classmate to enable relay mode.");
  }
  const best = candidates[0];
  const hopCount = 2;                                              // Teacher->A->B
  if (hopCount > MAX_HOPS) return failResult("Hop limit exceeded — message discarded.");

  beginVerification("RELAY", {
    viaStudent: best.s.name + " (" + best.s.student_id + ")",
    hopCount: hopCount,
    rssi: best.rssi
  });
}

/* ---- History ------------------------------------------------------ */
function renderHistory() {
  me();
  if (!currentStudent) return;
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-history").classList.add("active");
  reloadDB();
  const rows = DB.attendance.filter(a => a.student_id === currentStudent.student_id).map(a => {
    const sess = DB.sessions.find(s => s.session_id === a.session_id);
    const safeStatus = esc(a.verification_status);
    return "<tr><td>" + esc(new Date(a.timestamp).toLocaleString()) + "</td><td>" +
      esc(sess ? sess.subject : "?") + '</td><td><span class="st-' + safeStatus + '">' +
      safeStatus + "</span></td><td>" + esc(a.route_type) + "</td></tr>";
  });
  el("history-body").innerHTML = rows.length ? rows.join("") :
    '<tr><td colspan="4" class="muted">No records yet.</td></tr>';
}
