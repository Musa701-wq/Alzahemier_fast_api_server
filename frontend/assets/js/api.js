let authToken = null;
let adminToken = null;

export function setAuthToken(token) {
  authToken = token;
}

export function setAdminToken(token) {
  adminToken = token;
}

export function getAuthToken() {
  return authToken;
}

async function apiRequest(path, { method = "GET", body = null, useAdmin = false } = {}) {
  const headers = {};
  const tokenToUse = useAdmin && adminToken ? adminToken : authToken;
  if (tokenToUse) {
    headers["Authorization"] = `Bearer ${tokenToUse}`;
  }
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : null,
  });

  if (!response.ok) {
    let errDetail = `Request failed (${response.status})`;
    try {
      const errJson = await response.json();
      if (errJson.detail) errDetail = errJson.detail;
    } catch {
      // Ignore parse error
    }
    throw new Error(errDetail);
  }

  return response.json();
}

export async function fetchHealthStatus() {
  const start = performance.now();
  const data = await apiRequest("/health");
  return { data, latencyMs: Math.round(performance.now() - start) };
}

export async function signupUser({ email, password, full_name, language = "ur", role = "user" }) {
  return apiRequest("/auth/signup", {
    method: "POST",
    body: { email, password, full_name, language, role },
  });
}

export async function loginUser({ email, password }) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export async function createOrUpdatePerson({ name, age, gender, city }, existingPersonId = null) {
  if (existingPersonId) {
    return apiRequest(`/persons/${existingPersonId}`, {
      method: "PATCH",
      body: { name, age: Number(age), gender, city },
    });
  }
  try {
    return await apiRequest("/persons", {
      method: "POST",
      body: { name, age: Number(age), gender, city },
    });
  } catch {
    const existing = await apiRequest("/persons/me");
    return apiRequest(`/persons/${existing.id}`, {
      method: "PATCH",
      body: { name, age: Number(age), gender, city },
    });
  }
}

export async function grantConsent(personId, type) {
  return apiRequest("/consents", {
    method: "POST",
    body: { person_id: personId, type, granted: true },
  });
}

export async function startSession(personId) {
  return apiRequest("/sessions", {
    method: "POST",
    body: { person_id: personId },
  });
}

export async function submitTestResult(sessionId, payload) {
  return apiRequest(`/sessions/${sessionId}/results`, {
    method: "POST",
    body: payload,
  });
}

export async function runClockCheck(sessionId, payload) {
  return apiRequest(`/sessions/${sessionId}/clock-check`, {
    method: "POST",
    body: payload,
  });
}

export async function completeSession(sessionId, durationSeconds = 840) {
  return apiRequest(`/sessions/${sessionId}/complete?duration_seconds=${durationSeconds}`, {
    method: "POST",
  });
}

export async function listSessions(personId) {
  return apiRequest(`/sessions?person_id=${encodeURIComponent(personId)}`);
}

export async function createSessionReport(sessionId, userNotes = "") {
  return apiRequest("/reports", {
    method: "POST",
    body: { session_id: sessionId, user_notes: userNotes },
  });
}

export async function downloadReportPdfBlob(reportId) {
  const response = await fetch(`/reports/${reportId}/pdf`, {
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
  });
  if (!response.ok) {
    throw new Error("Could not download PDF report.");
  }
  return response.blob();
}

export async function createReportShareLink(reportId, sharedVia = "whatsapp") {
  return apiRequest(`/reports/${reportId}/share`, {
    method: "POST",
    body: { shared_via: sharedVia, expiry_days: 14 },
  });
}

export async function revokeReportShareLink(reportId) {
  return apiRequest(`/reports/${reportId}/share`, {
    method: "DELETE",
  });
}

export async function listDoctors({ city = "", specialty = "", mode = "" } = {}) {
  const params = new URLSearchParams();
  if (city) params.set("city", city);
  if (specialty) params.set("specialty", specialty);
  if (mode) params.set("mode", mode);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiRequest(`/doctors${qs}`);
}

export async function adminCreateDoctor(doctorPayload) {
  return apiRequest("/admin/doctors", {
    method: "POST",
    body: doctorPayload,
    useAdmin: true,
  });
}

export async function adminCreateSafetyResource(resourcePayload) {
  return apiRequest("/admin/safety-resources", {
    method: "POST",
    body: resourcePayload,
    useAdmin: true,
  });
}

export async function uploadDoctorDocument(payload) {
  return apiRequest("/documents", {
    method: "POST",
    body: payload,
  });
}

export async function createConfirmedMedicine(payload) {
  return apiRequest("/medicines", {
    method: "POST",
    body: payload,
  });
}

export async function listMedicines(personId) {
  return apiRequest(`/medicines?person_id=${encodeURIComponent(personId)}`);
}

export async function logMedicineDose(payload) {
  return apiRequest("/medicine-logs", {
    method: "POST",
    body: payload,
  });
}

export async function generateMonthlySummary(payload) {
  return apiRequest("/summaries/monthly/generate", {
    method: "POST",
    body: payload,
  });
}

export async function runSafetyCheck(text) {
  return apiRequest("/safety/check", {
    method: "POST",
    body: { text },
  });
}

export async function deletePersonAndAllData(personId) {
  return apiRequest(`/persons/${personId}`, {
    method: "DELETE",
  });
}
