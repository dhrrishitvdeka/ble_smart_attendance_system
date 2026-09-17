const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

function harness(fetchImpl = async () => { throw new Error("Offline"); }) {
  const storage = new Map();
  const nodes = new Map();
  const node = () => ({ value: "", textContent: "", innerHTML: "", checked: false,
    classList: { add() {}, remove() {} }, appendChild() {}, addEventListener() {},
    querySelector: () => null, querySelectorAll: () => [] });
  const context = vm.createContext({
    console, crypto: webcrypto, TextEncoder, TextDecoder, Date,
    setTimeout: fn => { fn(); return 1; }, clearTimeout() {},
    setInterval: () => 1, clearInterval() {}, alert() {},
    fetch: (...args) => fetchImpl(...args),
    location: { protocol: "http:", hostname: "localhost" }, navigator: {},
    window: { addEventListener() {} },
    document: { addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
      createElement: node, getElementById(id) {
        if (!nodes.has(id)) nodes.set(id, node());
        return nodes.get(id);
      } },
    localStorage: { getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value) }
  });
  for (const file of ["core.js", "teacher.js", "student.js", "admin.js"])
    vm.runInContext(fs.readFileSync(path.join(__dirname, file), "utf8"), context, { filename: file });
  const run = code => vm.runInContext(code, context);
  run(`DB = {
    admins: [], teachers: [{teacher_id: "T001"}, {teacher_id: "T002"}],
    students: [{ student_id: "S001", name: "Student One", class_id: "C2", enrolled_classes: ["C1", "C2"], registered_device_id: "D1", relay_active_for: null }],
    classes: [{class_id: "C1", teacher_id: "T001"}, {class_id: "C2", teacher_id: "T002"}], schedules: [],
    sessions: [{session_id: "SESSION1", class_id: "C1", teacher_id: "T001", status: "ACTIVE", expiration_time: Date.now() + 600000}],
    attendance: [], attendance_events: [], relay_events: [], audit_logs: [], seen_request_ids: [], student_secrets: { S001: "secret" }, online: true
  };
  saveDB(); currentStudent = DB.students[0]; authCtx = {deviceId: "D1", deviceSecret: "secret"};`);
  return { run, context, nodes, storage, stored: () => JSON.parse(storage.get("ble_attendance_db_v2")) };
}

test("relay opt-in persists across reload and does not detach the student", () => {
  const h = harness();
  h.run("toggleRelay(true); reloadDB()");
  assert.equal(h.stored().students[0].relay_active_for, "SESSION1");
  assert.equal(h.run("currentStudent === DB.students[0]"), true);
  h.run("toggleRelay(false); reloadDB()");
  assert.equal(h.stored().students[0].relay_active_for, null);
});

test("scan discovers an enrolled session started by another tab", () => {
  const h = harness();
  const saved = h.stored();
  h.run("DB.sessions = []");
  saved.sessions.unshift({ session_id: "OTHER", class_id: "C3", teacher_id: "T002", status: "ACTIVE", expiration_time: Date.now() + 600000 });
  h.storage.set("ble_attendance_db_v2", JSON.stringify(saved));
  h.run("renderScanResult()");
  assert.match(h.nodes.get("scan-result").innerHTML, /SESSION1/);
  assert.doesNotMatch(h.nodes.get("scan-result").innerHTML, /OTHER/);
});

test("relay selection includes classmates enrolled in multiple classes", () => {
  const h = harness();
  h.run(`DB.students.push({student_id: "S002", name: "Relay Student", class_id: "C1", enrolled_classes: ["C1"], relay_active_for: "SESSION1", position: "near"});
    saveDB();
    globalThis.selectedRelay = null;
    beginVerification = (route, info) => { selectedRelay = {route, info}; };
    attemptRelay();`);
  assert.equal(h.run("selectedRelay.route"), "RELAY");
  assert.equal(h.run("selectedRelay.info.viaStudent"), "Relay Student (S002)");
});

test("starting another teacher session preserves existing session relay opt-in", () => {
  const h = harness();
  h.run(`toggleRelay(true); currentTeacher = DB.teachers[1]; el("class-select").value = "C2"; startSession();`);
  assert.equal(h.stored().students[0].relay_active_for, "SESSION1");
  assert.equal(h.stored().sessions.length, 2);
});

test("legacy admin creates classes through authenticated same-origin requests", async () => {
  const calls = [];
  const h = harness(async (url, init) => {
    calls.push({url, init});
    return {ok: true, json: async () => url === "/api/auth/login"
      ? {access_token: "demo-token", role: "admin", user_id: "A001"} : {class_id: "C3"}};
  });
  await h.run(`currentAdmin = {admin_id: "A001"}; adminSessionPassword = "admin123";
    el("ac-id").value = "C3"; el("ac-subject").value = "Functional test";
    el("ac-teacher").value = "T001"; addClass();`);
  assert.deepEqual(calls.map(call => call.url), ["/api/auth/login", "/api/classes"]);
  assert.equal(calls[1].init.headers.Authorization, "Bearer demo-token");
  assert.match(h.nodes.get("ac-msg").textContent, /locally and in the backend/);
  assert.equal(h.stored().classes.find(c => c.class_id === "C3").teacher_id, "T001");
  h.run("adminLogout()");
  assert.equal(h.run("adminSessionPassword"), null);
  assert.equal(h.run("cloudAuth.size"), 0);
});
