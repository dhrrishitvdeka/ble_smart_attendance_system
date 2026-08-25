/* ============================================================
   STUDENT APP — login, device binding, BLE scan simulation,
   challenge-response attendance, optional relay mode, history.
   Student can NEVER directly choose PRESENT.
   ============================================================ */

let currentStudent = null;          // logged-in student record
let authCtx = null;                 // { deviceId } from login session
let currentChallenge = null;        // { value, expiresAt, used }
let scanTimer = null;

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
  updateRelayInfo();
  updateBleStatus();
  audit("STUDENT_LOGIN", s.student_id + " device=" + s.registered_device_id);
  showScreen("screen-student");
  studentHome();
}
function studentLogout() {
  if (currentStudent) currentStudent.relay_active_for = null;
  currentStudent = null; authCtx = null; saveDB();
  showScreen("screen-role");
}
function studentHome() {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-home").classList.add("active");
}

/* ---- Relay mode (spec §10/§11): explicit opt-in, session-only ---- */
function toggleRelay(on) {
  const s = me();
  const sess = getActiveSession();
  if (on && !sess) {
    alert("Relay mode is only allowed during an ACTIVE attendance session.");
    el("relay-mode").checked = false;
    return;
  }
  s.relay_active_for = on ? sess.session_id : null;
  audit(on ? "RELAY_ENABLED" : "RELAY_DISABLED", currentStudent.student_id);
  saveDB();
  updateRelayInfo();
}
function updateRelayInfo() {
  const info = el("relay-info");
  if (currentStudent.relay_active_for) {
    info.textContent = "\u26A1 Relay active for session " + currentStudent.relay_active_for +
      ". You forward messages but have NO authority to mark attendance.";
    info.className = "msg ok";
  } else info.textContent = "";
}

/* ---- BLE scan (spec §5) ------------------------------------------ */
function gotoScan() {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-scan").classList.add("active");
  el("scan-result").innerHTML = "";
  let dots = 0;
  scanTimer = setInterval(() => {
    dots = (dots + 1) % 4;
    el("sp-scan").querySelector("h3").textContent = "Scanning for teacher session" + ".".repeat(dots);
  }, 400);
  setTimeout(() => {
    clearInterval(scanTimer);
    stopScan();
    renderScanResult();
  }, 2200);
}
function stopScan() { if (scanTimer) { clearInterval(scanTimer); scanTimer = null; } }

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
  const badge = el("ble-status");
  if (!badge) return;
  const cap = bleCapability();
  if (cap.ok) {
    badge.textContent = "\u{1F534} Real BLE available \u2014 verification will connect to a real device";
    badge.className = "badge ok";
  } else {
    badge.textContent = "\u26A0 " + cap.reason;
    badge.className = "badge warn";
  }
}

async function tryRealBLE() {
  try {
    const device = await navigator.bluetooth.requestDevice({ acceptAllDevices: true });
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
  const activeSession = getActiveSession();
  if (!activeSession) {
    box.innerHTML = '<div class="step fail">\u2718 No active classroom session found.<br>' +
      "<small>Bluetooth is on and permissions granted (simulated), but the teacher has not started attendance.</small></div>";
    return;
  }
  if (me().class_id !== activeSession.class_id) {
    box.innerHTML = '<div class="step fail">\u2718 This session belongs to class ' +
      esc(activeSession.class_id) + " \u2014 you are enrolled in " + esc(me().class_id) + ".</div>";
    return;
  }
  const rssi = simulateRSSI();
  const p = proximityLabel(rssi);
  const cap = bleCapability();
  box.innerHTML =
    '<div class="step pass">\u2713 Classroom Session Found</div>' +
    '<div class="step">Subject: <b>' + esc(activeSession.subject) + "</b></div>" +
    '<div class="step">Teacher: ' + esc(DB.teachers.find(t => t.teacher_id === activeSession.teacher_id).name) + "</div>" +
    '<div class="step mono">Session: ' + esc(activeSession.session_id) + "</div>" +
    '<div class="step">BLE Signal: <span class="badge ' + p.cls + '">' + p.label + "</span> " +
    '<small class="mono">' + rssi + " dBm</small> <small>(proximity evidence, not distance)</small></div>" +
    '<div class="step"><small>' + (cap.ok
      ? "\u{1F534} Online mode: a real Web Bluetooth connection will be attempted when you verify."
      : "\u26A0 " + esc(cap.reason) + ".") + "</small></div>" +
    '<button class="btn primary block" onclick="beginVerification(\'DIRECT\')">VERIFY MY PRESENCE</button>';
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
    d.className = "step run"; d.innerHTML = name;
    steps.appendChild(d); return d;
  }
  function done(d, ok, note) {
    d.className = "step " + (ok ? "pass" : "fail");
    d.innerHTML += " \u2014 " + (ok ? "\u2713" : "\u2718") + (note ? " <small>" + note + "</small>" : "");
    return ok;
  }

  /* 1. send request */
  let d = step("Sending attendance request " + (routeType === "DIRECT" ? "(direct BLE)" : "(relayed, hop " + relayInfo.hopCount + " via " + relayInfo.viaStudent + ")"));
  await sleep(700);

  /* teacher-side validation */
  const session = getActiveSession();
  if (!session) {
    done(d, false, "session not active"); return failResult("Session expired or ended. NOT VERIFIED.");
  }
  if (DB.seen_request_ids.includes(requestId)) {   // replay prevention
    done(d, false, "duplicate request"); return failResult("Duplicate request rejected.");
  }
  DB.seen_request_ids.push(requestId); saveDB();
  done(d, true);

  /* teacher validates identity from the authenticated app session,
     never from a typed-in ID */
  d = step("Teacher validates identity & registered device");
  await sleep(600);
  if (!currentStudent || !authCtx) return failResult("Not authenticated.");
  if (currentStudent.class_id !== session.class_id) return failResult("You are not enrolled in this class.");
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
  done(d, true, '<span class="mono">' + currentChallenge.value.slice(0, 12) + "\u2026</span>");

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
    rssi = realBle.rssi != null ? realBle.rssi : simulateRSSI();
    rssiNote = "real device \u201c" + realBle.name + "\u201d connected" +
      (realBle.rssi != null ? ", RSSI " + realBle.rssi + " dBm" : " (RSSI unavailable \u2014 simulated)");
  } else if (realBle && realBle.skipped) {
    rssi = simulateRSSI();
    rssiNote = realBle.reason;
  } else if (realBle && !realBle.ok) {
    rssiNote = "real BLE failed (" + realBle.error + ") \u2014 fell back to simulation";
    rssi = routeType === "DIRECT" ? simulateRSSI() : relayInfo.rssi;
  } else {
    rssi = routeType === "DIRECT" ? simulateRSSI() : relayInfo.rssi;
    rssiNote = null;
  }

  const dup = DB.attendance.some(a => a.session_id === session.session_id && a.student_id === currentStudent.student_id);
  if (dup) { done(d, false, "already recorded this session"); return failResult("Attendance already requested for this session."); }

  if (routeType === "DIRECT") {
    if (rssi <= RSSI_FLOOR) {
      done(d, false, "no usable BLE link (" + rssi + " dBm)");
      return failResult("No direct BLE connection. Try the relay path. NOT VERIFIED (not absent).");
    }
    done(d, true, rssiNote ? (rssiNote + " \u2014 proximity evidence recorded") : ("RSSI " + rssi + " dBm \u2014 proximity evidence recorded"));
    recordAttendance(currentStudent, "DIRECT", rssi, 0, null);
    return successResult(rssi, "DIRECT", null, 0);
  }

  /* RELAY: communication works, but a relay does NOT prove physical
     presence (spec §15). Evidence stays weak -> teacher review. */
  done(d, true, "relayed via " + relayInfo.viaStudent + " \u2014 hop " + relayInfo.hopCount + "/" + MAX_HOPS);
  DB.relay_events.push({
    event_id: uid("rl"), message_id: uid("msg"), session_id: session.session_id,
    source_student_id: currentStudent.student_id, relay_student_id: relayInfo.viaStudent,
    hop_count: relayInfo.hopCount, timestamp: now(), status: "FORWARDED"
  });
  saveDB();
  recordAttendance(currentStudent, "RELAY", rssi, relayInfo.hopCount, relayInfo.viaStudent);
  successResult(rssi, "RELAY", relayInfo.viaStudent, relayInfo.hopCount);
}

function failResult(text) {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-result").classList.add("active");
  el("result-content").innerHTML =
    '<div class="panel" style="text-align:center"><h2 style="color:var(--amber)">NOT VERIFIED</h2>' +
    "<p class='muted' style='margin-top:8px'>" + text + "</p>" +
    "<p class='muted' style='margin-top:8px'><small>You are NOT marked absent \u2014 contact your teacher.</small></p></div>";
}

function successResult(rssi, route, via, hops) {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-result").classList.add("active");
  el("result-content").innerHTML =
    '<div class="panel" style="text-align:center"><h2 style="color:var(--green)">\u2713 VERIFICATION COMPLETE</h2>' +
    "<p class='muted' style='margin-top:8px'>Your presence request passed all checks and is <b>eligible</b>.<br>" +
    "The teacher finalizes attendance.</p>" +
    '<p class="mono muted" style="margin-top:10px">Route: ' + route +
    (via ? " via " + via + " (" + hops + "/" + MAX_HOPS + " hops)" : "") +
    " \u00b7 RSSI: " + rssi + " dBm (evidence)</p></div>";
}

/* ---- Relay path (spec §11–§14) -----------------------------------
   RELAY|message_id|session_id|source|TEACHER|ATTENDANCE_REQUEST|
   timestamp|hop_count|payload   — relays only forward; they never
   modify identity, status, or authorize attendance.
-------------------------------------------------------------------- */
function attemptRelay() {
  me();
  const sess = getActiveSession();
  const relays = DB.students.filter(s =>
    s.student_id !== currentStudent.student_id &&
    s.class_id === currentStudent.class_id &&          // relay must be a classmate
    s.relay_active_for === sess?.session_id &&         // session ID string, not the object
    simulateRSSI() > RSSI_FLOOR);

  if (!sess) return failResult("No active session \u2014 relay unavailable.");
  if (!relays.length) {
    DB.attendance_events.push({ event_id: uid("evt"), ts: new Date().toISOString(), event_type: "RELAY_UNAVAILABLE",
      student_id: currentStudent.student_id });
    saveDB();
    return failResult("No relay available. NOT VERIFIED (not absent) \u2014 move closer or ask a classmate to enable relay mode.");
  }
  relays.sort((a, b) => simulateRSSI() - simulateRSSI());       // prefer shortest reliable route
  const relay = relays[0];
  const hopCount = 2;                                              // Teacher->A->B
  if (hopCount > MAX_HOPS) return failResult("Hop limit exceeded \u2014 message discarded.");

  beginVerification("RELAY", {
    viaStudent: relay.name + " (" + relay.student_id + ")",
    hopCount: hopCount,
    rssi: -70 + (crypto.getRandomValues(new Uint8Array(1))[0] % 10)
  });
}

/* ---- History ------------------------------------------------------ */
function renderHistory() {
  document.querySelectorAll(".phone-page").forEach(p => p.classList.remove("active"));
  el("sp-history").classList.add("active");
  const rows = DB.attendance.filter(a => a.student_id === currentStudent.student_id).map(a => {
    const sess = DB.sessions.find(s => s.session_id === a.session_id);
    return "<tr><td>" + new Date(a.timestamp).toLocaleString() + "</td><td>" +
      (sess ? sess.subject : "?") + '</td><td><span class="st-' + a.verification_status + '">' +
      a.verification_status + "</span></td><td>" + a.route_type + "</td></tr>";
  });
  el("history-body").innerHTML = rows.length ? rows.join("") :
    '<tr><td colspan="4" class="muted">No records yet.</td></tr>';
}
