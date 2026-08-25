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
function val(id) { return el(id).value.trim(); }
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
function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function hashPassword(id, pw) { return sha256hex("salt_" + id + pw); }
function teacherClasses(teacherId) {
  return DB.classes.filter(c =>
    c.teacher_id === teacherId ||
    DB.schedules.some(sc => sc.class_id === c.class_id && sc.teacher_id === teacherId));
}

/* ---------------- local-first database ---------------- */
let DB = null;
const DB_KEY = "ble_attendance_db_v2";

function saveDB() { localStorage.setItem(DB_KEY, JSON.stringify(DB)); }
/* Re-read the shared DB so multi-tab play stays consistent */
function reloadDB() {
  const raw = localStorage.getItem(DB_KEY);
  if (raw) DB = JSON.parse(raw);
}
function loadDB() {
  const raw = localStorage.getItem(DB_KEY);
  if (raw) {
    DB = JSON.parse(raw);
    DB.admins = DB.admins || [];
    DB.schedules = DB.schedules || [];
    return;
  }
  DB = {
    admins: [], teachers: [], students: [], classes: [], schedules: [],
    sessions: [], attendance: [], attendance_events: [], relay_events: [], audit_logs: [],
    seen_request_ids: [], seen_message_ids: [],
    online: false
  };
}
function audit(event, detail) {
  DB.audit_logs.unshift({ ts: new Date().toLocaleTimeString(), event, detail });
  if (DB.audit_logs.length > 200) DB.audit_logs.length = 200;
  saveDB();
}

/* ---------------- seed data ---------------- */
async function seed() {
  DB.admins.push({
    admin_id: "A001", name: "Administrator", email: "admin@college.edu",
    password_hash: await hashPassword("A001", "admin123")
  });
  DB.teachers.push({
    teacher_id: "T001", name: "Dr. Sharma", email: "sharma@college.edu",
    password_hash: await sha256hex("salt_T001teach123")
  });
  DB.classes.push({ class_id: "CSE-A", class_name: "CSE-A", subject: "Data Structures", teacher_id: "T001" });

  const first = ["Aarav", "Diya", "Rohan", "Ishaan", "Meera", "Kabir"];
  const last  = ["Kumar", "Patel", "Verma", "Singh", "Iyer", "Shah"];
  for (let i = 0; i < first.length; i++) {
    const sid = "S00" + (i + 1);
    DB.students.push({
      student_id: sid,
      name: first[i] + " " + last[i],
      email: sid.toLowerCase() + "@student.college.edu",
      password_hash: await sha256hex("salt_" + sid + "stud123"),
      registered_device_id: "DEV-" + sid,
      device_secret: randHex(16),
      class_id: "CSE-A",
      position: "near",
      relay_active_for: null
    });
  }
}

/* ---------------- BLE simulation ---------------- */
/* RSSI is PROXIMITY EVIDENCE only — never exact distance (spec §9).
   Students no longer self-declare a position; the simulated link assumes
   an in-classroom device. Real Web Bluetooth RSSI overrides this when
   available (online mode). */
function simulateRSSI() {
  const noise = (crypto.getRandomValues(new Uint8Array(1))[0] % 13) - 6;
  return -56 + noise;
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
