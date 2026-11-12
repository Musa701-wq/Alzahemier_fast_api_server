let activeSessionPrompts = {};

export function setActiveSessionPrompts(prompts = {}) {
  activeSessionPrompts = prompts || {};
}

function getDynamicTestMetadata(stepNum, prompts = activeSessionPrompts) {
  const p = prompts || {};
  const oq = p.orientation_questions || {};
  const words = Array.isArray(p.words_en) && p.words_en.length > 0
    ? p.words_en.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    : [];
  const fluencyCat = p.fluency_category || "";
  const fluencyPrompt = p.fluency_prompt || "";
  const sceneTitle = p.picture_scene_title || "";
  const storyPrompt = p.picture_story_prompt || "";
  const clockTime = p.clock_target_time || "";

  const metaMap = {
    1: {
      domain: "Test 1 of 5 · Orientation Domain (AI-Tailored)",
      title: "1. Orientation (Time & Place Assessment)",
      instruction:
        oq.instruction ||
        "Please answer the 5 orientation questions below about today's day, date, month, season, and your city.",
      speech_prompt: `${oq.day || "What day of the week is today?"} ${oq.date || "What is today's date?"} ${oq.month || "What month is it?"} ${oq.season || "What season is it?"} ${oq.city || "Which city are you in right now?"}`,
    },
    2: {
      domain: "Test 2 of 5 · Immediate Memory Domain (AI Non-Repeating Words)",
      title: `2. Immediate Word Recall (${words.join(" · ")})`,
      instruction: `Listen carefully as the voice examiner reads your 5 personalized words (${words.join(", ")}), then repeat them back in any order.`,
      speech_prompt: `Listen carefully to these five words: ${words.join(", ")}. Please repeat them back into the microphone in any order.`,
    },
    3: {
      domain: "Test 3 of 5 · Verbal Fluency Domain (AI Category)",
      title: `3. 60-Second Verbal Fluency (${fluencyCat})`,
      instruction: fluencyPrompt,
      speech_prompt: fluencyPrompt,
    },
    4: {
      domain: "Test 4 of 5 · Language & Visual Description Domain",
      title: `4. Picture Story (${sceneTitle})`,
      instruction: storyPrompt,
      speech_prompt: storyPrompt,
    },
    5: {
      domain: "Test 5 of 5 · Delayed Memory Domain",
      title: "5. Delayed Word Recall (Recall Your Earlier 5 Words)",
      instruction:
        p.test5_instruction ||
        p.test7_instruction ||
        "Without looking back at Test 2, speak or type the 5 words that were presented to you earlier in this session.",
      speech_prompt:
        p.test5_instruction ||
        p.test7_instruction ||
        "Now, without looking back, what were the five words you learned earlier in this session? Please speak them aloud into the microphone.",
    },
  };
  return metaMap[stepNum] || metaMap[1];
}

export function switchSection(sectionId) {
  try {
    localStorage.setItem("yaadasht_active_section", sectionId);
  } catch {}
  document.querySelectorAll(".page-section").forEach((sec) => {
    sec.classList.toggle("active", sec.dataset.page === sectionId);
  });

  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.section === sectionId);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

export function renderActiveTestStep(stepNum, customPrompts = null) {
  if (customPrompts) {
    activeSessionPrompts = customPrompts;
  }
  try {
    localStorage.setItem("yaadasht_active_step", String(stepNum));
  } catch {}
  const meta = getDynamicTestMetadata(stepNum, activeSessionPrompts);
  const domEl = document.getElementById("currentTestDomainTag");
  const titleEl = document.getElementById("currentTestTitle");
  const instEl = document.getElementById("currentTestInstruction");
  const subEl = document.getElementById("voiceExaminerSubtitle");

  if (domEl) domEl.textContent = meta.domain;
  if (titleEl) titleEl.textContent = meta.title;
  if (instEl) instEl.textContent = meta.instruction;
  if (subEl) subEl.textContent = `Test ${stepNum} of 5 · Dynamic AI session ready for verbal response`;

  for (let i = 1; i <= 5; i++) {
    const pane = document.getElementById(`testPane${i}`);
    if (pane) pane.classList.toggle("hidden", i !== stepNum);
  }

  document.querySelectorAll("#testProgressDots .step-pill").forEach((pill) => {
    const s = Number(pill.dataset.step);
    pill.classList.remove("active", "done");
    if (s < stepNum) pill.classList.add("done");
    else if (s === stepNum) pill.classList.add("active");
  });

  const prevBtn = document.getElementById("btnPrevTest");
  if (prevBtn) prevBtn.disabled = stepNum <= 1;

  const nextLabel = document.getElementById("btnNextTestLabel");
  if (nextLabel) {
    nextLabel.textContent =
      stepNum < 5
        ? `Save Test ${stepNum} & Continue →`
        : "Save Test 5 & Complete Session ✓";
  }
}

let repeatTimeoutId = null;
let currentRepeatPass = 0;
let isSpeechPaused = false;
let isSpeechActive = false;

function updateQuestionPlayerUI(state, passNum = 0, maxPasses = 2) {
  const playBtn = document.getElementById("btnPlayQuestion");
  const pauseBtn = document.getElementById("btnPauseQuestion");
  const stopBtn = document.getElementById("btnStopQuestion");
  const badge = document.getElementById("questionRepeatBadge");

  if (state === "speaking") {
    if (playBtn) playBtn.textContent = `🔊 Playing (${passNum}/${maxPasses})...`;
    if (pauseBtn) {
      pauseBtn.disabled = false;
      pauseBtn.textContent = "⏸ Pause";
    }
    if (stopBtn) stopBtn.disabled = false;
    if (badge) badge.textContent = `Repeat: ${passNum} / ${maxPasses}`;
  } else if (state === "paused") {
    if (playBtn) playBtn.textContent = `⏸ Paused (${passNum}/${maxPasses})`;
    if (pauseBtn) {
      pauseBtn.disabled = false;
      pauseBtn.textContent = "▶ Resume";
    }
    if (stopBtn) stopBtn.disabled = false;
    if (badge) badge.textContent = `Paused (${passNum}/${maxPasses})`;
  } else if (state === "done") {
    if (playBtn) playBtn.textContent = "▶ Play Question";
    if (pauseBtn) {
      pauseBtn.disabled = true;
      pauseBtn.textContent = "⏸ Pause";
    }
    if (stopBtn) stopBtn.disabled = true;
    if (badge) badge.textContent = `Done: ${maxPasses} / ${maxPasses} ✓`;
  } else {
    if (playBtn) playBtn.textContent = "▶ Play Question";
    if (pauseBtn) {
      pauseBtn.disabled = true;
      pauseBtn.textContent = "⏸ Pause";
    }
    if (stopBtn) stopBtn.disabled = true;
    if (badge) badge.textContent = `Repeat: 0 / ${maxPasses}`;
  }
}

export function stopQuestionAudio() {
  if (repeatTimeoutId) {
    clearTimeout(repeatTimeoutId);
    repeatTimeoutId = null;
  }
  isSpeechPaused = false;
  isSpeechActive = false;
  currentRepeatPass = 0;
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  updateQuestionPlayerUI("idle", 0, 2);
}

export function pauseOrResumeQuestion() {
  if (!("speechSynthesis" in window) || !isSpeechActive) return;
  if (!isSpeechPaused) {
    window.speechSynthesis.pause();
    isSpeechPaused = true;
    updateQuestionPlayerUI("paused", currentRepeatPass, 2);
  } else {
    window.speechSynthesis.resume();
    isSpeechPaused = false;
    updateQuestionPlayerUI("speaking", currentRepeatPass, 2);
  }
}

/**
 * Speaks the current question aloud up to maxRepeats (default 2 times) and then automatically stops.
 */
export function speakInstruction(stepNum, customText = null, maxRepeats = 2) {
  if (!("speechSynthesis" in window)) return;
  stopQuestionAudio();

  const meta = getDynamicTestMetadata(stepNum, activeSessionPrompts);
  const text = customText || meta.speech_prompt || meta.instruction;
  if (!text) return;

  isSpeechActive = true;
  isSpeechPaused = false;

  const speakPass = (passNumber) => {
    if (!isSpeechActive) return;
    currentRepeatPass = passNumber;
    updateQuestionPlayerUI("speaking", passNumber, maxRepeats);

    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    utter.rate = 0.93;
    utter.pitch = 1.0;

    utter.onend = () => {
      if (!isSpeechActive) return;
      if (passNumber < maxRepeats) {
        repeatTimeoutId = setTimeout(() => {
          if (isSpeechActive) {
            speakPass(passNumber + 1);
          }
        }, 1200);
      } else {
        isSpeechActive = false;
        isSpeechPaused = false;
        updateQuestionPlayerUI("done", maxRepeats, maxRepeats);
      }
    };

    utter.onerror = () => {
      if (passNumber >= maxRepeats) {
        isSpeechActive = false;
        updateQuestionPlayerUI("idle", 0, maxRepeats);
      }
    };

    window.speechSynthesis.speak(utter);
  };

  speakPass(1);
}

export function showEmergencyBanner(safetyData) {
  const banner = document.getElementById("safetyBanner");
  const msgEl = document.getElementById("safetyBannerMessage");
  const numsEl = document.getElementById("safetyBannerNumbers");
  if (!banner) return;

  if (!safetyData || !safetyData.emergency_detected) {
    banner.classList.add("hidden");
    return;
  }

  if (msgEl) msgEl.textContent = safetyData.message;
  if (numsEl) {
    const resources = safetyData.resources || [];
    numsEl.innerHTML = resources
      .map(
        (r) =>
          `<a href="tel:${r.phone}" class="safety-num-pill">📞 ${r.label}: ${r.phone}</a>`
      )
      .join("");
  }
  banner.classList.remove("hidden");
}

export function renderCompletedSessionResult(session, allSessions = []) {
  const outcomeTitles = {
    looks_fine: "Outcome: Looks Fine (Low Risk — Retest in 3 Months)",
    keep_watching: "Outcome: Keep Watching (Moderate Variability — Retest in 1 Month)",
    see_doctor: "Outcome: See a Doctor (Specialist Consultation Recommended)",
  };

  const outTag = document.getElementById("resOutcomeTag");
  if (outTag) outTag.textContent = session.disclaimer || "Screening Aid Only";

  const headline = document.getElementById("resOutcomeHeadline");
  if (headline) {
    headline.textContent = outcomeTitles[session.outcome] || "Session Completed";
  }

  const reason = document.getElementById("resOutcomeGentleText");
  if (reason) {
    reason.textContent = session.outcome_reason || session.disclaimer || "";
  }

  const scoreVal = document.getElementById("resTotalScoreVal");
  if (scoreVal) {
    scoreVal.textContent = session.total_score !== null ? `${Math.round(session.total_score)}` : "—";
  }

  const stepBadge = document.getElementById("resNextStepBadge");
  if (stepBadge) {
    stepBadge.textContent = `Next Step: ${session.next_step || "Follow up"}`;
  }

  const homeOut = document.getElementById("homeLastOutcomeText");
  if (homeOut) {
    homeOut.textContent = `Score: ${session.total_score}/100 — ${outcomeTitles[session.outcome] || session.outcome}`;
  }
  const homeRetest = document.getElementById("homeNextRetestText");
  if (homeRetest) {
    homeRetest.textContent = session.next_step || "Retest scheduled.";
  }

  const dom = session.domain_scores || {};
  const deltas = session.domain_deltas || {};
  const fmtDom = (key) => {
    if (dom[key] === undefined) return "—";
    const d = deltas[key];
    const deltaStr = d !== undefined && d !== null ? ` (${d >= 0 ? "+" : ""}${d} vs last)` : "";
    return `${dom[key]} / 100${deltaStr}`;
  };
  const domOrientation = document.getElementById("domOrientation");
  if (domOrientation) domOrientation.textContent = fmtDom("orientation");
  const domMemory = document.getElementById("domMemory");
  if (domMemory) domMemory.textContent = fmtDom("memory");
  const domLanguage = document.getElementById("domLanguage");
  if (domLanguage) domLanguage.textContent = fmtDom("language");
  const domPlanning = document.getElementById("domPlanning");
  if (domPlanning) domPlanning.textContent = fmtDom("planning");
  const domAttention = document.getElementById("domAttention");
  if (domAttention) domAttention.textContent = fmtDom("attention");

  const perTestEl = document.getElementById("resPerTestList");
  if (perTestEl && session.results) {
    perTestEl.innerHTML = session.results
      .map((r) => {
        const markerLabels = (r.markers || []).map((m) => m.label).join(", ");
        return `
          <div class="finding-card">
            <strong>Test ${r.test_number}: ${r.test_type.replace(/_/g, " ").toUpperCase()} — ${r.score} / 100</strong>
            <span>Raw Points: ${r.raw_points} / ${r.max_points}${markerLabels ? ` · Notes: ${markerLabels}` : ""}</span>
          </div>
        `;
      })
      .join("");
  }

  const trendEl = document.getElementById("resTrendList");
  const completedList = (allSessions.length ? allSessions : [session]).filter(
    (s) => s.completed && s.total_score !== null
  );
  if (trendEl && completedList.length) {
    trendEl.innerHTML = completedList
      .map((s, idx) => {
        const dateShort = new Date(s.session_date).toLocaleDateString();
        return `
          <div class="trend-bar-row">
            <span>Session #${idx + 1} (${dateShort})</span>
            <div class="trend-bar-track">
              <div class="trend-bar-fill" style="width: ${Math.min(100, Math.max(5, s.total_score))}%"></div>
            </div>
            <strong>${s.total_score}/100</strong>
          </div>
        `;
      })
      .join("");
  }
}

export function renderDoctorsList(doctors, onShareWithDoctor = null) {
  const container = document.getElementById("doctorsListContainer");
  if (!container) return;

  if (!doctors || doctors.length === 0) {
    container.innerHTML = `
      <div class="finding-card" style="grid-column: 1 / -1;">
        <strong>No doctor listings match the current filter</strong>
        <span>Try clearing or changing the city, specialty, or consultation mode filter above.</span>
      </div>
    `;
    return;
  }

  container.innerHTML = doctors
    .map(
      (doc) => `
      <div class="doctor-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <strong style="font-size:16.5px;">${doc.name}</strong>
            ${doc.verified ? '<span class="verified-pill">Verified PMDC ✓</span>' : ""}
          </div>
          <p style="font-size:13px;color:var(--green-dark);font-weight:700;text-transform:uppercase;">
            ${doc.specialty.replace(/_/g, " ")} · ${doc.qualifications}
          </p>
          <p style="font-size:13.5px;color:var(--text-mid);margin-top:6px;">
            🏥 <strong>${doc.clinic_name}</strong> — ${doc.address}, ${doc.city}<br/>
            💰 Consultation Fee: PKR ${doc.fee_pkr} · Languages: ${(doc.languages || []).join(", ").toUpperCase()} · Experience: ${doc.years_experience} yrs
          </p>
        </div>
        <div class="doctor-card__actions">
          <a href="tel:${doc.phone}" class="btn-upload-main" style="text-decoration:none;">
            📞 Call ${doc.phone}
          </a>
          <button type="button" class="mode-pill btn-share-doctor-card" data-share-doc="${doc.id}">
            📤 Share My Report
          </button>
        </div>
      </div>
    `
    )
    .join("");

  if (onShareWithDoctor) {
    container.querySelectorAll(".btn-share-doctor-card").forEach((btn) => {
      btn.addEventListener("click", () => onShareWithDoctor(btn.dataset.shareDoc));
    });
  }
}

export function renderConfirmedMedicines(medicines, onLogDose) {
  const container = document.getElementById("confirmedMedicinesList");
  const homeMedEl = document.getElementById("homeMedicineQuickText");
  if (!container) return;

  const activeMeds = (medicines || []).filter((m) => m.active);
  const kpiMedCount = document.getElementById("kpiMedicineCount");
  if (kpiMedCount) {
    kpiMedCount.textContent = `${activeMeds.length} Active`;
  }
  if (homeMedEl && activeMeds.length > 0) {
    homeMedEl.textContent = activeMeds
      .map((m) => `${m.name} (${m.dose}) at ${(m.reminder_times || []).join(", ")}`)
      .join(" · ");
  }

  if (!activeMeds.length) {
    container.innerHTML = `
      <div class="finding-card">
        <strong>No confirmed medicines yet</strong>
        <span>Confirm a medicine on the left to start logging daily Taken or Skipped doses.</span>
      </div>
    `;
    return;
  }

  container.innerHTML = activeMeds
    .map(
      (m) => `
      <div class="finding-card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <div>
            <strong>💊 ${m.name} — ${m.dose} (${m.frequency_per_day}x/day at ${(m.reminder_times || []).join(", ")})</strong>
            <span style="display:block;">${m.instructions || "Confirmed against doctor prescription report"}</span>
          </div>
          <div style="display:flex;gap:6px;">
            <button type="button" class="btn-save" data-med-id="${m.id}" data-dose-status="taken">✓ Taken</button>
            <button type="button" class="mode-pill" data-med-id="${m.id}" data-dose-status="skipped">⏭ Skipped</button>
          </div>
        </div>
      </div>
    `
    )
    .join("");

  container.querySelectorAll("[data-med-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      onLogDose(btn.dataset.medId, btn.dataset.doseStatus);
    });
  });
}
