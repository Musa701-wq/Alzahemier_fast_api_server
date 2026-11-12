
let authToken = localStorage.getItem("yaadasht_auth_token") || null;

export function setAuthToken(token) {
  authToken = token;
  if (token) {
    localStorage.setItem("yaadasht_auth_token", token);
  } else {
    localStorage.removeItem("yaadasht_auth_token");
  }
}

export function getAuthToken() {
  return authToken;
}

async function apiRequest(path, { method = "GET", body = null } = {}) {
  const headers = {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
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
    let errDetail = "Something went wrong. Please try again.";
    try {
      const errJson = await response.json();
      if (typeof errJson.detail === "string" && errJson.detail.trim()) {
        errDetail = errJson.detail.trim();
      } else if (Array.isArray(errJson.detail) && errJson.detail.length > 0) {
        const firstErr = errJson.detail[0];
        const fieldName = Array.isArray(firstErr.loc)
          ? String(firstErr.loc[firstErr.loc.length - 1]).replace(/_/g, " ")
          : "input";
        errDetail = `Please check your ${fieldName} and try again.`;
      }
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

export async function signupUser({ email, password, full_name, language = "en" }) {
  return apiRequest("/auth/signup", {
    method: "POST",
    body: { email, password, full_name, language },
  });
}

export async function loginUser({ email, password }) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export async function emailAccessUser({ email, mode = "login", full_name = "Caregiver Account" }) {
  return apiRequest("/auth/email-access", {
    method: "POST",
    body: { email, mode, full_name },
  });
}

export async function checkExistingUser({ email = "", name = "" }) {
  return apiRequest("/auth/check-existing", {
    method: "POST",
    body: { email, name },
  });
}

export async function fetchCurrentUser() {
  return apiRequest("/auth/me");
}

export async function fetchMyPerson() {
  return apiRequest("/persons/me");
}

export async function createOrUpdatePerson(personData, existingPersonId = null) {
  const payload = {
    name: personData.name,
    age: Number(personData.age),
    gender: personData.gender,
    city: personData.city,
    education_level: personData.education_level || "secondary",
    occupation: personData.occupation || "retired",
    living_situation: personData.living_situation || "with_family",
    family_history_dementia: Boolean(personData.family_history_dementia),
    medical_conditions: personData.medical_conditions || [],
    observed_symptoms: personData.observed_symptoms || [],
    symptom_duration_months: Number(personData.symptom_duration_months ?? 6),
  };

  if (existingPersonId) {
    return apiRequest(`/persons/${existingPersonId}`, {
      method: "PATCH",
      body: payload,
    });
  }
  try {
    return await apiRequest("/persons", {
      method: "POST",
      body: payload,
    });
  } catch {
    const existing = await apiRequest("/persons/me");
    return apiRequest(`/persons/${existing.id}`, {
      method: "PATCH",
      body: payload,
    });
  }
}

export async function grantConsent(personId, type) {
  return apiRequest("/consents", {
    method: "POST",
    body: { person_id: personId, type, granted: true },
  });
}

export async function startSession(personId, sessionMode = "baseline") {
  return apiRequest("/sessions", {
    method: "POST",
    body: { person_id: personId, session_mode: sessionMode },
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

// OpenRouter AI Multimodal Endpoints
export async function fetchAIStatus() {
  return apiRequest("/ai/status");
}

export async function evaluatePictureStoryAI(description, sceneTitle = "", targetItems = []) {
  return apiRequest("/ai/picture-story", {
    method: "POST",
    body: {
      description,
      scene_title: sceneTitle,
      target_items: Array.isArray(targetItems) ? targetItems : [],
    },
  });
}

export async function evaluateClockVisionAI(imageDataUri, targetTime = "11:10", strokeData = null) {
  return apiRequest("/ai/clock-vision", {
    method: "POST",
    body: {
      image_data_uri: imageDataUri,
      target_time: targetTime,
      stroke_data: strokeData,
    },
  });
}

export async function extractPrescriptionAI(prescriptionText, imageDataUri = null) {
  return apiRequest("/ai/extract-prescription", {
    method: "POST",
    body: { prescription_text: prescriptionText, image_data_uri: imageDataUri },
  });
}

export async function ensureMicReady() {
  return apiRequest("/ai/ensure-mic-ready", {
    method: "POST",
    auth: false,
  });
}

export async function transcribeRecordedAudio({
  audioWavBase64,
  durationSeconds = 0,
  speakingSeconds = 0,
  pauseMs = 0,
  stepNumber = 1,
}) {
  return apiRequest("/ai/transcribe-audio", {
    method: "POST",
    body: {
      audio_wav_base64: audioWavBase64,
      duration_seconds: durationSeconds,
      speaking_seconds: speakingSeconds,
      pause_ms: pauseMs,
      step_number: stepNumber,
    },
  });
}
