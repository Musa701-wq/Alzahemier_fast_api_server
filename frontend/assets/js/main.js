import {
  completeSession,
  createConfirmedMedicine,
  createOrUpdatePerson,
  createReportShareLink,
  createSessionReport,
  deletePersonAndAllData,
  downloadReportPdfBlob,
  emailAccessUser,
  evaluateClockVisionAI,
  evaluatePictureStoryAI,
  extractPrescriptionAI,
  fetchCurrentUser,
  fetchHealthStatus,
  fetchMyPerson,
  generateMonthlySummary,
  getAuthToken,
  grantConsent,
  listDoctors,
  listMedicines,
  listSessions,
  loginUser,
  logMedicineDose,
  revokeReportShareLink,
  runClockCheck,
  runSafetyCheck,
  setAuthToken,
  signupUser,
  startSession,
  submitTestResult,
  transcribeRecordedAudio,
  uploadDoctorDocument,
} from "./api.js?v=8";
import {
  pauseOrResumeQuestion,
  renderActiveTestStep,
  renderCompletedSessionResult,
  renderConfirmedMedicines,
  renderDoctorsList,
  setActiveSessionPrompts,
  showEmergencyBanner,
  speakInstruction,
  stopQuestionAudio,
  switchSection,
} from "./ui.js?v=8";

// Session & Person State
let currentPerson = null;
let currentSession = null;
let currentCompletedSession = null;
let currentReport = null;
let currentStep = 1;
let sessionStartTimeMs = Date.now();

// Voice Examiner & Verbal Speech Interaction State
let voiceGuideActive = true;
let isListening = false;
let activeMicField = null;
let speechRecognitionInstance = null;
let browserRecognizedDuringSession = false;

// Real-Time Web Audio API Microphone Visualizer + PCM WAV Recorder + Timing State
let audioCtx = null;
let micAnalyser = null;
let micMediaStream = null;
let pcmProcessorNode = null;
let pcmChunks = [];
let pcmSampleRate = 16000;
let visualizerRafId = null;

// Voice Timing Metrics (Total Duration, Active Speaking Time, Hesitation Pause Time)
let recordStartMs = 0;
let lastFrameMs = 0;
let speakingDurationMs = 0;
let pauseDurationMs = 0;
let hasSpokenYet = false;
let lastRecordedAudioUrl = null;
let playbackAudioObj = null;

function encodePcmToWavBlob(float32Chunks, sampleRate) {
  let totalLen = 0;
  for (const c of float32Chunks) totalLen += c.length;
  const targetRate = 16000;
  const ratio = sampleRate / targetRate;
  const outLen = Math.max(1, Math.floor(totalLen / ratio));
  const buffer = new ArrayBuffer(44 + outLen * 2);
  const view = new DataView(buffer);

  const writeStr = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + outLen * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, outLen * 2, true);

  const merged = new Float32Array(totalLen);
  let offset = 0;
  for (const c of float32Chunks) {
    merged.set(c, offset);
    offset += c.length;
  }

  let byteOffset = 44;
  for (let i = 0; i < outLen; i++) {
    const idx = Math.min(totalLen - 1, Math.floor(i * ratio));
    const s = Math.max(-1, Math.min(1, merged[idx] || 0));
    view.setInt16(byteOffset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    byteOffset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result || ""));
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function drawIdleVoiceVisualizer(customBadgeText = null) {
  const canvas = document.getElementById("voiceVisualizerCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const barCount = 24;
  const gap = 3;
  const barWidth = Math.max(3, Math.floor((w - gap * (barCount - 1)) / barCount));
  ctx.fillStyle = "rgba(16, 185, 129, 0.28)";
  for (let i = 0; i < barCount; i++) {
    const bh = 4;
    const x = i * (barWidth + gap);
    const y = Math.round((h - bh) / 2);
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(x, y, barWidth, bh, 2) : ctx.fillRect(x, y, barWidth, bh);
    ctx.fill();
  }
  const lvlBadge = document.getElementById("voiceLevelBadge");
  if (lvlBadge && customBadgeText) {
    lvlBadge.textContent = customBadgeText;
  }
}

async function startVoiceVisualizerAndRecorder() {
  if (visualizerRafId) return;
  const canvas = document.getElementById("voiceVisualizerCanvas");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return;
  }

  try {
    stopQuestionAudio();

    micMediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioCtx = new AudioContextClass();
    pcmSampleRate = audioCtx.sampleRate || 44100;
    pcmChunks = [];

    const source = audioCtx.createMediaStreamSource(micMediaStream);
    micAnalyser = audioCtx.createAnalyser();
    micAnalyser.fftSize = 64;
    micAnalyser.smoothingTimeConstant = 0.75;
    source.connect(micAnalyser);

    pcmProcessorNode = audioCtx.createScriptProcessor(4096, 1, 1);
    pcmProcessorNode.onaudioprocess = (e) => {
      if (!isListening) return;
      const input = e.inputBuffer.getChannelData(0);
      pcmChunks.push(new Float32Array(input));
    };
    source.connect(pcmProcessorNode);
    pcmProcessorNode.connect(audioCtx.destination);

    recordStartMs = performance.now();
    lastFrameMs = recordStartMs;
    speakingDurationMs = 0;
    pauseDurationMs = 0;
    hasSpokenYet = false;

    const bufferLength = micAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const ctx = canvas ? canvas.getContext("2d") : null;
    const w = canvas ? canvas.width : 140;
    const h = canvas ? canvas.height : 28;
    const barCount = 24;
    const gap = 3;
    const barWidth = Math.max(3, Math.floor((w - gap * (barCount - 1)) / barCount));

    const renderFrame = () => {
      if (!micAnalyser) return;
      visualizerRafId = requestAnimationFrame(renderFrame);
      micAnalyser.getByteFrequencyData(dataArray);

      const now = performance.now();
      const dt = Math.max(0, now - lastFrameMs);
      lastFrameMs = now;

      if (ctx) ctx.clearRect(0, 0, w, h);
      let sum = 0;
      for (let i = 0; i < barCount; i++) {
        const val = dataArray[i % bufferLength] || 0;
        sum += val;
        const pct = val / 255;
        const bh = Math.max(4, Math.round(pct * (h - 4)));
        const x = i * (barWidth + gap);
        const y = Math.round((h - bh) / 2);

        if (ctx) {
          ctx.fillStyle = pct > 0.45 ? "#059669" : pct > 0.15 ? "#10b981" : "#6ee7b7";
          ctx.beginPath();
          ctx.roundRect ? ctx.roundRect(x, y, barWidth, bh, 2) : ctx.fillRect(x, y, barWidth, bh);
          ctx.fill();
        }
      }

      const avgPct = Math.min(100, Math.round((sum / (barCount * 150)) * 100));
      if (avgPct >= 10) {
        hasSpokenYet = true;
        speakingDurationMs += dt;
      } else if (hasSpokenYet) {
        pauseDurationMs += dt;
      }

      const totalSec = ((now - recordStartMs) / 1000).toFixed(1);
      const speakSec = (speakingDurationMs / 1000).toFixed(1);
      const pauseSec = (pauseDurationMs / 1000).toFixed(1);

      const lvlBadge = document.getElementById("voiceLevelBadge");
      if (lvlBadge) {
        lvlBadge.textContent = `🔴 ${totalSec}s · Speak ${speakSec}s · Pause ${pauseSec}s`;
      }

      const pauseInp = document.getElementById("t4PauseMs");
      if (pauseInp && currentStep === 4) {
        pauseInp.value = String(Math.round(pauseDurationMs));
      }
    };

    renderFrame();
  } catch (err) {
    console.warn("Microphone recorder notice:", err);
  }
}

async function stopVoiceVisualizerAndRecorder(targetFieldAtStop, stepAtStop) {
  if (visualizerRafId) {
    cancelAnimationFrame(visualizerRafId);
    visualizerRafId = null;
  }

  const totalSec = recordStartMs ? Math.max(0.1, (performance.now() - recordStartMs) / 1000) : 0;
  const speakSec = speakingDurationMs / 1000;
  const pauseSec = pauseDurationMs / 1000;
  const capturedChunks = pcmChunks.slice();
  const capturedRate = pcmSampleRate;
  pcmChunks = [];

  if (pcmProcessorNode) {
    try {
      pcmProcessorNode.disconnect();
    } catch {}
    pcmProcessorNode = null;
  }
  if (micMediaStream) {
    micMediaStream.getTracks().forEach((t) => t.stop());
    micMediaStream = null;
  }
  if (audioCtx) {
    try {
      audioCtx.close();
    } catch {}
    audioCtx = null;
  }
  micAnalyser = null;

  const summaryBadge =
    totalSec > 0.2
      ? `✓ ${totalSec.toFixed(1)}s (Speak ${speakSec.toFixed(1)}s · Pause ${pauseSec.toFixed(1)}s)`
      : "⏱ 0.0s · Idle";
  drawIdleVoiceVisualizer(summaryBadge);

  if (capturedChunks.length === 0 || totalSec < 0.25) {
    return;
  }

  const wavBlob = encodePcmToWavBlob(capturedChunks, capturedRate);
  if (lastRecordedAudioUrl) {
    URL.revokeObjectURL(lastRecordedAudioUrl);
  }
  lastRecordedAudioUrl = URL.createObjectURL(wavBlob);

  const playBtn = document.getElementById("btnPlayRecordedVoice");
  if (playBtn) {
    playBtn.textContent = `🔊 Play Voice (${totalSec.toFixed(1)}s)`;
    playBtn.classList.remove("hidden");
  }

  const bubble = document.getElementById("liveVoiceText");
  if (bubble) {
    bubble.textContent = `⏳ Processing recorded voice (${totalSec.toFixed(1)}s, Speak: ${speakSec.toFixed(1)}s, Pause: ${pauseSec.toFixed(1)}s)...`;
  }

  try {
    const wavB64 = await blobToBase64(wavBlob);
    const res = await transcribeRecordedAudio({
      audioWavBase64: wavB64,
      durationSeconds: totalSec,
      speakingSeconds: speakSec,
      pauseMs: Math.round(pauseDurationMs),
      stepNumber: stepAtStop,
    });

    if (res && res.transcript) {
      if (!browserRecognizedDuringSession) {
        routeTranscribedTextToField(res.transcript, targetFieldAtStop, stepAtStop);
      }
      if (bubble) {
        bubble.textContent = `✓ Recorded ${totalSec.toFixed(1)}s (Speak: ${speakSec.toFixed(1)}s, Pause: ${pauseSec.toFixed(1)}s) — "${res.transcript}"`;
      }
    } else if (bubble) {
      bubble.textContent = `✓ Voice recorded (${totalSec.toFixed(1)}s · Speak ${speakSec.toFixed(1)}s · Pause ${pauseSec.toFixed(1)}s). Click "🔊 Play Voice" to listen.`;
    }
  } catch {
    if (bubble) {
      bubble.textContent = `✓ Voice recorded (${totalSec.toFixed(1)}s · Speak ${speakSec.toFixed(1)}s). Click "🔊 Play Voice" to listen.`;
    }
  }
}

// Clock Canvas Stroke Recording State
let clockStrokes = [];
let currentStroke = null;
let clearClockCanvasFn = null;

// Dot Game State (1 to 12)
let dotNextExpected = 1;
let dotStartTime = null;
let dotErrors = 0;
let dotDurationSec = 0.0;
let resetDotGameFn = null;

function getDefaultTargetFieldForStep(stepNum) {
  if (stepNum === 1) {
    const t1Fields = ["t1Day", "t1Date", "t1Month", "t1Season", "t1City"];
    for (const fId of t1Fields) {
      const el = document.getElementById(fId);
      if (el && !el.value.trim()) return fId;
    }
    return "t1Day";
  }
  const map = { 2: "t2Response", 3: "t3Response", 4: "t4Response", 7: "t7Response" };
  return map[stepNum] || "t1Day";
}

function routeTranscribedTextToField(spokenText, explicitField = null, stepNum = currentStep) {
  if (!spokenText) return;
  const clean = spokenText.trim();
  if (!clean) return;

  if (stepNum === 1) {
    const matchedAny = parseOrientationSpeech(clean.toLowerCase());
    const targetId = explicitField || getDefaultTargetFieldForStep(1);
    const el = document.getElementById(targetId);
    if (el && (!matchedAny || explicitField)) {
      el.value = clean;
    }
    return;
  }

  const fieldId = explicitField || getDefaultTargetFieldForStep(stepNum);
  const el = document.getElementById(fieldId);
  if (el) {
    if (el.tagName === "TEXTAREA") {
      el.value = el.value ? `${el.value} ${clean}` : clean;
    } else {
      el.value = clean;
    }
  }
}

function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return;

  try {
    speechRecognitionInstance = new SpeechRecognition();
    speechRecognitionInstance.continuous = true;
    speechRecognitionInstance.interimResults = true;
    speechRecognitionInstance.lang = "en-US";

    speechRecognitionInstance.onresult = (event) => {
      let interimTranscript = "";
      let finalTranscript = "";

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interimTranscript += transcript;
        }
      }

      const activeText = (finalTranscript || interimTranscript).trim();
      const bubble = document.getElementById("liveVoiceText");
      if (bubble && activeText) {
        bubble.textContent = `🎙️ Hearing: "${activeText}"`;
      }

      if (finalTranscript) {
        browserRecognizedDuringSession = true;
        routeTranscribedTextToField(finalTranscript.trim(), activeMicField, currentStep);
      }
    };

    speechRecognitionInstance.onerror = () => {};

    speechRecognitionInstance.onend = () => {
      if (isListening) {
        try {
          speechRecognitionInstance.start();
        } catch {}
      }
    };
  } catch (err) {
    console.warn("SpeechRecognition init notice:", err);
  }
}

function parseOrientationSpeech(lower) {
  let matched = false;
  const days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  const months = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
  ];
  const seasons = ["winter", "spring", "summer", "autumn", "fall"];

  for (const d of days) {
    if (lower.includes(d)) {
      const el = document.getElementById("t1Day");
      if (el) el.value = d.charAt(0).toUpperCase() + d.slice(1);
      matched = true;
      break;
    }
  }

  for (const m of months) {
    if (lower.includes(m)) {
      const el = document.getElementById("t1Month");
      if (el) el.value = m.charAt(0).toUpperCase() + m.slice(1);
      matched = true;
      break;
    }
  }

  for (const s of seasons) {
    if (lower.includes(s)) {
      const canonical = s === "fall" ? "Autumn" : s.charAt(0).toUpperCase() + s.slice(1);
      const el = document.getElementById("t1Season");
      if (el) el.value = canonical;
      matched = true;
      break;
    }
  }

  const dateMatch = lower.match(/\b(3[01]|[12][0-9]|[1-9])(st|nd|rd|th)?\b/);
  if (dateMatch) {
    const el = document.getElementById("t1Date");
    if (el) el.value = dateMatch[1];
    matched = true;
  }

  const cities = ["lahore", "karachi", "islamabad", "rawalpindi", "peshawar", "quetta", "faisalabad", "multan", "london", "dubai"];
  for (const c of cities) {
    if (lower.includes(c)) {
      const el = document.getElementById("t1City");
      if (el) el.value = c.charAt(0).toUpperCase() + c.slice(1);
      matched = true;
      break;
    }
  }
  return matched;
}

function toggleSpeechRecognition(targetField = null) {
  if (isListening && (!targetField || targetField === activeMicField)) {
    const fieldAtStop = activeMicField;
    const stepAtStop = currentStep;
    isListening = false;
    activeMicField = null;
    if (speechRecognitionInstance) {
      try {
        speechRecognitionInstance.stop();
      } catch {}
    }
    updateMicUIState(false, fieldAtStop, stepAtStop);
    return;
  }

  activeMicField = targetField || getDefaultTargetFieldForStep(currentStep);
  browserRecognizedDuringSession = false;
  isListening = true;

  const targetInp = document.getElementById(activeMicField);
  if (targetInp) targetInp.focus();

  if (speechRecognitionInstance) {
    try {
      speechRecognitionInstance.start();
    } catch {}
  }
  updateMicUIState(true, activeMicField, currentStep);
}

function updateMicUIState(listening, fieldAtStop = null, stepAtStop = currentStep) {
  const btn = document.getElementById("btnGlobalMicToggle");
  const wave = document.getElementById("globalMicWave");
  const label = document.getElementById("globalMicLabel");
  const bubble = document.getElementById("liveVoiceBubble");
  const txt = document.getElementById("liveVoiceText");

  if (btn) btn.classList.toggle("is-listening", listening);
  if (wave) wave.classList.toggle("hidden", !listening);
  if (bubble) bubble.classList.toggle("active", listening);

  if (listening) {
    if (txt) txt.textContent = "🔴 Recording your voice... Speak now, then click Stop when finished.";
    startVoiceVisualizerAndRecorder();
  } else {
    stopVoiceVisualizerAndRecorder(fieldAtStop, stepAtStop);
  }

  if (label) {
    label.textContent = listening ? "⏹ Stop Recording" : "Record Answer";
  }

  document.querySelectorAll(".btn-field-mic").forEach((fBtn) => {
    const isTarget = listening && fBtn.dataset.voiceField === activeMicField;
    fBtn.classList.toggle("listening", isTarget);
    fBtn.textContent = isTarget ? "⏹ Stop" : "🎙️ Speak";
  });
}

function showAILoadingOverlay(visible, sessionMode = "baseline", patientName = "Patient") {
  const overlay = document.getElementById("aiLoadingOverlay");
  if (!overlay) return;
  if (!visible) {
    overlay.classList.add("hidden");
    return;
  }
  const titleEl = document.getElementById("aiLoadingTitle");
  const stepEl = document.getElementById("aiLoadingStepText");
  const badgeEl = document.getElementById("aiLoadingBadge");
  if (badgeEl) {
    badgeEl.textContent = sessionMode === "post_visit_adaptive" ? "Adaptive Mode" : "Personalized Assessment";
  }
  if (titleEl) {
    titleEl.textContent =
      sessionMode === "post_visit_adaptive"
        ? `Generating Adaptive Test for ${patientName}...`
        : `Loading & Generating Test for ${patientName}...`;
  }
  if (stepEl) {
    stepEl.textContent = "Syncing profile with MongoDB and preparing 7 cognitive questions.";
  }
  overlay.classList.remove("hidden");
}

function renderHomePatientDashboard(person, sessions = []) {
  const loggedView = document.getElementById("homeLoggedInView");
  const guestView = document.getElementById("homeGuestView");
  const cancelBtn = document.getElementById("btnCancelEditProfile");
  const headerLogoutBtn = document.getElementById("btnHeaderLogout");

  if (!person || (!person.id && !person.name)) {
    localStorage.removeItem("yaadasht_saved_person");
    if (loggedView) {
      loggedView.classList.add("hidden");
      loggedView.style.display = "none";
    }
    if (guestView) {
      guestView.classList.remove("hidden");
      guestView.style.display = "";
    }
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (headerLogoutBtn) headerLogoutBtn.classList.add("hidden");
    return;
  }

  try {
    localStorage.setItem("yaadasht_saved_person", JSON.stringify(person));
  } catch {}

  if (loggedView) {
    loggedView.classList.remove("hidden");
    loggedView.style.display = "flex";
  }
  if (guestView) {
    guestView.classList.add("hidden");
    guestView.style.display = "none";
  }
  if (cancelBtn) cancelBtn.classList.remove("hidden");
  if (headerLogoutBtn) headerLogoutBtn.classList.remove("hidden");

  const emailTag = document.getElementById("dashAccountEmailTag");
  const savedEmail = localStorage.getItem("yaadasht_caregiver_email");
  if (emailTag && savedEmail && !savedEmail.endsWith("@yaadasht.local")) {
    emailTag.textContent = `Email: ${savedEmail}`;
  } else if (emailTag) {
    emailTag.textContent = "Synced with MongoDB";
  }

  const nameHeading = document.getElementById("dashPatientNameHeading");
  if (nameHeading) nameHeading.textContent = `${person.name}'s Care Hub`;

  const ageGender = document.getElementById("dashAgeGender");
  if (ageGender) ageGender.textContent = `${person.age} yrs · ${(person.gender || "male").toUpperCase()}`;

  const cityEl = document.getElementById("dashCity");
  if (cityEl) cityEl.textContent = person.city || "Lahore";

  const eduEl = document.getElementById("dashEducation");
  if (eduEl) eduEl.textContent = (person.education_level || "secondary").replace(/_/g, " ").toUpperCase();

  const occEl = document.getElementById("dashOccupation");
  if (occEl) occEl.textContent = person.occupation || "Retired";

  const tagsEl = document.getElementById("dashSymptomsTags");
  if (tagsEl) {
    const syms = (person.observed_symptoms || []).map((s) => s.replace(/_/g, " "));
    const conds = (person.medical_conditions || []).map((c) => c.replace(/_/g, " "));
    const allTags = [...syms, ...conds];
    tagsEl.innerHTML =
      allTags.length > 0
        ? allTags.map((t) => `<span class="dash-tag-chip">${t}</span>`).join("")
        : `<span class="dash-tag-chip">Baseline Screening</span>`;
  }

  const countBadge = document.getElementById("dashSessionCountBadge");
  if (countBadge) countBadge.textContent = `${sessions.length} Session${sessions.length === 1 ? "" : "s"}`;

  const completedList = (sessions || []).filter((s) => s.completed);
  const kpiScore = document.getElementById("kpiLatestScore");
  const kpiOutcome = document.getElementById("homeLastOutcomeText");
  const kpiRetest = document.getElementById("kpiNextRetestBadge");
  if (completedList.length > 0) {
    const last = completedList[completedList.length - 1];
    if (kpiScore) kpiScore.textContent = `${Math.round(last.total_score ?? 0)} / 100`;
    if (kpiOutcome) kpiOutcome.textContent = (last.outcome || "Completed").replace(/_/g, " ").toUpperCase();
    if (kpiRetest) kpiRetest.textContent = "In 30 Days";
  } else {
    if (kpiScore) kpiScore.textContent = "—";
    if (kpiOutcome) kpiOutcome.textContent = "Ready for first test";
    if (kpiRetest) kpiRetest.textContent = "Due Now";
  }

  const listEl = document.getElementById("dashSessionsList");
  if (listEl) {
    if (!Array.isArray(sessions) || sessions.length === 0) {
      listEl.innerHTML = `
        <div class="finding-card" style="background:var(--bg-soft);">
          <strong>No sessions yet</strong>
          <span>Click "🧠 Start AI Test" above to begin.</span>
        </div>
      `;
    } else {
      const recent = [...sessions].reverse().slice(0, 4);
      listEl.innerHTML = recent
        .map((s, idx) => {
          const dt = s.session_date ? new Date(s.session_date).toLocaleDateString() : "Recent";
          const modeLbl = s.session_mode === "post_visit_adaptive" ? "🔄 Adaptive Follow-Up" : "🧠 AI Baseline";
          const statusStr = s.completed
            ? `Score: ${Math.round(s.total_score ?? 0)}/100 · ${(s.outcome || "").replace(/_/g, " ").toUpperCase()}`
            : `In Progress (${(s.results || []).length}/7 tests saved)`;
          return `
            <div class="finding-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;">
              <div>
                <strong style="font-size:13px;">${modeLbl} (${dt})</strong>
                <span style="display:block;font-size:12px;">${statusStr}</span>
              </div>
              <button type="button" class="mode-pill btn-dash-open-session" data-session-idx="${idx}" style="font-size:12px;padding:6px 12px;">
                ${s.completed ? "View Report" : "Resume"}
              </button>
            </div>
          `;
        })
        .join("");

      listEl.querySelectorAll(".btn-dash-open-session").forEach((btn) => {
        btn.addEventListener("click", () => {
          const targetSession = recent[Number(btn.dataset.sessionIdx)];
          if (!targetSession) return;
          if (targetSession.completed) {
            currentCompletedSession = targetSession;
            renderCompletedSessionResult(targetSession, sessions.filter((x) => x.completed));
            switchSection("result");
          } else {
            currentSession = targetSession;
            applySessionPromptsToUI(targetSession);
            const nextStepNum = Math.min(7, (targetSession.results || []).length + 1);
            handleStepTransition(nextStepNum);
            switchSection("session");
          }
        });
      });
    }
  }
}

function populatePersonForm(person) {
  if (!person) return;
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = String(val);
  };
  const savedEmail = localStorage.getItem("yaadasht_caregiver_email") || "";
  if (savedEmail && !savedEmail.endsWith("@yaadasht.local")) {
    setVal("inpPersonEmail", savedEmail);
  }
  setVal("inpPersonName", person.name || "");
  setVal("inpPersonAge", person.age || "");
  setVal("inpPersonGender", person.gender || "male");
  setVal("inpPersonCity", person.city || "Lahore");
  setVal("inpPersonEducation", person.education_level || "secondary");
  setVal("inpPersonOccupation", person.occupation && person.occupation !== "retired" ? person.occupation : "");
  setVal("inpFamilyHistory", person.family_history_dementia ? "true" : "false");
  setVal("inpSymptomDuration", person.symptom_duration_months ?? 6);

  const symSet = new Set(person.observed_symptoms || []);
  document.querySelectorAll(".chk-symptom").forEach((chk) => {
    chk.checked = symSet.has(chk.value);
  });

  const condSet = new Set(person.medical_conditions || []);
  document.querySelectorAll(".chk-condition").forEach((chk) => {
    chk.checked = condSet.has(chk.value);
  });

  const badge = document.getElementById("activePersonBadge");
  if (badge && person.name) {
    badge.textContent = `${person.name} (${person.age}y, ${person.city})`;
  }
  const onboardBadge = document.getElementById("onboardStatusBadge");
  if (onboardBadge && person.id) {
    onboardBadge.textContent = "Saved ✓";
  }
}

function saveFormDraftToStorage() {
  try {
    const draft = {
      email: document.getElementById("inpPersonEmail")?.value || "",
      name: document.getElementById("inpPersonName")?.value || "",
      age: document.getElementById("inpPersonAge")?.value || "",
      gender: document.getElementById("inpPersonGender")?.value || "male",
      city: document.getElementById("inpPersonCity")?.value || "Lahore",
      education_level: document.getElementById("inpPersonEducation")?.value || "secondary",
      occupation: document.getElementById("inpPersonOccupation")?.value || "",
      family_history_dementia: document.getElementById("inpFamilyHistory")?.value === "true",
      symptom_duration_months: Number(document.getElementById("inpSymptomDuration")?.value || 6),
      observed_symptoms: Array.from(document.querySelectorAll(".chk-symptom:checked")).map((el) => el.value),
      medical_conditions: Array.from(document.querySelectorAll(".chk-condition:checked")).map((el) => el.value),
    };
    localStorage.setItem("yaadasht_person_draft", JSON.stringify(draft));
  } catch {}
}

function restoreFormDraftFromStorage() {
  try {
    const savedPersonRaw = localStorage.getItem("yaadasht_saved_person");
    if (savedPersonRaw) {
      const savedP = JSON.parse(savedPersonRaw);
      if (savedP && (savedP.id || savedP.name)) {
        currentPerson = savedP;
        populatePersonForm(savedP);
        renderHomePatientDashboard(savedP, []);
        return;
      }
    }
    const raw = localStorage.getItem("yaadasht_person_draft");
    if (!raw) return;
    const draft = JSON.parse(raw);
    if (draft && (draft.name || draft.age)) {
      populatePersonForm(draft);
    }
    if (draft && draft.email) {
      const emEl = document.getElementById("inpPersonEmail");
      if (emEl) emEl.value = draft.email;
    }
  } catch {}
}

function applySessionPromptsToUI(session) {
  if (!session) return;
  const prompts = session.item_prompts || {};
  setActiveSessionPrompts(prompts);

  const oq = prompts.orientation_questions || {};
  if (oq.day) {
    const el = document.getElementById("lblT1Day");
    if (el) el.textContent = oq.day;
  }
  if (oq.date) {
    const el = document.getElementById("lblT1Date");
    if (el) el.textContent = oq.date;
  }
  if (oq.month) {
    const el = document.getElementById("lblT1Month");
    if (el) el.textContent = oq.month;
  }
  if (oq.season) {
    const el = document.getElementById("lblT1Season");
    if (el) el.textContent = oq.season;
  }
  if (oq.city) {
    const el = document.getElementById("lblT1City");
    if (el) el.textContent = oq.city;
  }

  if (prompts.words_en) {
    const chipsContainer = document.getElementById("t2WordChips");
    if (chipsContainer) {
      chipsContainer.innerHTML = prompts.words_en
        .map((wEn) => `<span class="word-chip">${wEn.charAt(0).toUpperCase() + wEn.slice(1)}</span>`)
        .join("");
      chipsContainer.classList.remove("hidden");
    }
  }

  const t3Title = document.getElementById("t3CategoryTitle");
  const t3Prompt = document.getElementById("t3CategoryPrompt");
  if (t3Title && prompts.fluency_category) {
    t3Title.textContent = `60-Second Verbal Fluency Challenge (${prompts.fluency_category})`;
  }
  if (t3Prompt && prompts.fluency_prompt) {
    t3Prompt.textContent = prompts.fluency_prompt;
  }

  const targetTime = prompts.clock_target_time || "11:10";
  const t5Time = document.getElementById("t5TargetTime");
  if (t5Time) t5Time.textContent = targetTime;
  const chkTimeLbl = document.getElementById("chkClockTargetLabel");
  if (chkTimeLbl) chkTimeLbl.textContent = targetTime;

  if (resetDotGameFn && prompts.dot_coords) {
    resetDotGameFn(prompts.dot_coords);
  }

  if (Array.isArray(session.results)) {
    for (const r of session.results) {
      if (r.test_number === 2 && r.raw_response) {
        const el = document.getElementById("t2Response");
        if (el) el.value = r.raw_response;
      } else if (r.test_number === 3 && r.raw_response) {
        const el = document.getElementById("t3Response");
        if (el) el.value = r.raw_response;
      } else if (r.test_number === 4 && r.raw_response) {
        const el = document.getElementById("t4Response");
        if (el) el.value = r.raw_response;
      } else if (r.test_number === 7 && r.raw_response) {
        const el = document.getElementById("t7Response");
        if (el) el.value = r.raw_response;
      }
    }
  }
}

async function bootstrapAccountAndData() {
  restoreFormDraftFromStorage();

  try {
    const { data } = await fetchHealthStatus();
    const verEl = document.getElementById("aboutVersion");
    if (verEl) verEl.textContent = `v${data.version}`;
    const healthDot = document.getElementById("healthDot");
    if (healthDot) healthDot.style.background = "#10b981";
  } catch {}

  try {
    let authenticated = false;
    if (getAuthToken()) {
      try {
        await fetchCurrentUser();
        authenticated = true;
      } catch {
        setAuthToken(null);
      }
    }

    if (!authenticated) {
      let savedEmail = localStorage.getItem("yaadasht_caregiver_email");
      let savedPass = localStorage.getItem("yaadasht_caregiver_pass");
      if (!savedEmail || !savedPass) {
        const suffix = Math.floor(Math.random() * 90000 + 10000);
        savedEmail = `caregiver_${suffix}@yaadasht.local`;
        savedPass = "password123";
        localStorage.setItem("yaadasht_caregiver_email", savedEmail);
        localStorage.setItem("yaadasht_caregiver_pass", savedPass);
      }
      try {
        const loginRes = await loginUser({ email: savedEmail, password: savedPass });
        setAuthToken(loginRes.access_token);
      } catch {
        const signupRes = await signupUser({
          email: savedEmail,
          password: savedPass,
          full_name: "Caregiver Account",
          language: "en",
        });
        setAuthToken(signupRes.access_token);
      }
    }

    try {
      const savedPerson = await fetchMyPerson();
      if (savedPerson && savedPerson.id) {
        currentPerson = savedPerson;
        populatePersonForm(savedPerson);

        const sessions = await listSessions(savedPerson.id);
        renderHomePatientDashboard(savedPerson, sessions || []);
        if (Array.isArray(sessions) && sessions.length > 0) {
          const completedList = sessions.filter((s) => s.completed);
          const openList = sessions.filter((s) => !s.completed);

          if (completedList.length > 0) {
            currentCompletedSession = completedList[completedList.length - 1];
            renderCompletedSessionResult(currentCompletedSession, completedList);
          }
          if (openList.length > 0) {
            currentSession = openList[openList.length - 1];
            applySessionPromptsToUI(currentSession);
          } else if (currentCompletedSession) {
            applySessionPromptsToUI(currentCompletedSession);
          }
        }

        try {
          const meds = await listMedicines(savedPerson.id);
          if (Array.isArray(meds) && meds.length > 0) {
            renderConfirmedMedicines(meds, async (medId, statusVal) => {
              const logRes = await logMedicineDose({
                medicine_id: medId,
                scheduled_time: "21:00",
                status: statusVal,
              });
              const fb = document.getElementById("medicineLogFeedback");
              if (fb) {
                fb.textContent = logRes.gentle_reminder
                  ? `Logged as ${statusVal}: ${logRes.gentle_reminder}`
                  : `Dose marked as TAKEN ✓ (${new Date(logRes.logged_at).toLocaleTimeString()})`;
              }
            });
          }
        } catch {}
      }
    } catch {}

    const savedStep = Number(localStorage.getItem("yaadasht_active_step") || 1);
    if (savedStep >= 1 && savedStep <= 7) {
      currentStep = savedStep;
    }
    renderActiveTestStep(currentStep, currentSession?.item_prompts || null);

    const savedSection = localStorage.getItem("yaadasht_active_section");
    if (savedSection && ["home", "session", "result", "doctors", "postvisit", "settings"].includes(savedSection)) {
      switchSection(savedSection);
    }

    await refreshDoctorsList();
  } catch (err) {
    console.warn("Bootstrap notice:", err);
  }
}

async function refreshDoctorsList(filterParams = {}) {
  const docs = await listDoctors(filterParams);
  renderDoctorsList(docs, async () => {
    try {
      if (!currentCompletedSession) {
        alert("Please complete the cognitive screening test session first before sharing your report with a doctor.");
        return;
      }
      if (!currentReport) {
        currentReport = await createSessionReport(currentCompletedSession.id);
      }
      currentReport = await createReportShareLink(currentReport.id, "whatsapp");
      const shareUrl = `${window.location.origin}/public/reports/${currentReport.share_token}`;
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(shareUrl);
        alert(`Report share link copied to clipboard for doctor!\n\nLink: ${shareUrl}`);
      } else {
        alert(`Report share link for doctor:\n\n${shareUrl}`);
      }
    } catch (err) {
      alert(err.message || "Could not generate share link.");
    }
  });
}

function clearAllTestInputsForNewSession(prompts = {}) {
  ["t1Day", "t1Date", "t1Month", "t1Season", "t1City", "t2Response", "t3Response", "t4Response", "t7Response"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    }
  );
  const pauseEl = document.getElementById("t4PauseMs");
  if (pauseEl) pauseEl.value = "0";

  ["chkClockCircle", "chkClockNumbers", "chkClockOrder", "chkClockSpacing", "chkClockTwoHands", "chkClockTimeMatch"].forEach(
    (id) => {
      const chk = document.getElementById(id);
      if (chk) chk.checked = false;
    }
  );

  if (clearClockCanvasFn) clearClockCanvasFn();
  if (resetDotGameFn) resetDotGameFn(prompts.dot_coords || null);
}

async function ensurePersonAndSessionReady(sessionMode = "baseline") {
  const rawEmail = document.getElementById("inpPersonEmail")?.value.trim().toLowerCase() || "";
  const rawName = document.getElementById("inpPersonName")?.value.trim() || currentPerson?.name || "";
  const rawAge = document.getElementById("inpPersonAge")?.value.trim() || String(currentPerson?.age || "");

  if (!rawName || !rawAge) {
    alert("Please enter the patient's Full Name and Age before starting the personalized test.");
    switchSection("home");
    document.getElementById("inpPersonName")?.focus();
    return false;
  }

  const age = Number(rawAge);
  const gender = document.getElementById("inpPersonGender")?.value || "male";
  const city = document.getElementById("inpPersonCity")?.value || "Lahore";
  const education_level = document.getElementById("inpPersonEducation")?.value || "secondary";
  const occupation = document.getElementById("inpPersonOccupation")?.value.trim() || "retired";
  const family_history_dementia = document.getElementById("inpFamilyHistory")?.value === "true";
  const symptom_duration_months = Number(document.getElementById("inpSymptomDuration")?.value || 6);

  const observed_symptoms = Array.from(document.querySelectorAll(".chk-symptom:checked")).map((el) => el.value);
  const medical_conditions = Array.from(document.querySelectorAll(".chk-condition:checked")).map((el) => el.value);

  const chkAudio = document.getElementById("chkConsentAudio")?.checked;
  if (!chkAudio) {
    alert("Please accept the consent checkbox before starting the cognitive tests.");
    return false;
  }

  const saveBtn = document.getElementById("btnSaveProfileAndStart");
  const dashBtn = document.getElementById("btnDashStartBaseline");
  const origSaveHtml = saveBtn ? saveBtn.innerHTML : "";
  const origDashHtml = dashBtn ? dashBtn.innerHTML : "";

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = "<span>⏳ Saving Profile &amp; Generating AI Test...</span>";
  }
  if (dashBtn) {
    dashBtn.disabled = true;
    dashBtn.innerHTML = "<span>⏳ Generating AI Test...</span>";
  }

  const startMs = performance.now();
  showAILoadingOverlay(true, sessionMode, rawName);
  const s1 = document.getElementById("aiLoadStep1");
  const s2 = document.getElementById("aiLoadStep2");
  const s3 = document.getElementById("aiLoadStep3");
  if (s1) s1.classList.add("active");
  if (s2) s2.classList.remove("active");
  if (s3) s3.classList.remove("active");

  try {
    // If user entered an email on the setup form and isn't already editing their active profile, check or create account by email
    const currentEmail = localStorage.getItem("yaadasht_caregiver_email") || "";
    if (rawEmail && rawEmail !== currentEmail.toLowerCase()) {
      const emailRes = await emailAccessUser({
        email: rawEmail,
        mode: "register",
        full_name: rawName,
      });
      setAuthToken(emailRes.access_token);
      localStorage.setItem("yaadasht_caregiver_email", rawEmail);
      localStorage.setItem("yaadasht_caregiver_pass", "password123");

      // If this email is ALREADY in the database with a saved person profile, load their existing profile & tests!
      if (emailRes.already_registered && emailRes.person) {
        currentPerson = emailRes.person;
        populatePersonForm(currentPerson);
        const existingSessions = await listSessions(currentPerson.id);
        renderHomePatientDashboard(currentPerson, existingSessions || []);
        alert(
          `Welcome back! "${rawEmail}" is already registered in the database.\nYour saved profile (${currentPerson.name}) and ${existingSessions.length} test session(s) have been loaded.`
        );
        switchSection("home");
        return false;
      }
    }

    currentPerson = await createOrUpdatePerson(
      {
        name: rawName,
        age,
        gender,
        city,
        education_level,
        occupation,
        living_situation: "with_family",
        family_history_dementia,
        medical_conditions,
        observed_symptoms,
        symptom_duration_months,
      },
      currentPerson?.id || null
    );
    saveFormDraftToStorage();
    if (s2) s2.classList.add("active");

    await grantConsent(currentPerson.id, "audio");
    await grantConsent(currentPerson.id, "data_processing");
    await grantConsent(currentPerson.id, "report_sharing");
    await grantConsent(currentPerson.id, "document_upload");

    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = `${currentPerson.name} (${currentPerson.age}y, ${currentPerson.city})`;
    const onboardBadge = document.getElementById("onboardStatusBadge");
    if (onboardBadge) onboardBadge.textContent = "Saved ✓";

    currentSession = await startSession(currentPerson.id, sessionMode);
    sessionStartTimeMs = Date.now();
    if (s3) s3.classList.add("active");

    const elapsed = performance.now() - startMs;
    if (elapsed < 1100) {
      await new Promise((r) => setTimeout(r, 1100 - elapsed));
    }

    const prompts = currentSession.item_prompts || {};
    clearAllTestInputsForNewSession(prompts);
    applySessionPromptsToUI(currentSession);
    renderActiveTestStep(1, prompts);

    try {
      const allSessions = await listSessions(currentPerson.id);
      renderHomePatientDashboard(currentPerson, allSessions || []);
    } catch {
      renderHomePatientDashboard(currentPerson, [currentSession]);
    }

    return true;
  } catch (err) {
    alert(err.message || "Error saving profile and generating test.");
    return false;
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = origSaveHtml || "<span>Save Profile &amp; Generate AI Test &rarr;</span>";
    }
    if (dashBtn) {
      dashBtn.disabled = false;
      dashBtn.innerHTML = origDashHtml || "<span>🧠 Start AI Test</span>";
    }
    showAILoadingOverlay(false);
  }
}

function initClockCanvas() {
  const canvas = document.getElementById("clockCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  function getCanvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    return {
      x: Math.round(clientX - rect.left),
      y: Math.round(clientY - rect.top),
      t: Date.now(),
    };
  }

  const startDraw = (e) => {
    e.preventDefault();
    const pt = getCanvasCoords(e);
    currentStroke = [pt];
    ctx.beginPath();
    ctx.moveTo(pt.x, pt.y);
    ctx.strokeStyle = "#044e3a";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
  };

  const moveDraw = (e) => {
    if (!currentStroke) return;
    e.preventDefault();
    const pt = getCanvasCoords(e);
    currentStroke.push(pt);
    ctx.lineTo(pt.x, pt.y);
    ctx.stroke();
  };

  const endDraw = () => {
    if (currentStroke && currentStroke.length > 1) {
      clockStrokes.push(currentStroke);
    }
    currentStroke = null;
  };

  canvas.addEventListener("mousedown", startDraw);
  canvas.addEventListener("mousemove", moveDraw);
  window.addEventListener("mouseup", endDraw);

  canvas.addEventListener("touchstart", startDraw, { passive: false });
  canvas.addEventListener("touchmove", moveDraw, { passive: false });
  window.addEventListener("touchend", endDraw);

  clearClockCanvasFn = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    clockStrokes = [];
  };

  document.getElementById("btnClearClockCanvas")?.addEventListener("click", clearClockCanvasFn);
}

function initDotConnectingGame() {
  const container = document.getElementById("dotGameBoard");
  if (!container) return;

  const progressEl = document.getElementById("dotGameProgress");
  const timeEl = document.getElementById("dotGameTime");
  const errEl = document.getElementById("dotGameErrors");

  const defaultCoords = [
    { x: 30, y: 35 }, { x: 80, y: 70 }, { x: 140, y: 30 },
    { x: 210, y: 65 }, { x: 270, y: 35 }, { x: 320, y: 85 },
    { x: 330, y: 155 }, { x: 260, y: 195 }, { x: 190, y: 160 },
    { x: 130, y: 200 }, { x: 70, y: 155 }, { x: 25, y: 110 },
  ];
  let activeCoords = defaultCoords;

  function resetGame(customCoords = null) {
    if (Array.isArray(customCoords) && customCoords.length === 12) {
      activeCoords = customCoords;
    }
    dotNextExpected = 1;
    dotStartTime = null;
    dotErrors = 0;
    dotDurationSec = 120.0;
    container.innerHTML = "";

    if (progressEl) progressEl.textContent = "0 / 12";
    if (timeEl) timeEl.textContent = "0.0s";
    if (errEl) errEl.textContent = "0";

    activeCoords.forEach((coord, idx) => {
      const num = idx + 1;
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "dot-btn";
      dot.textContent = String(num);
      dot.style.left = `${coord.x}px`;
      dot.style.top = `${coord.y}px`;
      dot.dataset.dotNum = String(num);

      dot.addEventListener("click", () => {
        if (!dotStartTime) {
          dotStartTime = performance.now();
        }
        if (num === dotNextExpected) {
          dot.classList.add("connected");
          dotNextExpected += 1;
          const completedCount = dotNextExpected - 1;
          if (progressEl) progressEl.textContent = `${completedCount} / 12`;

          const now = performance.now();
          const elapsed = dotStartTime ? ((now - dotStartTime) / 1000).toFixed(1) : "0.0";
          dotDurationSec = Number(elapsed);
          if (timeEl) timeEl.textContent = `${elapsed}s`;

          if (dotNextExpected > 12) {
            if (timeEl) timeEl.textContent = `${elapsed}s (Done!)`;
          }
        } else if (num > dotNextExpected) {
          dotErrors += 1;
          if (errEl) errEl.textContent = String(dotErrors);
          dot.classList.add("error");
          setTimeout(() => dot.classList.remove("error"), 400);
        }
      });

      container.appendChild(dot);
    });
  }

  resetDotGameFn = resetGame;
  document.getElementById("btnResetDotGame")?.addEventListener("click", () => resetGame());
  resetGame();
}

async function saveCurrentStepResult(stepNum) {
  if (!currentSession) {
    const ok = await ensurePersonAndSessionReady("baseline");
    if (!ok) return false;
  }

  let payload = {};

  if (stepNum === 1) {
    payload = {
      test_number: 1,
      test_type: "orientation",
      answers: {
        day: document.getElementById("t1Day")?.value || "",
        date: document.getElementById("t1Date")?.value || "",
        month: document.getElementById("t1Month")?.value || "",
        season: document.getElementById("t1Season")?.value || "",
        city: document.getElementById("t1City")?.value || "",
      },
      raw_response: `${document.getElementById("t1Day")?.value || ""} ${document.getElementById("t1Date")?.value || ""} ${document.getElementById("t1Month")?.value || ""} ${document.getElementById("t1Season")?.value || ""} ${document.getElementById("t1City")?.value || ""}`.trim(),
      audio_path: `audio/${currentSession.id}_test1.webm`,
    };
  } else if (stepNum === 2) {
    payload = {
      test_number: 2,
      test_type: "word_recall_immediate",
      raw_response: document.getElementById("t2Response")?.value || "",
      audio_path: `audio/${currentSession.id}_test2.webm`,
    };
  } else if (stepNum === 3) {
    payload = {
      test_number: 3,
      test_type: "verbal_fluency_animals",
      raw_response: document.getElementById("t3Response")?.value || "",
      duration_seconds: 60.0,
      audio_path: `audio/${currentSession.id}_test3.webm`,
    };
  } else if (stepNum === 4) {
    const descText = document.getElementById("t4Response")?.value || "";
    const pauseMs = Number(document.getElementById("t4PauseMs")?.value || 0);
    let aiMarkers = [];
    try {
      if (descText.trim()) {
        const aiStory = await evaluatePictureStoryAI(descText);
        if (aiStory && Array.isArray(aiStory.clinical_markers)) {
          aiMarkers = aiStory.clinical_markers;
        }
      }
    } catch {}

    payload = {
      test_number: 4,
      test_type: "picture_story",
      raw_response: descText,
      answers: {
        pause_ms: pauseMs,
        ai_markers: aiMarkers,
      },
      audio_path: `audio/${currentSession.id}_test4.webm`,
    };
  } else if (stepNum === 5) {
    payload = {
      test_number: 5,
      test_type: "clock_drawing",
      answers: {
        checklist: {
          closed_circle: Boolean(document.getElementById("chkClockCircle")?.checked),
          twelve_numbers: Boolean(document.getElementById("chkClockNumbers")?.checked),
          correct_order: Boolean(document.getElementById("chkClockOrder")?.checked),
          correct_spacing: Boolean(document.getElementById("chkClockSpacing")?.checked),
          two_hands: Boolean(document.getElementById("chkClockTwoHands")?.checked),
          hands_match_time: Boolean(document.getElementById("chkClockTimeMatch")?.checked),
        },
      },
      stroke_data: { strokes: clockStrokes },
      drawing_path: `drawings/${currentSession.id}_clock.png`,
    };
  } else if (stepNum === 6) {
    const connectedDotsCount = Math.min(12, dotNextExpected - 1);
    payload = {
      test_number: 6,
      test_type: "dot_connecting",
      answers: {
        connected_dots: connectedDotsCount,
        errors: dotErrors,
      },
      duration_seconds: dotDurationSec || 42.0,
    };
  } else if (stepNum === 7) {
    payload = {
      test_number: 7,
      test_type: "word_recall_delayed",
      raw_response: document.getElementById("t7Response")?.value || "",
      audio_path: `audio/${currentSession.id}_test7.webm`,
    };
  }

  const res = await submitTestResult(currentSession.id, payload);
  const indicator = document.getElementById("sessionSaveIndicator");
  if (indicator) indicator.textContent = `Test ${stepNum} Saved (${res.score}/100) ✓`;

  if (res.emergency_detected) {
    showEmergencyBanner({
      emergency_detected: true,
      message: "An urgent safety phrase was detected during the test response.",
      resources: res.emergency_resources,
    });
  }
  return true;
}

function getDynamicSpeechPrompt(stepNum) {
  const prompts = currentSession?.item_prompts || {};
  if (stepNum === 1) {
    const orientPairs = [
      { inputId: "t1Day", labelId: "lblT1Day" },
      { inputId: "t1Date", labelId: "lblT1Date" },
      { inputId: "t1Month", labelId: "lblT1Month" },
      { inputId: "t1Season", labelId: "lblT1Season" },
      { inputId: "t1City", labelId: "lblT1City" },
    ];
    for (const pair of orientPairs) {
      const inp = document.getElementById(pair.inputId);
      const lbl = document.getElementById(pair.labelId);
      if (inp && !inp.value.trim() && lbl) {
        inp.focus();
        return lbl.textContent.trim();
      }
    }
    const firstLbl = document.getElementById("lblT1Day");
    return firstLbl ? firstLbl.textContent.trim() : null;
  }
  if (stepNum === 2 && prompts.words_en) {
    return `Listen carefully to these five words: ${prompts.words_en.join(", ")}. Please repeat them back into the microphone in any order.`;
  }
  if (stepNum === 3 && prompts.fluency_prompt) {
    return prompts.fluency_prompt;
  }
  if (stepNum === 4 && prompts.picture_story_prompt) {
    return prompts.picture_story_prompt;
  }
  if (stepNum === 5 && prompts.clock_target_time) {
    return `Draw a clock face on the canvas with all twelve numbers, and set the hands to show ${prompts.clock_target_time}.`;
  }
  if (stepNum === 6 && prompts.test6_instruction) {
    return prompts.test6_instruction;
  }
  if (stepNum === 7 && prompts.test7_instruction) {
    return prompts.test7_instruction;
  }
  return null;
}

function handleStepTransition(newStep) {
  stopQuestionAudio();
  currentStep = newStep;
  renderActiveTestStep(currentStep);
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = (err) => reject(err);
    reader.readAsDataURL(file);
  });
}

function initEventListeners() {
  [
    "inpPersonEmail",
    "inpPersonName",
    "inpPersonAge",
    "inpPersonGender",
    "inpPersonCity",
    "inpPersonEducation",
    "inpPersonOccupation",
    "inpFamilyHistory",
    "inpSymptomDuration",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", saveFormDraftToStorage);
      el.addEventListener("change", saveFormDraftToStorage);
    }
  });
  document.querySelectorAll(".chk-symptom, .chk-condition").forEach((chk) => {
    chk.addEventListener("change", saveFormDraftToStorage);
  });

  // Quick Email Login for Returning Users (Loads Saved Profile & Tests from MongoDB)
  document.getElementById("btnQuickEmailLogin")?.addEventListener("click", async () => {
    const email = document.getElementById("inpQuickLoginEmail")?.value.trim().toLowerCase() || "";
    if (!email || !email.includes("@")) {
      alert("Please enter your registered email address to login.");
      document.getElementById("inpQuickLoginEmail")?.focus();
      return;
    }
    const btn = document.getElementById("btnQuickEmailLogin");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ Loading...";
    }
    showAILoadingOverlay(true, "baseline", email.split("@")[0]);
    try {
      const startMs = performance.now();
      const res = await emailAccessUser({ email, mode: "login" });
      setAuthToken(res.access_token);
      localStorage.setItem("yaadasht_caregiver_email", email);
      localStorage.setItem("yaadasht_caregiver_pass", "password123");

      const elapsed = performance.now() - startMs;
      if (elapsed < 900) {
        await new Promise((r) => setTimeout(r, 900 - elapsed));
      }

      if (res.person && res.person.id) {
        currentPerson = res.person;
        populatePersonForm(res.person);
        const sessions = await listSessions(res.person.id);
        renderHomePatientDashboard(res.person, sessions || []);
      } else {
        await bootstrapAccountAndData();
      }
      switchSection("home");
    } catch (err) {
      alert(err.message || "No account found with this email. Please fill the New Patient Setup form below.");
    } finally {
      showAILoadingOverlay(false);
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = "Login &rarr;";
      }
    }
  });

  // Navigation Links
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const targetSec = btn.dataset.section;
      if (targetSec === "session" && !currentSession) {
        const rawName = document.getElementById("inpPersonName")?.value.trim() || currentPerson?.name || "";
        const rawAge = document.getElementById("inpPersonAge")?.value.trim() || String(currentPerson?.age || "");
        if (rawName && rawAge) {
          await ensurePersonAndSessionReady("baseline");
        }
      }
      switchSection(targetSec);
    });
  });

  document.querySelectorAll("[data-nav-target]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      switchSection(btn.dataset.navTarget);
    });
  });

  document.getElementById("btnToggleSpeechOutput")?.addEventListener("click", () => {
    voiceGuideActive = !voiceGuideActive;
    const pill = document.getElementById("btnToggleSpeechOutput");
    const txt = document.getElementById("voiceGuideStatusText");
    if (voiceGuideActive) {
      if (pill) pill.classList.remove("muted");
      if (txt) txt.textContent = "🔊 Voice: On";
    } else {
      if (pill) pill.classList.add("muted");
      if (txt) txt.textContent = "🔇 Voice: Off";
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    }
  });

  document.getElementById("btnGlobalMicToggle")?.addEventListener("click", () => {
    toggleSpeechRecognition(null);
  });

  document.querySelectorAll(".btn-field-mic").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fieldId = btn.dataset.voiceField;
      if (isListening && activeMicField === fieldId) {
        toggleSpeechRecognition(null);
      } else {
        toggleSpeechRecognition(fieldId);
      }
    });
  });

  document.getElementById("btnSpeakAllOrientation")?.addEventListener("click", () => {
    activeMicField = null;
    toggleSpeechRecognition(null);
  });

  document.getElementById("btnExaminerSpeakWords")?.addEventListener("click", () => {
    const chips = Array.from(document.querySelectorAll("#t2WordChips .word-chip"))
      .map((c) => c.textContent.trim())
      .join(". ");
    const textToSpeak = chips || "Garden. Kettle. Mirror. Bangle. Pillow.";
    speakInstruction(2, `Listen carefully to these five words: ${textToSpeak}`);
  });

  document.getElementById("btnDismissSafety")?.addEventListener("click", () => {
    document.getElementById("safetyBanner")?.classList.add("hidden");
  });

  // Start Personalized Baseline 7-Test Session from Home
  const startBaselineFlow = async () => {
    const ok = await ensurePersonAndSessionReady("baseline");
    if (!ok) return;
    handleStepTransition(1);
    switchSection("session");
  };
  document.getElementById("btnQuickStartSession")?.addEventListener("click", startBaselineFlow);
  document.getElementById("btnSaveProfileAndStart")?.addEventListener("click", startBaselineFlow);
  document.getElementById("btnDashStartBaseline")?.addEventListener("click", startBaselineFlow);

  // Edit / Cancel Patient Profile toggle between Logged-In Hub and Guest Form View
  document.getElementById("btnEditPatientProfile")?.addEventListener("click", () => {
    const loggedView = document.getElementById("homeLoggedInView");
    const guestView = document.getElementById("homeGuestView");
    if (loggedView) {
      loggedView.classList.add("hidden");
      loggedView.style.display = "none";
    }
    if (guestView) {
      guestView.classList.remove("hidden");
      guestView.style.display = "";
    }
    document.getElementById("returningUserLoginBox")?.classList.add("hidden");
    document.getElementById("btnCancelEditProfile")?.classList.remove("hidden");
  });
  document.getElementById("btnCancelEditProfile")?.addEventListener("click", () => {
    if (currentPerson && (currentPerson.id || currentPerson.name)) {
      renderHomePatientDashboard(currentPerson, []);
    }
  });

  // One-Click Logout Handler (Header & Caregiver Hub)
  const handleLogout = async () => {
    stopQuestionAudio();
    setAuthToken(null);
    localStorage.removeItem("yaadasht_caregiver_email");
    localStorage.removeItem("yaadasht_caregiver_pass");
    localStorage.removeItem("yaadasht_person_draft");
    localStorage.removeItem("yaadasht_saved_person");
    localStorage.removeItem("yaadasht_active_section");
    localStorage.removeItem("yaadasht_active_step");

    currentPerson = null;
    currentSession = null;
    currentCompletedSession = null;
    currentReport = null;

    ["inpPersonEmail", "inpPersonName", "inpPersonAge", "inpPersonOccupation", "inpQuickLoginEmail"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    document.querySelectorAll(".chk-symptom, .chk-condition").forEach((chk) => {
      chk.checked = false;
    });

    document.getElementById("returningUserLoginBox")?.classList.remove("hidden");
    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = "Sign In";
    const onboardBadge = document.getElementById("onboardStatusBadge");
    if (onboardBadge) onboardBadge.textContent = "AI Personalized";

    renderHomePatientDashboard(null, []);
    switchSection("home");

    try {
      const suffix = Math.floor(Math.random() * 90000 + 10000);
      const guestEmail = `caregiver_${suffix}@yaadasht.local`;
      const guestPass = "password123";
      localStorage.setItem("yaadasht_caregiver_email", guestEmail);
      localStorage.setItem("yaadasht_caregiver_pass", guestPass);
      const signupRes = await signupUser({
        email: guestEmail,
        password: guestPass,
        full_name: "Caregiver Account",
        language: "en",
      });
      setAuthToken(signupRes.access_token);
    } catch {}
  };

  document.getElementById("btnHeaderLogout")?.addEventListener("click", handleLogout);
  document.getElementById("btnLogoutProfile")?.addEventListener("click", handleLogout);

  // Clean Account Login / Register Modal Controls
  const openAuthModal = () => {
    const emailInp = document.getElementById("inpAuthEmail");
    const savedEmail = localStorage.getItem("yaadasht_caregiver_email") || "";
    if (emailInp && !emailInp.value && !savedEmail.endsWith("@yaadasht.local")) {
      emailInp.value = savedEmail;
    }
    document.getElementById("authModalBackdrop")?.classList.remove("hidden");
  };
  document.getElementById("btnOpenAuthModal")?.addEventListener("click", openAuthModal);
  document.getElementById("btnCloseAuthModal")?.addEventListener("click", () => {
    document.getElementById("authModalBackdrop")?.classList.add("hidden");
  });

  const handleAuthSubmit = async (mode) => {
    const email = document.getElementById("inpAuthEmail")?.value.trim().toLowerCase() || "";
    const password = document.getElementById("inpAuthPassword")?.value || "password123";
    if (!email || !email.includes("@")) {
      alert("Please enter a valid email address.");
      return;
    }
    const loginBtn = document.getElementById("btnSubmitLogin");
    const signupBtn = document.getElementById("btnSubmitSignup");
    if (loginBtn) {
      loginBtn.disabled = true;
      loginBtn.textContent = mode === "login" ? "⏳ Signing In..." : "Sign In";
    }
    if (signupBtn) {
      signupBtn.disabled = true;
      signupBtn.textContent = mode === "signup" ? "⏳ Creating..." : "Create Account";
    }
    try {
      const res = await emailAccessUser({ email, mode: mode === "login" ? "login" : "register" });
      setAuthToken(res.access_token);
      localStorage.setItem("yaadasht_caregiver_email", email);
      localStorage.setItem("yaadasht_caregiver_pass", password);
      localStorage.removeItem("yaadasht_person_draft");
      currentPerson = null;
      currentSession = null;
      currentCompletedSession = null;
      document.getElementById("authModalBackdrop")?.classList.add("hidden");
      showAILoadingOverlay(true, "baseline", email.split("@")[0]);
      try {
        await bootstrapAccountAndData();
      } finally {
        showAILoadingOverlay(false);
      }
      if (!currentPerson) {
        renderHomePatientDashboard(null, []);
        const badge = document.getElementById("activePersonBadge");
        if (badge) badge.textContent = email.split("@")[0];
      }
    } catch (err) {
      alert(err.message || "Authentication failed. Please check your email.");
    } finally {
      if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.textContent = "Sign In";
      }
      if (signupBtn) {
        signupBtn.disabled = false;
        signupBtn.textContent = "Create Account";
      }
    }
  };
  document.getElementById("btnSubmitLogin")?.addEventListener("click", () => handleAuthSubmit("login"));
  document.getElementById("btnSubmitSignup")?.addEventListener("click", () => handleAuthSubmit("signup"));

  // Standalone New Test Button inside the 7 Tests screen
  document.getElementById("btnRegenerateAISession")?.addEventListener("click", async () => {
    const btn = document.getElementById("btnRegenerateAISession");
    if (btn) btn.textContent = "⏳ Generating...";
    try {
      const mode = currentSession?.session_mode || "baseline";
      const ok = await ensurePersonAndSessionReady(mode);
      if (ok) {
        handleStepTransition(currentStep);
      }
    } finally {
      if (btn) btn.textContent = "🔄 New Test";
    }
  });

  // Play Back User's Recorded Voice Clip
  document.getElementById("btnPlayRecordedVoice")?.addEventListener("click", () => {
    if (!lastRecordedAudioUrl) return;
    if (playbackAudioObj) {
      playbackAudioObj.pause();
      playbackAudioObj = null;
    }
    playbackAudioObj = new Audio(lastRecordedAudioUrl);
    playbackAudioObj.play().catch((err) => console.warn("Audio playback error:", err));
  });

  // Start Post-Visit AI Adaptive Follow-Up Session
  const startAdaptiveFlow = async () => {
    const ok = await ensurePersonAndSessionReady("post_visit_adaptive");
    if (!ok) return;
    handleStepTransition(1);
    switchSection("session");
  };
  document.getElementById("btnStartAdaptiveFollowupTest")?.addEventListener("click", startAdaptiveFlow);
  document.getElementById("btnDashStartAdaptive")?.addEventListener("click", startAdaptiveFlow);

  document.querySelectorAll("#testProgressDots .step-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      handleStepTransition(Number(pill.dataset.step));
    });
  });

  document.getElementById("btnPlayQuestion")?.addEventListener("click", () => {
    speakInstruction(currentStep, getDynamicSpeechPrompt(currentStep), 2);
  });

  document.getElementById("btnPauseQuestion")?.addEventListener("click", () => {
    pauseOrResumeQuestion();
  });

  document.getElementById("btnStopQuestion")?.addEventListener("click", () => {
    stopQuestionAudio();
  });

  document.querySelectorAll(".btn-play-subq").forEach((btn) => {
    btn.addEventListener("click", () => {
      const labelId = btn.getAttribute("data-subq-label");
      const labelEl = labelId ? document.getElementById(labelId) : null;
      const questionText = labelEl
        ? labelEl.textContent.replace(/^\d+\.\s*/, "").trim()
        : getDynamicSpeechPrompt(1);
      speakInstruction(1, questionText, 2);
      const grp = btn.closest(".form-group");
      const inp = grp?.querySelector("input");
      if (inp) inp.focus();
    });
  });

  document.getElementById("btnHideT2Words")?.addEventListener("click", () => {
    document.getElementById("t2WordChips")?.classList.toggle("hidden");
  });

  let t3Interval = null;
  document.getElementById("btnStartT3Timer")?.addEventListener("click", () => {
    clearInterval(t3Interval);
    let rem = 60;
    const disp = document.getElementById("t3TimerDisplay");
    if (disp) disp.textContent = "60s";

    activeMicField = "t3Response";
    toggleSpeechRecognition("t3Response");

    if (voiceGuideActive) {
      speakInstruction(3, "60 seconds started. Please begin speaking now.");
    }

    t3Interval = setInterval(() => {
      rem -= 1;
      if (disp) disp.textContent = `${rem}s`;
      if (rem <= 0) {
        clearInterval(t3Interval);
        if (voiceGuideActive) speakInstruction(3, "Time is up! You can review the words spoken.");
        toggleSpeechRecognition(null);
      }
    }, 1000);
  });

  document.getElementById("btnRunClockVisionCheck")?.addEventListener("click", async () => {
    try {
      if (!currentSession) {
        const ok = await ensurePersonAndSessionReady("baseline");
        if (!ok) return;
      }
      if (clockStrokes.length === 0) {
        alert("Please draw the clock face, numbers, and hands on the canvas first before running AI Vision analysis.");
        return;
      }
      const canvas = document.getElementById("clockCanvas");
      const dataUri = canvas ? canvas.toDataURL("image/png") : "";
      const targetTime = currentSession?.item_prompts?.clock_target_time || "11:10";

      let chk = null;
      let observations = "";
      try {
        if (dataUri) {
          const aiRes = await evaluateClockVisionAI(dataUri, targetTime, { strokes: clockStrokes });
          if (aiRes && aiRes.checklist) {
            chk = aiRes.checklist;
            observations = aiRes.observations || "";
          }
        }
      } catch (e) {
        console.warn("AI vision fallback:", e);
      }

      if (!chk) {
        const res = await runClockCheck(currentSession.id, {
          target_time: targetTime,
          stroke_data: { strokes: clockStrokes },
        });
        chk = res.checklist;
      }

      const c1 = document.getElementById("chkClockCircle");
      if (c1) c1.checked = !!chk.closed_circle;
      const c2 = document.getElementById("chkClockNumbers");
      if (c2) c2.checked = !!chk.twelve_numbers;
      const c3 = document.getElementById("chkClockOrder");
      if (c3) c3.checked = !!chk.correct_order;
      const c4 = document.getElementById("chkClockSpacing");
      if (c4) c4.checked = !!chk.correct_spacing;
      const c5 = document.getElementById("chkClockTwoHands");
      if (c5) c5.checked = !!chk.two_hands;
      const c6 = document.getElementById("chkClockTimeMatch");
      if (c6) c6.checked = !!chk.hands_match_time;

      alert(`Clock Vision Analysis Complete ✓${observations ? "\n\n" + observations : ""}`);
    } catch (err) {
      alert("Vision check notice: " + (err.message || err));
    }
  });

  document.getElementById("btnPrevTest")?.addEventListener("click", () => {
    if (currentStep > 1) {
      handleStepTransition(currentStep - 1);
    }
  });

  document.getElementById("btnSaveAndNextTest")?.addEventListener("click", async () => {
    try {
      const saved = await saveCurrentStepResult(currentStep);
      if (!saved) return;

      if (currentStep < 7) {
        handleStepTransition(currentStep + 1);
      } else {
        const elapsedSessionSec = Math.max(60, Math.round((Date.now() - sessionStartTimeMs) / 1000));
        currentCompletedSession = await completeSession(currentSession.id, elapsedSessionSec);
        currentReport = null;
        const allSessions = await listSessions(currentPerson.id);
        renderCompletedSessionResult(currentCompletedSession, allSessions);
        renderHomePatientDashboard(currentPerson, allSessions);
        switchSection("result");
        if (voiceGuideActive) {
          speakInstruction(7, "All seven cognitive tests completed. Your plain-language screening outcome is ready.");
        }
      }
    } catch (err) {
      alert(err.message || "Error saving test result.");
    }
  });

  document.getElementById("btnGeneratePdfReport")?.addEventListener("click", async () => {
    try {
      if (!currentCompletedSession) {
        alert("Please complete the 7 cognitive tests first.");
        return;
      }
      if (!currentReport) {
        currentReport = await createSessionReport(
          currentCompletedSession.id,
          "Completed guided 7-test home screening session."
        );
      }
      const blob = await downloadReportPdfBlob(currentReport.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `yaadasht_report_${currentCompletedSession.id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.message || "Unable to download PDF report.");
    }
  });

  document.getElementById("btnShareReportLink")?.addEventListener("click", async () => {
    try {
      if (!currentCompletedSession) {
        alert("Please complete a session first.");
        return;
      }
      if (!currentReport) {
        currentReport = await createSessionReport(currentCompletedSession.id);
      }
      currentReport = await createReportShareLink(currentReport.id, "whatsapp");
      const shareUrl = `${window.location.origin}/public/reports/${currentReport.share_token}`;
      const urlText = document.getElementById("shareLinkUrlText");
      if (urlText) urlText.textContent = shareUrl;
      document.getElementById("shareLinkBox")?.classList.remove("hidden");
      document.getElementById("btnRevokeShareLink")?.classList.remove("hidden");
    } catch (err) {
      alert(err.message);
    }
  });

  document.getElementById("btnRevokeShareLink")?.addEventListener("click", async () => {
    if (!currentReport) return;
    await revokeReportShareLink(currentReport.id);
    document.getElementById("shareLinkBox")?.classList.add("hidden");
    document.getElementById("btnRevokeShareLink")?.classList.add("hidden");
  });

  document.getElementById("btnSearchDoctors")?.addEventListener("click", async () => {
    const city = document.getElementById("filterDocCity")?.value || "";
    const specialty = document.getElementById("filterDocSpecialty")?.value || "";
    const mode = document.getElementById("filterDocMode")?.value || "";
    await refreshDoctorsList({ city, specialty, mode });
  });

  let latestDocId = null;
  document.getElementById("btnUploadDoctorDoc")?.addEventListener("click", async () => {
    try {
      if (!currentPerson) {
        const ok = await ensurePersonAndSessionReady("baseline");
        if (!ok) return;
      }
      const findingsText = document.getElementById("inpDocFindings")?.value.trim() || "";
      const followupDays = Number(document.getElementById("inpFollowupDays")?.value || 30);
      const fileInput = document.getElementById("inpDoctorReportFile");
      const file = fileInput?.files?.[0] || null;

      let fileDataUri = null;
      if (file && file.type.startsWith("image/")) {
        fileDataUri = await readFileAsDataURL(file);
      }

      if (!findingsText && !file) {
        alert("Please enter the doctor's findings/prescription text or select a prescription image file.");
        return;
      }

      const doc = await uploadDoctorDocument({
        person_id: currentPerson.id,
        file_path: file ? `documents/${Date.now()}_${file.name}` : `documents/visit_${Date.now()}.txt`,
        file_type: file && file.Name?.endsWith(".pdf") ? "pdf" : "image",
        findings_text: findingsText || (file ? `Uploaded prescription file: ${file.name}` : ""),
        followup_interval_days: followupDays,
        watch_domains: ["memory", "orientation", "planning"],
      });
      latestDocId = doc.id;

      const extracted = await extractPrescriptionAI(findingsText, fileDataUri);
      if (extracted) {
        if (extracted.findings_summary && !findingsText) {
          const fEl = document.getElementById("inpDocFindings");
          if (fEl) fEl.value = extracted.findings_summary;
        }
        if (Array.isArray(extracted.medicines) && extracted.medicines.length > 0) {
          const m = extracted.medicines[0];
          const medName = document.getElementById("inpMedName");
          if (medName && m.name) medName.value = m.name;
          const medDose = document.getElementById("inpMedDose");
          if (medDose && m.dose) medDose.value = m.dose;
          const medFreq = document.getElementById("inpMedFreq");
          if (medFreq && m.frequency_per_day) medFreq.value = m.frequency_per_day;
          if (Array.isArray(m.reminder_times) && m.reminder_times[0]) {
            const medTime = document.getElementById("inpMedTime");
            if (medTime) medTime.value = m.reminder_times[0];
          }
          alert(
            `Doctor report saved & AI extracted medicine candidate (${m.name} ${m.dose}).\nPlease verify against your paper prescription and tick the confirmation checkbox before saving.`
          );
          return;
        }
      }

      alert("Doctor report saved privately and follow-up retest scheduled ✓");
    } catch (err) {
      alert(err.message || "Error uploading doctor report.");
    }
  });

  const refreshMeds = async () => {
    if (!currentPerson) return;
    const meds = await listMedicines(currentPerson.id);
    renderConfirmedMedicines(meds, async (medId, statusVal) => {
      const logRes = await logMedicineDose({
        medicine_id: medId,
        scheduled_time: "21:00",
        status: statusVal,
      });
      const fb = document.getElementById("medicineLogFeedback");
      if (fb) {
        fb.textContent = logRes.gentle_reminder
          ? `Logged as ${statusVal}: ${logRes.gentle_reminder}`
          : `Dose marked as TAKEN ✓ (${new Date(logRes.logged_at).toLocaleTimeString()})`;
      }
    });
  };

  document.getElementById("btnSaveConfirmedMedicine")?.addEventListener("click", async () => {
    try {
      if (!currentPerson) {
        const ok = await ensurePersonAndSessionReady("baseline");
        if (!ok) return;
      }
      const medName = document.getElementById("inpMedName")?.value.trim() || "";
      const medDose = document.getElementById("inpMedDose")?.value.trim() || "";
      if (!medName || !medDose) {
        alert("Please enter the prescribed medicine name and dose from your doctor's prescription.");
        return;
      }
      const confirmed = document.getElementById("chkConfirmMedicine")?.checked;
      await createConfirmedMedicine({
        person_id: currentPerson.id,
        document_id: latestDocId,
        name: medName,
        dose: medDose,
        frequency_per_day: Number(document.getElementById("inpMedFreq")?.value || 1),
        reminder_times: [document.getElementById("inpMedTime")?.value || "21:00"],
        instructions: "Confirmed against doctor prescription report",
        confirmed_by_user: !!confirmed,
      });
      await refreshMeds();
    } catch (err) {
      alert(err.message);
    }
  });

  document.getElementById("btnGenerateMonthlySummary")?.addEventListener("click", async () => {
    try {
      if (!currentPerson) {
        const ok = await ensurePersonAndSessionReady("baseline");
        if (!ok) return;
      }
      const summary = await generateMonthlySummary({
        person_id: currentPerson.id,
        user_notes: ["Monthly post-visit adherence and cognitive retest review."],
      });
      const box = document.getElementById("monthlySummaryBox");
      const txt = document.getElementById("monthlySummaryText");
      if (box && txt) {
        txt.textContent = `Adherence: ${summary.adherence_pct}% (Taken: ${summary.taken_count}, Skipped: ${summary.skipped_count}, Missed: ${summary.missed_count}) · Score Change: ${summary.score_change ?? "N/A"} · ${summary.disclaimer}`;
        box.classList.remove("hidden");
      }
    } catch (err) {
      alert(err.message);
    }
  });

  document.getElementById("btnTestSafetyPhrase")?.addEventListener("click", async () => {
    const text = document.getElementById("inpSafetyTestPhrase")?.value || "want to die";
    const res = await runSafetyCheck(text);
    if (res.emergency_detected) {
      showEmergencyBanner(res);
    } else {
      alert("No emergency phrase detected in text.");
    }
  });

  document.getElementById("btnDeleteAllUserData")?.addEventListener("click", async () => {
    if (!currentPerson) {
      alert("No active person profile to delete.");
      return;
    }
    await deletePersonAndAllData(currentPerson.id);
    currentPerson = null;
    currentSession = null;
    currentCompletedSession = null;
    localStorage.removeItem("yaadasht_person_draft");
    localStorage.removeItem("yaadasht_saved_person");
    renderHomePatientDashboard(null, []);
    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = "Data Deleted";
    alert("All profile data, sessions, reports, and recorded files have been permanently deleted.");
    switchSection("home");
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initClockCanvas();
  initDotConnectingGame();
  initSpeechRecognition();
  drawIdleVoiceVisualizer();
  initEventListeners();
  await bootstrapAccountAndData();
});
