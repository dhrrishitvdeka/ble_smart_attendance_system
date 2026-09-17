/* ============================================================
   ADMIN CONSOLE — manages teachers, classes, schedules and
   student enrollment. Only the admin can:
     - add teachers
     - create classes and schedule them to a teacher
     - add students into ONE specific class (never all classes)
   ============================================================ */

let currentAdmin = null;
let adminSessionPassword = null;

async function adminLogin() {
  const a = DB.admins.find(x => x.admin_id === val("a-id").toUpperCase());
  const msg = el("a-login-msg");
  if (!a || !(await verifyPassword(a.admin_id, val("a-pass"), a.password_hash))) {
    msg.textContent = "Invalid credentials."; msg.className = "msg err"; return;
  }
  currentAdmin = a;
  adminSessionPassword = val("a-pass");
  cloudAuth.delete("admin:" + a.admin_id);
  msg.textContent = "";
  msg.className = "msg";
  el("admin-name").textContent = a.name;
  audit("ADMIN_LOGIN", a.admin_id);
  renderAdmin();
  showScreen("screen-admin");
}

function adminLogout() {
  if (currentAdmin) cloudAuth.delete("admin:" + currentAdmin.admin_id);
  adminSessionPassword = null;
  currentAdmin = null;
  showScreen("screen-role");
}

function adminMsg(id, text, ok) {
  const m = el(id);
  m.textContent = text;
  m.className = "msg " + (ok ? "ok" : "err");
}

/* ---------------- Add teacher ---------------- */
async function addTeacher() {
  if (!currentAdmin) return adminMsg("at-msg", "Login as admin first.", false);
  const id = val("at-id").toUpperCase(), name = val("at-name").trim(),
        email = val("at-email").trim(), pass = val("at-pass");
  if (!id || !name || !pass) return adminMsg("at-msg", "ID, name and password are required.", false);
  if (DB.teachers.some(t => t.teacher_id === id)) return adminMsg("at-msg", "Teacher ID already exists.", false);
  DB.teachers.push({
    teacher_id: id, name, email,
    password_hash: await hashPassword(id, pass)
  });
  audit("ADMIN_ADD_TEACHER", id + " " + name);
  saveDB();
  ["at-id", "at-name", "at-email", "at-pass"].forEach(i => el(i).value = "");
  adminMsg("at-msg", "Teacher " + id + " added.", true);
  renderAdmin();
}

/* ---------------- Add class ---------------- */
async function addClass() {
  if (!currentAdmin) return adminMsg("ac-msg", "Login as admin first.", false);
  const cid = val("ac-id").trim().toUpperCase(),
        code = (val("ac-code").trim().toUpperCase()) || cid,
        subject = val("ac-subject").trim(),
        tid = el("ac-teacher").value;
  if (!cid || !subject) return adminMsg("ac-msg", "Class ID and subject are required.", false);
  if (cid.length > 32) return adminMsg("ac-msg", "Class ID cannot exceed 32 characters.", false);
  if (code.length > 32) return adminMsg("ac-msg", "Class code cannot exceed 32 characters.", false);
  if (!tid) return adminMsg("ac-msg", "Create a teacher first.", false);
  if (DB.classes.some(c => c.class_id === cid)) return adminMsg("ac-msg", "Class ID already exists.", false);
  if (DB.classes.some(c => (c.class_code || c.class_id).toUpperCase() === code))
    return adminMsg("ac-msg", "Class code '" + code + "' is already in use.", false);
  DB.classes.push({ class_id: cid, class_name: cid, subject, teacher_id: tid, class_code: code });
  audit("ADMIN_ADD_CLASS", cid + " (code=" + code + ") subject=" + subject + " teacher=" + tid);
  saveDB();
  el("ac-id").value = ""; el("ac-subject").value = "";
  if (el("ac-code")) el("ac-code").value = "";
  adminMsg("ac-msg", "Class " + cid + " (Code: " + code + ") assigned to " + tid + ".", true);
  renderAdmin();

  try {
    const adminId = currentAdmin.admin_id;
    const headers = await cloudHeaders(adminId, adminSessionPassword, "admin");
    const response = await fetch(apiUrl("/api/classes"), {
      method: "POST",
      headers,
      body: JSON.stringify({
        class_id: cid,
        class_name: cid,
        subject: subject,
        teacher_id: tid,
        class_code: code
      })
    });
    if (!response.ok) {
      if (response.status === 401) cloudAuth.delete("admin:" + adminId);
      throw new Error("Backend rejected class creation (HTTP " + response.status + ").");
    }
    adminMsg("ac-msg", "Class " + cid + " created locally and in the backend.", true);
  } catch (error) {
    adminMsg("ac-msg", "Local simulation class only. Backend class creation failed: " + error.message, false);
  }
}

/* ---------------- Schedule class to teacher ---------------- */
function addSchedule() {
  if (!currentAdmin) return adminMsg("as-msg", "Login as admin first.", false);
  const cid = el("as-class").value, tid = el("as-teacher").value,
        day = val("as-day"), start = val("as-start"), end = val("as-end");
  if (!cid || !tid) return adminMsg("as-msg", "Select a class and a teacher.", false);
  function toMin(t) { const m = /^(\d{1,2}):(\d{2})$/.exec(t || ""); return m ? (+m[1]) * 60 + (+m[2]) : null; }
  const sm = start ? toMin(start) : null, em = end ? toMin(end) : null;
  if (start && !toMin(start) && start !== "") { /* allow free text but validate when both look like times */ }
  if (sm != null && em != null && sm >= em) return adminMsg("as-msg", "Start time must be before end time.", false);
  const schedule_id = uid("sch");
  DB.schedules.push({ schedule_id, class_id: cid, teacher_id: tid, day, start_time: start, end_time: end });
  audit("ADMIN_SCHEDULE", cid + " -> " + tid + " " + day + " " + start + "-" + end);
  saveDB();
  adminMsg("as-msg", "Class " + cid + " scheduled to " + tid + ".", true);
  renderAdmin();
}
function removeSchedule(sid) {
  if (!currentAdmin) return;
  DB.schedules = DB.schedules.filter(s => s.schedule_id !== sid);
  audit("ADMIN_UNSCHEDULE", sid);
  saveDB(); renderAdmin();
}

/* ---------------- Add student to ONE specific class ---------------- */
async function addStudent() {
  if (!currentAdmin) return adminMsg("asn-msg", "Login as admin first.", false);
  const sid = val("asn-id").toUpperCase(), name = val("asn-name").trim(),
        email = val("asn-email").trim(), pass = val("asn-pass"),
        cid = el("asn-class").value;
  if (!sid || !name || !pass) return adminMsg("asn-msg", "ID, name and password are required.", false);
  if (!cid) return adminMsg("asn-msg", "Create a class first — every student must be enrolled in exactly one class.", false);
  if (DB.students.some(s => s.student_id === sid)) return adminMsg("asn-msg", "Student ID already exists.", false);

  // The student is enrolled ONLY in the selected class.
  const secret = randHex(16);
  DB.student_secrets = DB.student_secrets || {};
  DB.student_secrets[sid] = secret;
  DB.students.push({
    student_id: sid, name, email,
    password_hash: await hashPassword(sid, pass),
    registered_device_id: "DEV-" + sid,
    class_id: cid,                       // single explicit enrollment
    relay_active_for: null
  });
  audit("ADMIN_ADD_STUDENT", sid + " enrolled in " + cid + " ONLY");
  saveDB();
  ["asn-id", "asn-name", "asn-email", "asn-pass"].forEach(i => el(i).value = "");
  adminMsg("asn-msg", "Student " + sid + " enrolled in " + cid + " only.", true);
  renderAdmin();
}

/* ---------------- Rendering ---------------- */
function renderAdmin() {
  const tOpts = '<option value="">— select teacher —</option>' +
    DB.teachers.map(t => '<option value="' + esc(t.teacher_id) + '">' + esc(t.teacher_id) + " · " + esc(t.name) + "</option>").join("");
  const cOpts = '<option value="">— select class —</option>' +
    DB.classes.map(c => '<option value="' + esc(c.class_id) + '">' + esc(c.class_id) + " (Code: " + esc(c.class_code || c.class_id) + ") · " + esc(c.subject) + "</option>").join("");

  el("ac-teacher").innerHTML = tOpts;
  el("as-class").innerHTML = cOpts;
  el("as-teacher").innerHTML = tOpts;
  el("asn-class").innerHTML = cOpts;

  el("adm-teachers").innerHTML = DB.teachers.map(t =>
    "<tr><td>" + esc(t.teacher_id) + "</td><td>" + esc(t.name) + "</td><td>" + esc(t.email || "-") + "</td></tr>"
  ).join("") || '<tr><td colspan="3" class="muted">No teachers yet.</td></tr>';

  el("adm-classes").innerHTML = DB.classes.map(c => {
    const t = DB.teachers.find(x => x.teacher_id === c.teacher_id);
    const scheds = DB.schedules.filter(s => s.class_id === c.class_id).length;
    const code = c.class_code || c.class_id;
    return "<tr><td><strong>" + esc(c.class_id) + "</strong><br><small class=\"mono muted\">Code: " + esc(code) + "</small></td><td>" + esc(c.subject) + "</td><td>" +
      esc(t ? t.teacher_id : "-") + "</td><td>" + scheds + "</td><td>" +
      DB.students.filter(s => s.class_id === c.class_id).length + "</td></tr>";
  }).join("") || '<tr><td colspan="5" class="muted">No classes yet.</td></tr>';

  el("adm-schedules").innerHTML = DB.schedules.map(s =>
    "<tr><td>" + esc(s.class_id) + "</td><td>" + esc(s.teacher_id) + "</td><td>" +
    esc(s.day || "-") + "</td><td>" + esc((s.start_time || "?") + " – " + (s.end_time || "?")) + "</td><td>" +
    '<button class="btn small danger" onclick="removeSchedule(\'' + esc(s.schedule_id) + '\')">Remove</button></td></tr>'
  ).join("") || '<tr><td colspan="5" class="muted">No schedules yet.</td></tr>';

  el("adm-students").innerHTML = DB.students.map(s =>
    "<tr><td>" + esc(s.student_id) + "</td><td>" + esc(s.name) + "</td><td>" +
    esc(s.class_id) + "</td><td>" + esc(s.registered_device_id) + "</td></tr>"
  ).join("") || '<tr><td colspan="4" class="muted">No students yet.</td></tr>';
}
