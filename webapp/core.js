/* ============================================================
   BLE Smart Classroom Attendance System — Web Simulation
   Core: local-first DB (localStorage ~ SQLite), crypto, seed.
   Teacher laptop = trusted root + final attendance authority.
   BLE detection alone NEVER equals presence.
   ============================================================ */

const MAX_HOPS = 2;
const SESSION_TTL_MS = 10 * 60 * 1000;   // session auto-expires
const CHALLENGE_TTL_MS = 30 * 1000;      // single-use, expires quickly
const RSSI_FLOOR = -90;                  // below this = no usable BLE communication

/* Shared UUID config — Windows & Android apps must match (spec §3) */
const UUIDS = {
  service:   "a5e8c0de-0001-4b7d-9c11-000000000001",
  session:   "a5e8c0de-0002-4b7d-9c11-000000000002",
  request:   "a5e8c0de-0003-4b7d-9c11-000000000003",
  challenge: "a5e8c0de-0004-4b7d-9c11-000000000004",
  response:  "a5e8c0de-0005-4b7d-9c11-000000000005",
  result:    "a5e8c0de-0006-4b7d-9c11-000000000006",
  relay:     "a5e8c0de-0007-4b7d-9c11-000000000007"
};

/* ---------------- helpers ---------------- */
function el(id) { return document.getElementById(id); }
function val(id) { const n = el(id); return n ? n.value.trim() : ""; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
async function sha256hex(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}
function uid(prefix) { return prefix + "_" + Math.random().toString(36).slice(2, 10); }
function randHex(n) {
  const a = new Uint8Array(n / 2);
  crypto.getRandomValues(a);
  return [...a].map(b => b.toString(16).padStart(2, "0")).join("").toUpperCase();
}
function now() { return Date.now(); }
/* Spotlight "More ..." toggle on the landing page */
function toggleSpotlight() {
  const extra = el("spot-extra");
  const link = el("spot-toggle");
  if (!extra || !link) return;
  const hidden = extra.classList.toggle("hidden");
  link.textContent = hidden ? "More ..." : "Less";
}
/* Click-to-copy for credential chips (event delegation, works for dynamic content) */
document.addEventListener("click", e => {
  const c = e.target && e.target.closest ? e.target.closest("code[data-copy]") : null;
  if (!c) return;
  const t = c.getAttribute("data-copy");
  const flash = msg => {
    const o = c.textContent;
    c.textContent = msg;
    setTimeout(() => { c.textContent = o; }, 900);
  };
  if (navigator.clipboard && navigator.clipboard.writeText)
    navigator.clipboard.writeText(t).then(() => flash("copied"), () => flash(t));
});
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
/* Escape for embedding inside single-quoted JS strings in inline handlers */
/* Hardened cryptographic password hashing using PBKDF2-HMAC-SHA256 (NIST SP 800-63B compliant) */
async function pbkdf2Hex(password, salt, iterations = 10000) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw", enc.encode(password), { name: "PBKDF2" }, false, ["deriveBits"]
  );
  const derived = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: enc.encode("ble_salt_v2_" + salt),
      iterations: iterations,
      hash: "SHA-256"
    },
    keyMaterial,
    256
  );
  return "pbkdf2$" + iterations + "$" + [...new Uint8Array(derived)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function hashPassword(id, pw) {
  return await pbkdf2Hex(pw, id, 10000);
}

async function verifyPassword(id, pw, storedHash) {
  if (!storedHash) return false;
  if (storedHash.startsWith("pbkdf2$")) {
    const parts = storedHash.split("$");
    const iters = parseInt(parts[1], 10) || 10000;
    const computed = await pbkdf2Hex(pw, id, iters);
    return computed === storedHash;
  }
  // Backward compatibility with initial seeds (single-iteration SHA-256)
  const legacyUpper = await sha256hex("salt_" + id.toUpperCase() + pw);
  if (legacyUpper === storedHash) return true;
  const legacyRaw = await sha256hex("salt_" + id + pw);
  return legacyRaw === storedHash;
}

function teacherClasses(teacherId) {
  return DB.classes.filter(c =>
    c.teacher_id === teacherId ||
    DB.schedules.some(sc => sc.class_id === c.class_id && sc.teacher_id === teacherId));
}

/* ---------------- local-first database ---------------- */
let DB = null;
const DB_KEY = "ble_attendance_db_v2";

function saveDB() {
  try { localStorage.setItem(DB_KEY, JSON.stringify(DB)); }
  catch (e) { console.error("saveDB failed:", e); }
}
/* Re-read the shared DB so multi-tab play stays consistent */
function reloadDB() {
  try {
    const raw = localStorage.getItem(DB_KEY);
    if (raw) DB = JSON.parse(raw);
  } catch (e) {
    console.error("reloadDB: corrupted DB, keeping in-memory copy", e);
  }
}
function loadDB() {
  try {
    const raw = localStorage.getItem(DB_KEY);
    if (raw) {
      DB = JSON.parse(raw);
      DB.admins = DB.admins || [];
      DB.schedules = DB.schedules || [];
      DB.attendance = DB.attendance || [];
      DB.attendance_events = DB.attendance_events || [];
      DB.relay_events = DB.relay_events || [];
      DB.audit_logs = DB.audit_logs || [];
      DB.seen_request_ids = DB.seen_request_ids || [];
      DB.seen_message_ids = DB.seen_message_ids || [];
      DB.student_secrets = DB.student_secrets || {};
      (DB.classes || []).forEach(c => {
        if (!c.class_code) c.class_code = c.class_id;
      });
      (DB.students || []).forEach(s => {
        if (!Array.isArray(s.enrolled_classes) || s.enrolled_classes.length === 0) {
          s.enrolled_classes = s.class_id ? [s.class_id] : ["CSE-A"];
        }
      });
      return;
    }
  } catch (e) {
    console.error("loadDB: corrupted, re-seeding", e);
  }
  DB = {
    admins: [], teachers: [], students: [], classes: [], schedules: [],
    sessions: [], attendance: [], attendance_events: [], relay_events: [], audit_logs: [],
    seen_request_ids: [], seen_message_ids: [], student_secrets: {},
    online: false
  };
}
function audit(event, detail) {
  DB.audit_logs.unshift({ ts: new Date().toLocaleTimeString(), event, detail });
  if (DB.audit_logs.length > 200) DB.audit_logs.length = 200;
  saveDB();
}

function findClassByCode(code) {
  if (!code) return null;
  const clean = code.trim().toUpperCase();
  return (DB.classes || []).find(c =>
    (c.class_code && c.class_code.trim().toUpperCase() === clean) ||
    (c.class_id && c.class_id.trim().toUpperCase() === clean)
  ) || null;
}

/* ---------------- seed data ---------------- */
async function seed() {
  DB.admins.push({
    admin_id: "A001", name: "Administrator", email: "admin@college.edu",
    password_hash: await hashPassword("A001", "admin123")
  });
  DB.teachers.push({
    teacher_id: "T001", name: "Dr. Sharma", email: "sharma@college.edu",
    password_hash: await hashPassword("T001", "teach123")
  });
  DB.classes.push({ class_id: "CSE-A", class_name: "CSE-A", subject: "Data Structures", teacher_id: "T001", class_code: "CSE-A" });

  const first = ["Aarav", "Diya", "Rohan", "Ishaan", "Meera", "Kabir"];
  const last  = ["Kumar", "Patel", "Verma", "Singh", "Iyer", "Shah"];
  DB.student_secrets = DB.student_secrets || {};
  for (let i = 0; i < first.length; i++) {
    const sid = "S00" + (i + 1);
    const secret = randHex(16);
    DB.student_secrets[sid] = secret;
    DB.students.push({
      student_id: sid,
      name: first[i] + " " + last[i],
      email: sid.toLowerCase() + "@student.college.edu",
      password_hash: await hashPassword(sid, "stud123"),
      registered_device_id: "DEV-" + sid,
      class_id: "CSE-A",
      enrolled_classes: ["CSE-A"],
      position: "near",
      relay_active_for: null
    });
  }
}

/* ---------------- BLE simulation ---------------- */
/* RSSI is PROXIMITY EVIDENCE only — never exact distance (spec §9).
   Simulated position (near / back / outside) drives the base RSSI so
   boundary/outside + relay scenarios can be tested. Real Web Bluetooth
   RSSI overrides this when available (online mode). */
function simulateRSSI(position) {
  const noise = (crypto.getRandomValues(new Uint8Array(1))[0] % 13) - 6;
  let base = -56; // near
  if (position === "back") base = -72;
  else if (position === "outside") base = -95;
  return base + noise;
}
function proximityLabel(rssi) {
  if (rssi > -60) return { label: "STRONG", cls: "ok" };
  if (rssi > -80) return { label: "MODERATE", cls: "warn" };
  return { label: "WEAK/NO SIGNAL", cls: "err" };
}

/* Active session lookup — shared across tabs via the DB */
let activeSession = null;
function getActiveSession() {
  reloadDB();
  return DB.sessions.find(s => s.status === "ACTIVE" && now() < s.expiration_time) || null;
}

/* ---------------- boot ---------------- */
window.addEventListener("DOMContentLoaded", async () => {
  loadDB();
  if (!DB.students.length) await seed();   // seed only once, never duplicate
  if (!DB.admins.length)                   // migrate pre-admin databases
    DB.admins.push({
      admin_id: "A001", name: "Administrator", email: "admin@college.edu",
      password_hash: await hashPassword("A001", "admin123")
    });
  saveDB();

  document.querySelectorAll(".card[data-role]").forEach(card => {
    card.addEventListener("click", () => {
      const role = card.dataset.role;
      if (role === "teacher") showScreen("screen-teacher-login");
      else if (role === "admin") showScreen("screen-admin-login");
      else showScreen("screen-student-login");
    });
  });

  showScreen("screen-role");
});
