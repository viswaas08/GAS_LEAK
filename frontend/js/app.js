// ---------------------------------------------------------------
// PipelineGuard dashboard — vanilla JS (no build step required).
// Talks to the FastAPI backend over REST + a WebSocket for live push.
// ---------------------------------------------------------------

const state = {
  zones: [],
  incidents: [],
  selectedZoneId: null,
  chart: null,
  chartData: { labels: [], mq2: [], mq135: [], pressure: [] },
  ws: null,
};

const root = document.getElementById("app");

function toast(msg, kind = "") {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ================= AUTH SCREENS =================

function renderAuth(mode = "login") {
  root.innerHTML = `
    <div class="auth-wrap">
      <div class="auth-card">
        <div class="auth-brand">
          <div class="brand-mark">⛽</div>
          <div>
            <div style="font-weight:600;font-size:15px;">PipelineGuard</div>
            <div style="color:var(--text-2);font-size:11px;">Control Room</div>
          </div>
        </div>
        <div id="auth-body"></div>
      </div>
    </div>`;
  if (mode === "login") renderLoginForm();
  else if (mode === "register") renderRegisterForm();
  else if (mode === "otp") renderOtpForm(mode.phone);
}

function renderLoginForm() {
  const body = document.getElementById("auth-body");
  body.innerHTML = `
    <div class="auth-title">Sign in</div>
    <div class="auth-sub">Monitor pipeline zones in real time.</div>
    <div id="auth-msg"></div>
    <form id="login-form">
      <div class="field"><label>Email</label><input type="email" name="email" required autocomplete="email" value="admin@pipelineguard.io"></div>
      <div class="field"><label>Password</label><input type="password" name="password" required autocomplete="current-password" value="Admin@12345"></div>
      <button class="btn-primary" type="submit">Sign in</button>
    </form>
    <div class="auth-switch">No account? <button id="go-register">Create one</button></div>
  `;
  document.getElementById("go-register").onclick = () => renderAuth("register");
  document.getElementById("login-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      const res = await API.login({ email: fd.get("email"), password: fd.get("password") });
      const me = await tempMe(res.access_token);
      API.setSession(res.access_token, me);
      bootDashboard();
    } catch (err) {
      showAuthMsg(err.message, "error");
    } finally { btn.disabled = false; }
  };
}

async function tempMe(token) {
  const r = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
  return r.json();
}

function renderRegisterForm() {
  const body = document.getElementById("auth-body");
  body.innerHTML = `
    <div class="auth-title">Create account</div>
    <div class="auth-sub">New accounts start as Viewer — an admin can promote you.</div>
    <div id="auth-msg"></div>
    <form id="register-form">
      <div class="field"><label>Full name</label><input name="name" required></div>
      <div class="field"><label>Email</label><input type="email" name="email" required></div>
      <div class="field"><label>Phone (with country code)</label><input name="phone" placeholder="+919876543210" required></div>
      <div class="field"><label>Password</label><input type="password" name="password" minlength="8" required></div>
      <button class="btn-primary" type="submit">Create account</button>
    </form>
    <div class="auth-switch">Have an account? <button id="go-login">Sign in</button></div>
  `;
  document.getElementById("go-login").onclick = () => renderAuth("login");
  document.getElementById("register-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      await API.register({
        name: fd.get("name"), email: fd.get("email"),
        phone: fd.get("phone"), password: fd.get("password"),
      });
      toast("Account created — verify your phone, then sign in.", "safe");
      renderOtpGate(fd.get("phone"));
    } catch (err) {
      showAuthMsg(err.message, "error");
    } finally { btn.disabled = false; }
  };
}

function renderOtpGate(phone) {
  const body = document.getElementById("auth-body");
  body.innerHTML = `
    <div class="auth-title">Verify your phone</div>
    <div class="auth-sub">We sent a 6-digit code to ${phone}. Assigned zones only send SMS alerts to verified numbers.</div>
    <div id="auth-msg"></div>
    <form id="otp-form">
      <div class="field"><label>Verification code</label><input name="code" maxlength="6" required></div>
      <button class="btn-primary" type="submit">Verify</button>
    </form>
    <div class="auth-switch"><button id="resend-otp">Resend code</button> · <button id="go-login2">Back to sign in</button></div>
  `;
  document.getElementById("go-login2").onclick = () => renderAuth("login");
  document.getElementById("resend-otp").onclick = async () => {
    try { await API.requestOtp(phone); toast("Code resent."); } catch (e) { showAuthMsg(e.message, "error"); }
  };
  document.getElementById("otp-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await API.verifyOtp(phone, fd.get("code"));
      toast("Phone verified. You can sign in now.", "safe");
      renderAuth("login");
    } catch (err) { showAuthMsg(err.message, "error"); }
  };
  API.requestOtp(phone).catch(() => {});
}

function showAuthMsg(msg, kind) {
  const el = document.getElementById("auth-msg");
  if (!el) return;
  el.innerHTML = `<div class="${kind === "error" ? "auth-error" : "auth-info"}">${escapeHtml(msg)}</div>`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ================= DASHBOARD SHELL =================

function bootDashboard() {
  const user = API.getUser();
  root.innerHTML = `
    <div class="topbar">
      <div class="brand"><div class="brand-mark">⛽</div>PipelineGuard<span class="brand-sub">Control Room</span></div>
      <div id="conn-pill" class="conn-pill"><span class="conn-dot"></span><span>Connecting…</span></div>
      <div class="topbar-spacer"></div>
      <div class="user-chip">
        <span>${escapeHtml(user?.name || "")}</span>
        <span class="role-badge">${escapeHtml(user?.role || "")}</span>
      </div>
      <button class="btn-ghost" id="logout-btn">Log out</button>
    </div>
    <div class="main">
      <div class="summary-row" id="summary-row"></div>
      <div class="zones-col">
        <div class="section-head"><h2>Pipeline zones</h2></div>
        <div class="zone-grid" id="zone-grid"></div>
      </div>
      <div class="side-col">
        <div class="panel">
          <h3>Recent incidents</h3>
          <div id="incident-list"></div>
        </div>
        <div class="panel">
          <h3>Demo simulation</h3>
          <div class="sim-grid" id="sim-grid"></div>
          <div class="sim-note">No physical ESP32 is attached to this prototype. These buttons publish synthetic sensor payloads through the same ingestion path a real device would use, so the full detection → alert → SMS → shutoff pipeline runs end-to-end.</div>
        </div>
      </div>
    </div>
    <div id="toast-stack"></div>
  `;
  document.getElementById("logout-btn").onclick = () => {
    API.clearSession();
    if (state.ws) state.ws.close();
    renderAuth("login");
  };
  loadZonesAndIncidents();
  connectWebSocket();
}

async function loadZonesAndIncidents() {
  try {
    state.zones = await API.listZones();
    state.incidents = await API.listIncidents();
    renderSummary();
    renderZoneGrid();
    renderIncidentList();
    renderSimGrid();
  } catch (err) {
    toast(err.message, "crit");
  }
}

function renderSummary() {
  const counts = { SAFE: 0, WARNING: 0, CRITICAL: 0, OFFLINE: 0 };
  state.zones.forEach(z => counts[z.status]++);
  const worst = counts.CRITICAL ? "CRITICAL" : counts.WARNING ? "WARNING" : counts.OFFLINE === state.zones.length ? "OFFLINE" : "SAFE";
  const colorVar = { SAFE: "var(--safe)", WARNING: "var(--warn)", CRITICAL: "var(--crit)", OFFLINE: "var(--offline)" }[worst];
  const label = { SAFE: "All pipelines safe", WARNING: "Elevated readings detected", CRITICAL: "Critical alert — action required", OFFLINE: "No devices reporting" }[worst];
  document.getElementById("summary-row").innerHTML = `
    <div class="summary-status"><span class="dot" style="background:${colorVar}"></span>${label}</div>
    <div class="summary-counts">
      <span><b>${counts.SAFE}</b> safe</span>
      <span><b>${counts.WARNING}</b> warning</span>
      <span><b>${counts.CRITICAL}</b> critical</span>
      <span><b>${counts.OFFLINE}</b> offline</span>
    </div>
    <div class="spacer"></div>
    <button class="btn-ghost" id="export-csv-btn">Export incidents CSV</button>
  `;
  document.getElementById("export-csv-btn").onclick = () => {
    window.open("/api/incidents/export.csv?token=" + API.getToken(), "_blank");
    // Note: backend reads Authorization header; for a plain link download in a
    // real deployment, issue a short-lived signed export URL instead.
    fetch("/api/incidents/export.csv", { headers: { Authorization: `Bearer ${API.getToken()}` } })
      .then(r => r.blob()).then(b => {
        const url = URL.createObjectURL(b);
        const a = document.createElement("a");
        a.href = url; a.download = "incidents.csv"; a.click();
        URL.revokeObjectURL(url);
      });
  };
}

function renderZoneGrid() {
  const grid = document.getElementById("zone-grid");
  if (!state.zones.length) {
    grid.innerHTML = `<div class="empty-note">No zones configured yet.</div>`;
    return;
  }
  grid.innerHTML = state.zones.map(z => `
    <div class="zone-card" data-status="${z.status}" data-zone-id="${z.id}">
      <div class="zone-card-top">
        <div>
          <div class="zone-name">${escapeHtml(z.name)}</div>
          <div class="zone-loc">${escapeHtml(z.location || "")} · ${escapeHtml(z.device_code || "no device")}</div>
        </div>
        <span class="status-badge ${z.status}"><span class="dot"></span>${z.status}</span>
      </div>
      <div class="zone-metrics">
        <div class="metric"><div class="metric-label">MQ-2</div><div class="metric-value">${z.latest ? z.latest.mq2.toFixed(0) : "—"}</div></div>
        <div class="metric"><div class="metric-label">MQ-135</div><div class="metric-value">${z.latest ? z.latest.mq135.toFixed(0) : "—"}</div></div>
        <div class="metric"><div class="metric-label">Pressure</div><div class="metric-value">${z.latest ? z.latest.pressure.toFixed(2) : "—"}</div></div>
      </div>
      <div class="zone-foot">
        <span>${z.device_online ? "● online" : "○ offline"}</span>
        <span class="valve-tag">${z.valve_state}</span>
      </div>
    </div>
  `).join("");
  grid.querySelectorAll(".zone-card").forEach(card => {
    card.onclick = () => openZoneDetail(card.dataset.zoneId);
  });
}

function renderIncidentList() {
  const list = document.getElementById("incident-list");
  const items = state.incidents.slice(0, 8);
  if (!items.length) {
    list.innerHTML = `<div class="empty-note">No incidents recorded yet.</div>`;
    return;
  }
  list.innerHTML = items.map(inc => {
    const zone = state.zones.find(z => z.id === inc.zone_id);
    return `
    <div class="incident-item">
      <div class="incident-top">
        <span class="incident-zone">${escapeHtml(zone ? zone.name : inc.zone_id.slice(0, 8))}</span>
        <span class="status-badge ${inc.status}"><span class="dot"></span>${inc.status}</span>
      </div>
      <div class="incident-reason">${escapeHtml(inc.reason)}</div>
      <div class="incident-meta">
        <span>${new Date(inc.created_at).toLocaleTimeString()}</span>
        <span>${inc.resolved ? "resolved" : inc.acknowledged_by ? `ack: ${escapeHtml(inc.acknowledged_by)}` : "open"}</span>
        <span>${inc.sms_sent ? "SMS sent" : "no SMS"}</span>
      </div>
      ${!inc.acknowledged_by && !inc.resolved ? `<button class="incident-ack-btn" data-id="${inc.id}">Acknowledge</button>` : ""}
    </div>`;
  }).join("");
  list.querySelectorAll(".incident-ack-btn").forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      try {
        await API.acknowledge(btn.dataset.id, "");
        toast("Incident acknowledged.", "safe");
        state.incidents = await API.listIncidents();
        renderIncidentList();
      } catch (err) { toast(err.message, "crit"); }
    };
  });
}

function renderSimGrid() {
  const grid = document.getElementById("sim-grid");
  if (!state.zones.length) { grid.innerHTML = ""; return; }
  const zoneOptionsId = "sim-zone-select";
  grid.innerHTML = `
    <select id="${zoneOptionsId}" style="grid-column:1/-1;background:var(--bg-2);border:1px solid var(--line);color:var(--text-0);padding:8px;border-radius:6px;font-size:12px;">
      ${state.zones.map(z => `<option value="${z.id}">${escapeHtml(z.name)}</option>`).join("")}
    </select>
    <button class="sim-btn" data-s="safe">✅ Normal</button>
    <button class="sim-btn danger" data-s="gas_leak">🔥 Gas leak</button>
    <button class="sim-btn danger" data-s="flame">🔥 Flame detected</button>
    <button class="sim-btn" data-s="pressure_anomaly">📉 Pressure anomaly</button>
    <button class="sim-btn" data-s="multi_warning">⚠️ Multi-warning</button>
    <button class="sim-btn" data-s="offline">📴 Mark offline</button>
  `;
  grid.querySelectorAll(".sim-btn").forEach(btn => {
    btn.onclick = async () => {
      const zoneId = document.getElementById(zoneOptionsId).value;
      try {
        await API.simulate(zoneId, btn.dataset.s);
        toast(`Simulated "${btn.dataset.s}" injected.`);
      } catch (err) { toast(err.message, "crit"); }
    };
  });
}

// ================= ZONE DETAIL =================

async function openZoneDetail(zoneId) {
  state.selectedZoneId = zoneId;
  const zone = state.zones.find(z => z.id === zoneId);
  if (!zone) return;

  const scrim = document.createElement("div");
  scrim.className = "overlay-scrim";
  scrim.id = "detail-scrim";
  scrim.innerHTML = `<div class="detail-panel" id="detail-panel"></div>`;
  scrim.onclick = (e) => { if (e.target === scrim) closeDetail(); };
  document.body.appendChild(scrim);

  await renderDetailPanel(zone);
}

function closeDetail() {
  const scrim = document.getElementById("detail-scrim");
  if (scrim) scrim.remove();
  state.selectedZoneId = null;
  if (state.chart) { state.chart.destroy(); state.chart = null; }
}

async function renderDetailPanel(zone) {
  const panel = document.getElementById("detail-panel");
  if (!panel) return;
  let readings = [];
  try { readings = await API.zoneReadings(zone.id, 40); } catch {}
  const latest = readings.length ? readings[readings.length - 1] : null;
  const incidents = state.incidents.filter(i => i.zone_id === zone.id).slice(0, 10);

  panel.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="detail-title">${escapeHtml(zone.name)}</div>
        <div style="color:var(--text-2);font-size:12.5px;margin-top:3px;">${escapeHtml(zone.location || "")} · ${escapeHtml(zone.device_code || "")} · ${zone.device_online ? "online" : "offline"}</div>
      </div>
      <button class="close-btn" id="close-detail">✕</button>
    </div>
    <span class="status-badge ${zone.status}" style="margin-bottom:16px;display:inline-flex;"><span class="dot"></span>${zone.status}</span>
    <div class="reason-box"><b>Reason:</b> ${escapeHtml(latest ? latest.reason : "No readings yet")}</div>
    <div class="detail-metrics">
      <div class="detail-metric"><div class="metric-label">MQ-2 (gas)</div><div class="metric-value">${latest ? latest.mq2.toFixed(0) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">MQ-135 (air quality)</div><div class="metric-value">${latest ? latest.mq135.toFixed(0) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">Pressure (bar)</div><div class="metric-value">${latest ? latest.pressure.toFixed(2) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">Flame</div><div class="metric-value">${latest ? (latest.flame_detected ? "DETECTED" : "clear") : "—"}</div></div>
    </div>
    <canvas class="chart" id="zone-chart"></canvas>
    <div class="valve-row">
      <div>
        <div class="valve-state-label">Actuator / valve state</div>
        <div class="valve-state-value" id="valve-state-value">${zone.valve_state}</div>
      </div>
    </div>
    <button class="btn-emergency" id="shutoff-btn">🚨 Emergency shutoff</button>
    <div class="timeline">
      <h3>Incident timeline</h3>
      <div id="timeline-list"></div>
    </div>
  `;
  document.getElementById("close-detail").onclick = closeDetail;
  document.getElementById("shutoff-btn").onclick = () => confirmShutoff(zone.id, zone.name);

  renderTimeline(incidents);
  renderChart(readings);
}

function renderTimeline(incidents) {
  const el = document.getElementById("timeline-list");
  if (!el) return;
  if (!incidents.length) { el.innerHTML = `<div class="empty-note">No incidents for this zone.</div>`; return; }
  const events = [];
  incidents.forEach(inc => {
    (inc.timeline_events || []).forEach(ev => events.push(ev));
  });
  events.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  el.innerHTML = events.slice(0, 15).map(ev => `
    <div class="timeline-item">
      <div class="timeline-dot"></div>
      <div style="flex:1;">${escapeHtml(ev.event)}</div>
      <div class="timeline-time">${new Date(ev.created_at).toLocaleTimeString()}</div>
    </div>
  `).join("");
}

function renderChart(readings) {
  const ctx = document.getElementById("zone-chart");
  if (!ctx || !window.Chart) return;
  const labels = readings.map(r => new Date(r.created_at).toLocaleTimeString());
  const mq2 = readings.map(r => r.mq2);
  const mq135 = readings.map(r => r.mq135);
  const pressure = readings.map(r => r.pressure * 200); // scaled onto same axis for visibility

  if (state.chart) state.chart.destroy();
  state.chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "MQ-2", data: mq2, borderColor: "#E5544B", backgroundColor: "transparent", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "MQ-135", data: mq135, borderColor: "#F0A93B", backgroundColor: "transparent", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "Pressure (×200)", data: pressure, borderColor: "#33C481", backgroundColor: "transparent", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#AEB9CC", boxWidth: 10, font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: "#7B879C", maxTicksLimit: 6, font: { size: 9 } }, grid: { color: "#1A2436" } },
        y: { ticks: { color: "#7B879C", font: { size: 9 } }, grid: { color: "#1A2436" } },
      },
    },
  });
}

// ================= EMERGENCY SHUTOFF =================

function confirmShutoff(zoneId, zoneName) {
  const scrim = document.createElement("div");
  scrim.className = "confirm-scrim";
  scrim.innerHTML = `
    <div class="confirm-box">
      <h3>Confirm emergency shutoff</h3>
      <p>This sends a shutoff command to the prototype actuator for <b>${escapeHtml(zoneName)}</b>. This is a safe demo actuator, not certified real-world gas equipment. Continue?</p>
      <div class="confirm-actions">
        <button class="confirm-cancel" id="confirm-cancel">Cancel</button>
        <button class="confirm-ok" id="confirm-ok">Send shutoff</button>
      </div>
    </div>`;
  document.body.appendChild(scrim);
  document.getElementById("confirm-cancel").onclick = () => scrim.remove();
  document.getElementById("confirm-ok").onclick = async () => {
    scrim.remove();
    const valveEl = document.getElementById("valve-state-value");
    const btn = document.getElementById("shutoff-btn");
    if (btn) btn.disabled = true;
    try {
      const res = await API.shutoff(zoneId);
      if (valveEl) valveEl.textContent = res.valve_state;
      toast("Shutoff command sent — waiting for ESP32 confirmation.");
      pollValveStatus(zoneId, btn);
    } catch (err) {
      toast(err.message, "crit");
      if (btn) btn.disabled = false;
    }
  };
}

async function pollValveStatus(zoneId, btn) {
  let tries = 0;
  const iv = setInterval(async () => {
    tries++;
    try {
      const res = await API.valveStatus(zoneId);
      const valveEl = document.getElementById("valve-state-value");
      if (valveEl) valveEl.textContent = res.valve_state;
      if (["CLOSED", "FAILED", "TIMEOUT"].includes(res.valve_state) || tries > 15) {
        clearInterval(iv);
        if (btn) btn.disabled = false;
        if (res.valve_state === "CLOSED") toast("Valve confirmed CLOSED by ESP32.", "safe");
        else if (res.valve_state === "FAILED") toast("Actuator reported FAILED — escalate manually.", "crit");
      }
    } catch { clearInterval(iv); if (btn) btn.disabled = false; }
  }, 1200);
}

// ================= WEBSOCKET & LIVE SYNC =================

let pollInterval = null;
let wsFailures = 0;

function startPollingFallback() {
  if (pollInterval) return;
  const pill = document.getElementById("conn-pill");
  if (pill) { pill.classList.add("live"); pill.innerHTML = `<span class="conn-dot"></span><span>Live</span>`; }
  pollInterval = setInterval(async () => {
    if (!API.getToken()) {
      clearInterval(pollInterval);
      pollInterval = null;
      return;
    }
    await loadZonesAndIncidents();
    if (state.selectedZoneId) {
      const zone = state.zones.find(z => z.id === state.selectedZoneId);
      if (zone) renderDetailPanel(zone);
    }
  }, 3500);
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let ws;
  try {
    ws = new WebSocket(`${proto}//${location.host}/ws`);
  } catch (e) {
    startPollingFallback();
    return;
  }
  state.ws = ws;
  const pill = () => document.getElementById("conn-pill");

  ws.onopen = () => {
    wsFailures = 0;
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    const p = pill();
    if (p) { p.classList.add("live"); p.innerHTML = `<span class="conn-dot"></span><span>Live</span>`; }
  };
  ws.onclose = () => {
    wsFailures++;
    if (wsFailures >= 2) {
      // Vercel / serverless functions do not maintain persistent WebSockets;
      // switch smoothly to live HTTP polling so dashboard remains fully active.
      startPollingFallback();
      return;
    }
    const p = pill();
    if (p) { p.classList.remove("live"); p.innerHTML = `<span class="conn-dot"></span><span>Connecting…</span>`; }
    setTimeout(() => { if (API.getToken() && wsFailures < 2) connectWebSocket(); }, 2000);
  };
  ws.onerror = () => {
    ws.close();
  };
  ws.onmessage = async (msg) => {
    let data;
    try { data = JSON.parse(msg.data); } catch { return; }
    if (data.event === "sensor_update") {
      await loadZonesAndIncidents();
      if (data.payload.status === "CRITICAL") toast(`CRITICAL — ${data.payload.zone_name}: ${data.payload.reason}`, "crit");
      if (state.selectedZoneId === data.payload.zone_id) {
        const zone = state.zones.find(z => z.id === data.payload.zone_id);
        if (zone) renderDetailPanel(zone);
      }
    } else if (data.event === "valve_update") {
      state.zones = await API.listZones();
      renderZoneGrid();
      const valveEl = document.getElementById("valve-state-value");
      if (valveEl && state.selectedZoneId === data.payload.zone_id) valveEl.textContent = data.payload.valve_state;
    }
  };
}

// ================= BOOT =================

window.addEventListener("pg:unauthorized", () => renderAuth("login"));

(function init() {
  if (API.getToken() && API.getUser()) {
    bootDashboard();
  } else {
    renderAuth("login");
  }
})();
