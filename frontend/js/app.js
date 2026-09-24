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
      <div class="field"><label>Email</label><input type="email" name="email" required autocomplete="email" placeholder="admin@pipelineguard.io"></div>
      <div class="field"><label>Password</label><input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></div>
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
        <div id="admin-panel-container"></div>
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
    renderAdminPanel();

    // Dynamically update the open detail drawer in place without resetting DOM
    if (state.selectedZoneId) {
      const zone = state.zones.find(z => z.id === state.selectedZoneId);
      if (zone) updateDetailPanel(zone);
    }
  } catch (err) {
    // Suppress background poll errors
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
    grid.innerHTML = `
      <div class="empty-note" style="grid-column: 1 / -1; padding: 36px 20px; text-align: center; border: 1px dashed var(--line); border-radius: var(--radius-m); background: var(--bg-1);">
        <div style="font-size: 32px; margin-bottom: 8px;">📡</div>
        <div style="font-size: 15px; font-weight: 600; color: var(--text-0); margin-bottom: 6px;">No Active Pipeline Zones Yet</div>
        <div style="color: var(--text-2); font-size: 13px; max-width: 440px; margin: 0 auto 16px auto; line-height: 1.5;">
          Power on your physical ESP32 WROOM-32. As soon as it transmits gas readings to <code>/api/sensors</code>, it will automatically register and stream live telemetry here.
        </div>
      </div>
    `;
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

function renderAdminPanel() {
  const container = document.getElementById("admin-panel-container");
  if (!container) return;
  const user = API.getUser();
  const isAdmin = user && user.role === "admin";

  if (!isAdmin) {
    container.innerHTML = `
      <div class="panel">
        <h3>System Status</h3>
        <p class="panel-desc">Real-time pipeline monitoring active. Telemetry is streamed directly from connected ESP32 field units.</p>
        <div style="font-size: 12.5px; color: var(--text-1); line-height: 1.7;">
          <div>• <b>Gas Warning Level:</b> &gt; 300.0</div>
          <div>• <b>Gas Critical Level:</b> &gt; 600.0</div>
          <div>• <b>Automated Shutoff:</b> Armed</div>
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="panel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <h3 style="margin:0;">Admin Console</h3>
        <span class="role-badge" style="background:var(--amber-dim);color:var(--amber);border:none;">ADMIN</span>
      </div>
      <p class="panel-desc" style="margin-bottom:14px;">Manage hardware units, inspect users, and review security logs.</p>
      <div style="display:flex;flex-direction:column;gap:8px;">
        <button class="btn-ghost" id="admin-add-zone-btn" style="text-align:left;display:flex;align-items:center;gap:10px;padding:9px 12px;width:100%;">
          <span>➕</span><span>Register New Pipeline Zone</span>
        </button>
        <button class="btn-ghost" id="admin-users-btn" style="text-align:left;display:flex;align-items:center;gap:10px;padding:9px 12px;width:100%;">
          <span>👥</span><span>View System Users</span>
        </button>
        <button class="btn-ghost" id="admin-audit-btn" style="text-align:left;display:flex;align-items:center;gap:10px;padding:9px 12px;width:100%;">
          <span>📋</span><span>Security Audit Logs</span>
        </button>
      </div>
    </div>
  `;

  document.getElementById("admin-add-zone-btn").onclick = openAddZoneModal;
  document.getElementById("admin-users-btn").onclick = openUsersModal;
  document.getElementById("admin-audit-btn").onclick = openAuditModal;
}

function openAdminModal(title, contentHtml) {
  const existing = document.getElementById("admin-scrim");
  if (existing) existing.remove();

  const scrim = document.createElement("div");
  scrim.className = "overlay-scrim";
  scrim.id = "admin-scrim";
  scrim.innerHTML = `
    <div class="detail-panel" style="max-width:620px;width:95%;">
      <div class="detail-head">
        <div class="detail-title">${escapeHtml(title)}</div>
        <button class="close-btn" id="close-admin-modal">✕</button>
      </div>
      <div style="margin-top:14px;">${contentHtml}</div>
    </div>
  `;
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };
  document.body.appendChild(scrim);
  document.getElementById("close-admin-modal").onclick = () => scrim.remove();
}

function openAddZoneModal() {
  openAdminModal("Register New Pipeline Zone", `
    <form id="add-zone-form">
      <div class="field">
        <label>Zone Name</label>
        <input name="name" placeholder="e.g. Sector 1 Pipeline" required>
      </div>
      <div class="field">
        <label>Location / Details</label>
        <input name="location" placeholder="e.g. Main Distribution Line" required>
      </div>
      <div class="field">
        <label>Device Code (matches ESP32)</label>
        <input name="device_code" placeholder="e.g. ESP32-01" required>
      </div>
      <button class="btn-primary" type="submit" style="margin-top:12px;">Register Zone</button>
    </form>
  `);

  document.getElementById("add-zone-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await API.createZone({
        name: fd.get("name"),
        location: fd.get("location"),
        device_code: fd.get("device_code")
      });
      toast("Pipeline zone registered successfully.", "safe");
      document.getElementById("admin-scrim")?.remove();
      await loadZonesAndIncidents();
    } catch (err) {
      toast(err.message, "crit");
    }
  };
}

async function openUsersModal() {
  openAdminModal("System Users", `<div class="empty-note">Loading users…</div>`);
  try {
    const users = await API.listUsers();
    const modalBody = document.querySelector("#admin-scrim .detail-panel > div:last-child");
    if (!modalBody) return;
    if (!users.length) {
      modalBody.innerHTML = `<div class="empty-note">No users found.</div>`;
      return;
    }
    modalBody.innerHTML = `
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:12.5px;color:var(--text-1);">
          <thead>
            <tr style="border-bottom:1px solid var(--line);text-align:left;color:var(--text-2);">
              <th style="padding:8px 6px;">Name</th>
              <th style="padding:8px 6px;">Email</th>
              <th style="padding:8px 6px;">Phone</th>
              <th style="padding:8px 6px;">Role</th>
              <th style="padding:8px 6px;">Phone Verified</th>
            </tr>
          </thead>
          <tbody>
            ${users.map(u => `
              <tr style="border-bottom:1px solid var(--line-soft);">
                <td style="padding:9px 6px;color:var(--text-0);font-weight:500;">${escapeHtml(u.name)}</td>
                <td style="padding:9px 6px;">${escapeHtml(u.email)}</td>
                <td style="padding:9px 6px;">${escapeHtml(u.phone || "—")}</td>
                <td style="padding:9px 6px;"><span class="role-badge">${escapeHtml(u.role)}</span></td>
                <td style="padding:9px 6px;">${u.phone_verified ? "✅ Yes" : "⏳ Pending"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  } catch (err) {
    toast(err.message, "crit");
  }
}

async function openAuditModal() {
  openAdminModal("Security & Operations Audit Log", `<div class="empty-note">Loading audit logs…</div>`);
  try {
    const logs = await API.listAudit();
    const modalBody = document.querySelector("#admin-scrim .detail-panel > div:last-child");
    if (!modalBody) return;
    if (!logs.length) {
      modalBody.innerHTML = `<div class="empty-note">No audit records logged yet.</div>`;
      return;
    }
    modalBody.innerHTML = `
      <div style="max-height:420px;overflow-y:auto;" class="scroll-thin">
        ${logs.map(log => `
          <div style="padding:10px;border-bottom:1px solid var(--line-soft);font-size:12.5px;">
            <div style="display:flex;justify-content:space-between;color:var(--text-2);margin-bottom:3px;font-size:11.5px;">
              <span style="font-weight:600;color:var(--amber);text-transform:uppercase;">${escapeHtml(log.action)}</span>
              <span>${new Date(log.created_at).toLocaleString()}</span>
            </div>
            <div style="color:var(--text-0);">${escapeHtml(log.detail || "No details")}</div>
          </div>
        `).join("")}
      </div>
    `;
  } catch (err) {
    toast(err.message, "crit");
  }
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
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
      <span class="status-badge ${zone.status}" id="detail-status-badge"><span class="dot"></span>${zone.status}</span>
      <span style="font-size:11.5px;color:var(--text-2);background:var(--bg-2);padding:3px 8px;border-radius:4px;border:1px solid var(--line);">Threshold: Warning &gt; 300 | Critical &gt; 600</span>
    </div>
    <div class="reason-box"><b>Reason:</b> <span id="detail-reason-val">${escapeHtml(latest ? latest.reason : "All readings within normal operating range")}</span></div>
    <div class="detail-metrics">
      <div class="detail-metric"><div class="metric-label">MQ-2 (gas)</div><div class="metric-value" id="detail-mq2-val">${latest ? latest.mq2.toFixed(0) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">MQ-135 (air quality)</div><div class="metric-value" id="detail-mq135-val">${latest ? latest.mq135.toFixed(0) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">Pressure (bar)</div><div class="metric-value" id="detail-pressure-val">${latest ? latest.pressure.toFixed(2) : "—"}</div></div>
      <div class="detail-metric"><div class="metric-label">Flame</div><div class="metric-value" id="detail-flame-val">${latest ? (latest.flame_detected ? '<span style="color:var(--crit);font-weight:700;">DETECTED</span>' : "clear") : "—"}</div></div>
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

async function updateDetailPanel(zone) {
  const panel = document.getElementById("detail-panel");
  if (!panel) return;

  let readings = [];
  try { readings = await API.zoneReadings(zone.id, 40); } catch {}
  const latest = readings.length ? readings[readings.length - 1] : null;
  const incidents = state.incidents.filter(i => i.zone_id === zone.id).slice(0, 10);

  // Update Status Badge
  const badge = document.getElementById("detail-status-badge");
  if (badge) {
    badge.className = `status-badge ${zone.status}`;
    badge.innerHTML = `<span class="dot"></span>${zone.status}`;
  }

  // Update Reason Text
  const reasonEl = document.getElementById("detail-reason-val");
  if (reasonEl && latest) {
    reasonEl.textContent = latest.reason || "All readings within normal operating range";
  }

  // Update Metric Numbers smoothly
  const mq2El = document.getElementById("detail-mq2-val");
  if (mq2El && latest) mq2El.textContent = latest.mq2.toFixed(0);

  const mq135El = document.getElementById("detail-mq135-val");
  if (mq135El && latest) mq135El.textContent = latest.mq135.toFixed(0);

  const presEl = document.getElementById("detail-pressure-val");
  if (presEl && latest) presEl.textContent = latest.pressure.toFixed(2);

  const flameEl = document.getElementById("detail-flame-val");
  if (flameEl && latest) {
    flameEl.innerHTML = latest.flame_detected
      ? '<span style="color:var(--crit);font-weight:700;">DETECTED</span>'
      : 'clear';
  }

  // Update Valve State
  const valveEl = document.getElementById("valve-state-value");
  if (valveEl) valveEl.textContent = zone.valve_state;

  // Update Incident Timeline
  renderTimeline(incidents);

  // Update Chart in place without destroying canvas
  if (state.chart && readings.length) {
    state.chart.data.labels = readings.map(r => new Date(r.created_at).toLocaleTimeString());
    state.chart.data.datasets[0].data = readings.map(r => r.mq2);
    state.chart.data.datasets[1].data = readings.map(r => r.mq135);
    state.chart.data.datasets[2].data = readings.map(r => r.pressure * 200);
    state.chart.update("none");
  }
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

// ================= FAST ACTIVE POLLING & LIVE SYNC =================

let pollInterval = null;

function startLivePolling() {
  if (pollInterval) return;
  const pill = document.getElementById("conn-pill");
  if (pill) { pill.classList.add("live"); pill.innerHTML = `<span class="conn-dot"></span><span>Live</span>`; }

  // High-frequency live polling: syncs telemetry every 1.2 seconds
  pollInterval = setInterval(async () => {
    if (!API.getToken()) {
      clearInterval(pollInterval);
      pollInterval = null;
      return;
    }
    await loadZonesAndIncidents();
  }, 1200);
}

function connectWebSocket() {
  startLivePolling(); // Always run live polling on cloud / serverless
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let ws;
  try {
    ws = new WebSocket(`${proto}//${location.host}/ws`);
  } catch (e) {
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
