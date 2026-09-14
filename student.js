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
  if (!s || !(await verifyPassword(s.student_id, val("st-pass"), s.password_hash))) {
    msg.textContent = "Invalid credentials. Check your ID and password."; msg.className = "msg err"; return;
  }
  msg.textContent = ""; msg.className = "msg";
  currentStudent = s;
  // Authenticated session carries the registered device & isolated secret
  const secret = (DB.student_secrets && DB.student_secrets[s.student_id]) || "";
  authCtx = { deviceId: s.registered_device_id, deviceSecret: secret };

  el("st-name").textContent = s.name;
  el("p-name").textContent = s.name;
  el("p-meta").textContent = s.student_id + " · " + (s.email || "");
  const avatar = document.querySelector("#sp-home .avatar");
  if (avatar) avatar.textContent = (s.name || "S").trim().charAt(0).toUpperCase() || "S";
  el("p-device").textContent = "Device " + s.registered_device_id;
  const enrolledList = (s.enrolled_classes && s.enrolled_classes.length) ? s.enrolled_classes.join(", ") : s.class_id;
  el("p-class").textContent = "Classes: " + enrolledList;
  const jInput = el("st-join-code");
  if (jInput) jInput.value = "";
  const jMsg = el("st-join-msg");
  if (jMsg) { jMsg.textContent = ""; jMsg.className = "msg"; }
  el("relay-mode").checked = s.relay_active_for != null;
  const posSel = el("sim-position");
  if (posSel) posSel.value = s.position || "near";
  updateRelayInfo();
  updateBleStatus();
  audit("STUDENT_LOGIN", s.student_id + " device=" + s.registered_device_id);
  showScreen("screen-student");
  studentHome();
}

async function joinClassByCode() {
  const code = val("st-join-code").trim().toUpperCase();
  const msg = el("st-join-msg");
  if (!msg) return;
  if (!code) {
    msg.textContent = "Please enter a class code.";
    msg.className = "msg err";
    return;
  }
  const student = me();
  if (!student) {
    msg.textContent = "Not logged in.";
    msg.className = "msg err";
    return;
  }

  let cls = findClassByCode(code);

  if (!cls) {
    try {
      const resp = await fetch("http://localhost:8000/api/classes/code/" + encodeURIComponent(code));
      if (resp.ok) {
        const remoteClass = await resp.json();
        if (!DB.classes.some(c => c.class_id === remoteClass.class_id)) {
          DB.classes.push({
            class_id: remoteClass.class_id,
            class_name: remoteClass.class_name,
            subject: remoteClass.subject,
            teacher_id: remoteClass.teacher_id,
            class_code: remoteClass.class_code || remoteClass.class_id
          });
          saveDB();
        }
        cls = remoteClass;
      }
    } catch (_) { /* offline fallback */ }
  }

  if (!cls) {
    msg.textContent = "Class code '" + esc(code) + "' not found. Check with your instructor.";
    msg.className = "msg err";
    return;
  }

  student.enrolled_classes = student.enrolled_classes || (student.class_id ? [student.class_id] : []);
  const alreadyEnrolled = student.class_id === cls.class_id || student.enrolled_classes.includes(cls.class_id);
  if (alreadyEnrolled) {
    msg.textContent = "You are already enrolled in class " + esc(cls.class_id) + " (" + esc(cls.subject) + ").";
    msg.className = "msg ok";
    return;
  }

  if (!student.enrolled_classes.includes(cls.class_id)) {
    student.enrolled_classes.push(cls.class_id);
  }
  student.class_id = cls.class_id;
  saveDB();
  currentStudent = student;

  const pClass = el("p-class");
  if (pClass) pClass.textContent = "Classes: " + student.enrolled_classes.join(", ");

  msg.textContent = "✓ Successfully joined " + esc(cls.class_name) + " (" + esc(cls.subject) + ")!";
  msg.className = "msg ok";

  const joinInput = el("st-join-code");
  if (joinInput) joinInput.value = "";

  audit("STUDENT_JOIN_CLASS", student.student_id + " joined " + cls.class_id + " via code " + code);

  try {
    const headers = { "Content-Type": "application/json" };
    if (student.cloudToken) {
      headers["Authorization"] = "Bearer " + student.cloudToken;
    }
    fetch("http://localhost:8000/api/classes/join", {
      method: "POST",
      headers,
      body: JSON.stringify({ student_id: student.student_id, class_code: code })
    }).catch(() => {});
  } catch (_) {}
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
    ? "Real BLE available — verification will attempt a real device connection"
    : cap.reason;
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
    return { ok: true, server, device, rssi, name: device.name || "unnamed device" };
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
  const enrolled = (myself.enrolled_classes && myself.enrolled_classes.length)
    ? myself.enrolled_classes
    : [myself.class_id];
  if (!enrolled.includes(sess.class_id)) {
    box.innerHTML = '<div class="step fail">✘ This session belongs to class ' +
      esc(sess.class_id) + " — you are enrolled in " + esc(enrolled.join(", ")) + ".</div>";
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
        ? "Real BLE mode: a Web Bluetooth connection will be attempted when you verify."
        : cap.reason + ".")) + "</small></div>" +
    '<button class="btn primary block" id="btn-verify-direct">Verify My Presence</button>' +
    '<button class="btn block" id="btn-verify-relay">Verify via Relay</button>';
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

  /* 1. Send attendance request & request challenge from Teacher Authority */
  let d = step("Requesting single-use challenge from Teacher GATT Authority");
  await sleep(600);

  let challengeStr = null;
  let gattService = null;
  let useRealGatt = false;

  if (realBle && realBle.ok && realBle.server) {
    try {
      gattService = await realBle.server.getPrimaryService(UUIDS.service);
      useRealGatt = true;
    } catch (e) {
      console.warn("GATT primary service discovery fallback to local simulation:", e);
    }
  }

  if (useRealGatt && gattService) {
    try {
      const reqChar = await gattService.getCharacteristic(UUIDS.request);
      await reqChar.writeValueWithResponse(new TextEncoder().encode(`${currentStudent.student_id}|${authCtx.deviceId}|${routeType}`));

      const chChar = await gattService.getCharacteristic(UUIDS.challenge);
      const chVal = await chChar.readValue();
      challengeStr = new TextDecoder().decode(chVal).trim();
      done(d, true, challengeStr.slice(0, 10) + "… (issued via Real Web Bluetooth GATT)");
    } catch (gattErr) {
      console.warn("Real GATT challenge request error, using simulation:", gattErr);
      useRealGatt = false;
    }
  }

  reloadDB();
  const session = getActiveSession();
  if (!useRealGatt) {
    if (!session || session.status !== "ACTIVE" || now() >= session.expiration_time) {
      done(d, false, "session not active"); return failResult("Session expired or ended. NOT VERIFIED.");
    }
    if (DB.seen_request_ids.length > 500) DB.seen_request_ids = DB.seen_request_ids.slice(-200);
    DB.seen_request_ids.push(requestId); saveDB();

    const challengeRes = teacherHandleChallengeRequest(session.session_id, currentStudent.student_id, authCtx.deviceId);
    if (!challengeRes.ok) {
      done(d, false, challengeRes.reason);
      return failResult(challengeRes.reason);
    }
    challengeStr = challengeRes.challenge;
    done(d, true, challengeStr.slice(0, 10) + "… (issued by Teacher root)");
  }

  /* 2. Compute hardware-bound response */
  d = step("Computing hardware-bound device signature: SHA-256(challenge || secret)");
  await sleep(700);
  const secret = authCtx.deviceSecret || (DB.student_secrets && DB.student_secrets[currentStudent.student_id]) || "";
  const response = await sha256hex(challengeStr + secret);
  done(d, true);

  /* 3. Capture radio proximity evidence */
  d = step("Measuring BLE proximity & Link Layer evidence");
  await sleep(600);

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

  if (routeType === "DIRECT" && rssi <= RSSI_FLOOR) {
    done(d, false, "no usable BLE link (" + rssi + " dBm)");
    return failResult("No direct BLE connection. Try the relay path below. NOT VERIFIED (not absent).");
  }
  done(d, true, rssiNote ? (rssiNote + " — proximity evidence recorded") : ("RSSI " + rssi + " dBm — proximity evidence recorded"));

  /* 4. Submit to Teacher Authority for cryptographic, enrollment, and proximity verification */
  d = step("Submitting proof & proximity to Teacher Authority for verification");
  await sleep(800);

  if (useRealGatt && gattService) {
    try {
      if (routeType === "RELAY") {
        const relayChar = await gattService.getCharacteristic(UUIDS.relay);
        const payload = `RELAY|${currentStudent.student_id}|${authCtx.deviceId}|${response}|${relayInfo.hopCount}|${relayInfo.viaStudent}|${rssi}`;
        await relayChar.writeValueWithResponse(new TextEncoder().encode(payload));
      } else {
        const respChar = await gattService.getCharacteristic(UUIDS.response);
        const payload = `${currentStudent.student_id}|${authCtx.deviceId}|${response}|${rssi}`;
        await respChar.writeValueWithResponse(new TextEncoder().encode(payload));
      }

      const resChar = await gattService.getCharacteristic(UUIDS.result);
      const resVal = await resChar.readValue();
      const resText = new TextDecoder().decode(resVal).trim();
      if (resText.startsWith("ELIGIBLE") || resText.startsWith("PRESENT")) {
        done(d, true, "Teacher GATT Authority verified challenge over BLE & recorded ELIGIBLE");
        return successResult(rssi, routeType, relayInfo ? relayInfo.viaStudent : null, relayInfo ? relayInfo.hopCount : 0);
      } else {
        const errReason = resText.split(":")[2] || resText;
        done(d, false, errReason);
        return failResult("Teacher Authority rejected verification: " + errReason);
      }
    } catch (e) {
      console.warn("Real GATT response transmission fallback to local store:", e);
    }
  }

  if (routeType === "RELAY") {
    reloadDB();
    DB.relay_events.push({
      event_id: uid("rl"), message_id: uid("msg"), session_id: session ? session.session_id : "SES_ACTIVE",
      source_student_id: currentStudent.student_id, relay_student_id: relayInfo.viaStudent,
      hop_count: relayInfo.hopCount, timestamp: now(), status: "FORWARDED"
    });
    saveDB();
  }

  if (!session) {
    return failResult("Session expired or inactive. NOT VERIFIED.");
  }

  const verifyRes = await teacherVerifyAttendanceSubmission(
    session.session_id,
    currentStudent.student_id,
    authCtx.deviceId,
    response,
    routeType,
    rssi,
    relayInfo
  );

  if (!verifyRes.ok) {
    done(d, false, verifyRes.reason);
    return failResult(verifyRes.reason);
  }

  done(d, true, "Teacher Authority verified challenge & recorded ELIGIBLE");
  return successResult(rssi, routeType, verifyRes.viaStudent, verifyRes.hopCount);
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
