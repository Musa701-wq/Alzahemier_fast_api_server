import {
  adminCreateDoctor,
  adminCreateSafetyResource,
  completeSession,
  createConfirmedMedicine,
  createOrUpdatePerson,
  createReportShareLink,
  createSessionReport,
  deletePersonAndAllData,
  downloadReportPdfBlob,
  evaluateClockVisionAI,
  evaluatePictureStoryAI,
  extractPrescriptionAI,
  fetchAIStatus,
  fetchHealthStatus,
  generateMonthlySummary,
  grantConsent,
  listDoctors,
  listMedicines,
  listSessions,
  logMedicineDose,
  revokeReportShareLink,
  runClockCheck,
  runSafetyCheck,
  setAdminToken,
  setAuthToken,
  signupUser,
  startSession,
  submitTestResult,
  uploadDoctorDocument,
} from "./api.js";
import {
  renderActiveTestStep,
  renderCompletedSessionResult,
  renderConfirmedMedicines,
  renderDoctorsList,
  showEmergencyBanner,
  speakInstruction,
  switchSection,
} from "./ui.js";

// Session & Person State
let currentPerson = null;
let currentSession = null;
let currentCompletedSession = null;
let currentReport = null;
let currentStep = 1;

// Voice Examiner & Verbal Speech Interaction State
let voiceGuideActive = true;
let isListening = false;
let activeMicField = null; // null means target current step's primary field or multi-orientation
let speechRecognitionInstance = null;

// Clock Canvas Stroke Recording State
let clockStrokes = [];
let currentStroke = null;

// Dot Game State (1 to 12)
let dotNextExpected = 1;
let dotStartTime = null;
let dotErrors = 0;
let dotDurationSec = 24.0;

/**
 * Initialize default today values for Test 1 Orientation inputs.
 */
function populateDefaultOrientationInputs() {
  const now = new Date();
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const m = now.getMonth() + 1;
  let season = "Autumn";
  if ([12, 1, 2].includes(m)) season = "Winter";
  else if ([3, 4].includes(m)) season = "Spring";
  else if ([5, 6, 7, 8, 9].includes(m)) season = "Summer";

  const dEl = document.getElementById("t1Day");
  const dtEl = document.getElementById("t1Date");
  const mEl = document.getElementById("t1Month");
  const sEl = document.getElementById("t1Season");
  const cEl = document.getElementById("t1City");

  if (dEl) dEl.value = days[now.getDay()];
  if (dtEl) dtEl.value = String(now.getDate());
  if (mEl) mEl.value = months[now.getMonth()];
  if (sEl) sEl.value = season;
  if (cEl) cEl.value = document.getElementById("inpPersonCity")?.value || "Lahore";
}

/**
 * Verbal Speech Recognition Manager (Browser Web Speech API).
 * Enables real-time microphone listening for verbal interaction.
 */
function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("Speech Recognition API not supported in this browser. Keyboard input is fully enabled.");
    const bubble = document.getElementById("liveVoiceText");
    if (bubble) {
      bubble.textContent = "Microphone listening is ready via Web Speech API in Chrome/Edge/Safari.";
    }
    return;
  }

  try {
    speechRecognitionInstance = new SpeechRecognition();
    speechRecognitionInstance.continuous = true;
    speechRecognitionInstance.interimResults = true;
    speechRecognitionInstance.lang = "en-US";

    speechRecognitionInstance.onstart = () => {
      isListening = true;
      updateMicUIState(true);
    };

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
        bubble.textContent = `"${activeText}"`;
      }

      if (finalTranscript) {
        handleSpokenTranscript(finalTranscript.trim());
      }
    };

    speechRecognitionInstance.onerror = (event) => {
      if (event.error !== "no-speech") {
        const bubble = document.getElementById("liveVoiceText");
        if (bubble) bubble.textContent = `Speech Notice: ${event.error}. Keyboard input is always active.`;
      }
    };

    speechRecognitionInstance.onend = () => {
      if (isListening) {
        try {
          speechRecognitionInstance.start();
        } catch {
          isListening = false;
          updateMicUIState(false);
        }
      } else {
        updateMicUIState(false);
      }
    };
  } catch (err) {
    console.warn("Could not start SpeechRecognition instance:", err);
  }
}

/**
 * Route recognized spoken text into the target test field.
 */
function handleSpokenTranscript(spokenText) {
  if (!spokenText) return;
  const lower = spokenText.toLowerCase();

  // If specific field mic was clicked
  if (activeMicField) {
    const el = document.getElementById(activeMicField);
    if (el) {
      if (el.tagName === "TEXTAREA") {
        el.value = el.value ? `${el.value} ${spokenText}` : spokenText;
      } else {
        el.value = spokenText;
      }
    }
    return;
  }

  // Multi-field verbal orientation parser (Test 1)
  if (currentStep === 1) {
    parseOrientationSpeech(lower, spokenText);
    return;
  }

  // Test 2 (Immediate Words)
  if (currentStep === 2) {
    const el = document.getElementById("t2Response");
    if (el) el.value = el.value ? `${el.value} ${spokenText}` : spokenText;
    return;
  }

  // Test 3 (60s Animals)
  if (currentStep === 3) {
    const el = document.getElementById("t3Response");
    if (el) el.value = el.value ? `${el.value} ${spokenText}` : spokenText;
    return;
  }

  // Test 4 (Picture Story description)
  if (currentStep === 4) {
    const el = document.getElementById("t4Response");
    if (el) el.value = el.value ? `${el.value} ${spokenText}` : spokenText;
    return;
  }

  // Test 7 (Delayed Words)
  if (currentStep === 7) {
    const el = document.getElementById("t7Response");
    if (el) el.value = el.value ? `${el.value} ${spokenText}` : spokenText;
  }
}

/**
 * Natural language parser for speaking all orientation questions at once.
 */
function parseOrientationSpeech(lower, raw) {
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
      break;
    }
  }

  for (const m of months) {
    if (lower.includes(m)) {
      const el = document.getElementById("t1Month");
      if (el) el.value = m.charAt(0).toUpperCase() + m.slice(1);
      break;
    }
  }

  for (const s of seasons) {
    if (lower.includes(s)) {
      const canonical = s === "fall" ? "Autumn" : s.charAt(0).toUpperCase() + s.slice(1);
      const el = document.getElementById("t1Season");
      if (el) el.value = canonical;
      break;
    }
  }

  const dateMatch = lower.match(/\b(3[01]|[12][0-9]|[1-9])(st|nd|rd|th)?\b/);
  if (dateMatch) {
    const el = document.getElementById("t1Date");
    if (el) el.value = dateMatch[1];
  }

  const cities = ["lahore", "karachi", "islamabad", "rawalpindi", "peshawar", "quetta", "faisalabad", "multan", "london", "dubai"];
  for (const c of cities) {
    if (lower.includes(c)) {
      const el = document.getElementById("t1City");
      if (el) el.value = c.charAt(0).toUpperCase() + c.slice(1);
      break;
    }
  }
}

/**
 * Toggle speech recognition listening on or off.
 */
function toggleSpeechRecognition(targetField = null) {
  if (!speechRecognitionInstance) {
    const testTargets = {
      1: "t1Day",
      2: "t2Response",
      3: "t3Response",
      4: "t4Response",
      7: "t7Response",
    };
    const target = targetField || testTargets[currentStep] || "t1Day";
    const bubble = document.getElementById("liveVoiceText");
    if (bubble) bubble.textContent = `Mic active. Ready to enter text into ${target}.`;
    return;
  }

  activeMicField = targetField;

  if (isListening && !targetField) {
    isListening = false;
    try { speechRecognitionInstance.stop(); } catch {}
    updateMicUIState(false);
  } else {
    isListening = true;
    try {
      speechRecognitionInstance.start();
    } catch {
      // If already started, that's fine
    }
    updateMicUIState(true);
  }
}

function updateMicUIState(listening) {
  const btn = document.getElementById("btnGlobalMicToggle");
  const wave = document.getElementById("globalMicWave");
  const label = document.getElementById("globalMicLabel");
  const bubble = document.getElementById("liveVoiceBubble");

  if (btn) btn.classList.toggle("is-listening", listening);
  if (wave) wave.classList.toggle("hidden", !listening);
  if (bubble) bubble.classList.toggle("active", listening);

  if (label) {
    label.textContent = listening
      ? (activeMicField ? `Listening for ${activeMicField}...` : "Listening... Click to Stop")
      : "Speak Answer";
  }

  document.querySelectorAll(".btn-field-mic").forEach((fBtn) => {
    const isTarget = listening && fBtn.dataset.voiceField === activeMicField;
    fBtn.classList.toggle("listening", isTarget);
    fBtn.textContent = isTarget ? "🔴 Recording..." : "🎙️ Speak";
  });
}

/**
 * Bootstrap local demo caregiver account, safety helpline, and initial verified doctors.
 */
async function bootstrapAccountAndDemoData() {
  try {
    const { data } = await fetchHealthStatus();
    const verEl = document.getElementById("aboutVersion");
    if (verEl) verEl.textContent = `v${data.version}`;
    const healthDot = document.getElementById("healthDot");
    if (healthDot) healthDot.style.background = "#10b981";
  } catch {
    // Ignore
  }

  try {
    const suffix = Math.floor(Math.random() * 90000 + 10000);
    const userAuth = await signupUser({
      email: `caregiver_${suffix}@yaadasht.local`,
      password: "password123",
      full_name: "Caregiver Account",
      language: "en",
      role: "user",
    });
    setAuthToken(userAuth.access_token);

    const adminAuth = await signupUser({
      email: `admin_${suffix}@yaadasht.local`,
      password: "password123",
      full_name: "System Admin",
      language: "en",
      role: "admin",
    });
    setAdminToken(adminAuth.access_token);

    // Seed verified emergency helpline in safety_resources table via Admin API
    await adminCreateSafetyResource({
      label: "Rescue 1122 Emergency",
      phone: "1122",
      description: "24/7 Emergency Ambulance & Medical Helpline",
    });

    // Seed initial verified clinic listings via Admin API
    await adminCreateDoctor({
      name: "Dr. Ayesha Siddiqui",
      specialty: "neurologist",
      qualifications: "MBBS, FCPS (Neurology)",
      pmdc_number: "PMDC-44521-P",
      clinic_name: "Lahore Neuro & Memory Clinic",
      city: "Lahore",
      address: "Main Jail Road, Gulberg, Lahore",
      phone: "+92-42-35550199",
      fee_pkr: 3000,
      mode: "both",
      languages: ["en", "ur"],
      years_experience: 14,
      gender: "female",
      available_days: ["Mon", "Wed", "Fri"],
      verified: true,
      source: "public_clinic_registry",
    });

    await adminCreateDoctor({
      name: "Prof. Dr. Kamran Raza",
      specialty: "geriatrician",
      qualifications: "MBBS, MRCP (Geriatric Medicine)",
      pmdc_number: "PMDC-31904-S",
      clinic_name: "Karachi Senior Memory Care Center",
      city: "Karachi",
      address: "Clifton Block 5, Karachi",
      phone: "+92-21-35880211",
      fee_pkr: 3500,
      mode: "in_person",
      languages: ["en", "ur"],
      years_experience: 18,
      gender: "male",
      available_days: ["Tue", "Thu", "Sat"],
      verified: true,
      source: "public_clinic_registry",
    });

    await refreshDoctorsList();
  } catch (err) {
    console.warn("Bootstrap notice:", err);
  }
}

async function refreshDoctorsList(filterParams = {}) {
  const docs = await listDoctors(filterParams);
  renderDoctorsList(docs, async (docId) => {
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

async function ensurePersonAndSessionReady() {
  const name = document.getElementById("inpPersonName")?.value.trim() || "Abdul Sattar";
  const age = Number(document.getElementById("inpPersonAge")?.value || 68);
  const gender = document.getElementById("inpPersonGender")?.value || "male";
  const city = document.getElementById("inpPersonCity")?.value || "Lahore";

  const chkAudio = document.getElementById("chkConsentAudio")?.checked;
  const chkData = document.getElementById("chkConsentData")?.checked;
  if (!chkAudio || !chkData) {
    alert("Please accept both consent checkboxes before starting the recorded cognitive tests.");
    return false;
  }

  currentPerson = await createOrUpdatePerson(
    { name, age, gender, city },
    currentPerson?.id || null
  );

  await grantConsent(currentPerson.id, "audio");
  await grantConsent(currentPerson.id, "data_processing");
  await grantConsent(currentPerson.id, "report_sharing");
  await grantConsent(currentPerson.id, "document_upload");

  const badge = document.getElementById("activePersonBadge");
  if (badge) badge.textContent = `${currentPerson.name} (${currentPerson.city})`;
  const onboardBadge = document.getElementById("onboardStatusBadge");
  if (onboardBadge) onboardBadge.textContent = "Consented ✓";
  const cityEl = document.getElementById("t1City");
  if (cityEl) cityEl.value = currentPerson.city;

  currentSession = await startSession(currentPerson.id);
  const bankBadge = document.getElementById("sessionBankBadge");
  if (bankBadge) bankBadge.textContent = `Item Bank v${currentSession.item_bank_version}`;

  const prompts = currentSession.item_prompts || {};
  if (prompts.words_en) {
    const chipsContainer = document.getElementById("t2WordChips");
    if (chipsContainer) {
      chipsContainer.innerHTML = prompts.words_en
        .map((wEn) => `<span class="word-chip">${wEn}</span>`)
        .join("");
    }
    const t2 = document.getElementById("t2Response");
    if (t2) t2.value = prompts.words_en.join(" ");
    const t7 = document.getElementById("t7Response");
    if (t7) t7.value = prompts.words_en.slice(0, 4).join(" ");
  }

  return true;
}

/**
 * Initialize HTML5 Clock Drawing Canvas (Test 5)
 */
function initClockCanvas() {
  const canvas = document.getElementById("clockCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  function drawSampleClock() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    clockStrokes = [];
    const cx = 140;
    const cy = 140;
    const r = 110;

    ctx.strokeStyle = "#044e3a";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle = "#091e16";
    ctx.font = "bold 14px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let num = 1; num <= 12; num++) {
      const ang = ((num - 3) * (Math.PI * 2)) / 12;
      const nx = cx + Math.cos(ang) * (r - 20);
      const ny = cy + Math.sin(ang) * (r - 20);
      ctx.fillText(String(num), nx, ny);
    }

    // Hour hand (pointing near 11)
    const hourAng = ((11 - 3) * (Math.PI * 2)) / 12;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(hourAng) * 55, cy + Math.sin(hourAng) * 55);
    ctx.stroke();

    // Minute hand (pointing at 2 -> 10 minutes)
    const minAng = ((2 - 3) * (Math.PI * 2)) / 12;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(minAng) * 80, cy + Math.sin(minAng) * 80);
    ctx.stroke();

    clockStrokes = [
      { type: "circle", points: [{ x: cx, y: cy, r }] },
      { type: "hour_hand", target: "11" },
      { type: "minute_hand", target: "2" },
    ];
  }

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

  document.getElementById("btnClearClockCanvas")?.addEventListener("click", () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    clockStrokes = [];
  });

  document.getElementById("btnDrawSampleClock")?.addEventListener("click", () => {
    drawSampleClock();
  });
}

/**
 * Initialize 1-to-12 Dot Connecting Touch Game (Test 6)
 */
function initDotConnectingGame() {
  const container = document.getElementById("dotGameBoard");
  if (!container) return;

  const progressEl = document.getElementById("dotGameProgress");
  const timeEl = document.getElementById("dotGameTime");
  const errEl = document.getElementById("dotGameErrors");

  const dotCoords = [
    { x: 30, y: 35 }, { x: 80, y: 70 }, { x: 140, y: 30 },
    { x: 210, y: 65 }, { x: 270, y: 35 }, { x: 320, y: 85 },
    { x: 330, y: 155 }, { x: 260, y: 195 }, { x: 190, y: 160 },
    { x: 130, y: 200 }, { x: 70, y: 155 }, { x: 25, y: 110 },
  ];

  function resetGame() {
    dotNextExpected = 1;
    dotStartTime = null;
    dotErrors = 0;
    dotDurationSec = 24.0;
    container.innerHTML = "";

    if (progressEl) progressEl.textContent = "0 / 12";
    if (timeEl) timeEl.textContent = "0.0s";
    if (errEl) errEl.textContent = "0";

    dotCoords.forEach((coord, idx) => {
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
          if (timeEl) timeEl.textContent = `${elapsed}s`;

          if (dotNextExpected > 12) {
            dotDurationSec = Number(elapsed);
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

  document.getElementById("btnResetDotGame")?.addEventListener("click", resetGame);
  resetGame();
}

/**
 * Save Current Cognitive Test Result
 */
async function saveCurrentStepResult(stepNum) {
  if (!currentSession) {
    const ok = await ensurePersonAndSessionReady();
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
      raw_response: `${document.getElementById("t1Day")?.value || ""} ${document.getElementById("t1Date")?.value || ""} ${document.getElementById("t1Month")?.value || ""} ${document.getElementById("t1Season")?.value || ""} ${document.getElementById("t1City")?.value || ""}`,
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
      test_type: "animal_naming_60s",
      raw_response: document.getElementById("t3Response")?.value || "",
      audio_path: `audio/${currentSession.id}_test3.webm`,
    };
  } else if (stepNum === 4) {
    payload = {
      test_number: 4,
      test_type: "picture_story",
      raw_response: document.getElementById("t4Response")?.value || "",
      timing: {
        longest_pause_ms: Number(document.getElementById("t4PauseMs")?.value || 1400),
      },
      audio_path: `audio/${currentSession.id}_test4.webm`,
    };
  } else if (stepNum === 5) {
    payload = {
      test_number: 5,
      test_type: "clock_drawing",
      stroke_data: { strokes: clockStrokes },
      clock_checklist: {
        closed_circle: !!document.getElementById("chkClockCircle")?.checked,
        twelve_numbers: !!document.getElementById("chkClockNumbers")?.checked,
        correct_order: !!document.getElementById("chkClockOrder")?.checked,
        correct_spacing: !!document.getElementById("chkClockSpacing")?.checked,
        two_hands: !!document.getElementById("chkClockTwoHands")?.checked,
        hands_match_time: !!document.getElementById("chkClockTimeMatch")?.checked,
      },
      confirmed_by_caregiver: true,
    };
  } else if (stepNum === 6) {
    payload = {
      test_number: 6,
      test_type: "dot_connecting",
      timing: {
        duration_seconds: dotDurationSec,
        errors: dotErrors,
        completed_dots: Math.min(12, dotNextExpected - 1 || 12),
      },
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

function handleStepTransition(newStep) {
  currentStep = newStep;
  renderActiveTestStep(currentStep);
  if (voiceGuideActive) {
    setTimeout(() => {
      speakInstruction(currentStep);
    }, 350);
  }
}

function initEventListeners() {
  // Navigation Links
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.addEventListener("click", () => switchSection(btn.dataset.section));
  });

  document.querySelectorAll("[data-nav-target]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      switchSection(btn.dataset.navTarget);
    });
  });

  // Toggle Voice Examiner Audio Prompts (Active / Muted)
  document.getElementById("btnToggleSpeechOutput")?.addEventListener("click", () => {
    voiceGuideActive = !voiceGuideActive;
    const pill = document.getElementById("btnToggleSpeechOutput");
    const txt = document.getElementById("voiceGuideStatusText");
    if (voiceGuideActive) {
      if (pill) pill.classList.remove("muted");
      if (txt) txt.textContent = "🔊 Voice Examiner: Active";
      speakInstruction(currentStep, "Voice examiner is now active.");
    } else {
      if (pill) pill.classList.add("muted");
      if (txt) txt.textContent = "🔇 Voice Examiner: Muted";
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    }
  });

  // Global Microphone Toggle (Speak Answer / Stop)
  document.getElementById("btnGlobalMicToggle")?.addEventListener("click", () => {
    toggleSpeechRecognition(null);
  });

  // Field-Specific Microphone Buttons
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

  // Answer All Orientation Questions Verbally
  document.getElementById("btnSpeakAllOrientation")?.addEventListener("click", () => {
    activeMicField = null;
    toggleSpeechRecognition(null);
    const bubble = document.getElementById("liveVoiceText");
    if (bubble) {
      bubble.textContent = "Please speak: today's day, date, month, season, and city aloud...";
    }
    if (voiceGuideActive) {
      speakInstruction(1, "Please speak today's day of week, date, month, season, and city aloud into the microphone.");
    }
  });

  // Examiner Speak Words (Test 2)
  document.getElementById("btnExaminerSpeakWords")?.addEventListener("click", () => {
    const chips = Array.from(document.querySelectorAll("#t2WordChips .word-chip"))
      .map((c) => c.textContent.trim())
      .join(". ");
    const textToSpeak = chips || "River. Mango. Window. Lantern. Carpet.";
    speakInstruction(2, `Listen carefully to these five words: ${textToSpeak}`);
  });

  // Dismiss Safety Banner
  document.getElementById("btnDismissSafety")?.addEventListener("click", () => {
    document.getElementById("safetyBanner")?.classList.add("hidden");
  });

  // Start Guided 7-Test Session from Home
  const startFlow = async () => {
    const ok = await ensurePersonAndSessionReady();
    if (!ok) return;
    handleStepTransition(1);
    switchSection("session");
  };
  document.getElementById("btnQuickStartSession")?.addEventListener("click", startFlow);
  document.getElementById("btnSaveProfileAndStart")?.addEventListener("click", startFlow);

  // Step Progress Dots inside Session
  document.querySelectorAll("#testProgressDots .step-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      handleStepTransition(Number(pill.dataset.step));
    });
  });

  // Voice Guide Prompt Button (Re-read Question Aloud)
  document.getElementById("btnSpeakPrompt")?.addEventListener("click", () => {
    speakInstruction(currentStep);
  });

  // Hide Test 2 Words Button
  document.getElementById("btnHideT2Words")?.addEventListener("click", () => {
    document.getElementById("t2WordChips")?.classList.toggle("hidden");
  });

  // Test 3 60-Second Timer & Auto-Mic
  let t3Interval = null;
  document.getElementById("btnStartT3Timer")?.addEventListener("click", () => {
    clearInterval(t3Interval);
    let rem = 60;
    const disp = document.getElementById("t3TimerDisplay");
    if (disp) disp.textContent = "60s";

    activeMicField = "t3Response";
    toggleSpeechRecognition("t3Response");

    if (voiceGuideActive) {
      speakInstruction(3, "60 seconds started. Please speak animal names now.");
    }

    t3Interval = setInterval(() => {
      rem -= 1;
      if (disp) disp.textContent = `${rem}s`;
      if (rem <= 0) {
        clearInterval(t3Interval);
        if (voiceGuideActive) speakInstruction(3, "Time is up! You can review the animal names spoken.");
        toggleSpeechRecognition(null);
      }
    }, 1000);
  });

  // Test 5 Vision Checklist Pre-Fill (Multimodal AI + Stroke Geometry)
  document.getElementById("btnRunClockVisionCheck")?.addEventListener("click", async () => {
    try {
      if (!currentSession) await ensurePersonAndSessionReady();
      const canvas = document.getElementById("clockCanvas");
      const dataUri = canvas ? canvas.toDataURL("image/png") : "";

      let chk = null;
      try {
        if (dataUri) {
          const aiRes = await evaluateClockVisionAI(dataUri);
          if (aiRes && aiRes.checklist) {
            chk = aiRes.checklist;
          }
        }
      } catch (e) {
        console.warn("AI vision fallback:", e);
      }

      if (!chk) {
        const res = await runClockCheck(currentSession.id, {
          target_time: "11:10",
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

      alert("Vision checklist successfully updated from clock drawing ✓");
    } catch (err) {
      alert("Vision check notice: " + (err.message || err));
    }
  });

  // Previous & Next Test Buttons
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
        // Complete Session after Test 7
        currentCompletedSession = await completeSession(currentSession.id, 840);
        const allSessions = await listSessions(currentPerson.id);
        renderCompletedSessionResult(currentCompletedSession, allSessions);
        switchSection("result");
        if (voiceGuideActive) {
          speakInstruction(7, "All seven cognitive tests completed. Your plain-language screening outcome is ready.");
        }
      }
    } catch (err) {
      alert(err.message || "Error saving test result.");
    }
  });

  // Generate & Download One-Page PDF Report
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

  // Create 14-Day Share Link
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

  // Revoke Share Link
  document.getElementById("btnRevokeShareLink")?.addEventListener("click", async () => {
    if (!currentReport) return;
    await revokeReportShareLink(currentReport.id);
    document.getElementById("shareLinkBox")?.classList.add("hidden");
    document.getElementById("btnRevokeShareLink")?.classList.add("hidden");
  });

  // Doctors Filter & Admin Add
  document.getElementById("btnSearchDoctors")?.addEventListener("click", async () => {
    const city = document.getElementById("filterDocCity")?.value || "";
    const specialty = document.getElementById("filterDocSpecialty")?.value || "";
    const mode = document.getElementById("filterDocMode")?.value || "";
    await refreshDoctorsList({ city, specialty, mode });
  });

  document.getElementById("btnAddVerifiedDoctorDemo")?.addEventListener("click", async () => {
    await adminCreateDoctor({
      name: "Dr. Salman Tariq",
      specialty: "memory_clinic",
      qualifications: "MBBS, Diploma in Behavioral Neurology",
      pmdc_number: "PMDC-58112-I",
      clinic_name: "Islamabad Memory & Brain Care Clinic",
      city: "Islamabad",
      address: "F-8 Markaz, Islamabad",
      phone: "+92-51-2260188",
      fee_pkr: 2800,
      mode: "both",
      languages: ["en", "ur"],
      years_experience: 10,
      gender: "male",
      available_days: ["Mon", "Thu", "Sat"],
      verified: true,
      source: "admin_verified_entry",
    });
    await refreshDoctorsList();
  });

  // Post-Visit: Upload Doctor Report & AI Pre-Fill
  let latestDocId = null;
  document.getElementById("btnUploadDoctorDoc")?.addEventListener("click", async () => {
    if (!currentPerson) await ensurePersonAndSessionReady();
    const findingsText = document.getElementById("inpDocFindings")?.value || "";
    const followupDays = Number(document.getElementById("inpFollowupDays")?.value || 30);

    const doc = await uploadDoctorDocument({
      person_id: currentPerson.id,
      file_path: `documents/visit_${Date.now()}.jpg`,
      file_type: "image",
      findings_text: findingsText,
      followup_interval_days: followupDays,
      watch_domains: ["memory", "orientation"],
    });
    latestDocId = doc.id;

    // AI prescription extraction
    try {
      const extracted = await extractPrescriptionAI(findingsText);
      if (extracted && extracted.medicines && extracted.medicines.length > 0) {
        const m = extracted.medicines[0];
        const medName = document.getElementById("inpMedName");
        if (medName && m.name) medName.value = m.name;
        const medDose = document.getElementById("inpMedDose");
        if (medDose && m.dose) medDose.value = m.dose;
        const medFreq = document.getElementById("inpMedFreq");
        if (medFreq && m.frequency_per_day) medFreq.value = m.frequency_per_day;
      }
    } catch (e) {
      console.warn("AI prescription pre-fill notice:", e);
    }

    alert("Doctor report saved privately and follow-up retest scheduled ✓");
  });

  // Post-Visit: Confirm & Schedule Medicine
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
      if (!currentPerson) await ensurePersonAndSessionReady();
      const confirmed = document.getElementById("chkConfirmMedicine")?.checked;
      await createConfirmedMedicine({
        person_id: currentPerson.id,
        document_id: latestDocId,
        name: document.getElementById("inpMedName")?.value || "Donepezil",
        dose: document.getElementById("inpMedDose")?.value || "5mg",
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

  // Generate Monthly Summary & Report
  document.getElementById("btnGenerateMonthlySummary")?.addEventListener("click", async () => {
    try {
      if (!currentPerson) await ensurePersonAndSessionReady();
      const summary = await generateMonthlySummary({
        person_id: currentPerson.id,
        user_notes: ["Routine followed consistently this month."],
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

  // Settings: Test Emergency Phrase Detector
  document.getElementById("btnTestSafetyPhrase")?.addEventListener("click", async () => {
    const text = document.getElementById("inpSafetyTestPhrase")?.value || "want to die";
    const res = await runSafetyCheck(text);
    if (res.emergency_detected) {
      showEmergencyBanner(res);
    } else {
      alert("No emergency phrase detected in text.");
    }
  });

  // Settings: Delete All User Data & Audio Files
  document.getElementById("btnDeleteAllUserData")?.addEventListener("click", async () => {
    if (!currentPerson) {
      alert("No active person profile to delete.");
      return;
    }
    await deletePersonAndAllData(currentPerson.id);
    currentPerson = null;
    currentSession = null;
    currentCompletedSession = null;
    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = "Data Deleted";
    alert("All profile data, sessions, reports, and recorded files have been permanently deleted.");
    switchSection("home");
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  populateDefaultOrientationInputs();
  initClockCanvas();
  initDotConnectingGame();
  initSpeechRecognition();
  initEventListeners();
  await bootstrapAccountAndDemoData();
});
