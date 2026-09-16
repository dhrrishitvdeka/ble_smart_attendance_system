"use strict";

const byId = id => document.getElementById(id);
let token = null;
let identity = null;
let sessions = [];
let busy = false;

async function request(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request rejected: " + response.status);
  return data;
}

function options(select, rows, value, text) {
  const previous = select.value;
  select.replaceChildren(...rows.map(row => {
    const option = document.createElement("option");
    option.value = value(row);
    option.textContent = text(row);
    return option;
  }));
  if (rows.some(row => value(row) === previous)) select.value = previous;
}

function selectedPath() {
  const id = byId("session-select").value;
  if (!id) throw new Error("Start or select a session first.");
  return "/api/demo/sessions/" + encodeURIComponent(id);
}

async function refreshAttendance() {
  byId("attendance").replaceChildren();
  if (!byId("session-select").value) {
    byId("session-status").textContent = "No sessions. Ask the teacher to start one.";
    return;
  }
  const session = sessions.find(s => s.session_id === byId("session-select").value);
  byId("session-status").textContent = session.status + " — " + session.subject + " — SIMULATION";
  const rows = await request(selectedPath() + "/attendance");
  byId("attendance").replaceChildren(...rows.map(row => {
    const tr = document.createElement("tr");
    for (const value of [row.student_id, row.name, row.status, row.route || "—", row.rssi ?? "—"]) {
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.append(td);
    }
    return tr;
  }));
  if (identity.role === "student") {
    const relays = session.status === "ACTIVE" ? await request(selectedPath() + "/relays") : [];
    options(byId("relay"), ["", ...relays], s => s, s => s || "Direct");
  }
}

async function refresh() {
  const classes = await request("/api/demo/classes");
  options(byId("class-select"), classes, c => c.class_id, c => c.class_name + " / " + c.subject);
  sessions = await request("/api/demo/sessions");
  options(byId("session-select"), sessions, s => s.session_id, s => s.class_id + " — " + s.status + " — " + s.session_id.slice(-8));
  await refreshAttendance();
}

async function run(action) {
  if (busy) return;
  busy = true;
  byId("message").textContent = "Working…";
  try {
    const message = await action();
    byId("message").textContent = message || "Updated.";
  } catch (error) {
    byId("message").textContent = error.message;
  } finally {
    busy = false;
  }
}

byId("login-form").addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const data = await request("/api/auth/login", { username: byId("username").value, password: byId("password").value });
    token = data.access_token;
    identity = await request("/api/demo/profile");
    byId("password").value = "";
    byId("identity").textContent = identity.user_id + " / " + identity.role;
    byId("login-panel").hidden = true;
    byId("workspace").hidden = false;
    byId("teacher-panel").hidden = identity.role === "student";
    byId("admin-panel").hidden = identity.role !== "admin";
    byId("student-panel").hidden = identity.role !== "student";
    await refresh();
    return "Signed in. Tokens are kept only in this tab's memory.";
  });
});

byId("logout").addEventListener("click", () => {
  if (busy) return;
  token = null;
  identity = null;
  sessions = [];
  byId("attendance").replaceChildren();
  byId("workspace").hidden = true;
  byId("login-panel").hidden = false;
  byId("message").textContent = "Signed out. Relay opt-in remains session-bound; disable it before leaving if desired.";
});
byId("refresh").addEventListener("click", () => run(refresh));
byId("session-select").addEventListener("change", () => run(refreshAttendance));
byId("start").addEventListener("click", () => run(async () => {
  const session = await request("/api/demo/sessions", { class_id: byId("class-select").value });
  await refresh();
  byId("session-select").value = session.session_id;
  await refreshAttendance();
  return "Session started. Students can refresh their tabs.";
}));
byId("finalize").addEventListener("click", () => run(async () => {
  const result = await request(selectedPath() + "/finalize", {});
  await refresh();
  return "Finalized " + result.updated + " eligible records. Remaining students are NOT_VERIFIED, not absent.";
}));
byId("verify").addEventListener("click", () => run(async () => {
  const path = selectedPath();
  const proof = await request(path + "/challenge", { position: byId("position").value, relay_student_id: byId("relay").value || null });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(proof.nonce));
  const response = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  const result = await request(path + "/verify", { challenge_id: proof.challenge_id, response });
  await refreshAttendance();
  return result.status + " — simulation accepted by backend; teacher must finalize.";
}));
for (const [id, enabled] of [["relay-on", true], ["relay-off", false]]) {
  byId(id).addEventListener("click", () => run(async () => {
    await request(selectedPath() + "/relay", { enabled, position: byId("position").value });
    return "Session relay " + (enabled ? "enabled" : "disabled") + " (simulated).";
  }));
}
byId("join-form").addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    await request("/api/v2/classes/join", { class_code: byId("join-code").value });
    await refresh();
    return "Class joined.";
  });
});
byId("class-form").addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    await request("/api/classes", { class_id: byId("class-id").value, class_name: byId("class-name").value,
      subject: byId("subject").value, teacher_id: byId("teacher-id").value, class_code: byId("class-code").value });
    await refresh();
    return "Class created.";
  });
});
