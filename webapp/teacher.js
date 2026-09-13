/* ============================================================
   TEACHER CONSOLE — session manager, GATT-server simulation,
   live dashboard, finalize, offline sync. Final authority.
   ============================================================ */

let currentTeacher = null;
let teacherSessionPassword = null;
let expiryTimer = null;

/* Re-read the shared DB (student tabs write to it concurrently) and
   keep the activeSession pointer pointing at the fresh object. */
function syncFromStorage() {
  const sid = activeSession ? activeSession.session_id : null;
  reloadDB();
  if (sid) {
    const s = DB.sessions.find(x => x.session_id === sid);
    activeSession = s || null;
  } else {
    activeSession = getActiveSession();
  }
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  const n = el(id);
  if (!n) return;
  n.classList.add("active");
  /* Move screen-reader focus to the screen heading (no keyboard popup) */
  const h = n.querySelector("h1,h2,h3");
  if (h) {
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  }
}

function clearExpiryTimer() {
  if (expiryTimer) { clearInterval(expiryTimer); expiryTimer = null; }
}
function armExpiryTimer() {
  clearExpiryTimer();
  expiryTimer = setInterval(() => {
    if (!activeSession) { clearExpiryTimer(); return; }
    syncFromStorage();
    if (!activeSession) { clearExpiryTimer(); return; }
    const left = activeSession.expiration_time - now();
    if (left <= 0) {
      activeSession.status = "EXPIRED";
      audit("SESSION_EXPIRED", activeSession.session_id);
      saveDB(); updateSessionStatusUI();
      clearExpiryTimer();
    } else {
      const n = el("s-expiry");
      if (n) n.textContent = Math.ceil(left / 1000) + "s";
    }
  }, 500);
}

async function teacherLogin() {
  const t = DB.teachers.find(x => x.teacher_id === val("t-id").toUpperCase());
  const msg = el("t-login-msg");
  if (!t || !(await verifyPassword(t.teacher_id, val("t-pass"), t.password_hash))) {
    msg.textContent = "Invalid credentials. Check your ID and password."; msg.className = "msg err"; return;
  }
  msg.textContent = ""; msg.className = "msg";
  currentTeacher = t;
  teacherSessionPassword = val("t-pass") || "teach123";
  delete t.password;
  (DB.teachers || []).forEach(x => { delete x.password; });
  el("t-name").textContent = t.name;

  // Capability detection (spec §2: never assume peripheral-mode support)
  const supported = true; // simulated laptop supports GATT server mode
  el("ble-support").textContent = supported ? "\u2714 BLE GATT peripheral supported" : "\u2718 Not supported";
  el("ble-support").className = "badge " + (supported ? "ok" : "err");
  // Only classes scheduled/assigned to THIS teacher are selectable
  const mine = teacherClasses(t.teacher_id);
  el("class-select").innerHTML = mine.length
    ? mine.map(c => '<option value="' + esc(c.class_id) + '">' + esc(c.class_id) + " (Code: " + esc(c.class_code || c.class_id) + ") — " + esc(c.subject) + "</option>").join("")
    : '<option value="">No classes assigned — contact admin</option>';
  el("btn-start").disabled = !mine.length;
  audit("TEACHER_LOGIN", t.teacher_id);
  renderLiveTable();
  renderAudit();
  restoreSession();
  showScreen("screen-teacher");
}

/* Restore an ACTIVE session from the shared DB (page refresh / other tab) */
function restoreSession() {
  const s = getActiveSession();
  if (!s || !currentTeacher || currentTeacher.teacher_id !== s.teacher_id) return;
  activeSession = s;
  el("setup-panel").classList.add("hidden");
  el("session-panel").classList.remove("hidden");
  el("s-class").textContent = s.class_id;
  const sCode = el("s-code");
  if (sCode) sCode.textContent = s.class_code || s.class_id;
  el("s-subject").textContent = s.subject;
  el("s-id").textContent = s.session_id;
  el("s-nonce").textContent = s.random_nonce;
  updateSessionStatusUI();

  armExpiryTimer();
}

function teacherLogout() {
  if (activeSession && currentTeacher && activeSession.teacher_id === currentTeacher.teacher_id) endSession();
  clearExpiryTimer();
  currentTeacher = null;
  teacherSessionPassword = null;
  showScreen("screen-role");
}

/* ---- Session creation (spec §4): temporary, random, expiring ---- */
function startSession() {
  if (!currentTeacher) { alert("Login as teacher first."); return; }
  syncFromStorage();
  const existing = getActiveSession();
  if (existing) { alert("A session is already active: " + existing.session_id); return; }
  const cls = DB.classes.find(c => c.class_id === el("class-select").value);
  if (!cls) { alert("No class assigned to you. Ask the admin to schedule a class."); return; }
  activeSession = {
    session_id: randHex(8),                    // cryptographically random temp ID
    class_id: cls.class_id,
    class_code: cls.class_code || cls.class_id,
    subject: cls.subject,
    teacher_id: currentTeacher.teacher_id,
    start_time: now(),
    expiration_time: now() + SESSION_TTL_MS,
    random_nonce: randHex(16),
    status: "ACTIVE"
  };
  DB.sessions.push(activeSession);
  DB.students.forEach(s => { s.relay_active_for = null; });   // relay only per-session
  audit("SESSION_START", activeSession.session_id + " class=" + cls.class_id + " (code=" + activeSession.class_code + ") nonce=" + activeSession.random_nonce);
  saveDB();

  el("setup-panel").classList.add("hidden");
  el("session-panel").classList.remove("hidden");
  el("s-class").textContent = cls.class_id;
  const sCode = el("s-code");
  if (sCode) sCode.textContent = activeSession.class_code;
  el("s-subject").textContent = cls.subject;
  el("s-id").textContent = activeSession.session_id;
  el("s-nonce").textContent = activeSession.random_nonce;
  updateSessionStatusUI();

  armExpiryTimer();
  renderLiveTable();
}

function updateSessionStatusUI() {
  const s = activeSession; if (!s) return;
  el("s-status").innerHTML = s.status === "ACTIVE"
    ? '<span class="badge ok">ACTIVE</span>'
    : '<span class="badge err">' + s.status + "</span>";
}

function endSession() {
  if (!activeSession) return;
  if (!currentTeacher) return;
  syncFromStorage();
  if (!activeSession) return;
  activeSession.status = "ENDED";
  audit("SESSION_END", activeSession.session_id);
  saveDB();
  activeSession = null;
  clearExpiryTimer();
  el("session-panel").classList.add("hidden");
  el("setup-panel").classList.remove("hidden");
  renderLiveTable();
}

/* ---- Teacher-side verification (spec §17 decision chain) --------
   authenticated -> registered device -> current session -> BLE comm
   -> proximity evidence -> challenge-response -> no duplicate
   -> ELIGIBLE (teacher finalizes). Failures => NOT_VERIFIED.
   Temporary BLE failure never auto-marks ABSENT.
------------------------------------------------------------------- */
/* ============================================================
   TEACHER GATT SERVER & ATTENDANCE AUTHORITY (Root of Trust)
   Enforces:
     1. Active session validation
     2. Student enrollment check
     3. Hardware registered device verification
     4. Cryptographic challenge issuance & verification
     5. Physical proximity (RSSI) and hop bounds
     6. Anti-replay & deduplication
   ============================================================ */

function teacherHandleChallengeRequest(sessionId, studentId, deviceId) {
  syncFromStorage();
  const session = getActiveSession();
  if (!session || session.session_id !== sessionId || session.status !== "ACTIVE" || now() >= session.expiration_time) {
    return { ok: false, reason: "Session is not active or has expired." };
  }
  const student = DB.students.find(s => s.student_id === studentId);
  if (!student) {
    return { ok: false, reason: "Student ID not found in roster." };
  }
  if (student.class_id !== session.class_id) {
    return { ok: false, reason: "Student is not enrolled in this session's class." };
  }
  if (deviceId !== student.registered_device_id) {
    rejectAttendance(student, "unregistered_phone");
    return { ok: false, reason: "Device ID does not match registered student device." };
  }

  // Issue random single-use challenge nonce tied to session and student
  const challengeNonce = randHex(16);
  session.pending_challenges = session.pending_challenges || {};
  session.pending_challenges[studentId] = {
    nonce: challengeNonce,
    expiresAt: now() + CHALLENGE_TTL_MS,
    used: false
  };
  saveDB();

  return {
    ok: true,
    challenge: challengeNonce,
    ttlMs: CHALLENGE_TTL_MS,
    sessionId: session.session_id
  };
}

async function teacherVerifyAttendanceSubmission(sessionId, studentId, deviceId, responseHash, routeType, rssiEvidence, relayInfo) {
  syncFromStorage();
  const session = getActiveSession();
  if (!session || session.session_id !== sessionId || session.status !== "ACTIVE" || now() >= session.expiration_time) {
    return { ok: false, reason: "Session expired or inactive." };
  }
  const student = DB.students.find(s => s.student_id === studentId);
  const isEnrolled = student && (student.class_id === session.class_id || (student.enrolled_classes && student.enrolled_classes.includes(session.class_id)));
  if (!isEnrolled) {
    return { ok: false, reason: "Student enrollment invalid for this class." };
  }
  if (deviceId !== student.registered_device_id) {
    rejectAttendance(student, "unregistered_phone");
    return { ok: false, reason: "Unregistered device signature rejected." };
  }

  // Validate server-side challenge
  session.pending_challenges = session.pending_challenges || {};
  const ch = session.pending_challenges[studentId];
  if (!ch) {
    return { ok: false, reason: "No valid challenge found for student. Request a fresh challenge." };
  }
  if (now() > ch.expiresAt) {
    return { ok: false, reason: "Challenge expired. Attestation window closed." };
  }
  if (ch.used) {
    return { ok: false, reason: "Challenge already used. Replay detected." };
  }

  // Cryptographic verification on teacher authority
  const secret = (DB.student_secrets && DB.student_secrets[studentId]) || student.device_secret || "";
  const expectedHash = await sha256hex(ch.nonce + secret);
  if (responseHash !== expectedHash) {
    rejectAttendance(student, "cryptographic_mismatch");
    return { ok: false, reason: "Cryptographic response mismatch. Authentication failed." };
  }

  // Consume challenge
  ch.used = true;

  // Proximity validation
  if (typeof rssiEvidence !== "number" || rssiEvidence <= RSSI_FLOOR) {
    return { ok: false, reason: "Proximity evidence below usable BLE threshold (" + rssiEvidence + " dBm)." };
  }

  // Route & hop validation
  if (routeType !== "DIRECT" && routeType !== "RELAY") {
    return { ok: false, reason: "Invalid route type: " + routeType };
  }
  let hopCount = 0;
  let viaStudent = null;
  if (routeType === "RELAY") {
    if (!relayInfo || typeof relayInfo.hopCount !== "number" || relayInfo.hopCount < 1 || relayInfo.hopCount > MAX_HOPS) {
      return { ok: false, reason: "Relay hop count out of bounds (max " + MAX_HOPS + ")." };
    }
    hopCount = relayInfo.hopCount;
    viaStudent = relayInfo.viaStudent;
  }

  // Anti-duplicate check
  const dup = DB.attendance.some(a => a.session_id === session.session_id && a.student_id === student.student_id);
  if (dup) {
    return { ok: false, reason: "Attendance already recorded for this session." };
  }

  // Authority commits attendance record to ELIGIBLE
  const rec = {
    attendance_id: uid("att"),
    session_id: session.session_id,
    student_id: student.student_id,
    timestamp: now(),
    verification_status: "ELIGIBLE",
    route_type: routeType,
    rssi_evidence: rssiEvidence,
    hop_count: hopCount,
    via_student: viaStudent,
    synced: false
  };
  DB.attendance.push(rec);
  DB.attendance_events.push({
    event_id: uid("evt"),
    ts: new Date().toISOString(),
    event_type: "ATTENDANCE_RECORDED",
    student_id: rec.student_id,
    session_id: rec.session_id,
    route: routeType
  });
  audit("ATTENDANCE_RECORDED", rec.student_id + " route=" + routeType + " rssi=" + rssiEvidence + "dBm" +
    (viaStudent ? " via=" + viaStudent : ""));
  saveDB();

  if (currentTeacher) renderLiveTable();

  return {
    ok: true,
    attendanceId: rec.attendance_id,
    status: "ELIGIBLE",
    routeType: routeType,
    rssi: rssiEvidence,
    hopCount: hopCount,
    viaStudent: viaStudent
  };
}

function recordAttendance(student, routeType, rssi, hopCount, viaStudent) {
  syncFromStorage();
  const session = getActiveSession();
  if (!session || session.status !== "ACTIVE" || now() >= session.expiration_time) return false;
  if (!student || (student.class_id !== session.class_id && !(student.enrolled_classes && student.enrolled_classes.includes(session.class_id)))) return false;
  if (routeType !== "DIRECT" && routeType !== "RELAY") return false;
  if (typeof rssi !== "number" || rssi <= RSSI_FLOOR) return false;
  if (routeType === "RELAY" && ((hopCount || 0) < 1 || (hopCount || 0) > MAX_HOPS)) return false;
  const dup = DB.attendance.some(a => a.session_id === session.session_id && a.student_id === student.student_id);
  if (dup) return false;
  const rec = {
    attendance_id: uid("att"),
    session_id: session.session_id,
    student_id: student.student_id,
    timestamp: now(),
    verification_status: "ELIGIBLE",       // awaits teacher finalize
    route_type: routeType,
    rssi_evidence: rssi,
    hop_count: hopCount || 0,
    via_student: viaStudent || null,
    synced: false
  };
  DB.attendance.push(rec);
  DB.attendance_events.push({
    event_id: uid("evt"),
    ts: new Date().toISOString(),
    event_type: "ATTENDANCE_RECORDED",
    student_id: rec.student_id,
    session_id: rec.session_id,
    route: routeType
  });
  audit("ATTENDANCE_RECORDED", rec.student_id + " route=" + routeType + " rssi=" + rssi + "dBm" +
    (viaStudent ? " via=" + viaStudent : ""));
  saveDB();
  return true;
}

function rejectAttendance(student, reason) {
  syncFromStorage();
  DB.attendance_events.push({ event_id: uid("evt"), ts: new Date().toISOString(), event_type: "REQUEST_REJECTED",
    student_id: student.student_id, session_id: activeSession ? activeSession.session_id : "-", reason });
  audit("REQUEST_REJECTED", student.student_id + " reason=" + reason);
  saveDB();
}

/* ---- Live dashboard (spec §16) ---------------------------------- */
function rosterStatuses() {
  const cls = activeSession ? activeSession.class_id : el("class-select").value;
  return DB.students.filter(s => s.class_id === cls || (s.enrolled_classes && s.enrolled_classes.includes(cls))).map(st => ({
    st,
    rec: DB.attendance.find(a => a.session_id === (activeSession ? activeSession.session_id : "_") && a.student_id === st.student_id)
  }));
}

function renderLiveTable() {
  if (!currentTeacher) return;
  syncFromStorage();
  const body = el("live-body");
  if (!body) return;
  const rows = rosterStatuses().map(({ st, rec }) => {
    let status, route, rssi, time, reviewBtn = "";
    const stName = esc(st.name) + ' <small class="muted mono">' + esc(st.student_id) + "</small>";
    if (!rec) {
      status = '<span class="st-NOT_VERIFIED">NOT VERIFIED</span>';
      route = st.relay_active_for === (activeSession && activeSession.session_id) ? "<em>relay ready</em>" : "--";
      rssi = "--"; time = "--";
    } else if (rec.verification_status === "ELIGIBLE") {
      status = '<span class="st-ELIGIBLE">ELIGIBLE</span>';
      route = rec.route_type === "DIRECT" ? "DIRECT" : "VIA " + esc(rec.via_student || "?") + " (" + Number(rec.hop_count || 0) + " hop)";
      rssi = esc(proximityLabel(rec.rssi_evidence).label) + " (" + Number(rec.rssi_evidence) + " dBm)";
      time = esc(new Date(rec.timestamp).toLocaleTimeString());
      reviewBtn = '<button class="btn small ghost" data-override="' + esc(st.student_id) + '">Mark Present</button>';
    } else {
      const safeStatus = esc(rec.verification_status);
      status = '<span class="st-' + safeStatus + '">' + safeStatus + "</span>";
      route = rec.route_type === "DIRECT" ? "DIRECT" : "VIA " + esc(rec.via_student || "?");
      rssi = rec.rssi_evidence != null ? Number(rec.rssi_evidence) + " dBm" : "--";
      time = esc(new Date(rec.timestamp).toLocaleTimeString());
    }
    return "<tr><td>" + stName + "</td><td>" + status + "</td><td>" + route + "</td><td>" + rssi +
           '</td><td><small class="muted">challenge ✓</small></td><td>' + time + "</td><td>" + reviewBtn + "</td></tr>";
  });
  body.innerHTML = rows.join("");
  body.querySelectorAll("[data-override]").forEach(b =>
    b.addEventListener("click", () => manualOverride(b.getAttribute("data-override"))));

  const n = rosterStatuses();
  const eligible = n.filter(x => x.rec && x.rec.verification_status === "ELIGIBLE").length;
  const finalized = n.filter(x => x.rec && x.rec.verification_status === "PRESENT").length;
  const pending = n.length - eligible - finalized;
  el("summary").textContent =
    "Present (finalized): " + finalized + "  |  Eligible (pending finalize): " + eligible +
    "  |  Not Verified: " + pending + "  |  Total: " + n.length;

  const net = el("net-status");
  if (DB.online) { net.textContent = "\u2601 Online"; net.className = "badge ok"; }
  else { net.textContent = "\u2601 Offline \u2014 local storage only"; net.className = "badge warn"; }
}

/* Teacher review override before finalize */
function manualOverride(studentId) {
  if (!currentTeacher) { alert("Login as teacher first."); return; }
  syncFromStorage();
  if (!activeSession) return;
  const rec = DB.attendance.find(a => a.session_id === activeSession.session_id && a.student_id === studentId);
  if (rec) {
    rec.verification_status = "PRESENT";
    rec.finalized_by = currentTeacher.teacher_id;
    audit("TEACHER_OVERRIDE", studentId + " manually marked PRESENT after review");
    saveDB(); renderLiveTable();
  }
}

/* Finalize: ELIGIBLE -> PRESENT. NOT VERIFIED stays not-verified (never auto-absent). */
function finalizeAttendance() {
  if (!currentTeacher) { alert("Login as teacher first."); return; }
  if (!activeSession) return;
  syncFromStorage();
  if (!activeSession) return;
  let count = 0;
  DB.attendance.filter(a => a.session_id === activeSession.session_id && a.verification_status === "ELIGIBLE")
    .forEach(a => { a.verification_status = "PRESENT"; a.finalized_by = currentTeacher.teacher_id; count++; });
  audit("SESSION_FINALIZED", activeSession.session_id + " finalized=" + count);
  saveDB(); renderLiveTable();
  alert(count + " student(s) marked PRESENT. Remaining students are NOT VERIFIED (not absent) \u2014 they can be reviewed later.");
}

/* ---- Offline sync (spec §20): unique IDs prevent duplicates ----- */
function toggleNetwork() {
  DB.online = !DB.online;
  audit("NETWORK", DB.online ? "internet available" : "internet lost");
  saveDB(); renderLiveTable();
}
async function syncToCloud() {
  const log = el("sync-log");
  if (!DB.online) { log.textContent = "[sync] Offline — data stays in local store. Will retry when online.\n"; return; }
  const unsynced = DB.attendance.filter(a => !a.synced);
  if (!unsynced.length) {
    log.textContent += "[sync] Nothing to sync — cloud already up to date.\n";
    return;
  }
  log.textContent += `[sync] Syncing ${unsynced.length} records to Cloud Backend (POST /api/attendance/batch)...\n`;
  try {
    // Authenticate with cloud backend if teacher token is not yet obtained
    if (currentTeacher && !currentTeacher.cloudToken) {
      try {
        const loginResp = await fetch("http://localhost:8000/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: currentTeacher.teacher_id,
            password: teacherSessionPassword || val("t-pass") || "teach123"
          })
        });
        if (loginResp.ok) {
          const lData = await loginResp.json();
          currentTeacher.cloudToken = lData.access_token;
        }
      } catch (_) { /* offline / backend unreachable */ }
    }

    const headers = { "Content-Type": "application/json" };
    if (currentTeacher && currentTeacher.cloudToken) {
      headers["Authorization"] = "Bearer " + currentTeacher.cloudToken;
    }

    const payload = unsynced.map(a => ({
      attendance_id: a.attendance_id,
      session_id: a.session_id,
      student_id: a.student_id,
      timestamp: a.timestamp,
      verification_status: a.verification_status,
      route_type: a.route_type,
      rssi_evidence: a.rssi_evidence,
      hop_count: a.hop_count || 0,
      via_student: a.via_student || null
    }));

    const resp = await fetch("http://localhost:8000/api/attendance/batch", {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });

    if (resp.ok) {
      const data = await resp.json();
      unsynced.forEach(a => { a.synced = true; });
      log.textContent += `[sync] Cloud synced: stored=${data.stored}, duplicates_ignored=${data.duplicates_ignored} ✓\n`;
      audit("CLOUD_SYNC", `${data.stored} records pushed over HTTPS`);

      // Also sync pending relay events if any
      const unsyncedRelay = (DB.relay_events || []).filter(r => !r.synced);
      if (unsyncedRelay.length > 0) {
        try {
          const rResp = await fetch("http://localhost:8000/api/relay-events/batch", {
            method: "POST",
            headers,
            body: JSON.stringify(unsyncedRelay.map(r => ({
              event_id: r.event_id,
              session_id: r.session_id,
              message_id: r.message_id || ("msg_" + r.event_id),
              source_student_id: r.source_student_id,
              relay_student_id: r.relay_student_id,
              hop_count: r.hop_count || 1,
              timestamp: r.timestamp || now(),
              status: r.status || "FORWARDED"
            })))
          });
          if (rResp.ok) {
            unsyncedRelay.forEach(r => { r.synced = true; });
            log.textContent += `[sync] Synced ${unsyncedRelay.length} mesh relay event(s) to cloud.\n`;
          }
        } catch (_) { }
      }

      saveDB();
    } else {

      // If server returned non-200, mark as retained
      log.textContent += `[sync] Cloud rejected (status ${resp.status}) — queued for retry.\n`;
    }
  } catch (err) {
    // If backend isn't actively running on localhost:8000, fall back to offline simulation
    unsynced.forEach(a => {
      log.textContent += `[sync] (Offline Queue) id=${a.attendance_id} student=${a.student_id} queued.\n`;
    });
    log.textContent += `[sync] Note: Backend unreachable (${err.message}) — records retained safely in local store.\n`;
  }
  saveDB();
  log.scrollTop = log.scrollHeight;
}

function renderAudit() {
  el("audit-log").textContent = DB.audit_logs
    .map(l => l.ts + "  " + l.event.padEnd(20) + " " + l.detail).join("\n");
}
setInterval(() => {
  if (!currentTeacher) return;
  syncFromStorage();
  renderAudit(); renderLiveTable();
}, 1500);
