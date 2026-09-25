const API = (() => {
  const TOKEN_KEY = "pg_token";
  const USER_KEY = "pg_user";

  function getToken() { return localStorage.getItem(TOKEN_KEY); }
  function setSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; }
  }
  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  async function request(path, { method = "GET", body, auth = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth) {
      const t = getToken();
      if (t) headers["Authorization"] = `Bearer ${t}`;
    }
    const res = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      clearSession();
      window.dispatchEvent(new CustomEvent("pg:unauthorized"));
      throw new Error("Session expired — please log in again");
    }
    if (!res.ok) {
      let detail = "Request failed";
      try {
        const data = await res.json();
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } catch {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res.text();
  }

  return {
    getToken, setSession, getUser, clearSession,
    register: (data) => request("/api/auth/register", { method: "POST", body: data, auth: false }),
    login: (data) => request("/api/auth/login", { method: "POST", body: data, auth: false }),
    requestOtp: (phone) => request("/api/auth/otp/request", { method: "POST", body: { phone }, auth: false }),
    verifyOtp: (phone, code) => request("/api/auth/otp/verify", { method: "POST", body: { phone, code }, auth: false }),
    me: () => request("/api/auth/me"),

    listZones: () => request("/api/zones"),
    getZone: (id) => request(`/api/zones/${id}`),
    zoneReadings: (id, limit = 60) => request(`/api/zones/${id}/readings?limit=${limit}`),
    createZone: (data) => request("/api/zones", { method: "POST", body: data }),
    assignUser: (zoneId, userId) => request(`/api/zones/${zoneId}/assign`, { method: "POST", body: { user_id: userId } }),

    listIncidents: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return request(`/api/incidents${qs ? "?" + qs : ""}`);
    },
    acknowledge: (id, note) => request(`/api/incidents/${id}/acknowledge`, { method: "POST", body: { note } }),

    shutoff: (zoneId) => request("/api/actuator/shutoff", { method: "POST", body: { zone_id: zoneId, confirm: true } }),
    setValveState: (zoneId, targetState) => request("/api/actuator/valve-control", { method: "POST", body: { zone_id: zoneId, target_state: targetState } }),
    valveStatus: (zoneId) => request(`/api/actuator/${zoneId}/status`),

    simulate: (zoneId, scenario) => request("/api/simulate/event", { method: "POST", body: { zone_id: zoneId, scenario } }),

    listUsers: () => request("/api/audit/users"),
    listAuditModules: () => request("/api/audit/modules"),
    listAudit: (module, search) => {
      const q = new URLSearchParams();
      if (module) q.set("module", module);
      if (search) q.set("search", search);
      return request(`/api/audit${q.toString() ? "?" + q.toString() : ""}`);
    },

    // Pipeline Schematic & Dynamic Hardware Module Insertion
    getSchematic: () => request("/api/pipeline/schematic"),
    connectModule: (data) => request("/api/pipeline/modules/connect", { method: "POST", body: data }),
    updateModulePosition: (deviceCode, data) => request(`/api/pipeline/modules/${encodeURIComponent(deviceCode)}/position`, { method: "PUT", body: data }),
    disconnectModule: (deviceCode) => request(`/api/pipeline/modules/${encodeURIComponent(deviceCode)}`, { method: "DELETE" }),
    scanPipelineModules: () => request("/api/pipeline/scan-detect", { method: "POST" }),
  };
})();
