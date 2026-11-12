import {
  checkExistingUser,
  completeSession,
  createConfirmedMedicine,
  createOrUpdatePerson,
  createReportShareLink,
  createSessionReport,
  deletePersonAndAllData,
  downloadReportPdfBlob,
  emailAccessUser,
  ensureMicReady,
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
} from "./api.js?v=19";
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
} from "./ui.js?v=19";

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
let lastTargetMicField = null;
let speechRecognitionInstance = null;
let browserRecognizedDuringSession = false;
let accumulatedFinalText = "";
let latestInterimText = "";

// Real-Time Web Audio API Microphone Visualizer + MediaRecorder + PCM WAV Recorder + Timing State
let audioCtx = null;
let micAnalyser = null;
let micMediaStream = null;
let pcmProcessorNode = null;
let pcmChunks = [];
let pcmSampleRate = 16000;
let mediaRecorderInstance = null;
let mediaRecorderChunks = [];
let visualizerRafId = null;
let liveTranscribeIntervalId = null;
let liveTranscribeBusy = false;

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

  // Peak-normalize audio so quiet laptop microphones are loud and clear for playback & STT
  let peak = 0;
  for (let i = 0; i < totalLen; i++) {
    const absVal = Math.abs(merged[i]);
    if (absVal > peak) peak = absVal;
  }
  const gain = peak > 0.0005 && peak < 0.85 ? Math.min(35.0, 0.85 / peak) : 1.0;

  let byteOffset = 44;
  for (let i = 0; i < outLen; i++) {
    const idx = Math.min(totalLen - 1, Math.floor(i * ratio));
    const s = Math.max(-1, Math.min(1, (merged[idx] || 0) * gain));
    view.setInt16(byteOffset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    byteOffset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function decodeRecordedBlobToWav(rawBlob, fallbackChunks, fallbackRate) {
  if (rawBlob && rawBlob.size > 100) {
    try {
      const arrayBuf = await rawBlob.arrayBuffer();
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const decodeCtx = new AudioContextClass();
      const audioBuffer = await decodeCtx.decodeAudioData(arrayBuf);
      const chData = new Float32Array(audioBuffer.getChannelData(0));
      const sr = audioBuffer.sampleRate || 44100;
      try {
        await decodeCtx.close();
      } catch (_e) { }
      return encodePcmToWavBlob([chData], sr);
    } catch (_e) { }
  }
  return encodePcmToWavBlob(fallbackChunks, fallbackRate);
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

    // Ensure Windows OS microphone is unmuted and at 100% volume before opening stream
    await ensureMicReady().catch(() => { });

    try {
      micMediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
        },
      });
    } catch (_e) {
      micMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioCtx = new AudioContextClass();
    if (audioCtx.state === "suspended") {
      try {
        await audioCtx.resume();
      } catch (_e) { }
    }
    pcmSampleRate = audioCtx.sampleRate || 44100;
    pcmChunks = [];
    mediaRecorderChunks = [];

    if (typeof window.MediaRecorder !== "undefined") {
      try {
        mediaRecorderInstance = new MediaRecorder(micMediaStream);
        mediaRecorderInstance.ondataavailable = (ev) => {
          if (ev.data && ev.data.size > 0) {
            mediaRecorderChunks.push(ev.data);
          }
        };
        mediaRecorderInstance.start(200);
      } catch (_e) {
        mediaRecorderInstance = null;
      }
    }

    const source = audioCtx.createMediaStreamSource(micMediaStream);
    micAnalyser = audioCtx.createAnalyser();
    micAnalyser.fftSize = 256;
    micAnalyser.smoothingTimeConstant = 0.5;
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

    const bufferLength = micAnalyser.fftSize;
    const timeDataArray = new Uint8Array(bufferLength);
    const ctx = canvas ? canvas.getContext("2d") : null;
    const w = canvas ? canvas.width : 140;
    const h = canvas ? canvas.height : 28;
    const barCount = 24;
    const gap = 3;
    const barWidth = Math.max(3, Math.floor((w - gap * (barCount - 1)) / barCount));

    const renderFrame = () => {
      if (!micAnalyser) return;
      visualizerRafId = requestAnimationFrame(renderFrame);
      micAnalyser.getByteTimeDomainData(timeDataArray);

      const now = performance.now();
      const dt = Math.max(0, now - lastFrameMs);
      lastFrameMs = now;

      if (ctx) ctx.clearRect(0, 0, w, h);
      let maxDeviation = 0;
      const stepSamples = Math.max(1, Math.floor(bufferLength / barCount));

      for (let i = 0; i < barCount; i++) {
        let localMax = 0;
        const startIdx = i * stepSamples;
        for (let j = 0; j < stepSamples; j++) {
          const sample = timeDataArray[(startIdx + j) % bufferLength] || 128;
          const dev = Math.abs(sample - 128);
          if (dev > localMax) localMax = dev;
        }
        if (localMax > maxDeviation) maxDeviation = localMax;

        // Amplify visual sensitivity so normal speech shows lively green bars
        const pct = Math.min(1.0, (localMax / 28.0));
        const bh = Math.max(4, Math.round(pct * (h - 4)));
        const x = i * (barWidth + gap);
        const y = Math.round((h - bh) / 2);

        if (ctx) {
          ctx.fillStyle = pct > 0.45 ? "#059669" : pct > 0.12 ? "#10b981" : "#6ee7b7";
          ctx.beginPath();
          ctx.roundRect ? ctx.roundRect(x, y, barWidth, bh, 2) : ctx.fillRect(x, y, barWidth, bh);
          ctx.fill();
        }
      }

      if (maxDeviation >= 2) {
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

    // Live periodic backend transcription every 2.6 seconds while user is still speaking
    clearInterval(liveTranscribeIntervalId);
    liveTranscribeBusy = false;
    liveTranscribeIntervalId = setInterval(async () => {
      if (!isListening || liveTranscribeBusy || pcmChunks.length < 6) return;
      if (speakingDurationMs < 250) return;
      liveTranscribeBusy = true;
      try {
        const snapshotChunks = pcmChunks.slice();
        const snapshotRate = pcmSampleRate;
        const targetFieldNow = activeMicField || lastTargetMicField;
        const stepNow = currentStep;
        const wavSnap = encodePcmToWavBlob(snapshotChunks, snapshotRate);
        const wavB64 = await blobToBase64(wavSnap);
        const res = await transcribeRecordedAudio({
          audioWavBase64: wavB64,
          durationSeconds: (performance.now() - recordStartMs) / 1000,
          speakingSeconds: speakingDurationMs / 1000,
          pauseMs: Math.round(pauseDurationMs),
          stepNumber: stepNow,
        });
        if (res && res.transcript && isListening) {
          routeTranscribedTextToField(res.transcript, targetFieldNow, stepNow, true);
          const bubble = document.getElementById("liveVoiceText");
          if (bubble) {
            bubble.textContent = `🎙️ Hearing: "${res.transcript}"`;
          }
        }
      } catch (_e) { } finally {
        liveTranscribeBusy = false;
      }
    }, 2600);

    if (speechRecognitionInstance && isListening) {
      try {
        speechRecognitionInstance.start();
      } catch (_e) { }
    }
  } catch (err) {
    console.warn("Microphone recorder notice:", err);
  }
}

async function stopVoiceVisualizerAndRecorder(targetFieldAtStop, stepAtStop) {
  clearInterval(liveTranscribeIntervalId);
  liveTranscribeIntervalId = null;

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

  let recordedMediaBlob = null;
  if (mediaRecorderInstance) {
    try {
      if (mediaRecorderInstance.state !== "inactive") {
        await new Promise((resolve) => {
          mediaRecorderInstance.onstop = resolve;
          mediaRecorderInstance.stop();
        });
      }
      if (mediaRecorderChunks.length > 0) {
        recordedMediaBlob = new Blob(mediaRecorderChunks, {
          type: mediaRecorderInstance.mimeType || "audio/webm",
        });
      }
    } catch (_e) { }
    mediaRecorderInstance = null;
    mediaRecorderChunks = [];
  }

  if (pcmProcessorNode) {
    try {
      pcmProcessorNode.disconnect();
    } catch (_e) { }
    pcmProcessorNode = null;
  }
  if (micMediaStream) {
    micMediaStream.getTracks().forEach((t) => t.stop());
    micMediaStream = null;
  }
  if (audioCtx) {
    try {
      audioCtx.close();
    } catch (_e) { }
    audioCtx = null;
  }
  micAnalyser = null;

  const summaryBadge =
    totalSec > 0.2
      ? `✓ ${totalSec.toFixed(1)}s (Speak ${speakSec.toFixed(1)}s · Pause ${pauseSec.toFixed(1)}s)`
      : "⏱ 0.0s · Idle";
  drawIdleVoiceVisualizer(summaryBadge);

  if ((!recordedMediaBlob && capturedChunks.length === 0) || totalSec < 0.25) {
    return;
  }

  const wavBlob = await decodeRecordedBlobToWav(recordedMediaBlob, capturedChunks, capturedRate);
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
    bubble.textContent = "⏳ Converting your voice to text...";
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
      routeTranscribedTextToField(res.transcript, targetFieldAtStop, stepAtStop, true);
      if (bubble) {
        bubble.textContent = `✓ Voice recorded: "${res.transcript}"`;
      }
    } else if (bubble) {
      const liveText = (accumulatedFinalText + " " + latestInterimText).trim();
      if (liveText) {
        bubble.textContent = `✓ Voice recorded: "${liveText}"`;
      } else {
        bubble.textContent = "✓ Voice recorded. Click \"🔊 Play Voice\" to listen.";
      }
    }
  } catch (_e) {
    if (bubble) {
      bubble.textContent = "✓ Voice recorded. Click \"🔊 Play Voice\" to listen.";
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
  const map = { 2: "t2Response", 3: "t3Response", 4: "t4Response", 5: "t5Response" };
  return map[stepNum] || "t1Day";
}

function routeTranscribedTextToField(spokenText, explicitField = null, stepNum = currentStep, replaceValue = false) {
  if (!spokenText) return;
  const clean = spokenText
    .replace(/(60\s*seconds?\s*started\.?|second\s*started\.?|please\s*begin\s*speaking\s*now\.?|speaking\s*now\.?|60\s*second\s*please\s*begin\s*speaking\s*now\.?)/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!clean) return;

  if (stepNum === 1) {
    const matchedAny = parseOrientationSpeech(clean.toLowerCase());
    const targetId = explicitField || lastTargetMicField || getDefaultTargetFieldForStep(1);
    const el = document.getElementById(targetId);
    if (el && (!matchedAny || explicitField)) {
      el.value = clean;
    }
    return;
  }

  const fieldId = explicitField || lastTargetMicField || getDefaultTargetFieldForStep(stepNum);
  const el = document.getElementById(fieldId);
  if (el) {
    if (el.tagName === "TEXTAREA" && !replaceValue) {
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

      if (finalTranscript.trim()) {
        accumulatedFinalText = (accumulatedFinalText + " " + finalTranscript.trim()).trim();
      }
      latestInterimText = interimTranscript.trim();

      const fullSpokenSoFar = (accumulatedFinalText + " " + latestInterimText).trim();
      const bubble = document.getElementById("liveVoiceText");
      if (bubble && fullSpokenSoFar) {
        bubble.textContent = `🎙️ Hearing: "${fullSpokenSoFar}"`;
      }

      if (fullSpokenSoFar) {
        browserRecognizedDuringSession = true;
        routeTranscribedTextToField(
          fullSpokenSoFar,
          activeMicField || lastTargetMicField,
          currentStep,
          true
        );
      }
    };

    speechRecognitionInstance.onerror = () => { };

    speechRecognitionInstance.onend = () => {
      if (isListening) {
        try {
          speechRecognitionInstance.start();
        } catch (_e) { }
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
    const fieldAtStop = activeMicField || lastTargetMicField;
    const stepAtStop = currentStep;
    isListening = false;
    activeMicField = null;
    if (speechRecognitionInstance) {
      try {
        speechRecognitionInstance.stop();
      } catch (_e) { }
    }
    updateMicUIState(false, fieldAtStop, stepAtStop);
    return;
  }

  activeMicField = targetField || getDefaultTargetFieldForStep(currentStep);
  lastTargetMicField = activeMicField;
  browserRecognizedDuringSession = false;
  accumulatedFinalText = "";
  latestInterimText = "";
  isListening = true;

  const targetInp = document.getElementById(activeMicField);
  if (targetInp) targetInp.focus();

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
    overlay.style.display = "none";
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
  overlay.style.display = "flex";
}

function setGuestAuthTabMode(mode = "login") {
  const switcherBar = document.getElementById("authModeSwitcherBar");
  const tabLogin = document.getElementById("btnTabLogin");
  const tabSignup = document.getElementById("btnTabSignup");
  const loginView = document.getElementById("guestLoginView");
  const signupView = document.getElementById("guestSignupView");
  const cancelBtn = document.getElementById("btnCancelEditProfile");
  const stepTag = document.getElementById("signupCardStepTag");
  const heading = document.getElementById("signupCardHeading");
  const bottomSwitch = document.getElementById("signupBottomSwitchWrap");
  const saveStartBtn = document.getElementById("btnSaveProfileAndStart");

  if (mode === "edit") {
    if (switcherBar) switcherBar.style.display = "none";
    if (loginView) loginView.classList.add("hidden");
    if (signupView) signupView.classList.remove("hidden");
    if (cancelBtn) cancelBtn.classList.remove("hidden");
    if (stepTag) stepTag.textContent = "Update Saved Profile";
    if (heading) heading.textContent = "Edit Patient Profile";
    if (bottomSwitch) bottomSwitch.classList.add("hidden");
    if (saveStartBtn) saveStartBtn.innerHTML = "<span>Save Profile &amp; Resume Test &rarr;</span>";
    return;
  }

  if (switcherBar) switcherBar.style.display = "grid";
  if (cancelBtn) cancelBtn.classList.add("hidden");
  if (stepTag) stepTag.textContent = "First-Time Patient Registration";
  if (heading) heading.textContent = "Create Patient Profile";
  if (bottomSwitch) bottomSwitch.classList.remove("hidden");
  if (saveStartBtn) saveStartBtn.innerHTML = "<span>Sign Up &amp; Generate AI Test &rarr;</span>";

  if (mode === "signup") {
    if (loginView) loginView.classList.add("hidden");
    if (signupView) signupView.classList.remove("hidden");
    if (tabSignup) {
      tabSignup.style.background = "var(--emerald-deep)";
      tabSignup.style.color = "#ffffff";
    }
    if (tabLogin) {
      tabLogin.style.background = "transparent";
      tabLogin.style.color = "var(--text-mid)";
    }
  } else {
    if (loginView) loginView.classList.remove("hidden");
    if (signupView) signupView.classList.add("hidden");
    if (tabLogin) {
      tabLogin.style.background = "var(--emerald-deep)";
      tabLogin.style.color = "#ffffff";
    }
    if (tabSignup) {
      tabSignup.style.background = "transparent";
      tabSignup.style.color = "var(--text-mid)";
    }
  }
}

function renderHomePatientDashboard(person, sessions = [], medicines = null) {
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
    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = "Login / Sign Up";
    setGuestAuthTabMode("login");
    return;
  }

  try {
    localStorage.setItem("yaadasht_saved_person", JSON.stringify(person));
  } catch (_e) { }

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

  const badge = document.getElementById("activePersonBadge");
  if (badge && person.name) {
    badge.textContent = `${person.name} (${person.age}y, ${person.city})`;
  }

  const emailTag = document.getElementById("dashAccountEmailTag");
  const savedEmail = localStorage.getItem("yaadasht_caregiver_email");
  if (emailTag && savedEmail && !savedEmail.endsWith("@yaadasht.local")) {
    emailTag.textContent = `Email: ${savedEmail}`;
  } else if (emailTag) {
    emailTag.textContent = "Active Account";
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

  const safeSessions = Array.isArray(sessions) ? sessions : [];
  const countBadge = document.getElementById("dashSessionCountBadge");
  if (countBadge) countBadge.textContent = `${safeSessions.length} Session${safeSessions.length === 1 ? "" : "s"}`;

  const completedList = safeSessions.filter((s) => s.completed);
  const openList = safeSessions.filter((s) => !s.completed);
  const pendingSession = openList.length > 0 ? openList[openList.length - 1] : null;

  const kpiScore = document.getElementById("kpiLatestScore");
  const kpiOutcome = document.getElementById("homeLastOutcomeText");
  const kpiRetest = document.getElementById("kpiNextRetestBadge");
  const kpiRetestSub = document.getElementById("homeNextRetestText");
  const kpiMedCount = document.getElementById("kpiMedicineCount");
  const dashStartBtn = document.getElementById("btnDashStartBaseline");
  const postVisitBtn = document.getElementById("btnStartAdaptiveFollowupTest");

  if (Array.isArray(medicines)) {
    if (kpiMedCount) {
      kpiMedCount.textContent =
        medicines.length > 0
          ? `${medicines.length} Active Medicine${medicines.length === 1 ? "" : "s"}`
          : "0 Active";
    }
  }

  if (pendingSession) {
    const doneCount = Array.isArray(pendingSession.results) ? pendingSession.results.length : 0;
    const nextStep = Math.min(5, doneCount + 1);
    if (dashStartBtn) {
      dashStartBtn.innerHTML = `<span>▶ Resume Pending AI Test (Step ${nextStep} of 7)</span>`;
    }
    if (postVisitBtn) {
      postVisitBtn.innerHTML = `<span>▶ Resume Pending AI Test (Step ${nextStep} of 7)</span>`;
    }
    if (completedList.length === 0) {
      if (kpiScore) kpiScore.textContent = `${doneCount} / 7 Done`;
      if (kpiOutcome) kpiOutcome.textContent = `Pending Session in MongoDB (Step ${nextStep} next)`;
      if (kpiRetest) kpiRetest.textContent = "In Progress";
      if (kpiRetestSub) kpiRetestSub.textContent = `Complete all 7 steps to unlock final AI analysis`;
    }
  } else {
    if (dashStartBtn) {
      dashStartBtn.innerHTML = `<span>🧠 Generate New AI Test</span>`;
    }
    if (postVisitBtn) {
      postVisitBtn.innerHTML = `<span>🔄 Start AI Adaptive Post-Visit Test (7 Steps)</span>`;
    }
  }

  if (completedList.length > 0) {
    const last = completedList[completedList.length - 1];
    const scoreNum = Math.round(last.total_score ?? 0);
    const outcomeRaw = (last.outcome || "completed").toLowerCase();
    if (kpiScore) kpiScore.textContent = `${scoreNum} / 100`;
    if (kpiOutcome) {
      const modePrefix = last.session_mode === "post_visit_adaptive" ? "Post-Visit" : "Baseline";
      kpiOutcome.textContent = `${modePrefix}: ${outcomeRaw.replace(/_/g, " ").toUpperCase()}`;
    }
    if (pendingSession) {
      const doneCount = Array.isArray(pendingSession.results) ? pendingSession.results.length : 0;
      if (kpiRetest) kpiRetest.textContent = `Pending (${doneCount}/7)`;
      if (kpiRetestSub) kpiRetestSub.textContent = "Finish pending test in MongoDB before starting a new one";
    } else if (outcomeRaw.includes("urgent") || outcomeRaw.includes("consult") || scoreNum < 70) {
      if (kpiRetest) kpiRetest.textContent = "Consult Doctor";
      if (kpiRetestSub) kpiRetestSub.textContent = "AI recommends specialist review or new follow-up test";
    } else {
      if (kpiRetest) kpiRetest.textContent = "Ready Anytime";
      if (kpiRetestSub) kpiRetestSub.textContent = "No pending test — you can generate a new AI test anytime";
    }
  } else if (!pendingSession) {
    if (kpiScore) kpiScore.textContent = "Not Tested";
    if (kpiOutcome) kpiOutcome.textContent = "No completed test in MongoDB yet";
    if (kpiRetest) kpiRetest.textContent = "Start Now";
    if (kpiRetestSub) kpiRetestSub.textContent = "Generate your first 7-step AI cognitive screening";
  }

  const listEl = document.getElementById("dashSessionsList");
  if (listEl) {
    if (safeSessions.length === 0) {
      listEl.innerHTML = `
        <div class="finding-card" style="background:var(--bg-soft);">
          <strong>No sessions in MongoDB yet</strong>
          <span>Click "🧠 Generate New AI Test" above to generate and save your 7-step test.</span>
        </div>
      `;
    } else {
      const recent = [...safeSessions].reverse().slice(0, 5);
      listEl.innerHTML = recent
        .map((s, idx) => {
          const dt = s.session_date ? new Date(s.session_date).toLocaleDateString() : "Saved";
          const modeLbl = s.session_mode === "post_visit_adaptive" ? "🔄 Post-Visit Adaptive" : "🧠 AI Baseline";
          const doneCount = Array.isArray(s.results) ? s.results.length : 0;
          const statusStr = s.completed
            ? `Completed · Score: ${Math.round(s.total_score ?? 0)}/100 · ${(s.outcome || "").replace(/_/g, " ").toUpperCase()}`
            : `Pending in MongoDB (${doneCount}/5 tests saved — Resume at Step ${Math.min(5, doneCount + 1)})`;
          return `
            <div class="finding-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;">
              <div>
                <strong style="font-size:13px;">${modeLbl} (${dt})</strong>
                <span style="display:block;font-size:12px;">${statusStr}</span>
              </div>
              <button type="button" class="mode-pill btn-dash-open-session" data-session-idx="${idx}" style="font-size:12px;padding:6px 12px;">
                ${s.completed ? "View Analysis" : `Resume (${doneCount}/7)`}
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
            renderCompletedSessionResult(targetSession, safeSessions.filter((x) => x.completed));
            switchSection("result");
          } else {
            currentSession = targetSession;
            applySessionPromptsToUI(targetSession);
            const nextStepNum = Math.min(5, (targetSession.results || []).length + 1);
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
  } catch (_e) { }
}

function restoreFormDraftFromStorage() {
  try {
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
  } catch (_e) { }
}

function applySessionPromptsToUI(session) {
  if (!session) return;
  const prompts = session.item_prompts || {};
  setActiveSessionPrompts(prompts);

  const persistBadge = document.getElementById("sessionPersistenceBadge");
  if (persistBadge) {
    const doneCount = Array.isArray(session.results) ? session.results.length : 0;
    persistBadge.textContent = session.completed
      ? "Completed Session ✓"
      : `Saved in MongoDB (${doneCount}/5 Done)`;
  }

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
  const stepPill3 = document.getElementById("stepPill3Text");
  if (t3Title && prompts.fluency_category) {
    t3Title.textContent = `60-Second Verbal Fluency Challenge (${prompts.fluency_category})`;
  }
  if (stepPill3 && prompts.fluency_category) {
    stepPill3.textContent = `3. ${prompts.fluency_category}`;
  }
  if (t3Prompt && prompts.fluency_prompt) {
    t3Prompt.textContent = prompts.fluency_prompt;
  }

  const sceneBox = document.getElementById("t4SceneVisualContainer");
  if (sceneBox) {
    const imgUrl = typeof prompts.picture_image_url === "string" ? prompts.picture_image_url.trim() : "";
    const rawSvg = typeof prompts.picture_scene_svg === "string" ? prompts.picture_scene_svg.trim() : "";
    const titleText = prompts.picture_scene_title || "AI Visual Scene";
    if (imgUrl) {
      sceneBox.innerHTML = `<img src="${imgUrl}" alt="${titleText}" style="width:100%;height:240px;object-fit:cover;border-radius:12px;display:block;border:1px solid #a7f3d0;" />`;
    } else if (rawSvg.startsWith("<svg") && rawSvg.includes("</svg>")) {
      const safeSvg = rawSvg
        .replace(/<script[\s\S]*?<\/script>/gi, "")
        .replace(/\son\w+\s*=\s*(['"]).*?\1/gi, "");
      sceneBox.innerHTML = safeSvg;
    } else {
      const itemsList = Array.isArray(prompts.picture_target_items) ? prompts.picture_target_items.slice(0, 8) : [];
      sceneBox.innerHTML = `
        <div style="padding:18px;border-radius:12px;background:#ecfdf5;border:1px solid #a7f3d0;text-align:center;">
          <div style="font-weight:700;color:#065f46;font-size:15px;margin-bottom:10px;">${titleText}</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;">
            ${itemsList.map((it) => `<span class="word-chip" style="font-size:12px;padding:4px 10px;">${it}</span>`).join("")}
          </div>
        </div>
      `;
    }
  }
  const t4Prompt = document.getElementById("t4StoryPromptText");
  if (t4Prompt && prompts.picture_story_prompt) {
    t4Prompt.textContent = prompts.picture_story_prompt;
  }

  const t5Instr = document.getElementById("t5InstructionText");
  if (t5Instr && (prompts.test5_instruction || prompts.test7_instruction)) {
    t5Instr.textContent = prompts.test5_instruction || prompts.test7_instruction;
  }

  if (Array.isArray(session.results)) {
    for (const r of session.results) {
      if (r.test_number === 1 && r.answers) {
        if (r.answers.day) {
          const el = document.getElementById("t1Day");
          if (el) el.value = r.answers.day;
        }
        if (r.answers.date) {
          const el = document.getElementById("t1Date");
          if (el) el.value = r.answers.date;
        }
        if (r.answers.month) {
          const el = document.getElementById("t1Month");
          if (el) el.value = r.answers.month;
        }
        if (r.answers.season) {
          const el = document.getElementById("t1Season");
          if (el) el.value = r.answers.season;
        }
        if (r.answers.city) {
          const el = document.getElementById("t1City");
          if (el) el.value = r.answers.city;
        }
      } else if (r.test_number === 2 && r.raw_response) {
        const el = document.getElementById("t2Response");
        if (el) el.value = r.raw_response;
      } else if (r.test_number === 3 && r.raw_response) {
        const el = document.getElementById("t3Response");
        if (el) el.value = r.raw_response;
      } else if (r.test_number === 4 && r.raw_response) {
        const el = document.getElementById("t4Response");
        if (el) el.value = r.raw_response;
      } else if ((r.test_number === 5 || r.test_number === 7) && r.raw_response) {
        const el = document.getElementById("t5Response");
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
  } catch (_e) { }

  try {
    let authenticated = false;
    if (getAuthToken()) {
      try {
        await fetchCurrentUser();
        authenticated = true;
      } catch (_e) {
        setAuthToken(null);
      }
    }

    if (!authenticated) {
      const savedEmail = localStorage.getItem("yaadasht_caregiver_email") || "";
      if (savedEmail && savedEmail.includes("@") && !savedEmail.endsWith("@yaadasht.local")) {
        try {
          const res = await emailAccessUser({ email: savedEmail, mode: "login" });
          setAuthToken(res.access_token);
          authenticated = true;
        } catch (_e) {
          localStorage.removeItem("yaadasht_caregiver_email");
        }
      } else {
        localStorage.removeItem("yaadasht_caregiver_email");
        localStorage.removeItem("yaadasht_caregiver_pass");
      }
    }

    if (!authenticated) {
      currentPerson = null;
      currentSession = null;
      currentCompletedSession = null;
      renderHomePatientDashboard(null, []);
      await refreshDoctorsList();
      return;
    }

    try {
      const savedPerson = await fetchMyPerson();
      if (savedPerson && savedPerson.id) {
        currentPerson = savedPerson;
        populatePersonForm(savedPerson);

        const sessions = (await listSessions(savedPerson.id)) || [];
        let meds = [];
        try {
          meds = (await listMedicines(savedPerson.id)) || [];
        } catch (_e) { }

        renderHomePatientDashboard(savedPerson, sessions, meds);

        if (sessions.length > 0) {
          const completedList = sessions.filter((s) => s.completed);
          const openList = sessions.filter((s) => !s.completed);

          if (completedList.length > 0) {
            currentCompletedSession = completedList[completedList.length - 1];
            renderCompletedSessionResult(currentCompletedSession, completedList);
          }
          if (openList.length > 0) {
            currentSession = openList[openList.length - 1];
            applySessionPromptsToUI(currentSession);
            currentStep = Math.min(5, (currentSession.results || []).length + 1);
          } else if (currentCompletedSession) {
            currentSession = null;
            currentStep = 1;
            clearAllTestInputsForNewSession({});
          }
        }

        if (meds.length > 0) {
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
      } else {
        renderHomePatientDashboard(null, []);
      }
    } catch (_e) {
      renderHomePatientDashboard(null, []);
    }

    renderActiveTestStep(currentStep, currentSession?.item_prompts || null);

    const savedSection = localStorage.getItem("yaadasht_active_section");
    if (savedSection && ["home", "session", "result", "doctors", "postvisit", "settings"].includes(savedSection)) {
      if (savedSection === "session" && !currentSession) {
        switchSection("home");
      } else {
        switchSection(savedSection);
      }
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
  ["t1Day", "t1Date", "t1Month", "t1Season", "t1City", "t2Response", "t3Response", "t4Response", "t5Response"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    }
  );
  const pauseEl = document.getElementById("t4PauseMs");
  if (pauseEl) pauseEl.value = "0";
  const voiceTxt = document.getElementById("liveVoiceText");
  if (voiceTxt) voiceTxt.textContent = 'Press "▶ Play Question" (2x repeat) or "🎙️ Record Answer" to record & transcribe your voice.';
  const playBtn = document.getElementById("btnPlayRecordedVoice");
  if (playBtn) playBtn.classList.add("hidden");
  const saveInd = document.getElementById("sessionSaveIndicator");
  if (saveInd) saveInd.textContent = "Auto-saves each test";
  if (lastRecordedAudioUrl) {
    URL.revokeObjectURL(lastRecordedAudioUrl);
    lastRecordedAudioUrl = null;
  }
}

let detectedExistingAccount = null;

function toggleExistingUserPromptUI(existingInfo) {
  detectedExistingAccount = existingInfo && existingInfo.exists ? existingInfo : null;
  const alertBox = document.getElementById("existingUserDetectedBox");
  const alertText = document.getElementById("existingUserDetectedText");
  const extraFields = document.getElementById("newPatientExtraFieldsWrap");
  const saveStartBtn = document.getElementById("btnSaveProfileAndStart");

  if (detectedExistingAccount) {
    if (alertBox) alertBox.classList.remove("hidden");
    if (alertText) {
      const pName = detectedExistingAccount.person_name || "Saved Patient";
      const pEmail = detectedExistingAccount.email ? ` (${detectedExistingAccount.email})` : "";
      alertText.textContent = `Welcome back! ${pName}${pEmail} is already saved in our database. No need to fill the form again — simply login below.`;
    }
    if (extraFields) extraFields.classList.add("hidden");
    if (saveStartBtn) saveStartBtn.classList.add("hidden");
  } else {
    if (alertBox) alertBox.classList.add("hidden");
    if (extraFields) extraFields.classList.remove("hidden");
    if (saveStartBtn) saveStartBtn.classList.remove("hidden");
  }
}

async function performQuickLogin({ email = "", name = "" } = {}) {
  const cleanEmail = (email || "").trim().toLowerCase();
  const cleanName = (name || "").trim();
  if (!cleanEmail && !cleanName) {
    alert("Please enter your registered Email or Patient Name to login.");
    return false;
  }

  showAILoadingOverlay(true);
  try {
    const startMs = performance.now();
    const res = await emailAccessUser({
      email: cleanEmail,
      full_name: cleanName,
      mode: "login",
    });
    setAuthToken(res.access_token);
    if (res.email) {
      localStorage.setItem("yaadasht_caregiver_email", res.email);
      localStorage.setItem("yaadasht_caregiver_pass", "password123");
    }

    const elapsed = performance.now() - startMs;
    if (elapsed < 600) {
      await new Promise((r) => setTimeout(r, 600 - elapsed));
    }

    toggleExistingUserPromptUI(null);

    if (res.person && res.person.id) {
      currentPerson = res.person;
      populatePersonForm(res.person);
      const sessions = (await listSessions(res.person.id)) || [];
      let meds = [];
      try {
        meds = (await listMedicines(res.person.id)) || [];
      } catch (_e) { }

      const completedList = sessions.filter((s) => s.completed);
      const openList = sessions.filter((s) => !s.completed);
      if (completedList.length > 0) {
        currentCompletedSession = completedList[completedList.length - 1];
        renderCompletedSessionResult(currentCompletedSession, completedList);
      }
      if (openList.length > 0) {
        currentSession = openList[openList.length - 1];
        applySessionPromptsToUI(currentSession);
        currentStep = Math.min(5, (currentSession.results || []).length + 1);
      } else {
        currentSession = null;
        currentStep = 1;
      }

      renderHomePatientDashboard(res.person, sessions, meds);
    } else {
      await bootstrapAccountAndData();
    }
    switchSection("home");
    return true;
  } catch (err) {
    if (cleanEmail && cleanEmail.includes("@")) {
      const signupEmailInp = document.getElementById("inpPersonEmail");
      if (signupEmailInp) signupEmailInp.value = cleanEmail;
      setGuestAuthTabMode("signup");
      document.getElementById("inpPersonName")?.focus();
      alert("This email is not registered yet. Switched to Sign Up — please enter the patient profile details once to create your account.");
    } else {
      alert(err.message || "No account found with this email. Please switch to Sign Up to create a new account.");
    }
    return false;
  } finally {
    showAILoadingOverlay(false);
  }
}

async function ensurePersonAndSessionReady(sessionMode = "baseline") {
  const rawEmail =
    document.getElementById("inpPersonEmail")?.value.trim().toLowerCase() ||
    document.getElementById("inpQuickLoginEmail")?.value.trim().toLowerCase() ||
    localStorage.getItem("yaadasht_caregiver_email") ||
    "";
  const rawName = document.getElementById("inpPersonName")?.value.trim() || currentPerson?.name || "";
  const rawAge = document.getElementById("inpPersonAge")?.value.trim() || String(currentPerson?.age || "");

  const saveBtn = document.getElementById("btnSaveProfileAndStart");
  const dashBtn = document.getElementById("btnDashStartBaseline");
  const origSaveHtml = saveBtn ? saveBtn.innerHTML : "";
  const origDashHtml = dashBtn ? dashBtn.innerHTML : "";

  if (saveBtn) saveBtn.disabled = true;
  if (dashBtn) dashBtn.disabled = true;

  const startMs = performance.now();
  showAILoadingOverlay(true);
  await new Promise((r) => setTimeout(r, 50));

  try {
    // 1. If the user is on the Guest / Setup screen or entered an email, check/authenticate with MongoDB first
    const currentEmail = (localStorage.getItem("yaadasht_caregiver_email") || "").toLowerCase();
    const guestViewVisible = !document.getElementById("homeGuestView")?.classList.contains("hidden");

    if (!getAuthToken() || (rawEmail && rawEmail.includes("@") && rawEmail !== currentEmail)) {
      if (!rawEmail || !rawEmail.includes("@")) {
        showAILoadingOverlay(false);
        alert("Please enter your Email Address so your profile and AI tests can be saved in MongoDB.");
        document.getElementById("inpPersonEmail")?.focus();
        return false;
      }
      const emailRes = await emailAccessUser({
        email: rawEmail,
        mode: "register",
        full_name: rawName || rawEmail.split("@")[0],
      });
      setAuthToken(emailRes.access_token);
      localStorage.setItem("yaadasht_caregiver_email", emailRes.email || rawEmail);
      localStorage.setItem("yaadasht_caregiver_pass", "password123");

      // If this user already existed in MongoDB and was on the guest screen, log them straight into their Home Dashboard!
      if (emailRes.already_registered && emailRes.person && guestViewVisible) {
        currentPerson = emailRes.person;
        populatePersonForm(currentPerson);
        const existingSessions = (await listSessions(currentPerson.id)) || [];
        let meds = [];
        try {
          meds = (await listMedicines(currentPerson.id)) || [];
        } catch (_e) { }
        const openList = existingSessions.filter((s) => !s.completed);
        const completedList = existingSessions.filter((s) => s.completed);
        if (completedList.length > 0) {
          currentCompletedSession = completedList[completedList.length - 1];
          renderCompletedSessionResult(currentCompletedSession, completedList);
        }
        if (openList.length > 0) {
          currentSession = openList[openList.length - 1];
          applySessionPromptsToUI(currentSession);
        }
        renderHomePatientDashboard(currentPerson, existingSessions, meds);
        switchSection("home");
        return false;
      }
    }

    // 2. If we already have a logged-in person in MongoDB, check if they have a PENDING (uncompleted) session first!
    if (currentPerson && currentPerson.id && !guestViewVisible) {
      const existingSessions = (await listSessions(currentPerson.id)) || [];
      const openList = existingSessions.filter((s) => !s.completed);
      if (openList.length > 0) {
        currentSession = openList[openList.length - 1];
        sessionStartTimeMs = Date.now();
        clearAllTestInputsForNewSession(currentSession.item_prompts || {});
        applySessionPromptsToUI(currentSession);
        const resumeStep = Math.min(5, (currentSession.results || []).length + 1);
        currentStep = resumeStep;
        renderActiveTestStep(resumeStep, currentSession.item_prompts || {});
        renderHomePatientDashboard(currentPerson, existingSessions);
        return true;
      }
    }

    // 3. Validate patient profile fields when creating or updating profile
    if (!rawName || !rawAge) {
      showAILoadingOverlay(false);
      alert("Please enter the patient's Full Name and Age before starting the personalized test.");
      switchSection("home");
      document.getElementById("inpPersonName")?.focus();
      return false;
    }

    const chkAudio = document.getElementById("chkConsentAudio")?.checked;
    if (!chkAudio) {
      showAILoadingOverlay(false);
      alert("Please accept the consent checkbox before starting the cognitive tests.");
      return false;
    }

    const age = Number(rawAge);
    const gender = document.getElementById("inpPersonGender")?.value || currentPerson?.gender || "male";
    const city = document.getElementById("inpPersonCity")?.value || currentPerson?.city || "Lahore";
    const education_level =
      document.getElementById("inpPersonEducation")?.value || currentPerson?.education_level || "secondary";
    const occupation =
      document.getElementById("inpPersonOccupation")?.value.trim() || currentPerson?.occupation || "retired";
    const family_history_dementia =
      document.getElementById("inpFamilyHistory")?.value === "true" || Boolean(currentPerson?.family_history_dementia);
    const symptom_duration_months = Number(
      document.getElementById("inpSymptomDuration")?.value || currentPerson?.symptom_duration_months || 6
    );

    const observed_symptoms = Array.from(document.querySelectorAll(".chk-symptom:checked")).map((el) => el.value);
    const medical_conditions = Array.from(document.querySelectorAll(".chk-condition:checked")).map((el) => el.value);

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
        medical_conditions: medical_conditions.length > 0 ? medical_conditions : currentPerson?.medical_conditions || [],
        observed_symptoms: observed_symptoms.length > 0 ? observed_symptoms : currentPerson?.observed_symptoms || [],
        symptom_duration_months,
      },
      currentPerson?.id || null
    );
    saveFormDraftToStorage();

    await grantConsent(currentPerson.id, "audio");
    await grantConsent(currentPerson.id, "data_processing");
    await grantConsent(currentPerson.id, "report_sharing");
    await grantConsent(currentPerson.id, "document_upload");

    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = `${currentPerson.name} (${currentPerson.age}y, ${currentPerson.city})`;
    const onboardBadge = document.getElementById("onboardStatusBadge");
    if (onboardBadge) onboardBadge.textContent = "Saved ✓";

    // 4. Start or resume session from backend (backend returns pending session if one exists, or generates a new AI 7-test session)
    currentSession = await startSession(currentPerson.id, sessionMode);
    sessionStartTimeMs = Date.now();

    const elapsed = performance.now() - startMs;
    if (elapsed < 600) {
      await new Promise((r) => setTimeout(r, 600 - elapsed));
    }

    const prompts = currentSession.item_prompts || {};
    clearAllTestInputsForNewSession(prompts);
    applySessionPromptsToUI(currentSession);
    const nextStep = Math.min(5, (currentSession.results || []).length + 1);
    currentStep = nextStep;
    renderActiveTestStep(nextStep, prompts);

    try {
      const allSessions = await listSessions(currentPerson.id);
      renderHomePatientDashboard(currentPerson, allSessions || []);
    } catch (_e) {
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
      if (origDashHtml) dashBtn.innerHTML = origDashHtml;
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
      test_type: "animal_naming",
      raw_response: document.getElementById("t3Response")?.value || "",
      timing: { duration_seconds: 60.0 },
      audio_path: `audio/${currentSession.id}_test3.webm`,
    };
  } else if (stepNum === 4) {
    const descText = document.getElementById("t4Response")?.value || "";
    const pauseMs = Number(document.getElementById("t4PauseMs")?.value || 0);
    let aiMarkers = [];
    try {
      if (descText.trim()) {
        const sceneTitle = currentSession?.item_prompts?.picture_scene_title || "";
        const targetItems = currentSession?.item_prompts?.picture_target_items || [];
        const aiStory = await evaluatePictureStoryAI(descText, sceneTitle, targetItems);
        if (aiStory && Array.isArray(aiStory.clinical_markers)) {
          aiMarkers = aiStory.clinical_markers;
        }
      }
    } catch (_e) { }

    payload = {
      test_number: 4,
      test_type: "picture_story",
      raw_response: descText,
      timing: {
        pause_ms: pauseMs,
        ai_markers: aiMarkers,
      },
      answers: {
        pause_ms: pauseMs,
        ai_markers: aiMarkers,
      },
      audio_path: `audio/${currentSession.id}_test4.webm`,
    };
  } else if (stepNum === 5) {
    payload = {
      test_number: 5,
      test_type: "word_recall_delayed",
      raw_response: document.getElementById("t5Response")?.value || "",
      audio_path: `audio/${currentSession.id}_test5.webm`,
    };
  }

  const res = await submitTestResult(currentSession.id, payload);
  if (currentSession) {
    if (!Array.isArray(currentSession.results)) currentSession.results = [];
    const existingIdx = currentSession.results.findIndex((r) => r.test_number === stepNum);
    if (existingIdx >= 0) {
      currentSession.results[existingIdx] = res;
    } else {
      currentSession.results.push(res);
    }
    const persistBadge = document.getElementById("sessionPersistenceBadge");
    if (persistBadge) {
      persistBadge.textContent = `Saved in MongoDB (${currentSession.results.length}/5 Done)`;
    }
  }
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

  // Live Database Check: If user types an Email or Name that already exists in MongoDB, show "Simply Login"
  let checkUserDebounceTimer = null;
  const triggerExistingUserCheck = () => {
    clearTimeout(checkUserDebounceTimer);
    checkUserDebounceTimer = setTimeout(async () => {
      if (currentPerson && currentPerson.id) return;
      const emailVal = document.getElementById("inpPersonEmail")?.value.trim().toLowerCase() || "";
      const nameVal = document.getElementById("inpPersonName")?.value.trim() || "";
      if ((emailVal && emailVal.includes("@") && emailVal.includes(".")) || nameVal.length >= 3) {
        try {
          const checkRes = await checkExistingUser({ email: emailVal, name: nameVal });
          toggleExistingUserPromptUI(checkRes);
        } catch (_e) { }
      } else {
        toggleExistingUserPromptUI(null);
      }
    }, 350);
  };

  document.getElementById("inpPersonEmail")?.addEventListener("input", triggerExistingUserCheck);
  document.getElementById("inpPersonName")?.addEventListener("input", triggerExistingUserCheck);

  document.getElementById("btnLoginDetectedUser")?.addEventListener("click", async () => {
    const emailToUse =
      detectedExistingAccount?.email ||
      document.getElementById("inpPersonEmail")?.value.trim().toLowerCase() ||
      "";
    const nameToUse =
      detectedExistingAccount?.person_name ||
      document.getElementById("inpPersonName")?.value.trim() ||
      "";
    await performQuickLogin({ email: emailToUse, name: nameToUse });
  });

  document.getElementById("btnDismissExistingPrompt")?.addEventListener("click", () => {
    toggleExistingUserPromptUI(null);
  });

  // Tab Switcher on Home Card: Show ONLY Login OR Sign Up at a time
  document.getElementById("btnTabLogin")?.addEventListener("click", () => {
    setGuestAuthTabMode("login");
    document.getElementById("inpQuickLoginEmail")?.focus();
  });
  document.getElementById("btnTabSignup")?.addEventListener("click", () => {
    setGuestAuthTabMode("signup");
    document.getElementById("inpPersonEmail")?.focus();
  });
  document.getElementById("btnSwitchToSignupLink")?.addEventListener("click", () => {
    const loginEmail = document.getElementById("inpQuickLoginEmail")?.value.trim() || "";
    const signupEmailInp = document.getElementById("inpPersonEmail");
    if (loginEmail && signupEmailInp && !signupEmailInp.value) {
      signupEmailInp.value = loginEmail;
    }
    setGuestAuthTabMode("signup");
    document.getElementById("inpPersonEmail")?.focus();
  });
  document.getElementById("btnSwitchToLoginLink")?.addEventListener("click", () => {
    const signupEmail = document.getElementById("inpPersonEmail")?.value.trim() || "";
    const loginEmailInp = document.getElementById("inpQuickLoginEmail");
    if (signupEmail && loginEmailInp && !loginEmailInp.value) {
      loginEmailInp.value = signupEmail;
    }
    setGuestAuthTabMode("login");
    document.getElementById("inpQuickLoginEmail")?.focus();
  });

  // Quick Email Login for Returning Users (Loads Saved Profile & Tests from Database)
  const triggerQuickEmailLogin = async () => {
    const email = document.getElementById("inpQuickLoginEmail")?.value.trim().toLowerCase() || "";
    if (!email) {
      alert("Please enter your registered email address to login.");
      document.getElementById("inpQuickLoginEmail")?.focus();
      return;
    }
    const btn = document.getElementById("btnQuickEmailLogin");
    if (btn) btn.disabled = true;
    try {
      await performQuickLogin({ email });
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  document.getElementById("btnQuickEmailLogin")?.addEventListener("click", triggerQuickEmailLogin);
  document.getElementById("inpQuickLoginEmail")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      triggerQuickEmailLogin();
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
          const ok = await ensurePersonAndSessionReady("baseline");
          if (!ok) return;
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
    if (!chips) return;
    speakInstruction(2, `Listen carefully to these five words: ${chips}`);
  });

  document.getElementById("btnDismissSafety")?.addEventListener("click", () => {
    document.getElementById("safetyBanner")?.classList.add("hidden");
  });

  // Start or Resume Personalized Baseline 7-Test Session from Home
  const startBaselineFlow = async () => {
    const ok = await ensurePersonAndSessionReady("baseline");
    if (!ok) return;
    const nextStep = Math.min(5, (currentSession?.results?.length || 0) + 1);
    handleStepTransition(nextStep);
    switchSection("session");
  };
  // Hero "Start 7 Guided Tests" button: If not logged in yet, switch to Sign Up tab or start if fields filled
  document.getElementById("btnQuickStartSession")?.addEventListener("click", async () => {
    if (currentPerson && currentPerson.id) {
      await startBaselineFlow();
      return;
    }
    const rawName = document.getElementById("inpPersonName")?.value.trim() || "";
    const rawAge = document.getElementById("inpPersonAge")?.value.trim() || "";
    if (rawName && rawAge) {
      await startBaselineFlow();
    } else {
      setGuestAuthTabMode("signup");
      document.getElementById("inpPersonEmail")?.focus();
    }
  });
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
    setGuestAuthTabMode("edit");
  });
  document.getElementById("btnCancelEditProfile")?.addEventListener("click", async () => {
    if (currentPerson && (currentPerson.id || currentPerson.name)) {
      let sessions = [];
      let meds = [];
      try {
        sessions = (await listSessions(currentPerson.id)) || [];
        meds = (await listMedicines(currentPerson.id)) || [];
      } catch (_e) { }
      renderHomePatientDashboard(currentPerson, sessions, meds);
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
    toggleExistingUserPromptUI(null);

    ["inpPersonEmail", "inpPersonName", "inpPersonAge", "inpPersonOccupation", "inpQuickLoginEmail"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    document.querySelectorAll(".chk-symptom, .chk-condition").forEach((chk) => {
      chk.checked = false;
    });

    const badge = document.getElementById("activePersonBadge");
    if (badge) badge.textContent = "Login / Sign Up";
    const onboardBadge = document.getElementById("onboardStatusBadge");
    if (onboardBadge) onboardBadge.textContent = "AI Personalized";

    renderHomePatientDashboard(null, []);
    switchSection("home");
  };

  document.getElementById("btnHeaderLogout")?.addEventListener("click", handleLogout);
  document.getElementById("btnLogoutProfile")?.addEventListener("click", handleLogout);

  // Header Account Button: If logged in, go to Home Hub; if logged out, go to Home Login Tab
  document.getElementById("btnOpenAuthModal")?.addEventListener("click", () => {
    switchSection("home");
    if (!currentPerson || !currentPerson.id) {
      setGuestAuthTabMode("login");
      document.getElementById("inpQuickLoginEmail")?.focus();
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

  // Start or Resume Post-Visit AI Adaptive Follow-Up Session
  const startAdaptiveFlow = async () => {
    const ok = await ensurePersonAndSessionReady("post_visit_adaptive");
    if (!ok) return;
    const nextStep = Math.min(5, (currentSession?.results?.length || 0) + 1);
    handleStepTransition(nextStep);
    switchSection("session");
  };
  document.getElementById("btnStartAdaptiveFollowupTest")?.addEventListener("click", startAdaptiveFlow);

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
    stopQuestionAudio();
    let rem = 60;
    const disp = document.getElementById("t3TimerDisplay");
    if (disp) disp.textContent = "60s";

    activeMicField = "t3Response";
    toggleSpeechRecognition("t3Response");

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
      const targetTime = currentSession?.item_prompts?.clock_target_time || "";

      const aiRes = await evaluateClockVisionAI(dataUri, targetTime, { strokes: clockStrokes });
      const chk = aiRes.checklist || {};
      const observations = aiRes.observations || "";

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

      if (currentStep < 5) {
        handleStepTransition(currentStep + 1);
      } else {
        showAILoadingOverlay(true);
        try {
          const elapsedSessionSec = Math.max(60, Math.round((Date.now() - sessionStartTimeMs) / 1000));
          currentCompletedSession = await completeSession(currentSession.id, elapsedSessionSec);
          currentSession = null;
          currentReport = null;
          currentStep = 1;
          clearAllTestInputsForNewSession({});
          const persistBadge = document.getElementById("sessionPersistenceBadge");
          if (persistBadge) persistBadge.textContent = "Session Completed ✓";
          const allSessions = (await listSessions(currentPerson.id)) || [];
          let meds = [];
          try {
            meds = (await listMedicines(currentPerson.id)) || [];
          } catch (_e) { }
          renderCompletedSessionResult(
            currentCompletedSession,
            allSessions.filter((s) => s.completed)
          );
          renderHomePatientDashboard(currentPerson, allSessions, meds);
          switchSection("result");
          if (voiceGuideActive) {
            speakInstruction(5, "All five cognitive tests completed. Your screening outcome is ready.");
          }
        } finally {
          showAILoadingOverlay(false);
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
    const meds = (await listMedicines(currentPerson.id)) || [];
    const sessions = (await listSessions(currentPerson.id)) || [];
    renderHomePatientDashboard(currentPerson, sessions, meds);
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
