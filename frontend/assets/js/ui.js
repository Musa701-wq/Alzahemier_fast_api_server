const TEST_METADATA = {
  1: {
    domain: "Test 1 of 7 · Orientation Domain",
    title: "1. Orientation (Time & Place Assessment)",
    instruction: "Please answer the 5 questions below about today's day, date, month, season, and your city.",
    speech_prompt: "Please tell me: What day of the week is today, what is today's date, what month is it, what season is it, and which city are you in right now? You can answer verbally or type your answers.",
  },
  2: {
    domain: "Test 2 of 7 · Immediate Memory Domain",
    title: "2. Immediate Word Recall (Repeat 5 Words)",
    instruction: "Listen carefully as the voice examiner reads 5 words, then speak them back into the microphone in any order.",
    speech_prompt: "Listen carefully to these five words: River, Mango, Window, Lantern, Carpet. Please repeat them back into the microphone in any order.",
  },
  3: {
    domain: "Test 3 of 7 · Verbal Fluency Domain",
    title: "3. Animal Naming (60 Seconds Verbal Fluency)",
    instruction: "You have 60 seconds to name as many different animals as possible aloud into the microphone.",
    speech_prompt: "You have 60 seconds to name as many different animals as you can. Press start and begin speaking animal names aloud.",
  },
  4: {
    domain: "Test 4 of 7 · Language & Visual Description Domain",
    title: "4. Picture Story (Describe the Scene Aloud)",
    instruction: "Look at the courtyard scene illustration and describe everything you see happening into the microphone.",
    speech_prompt: "Look at this courtyard scene. Please describe everything you see happening in this picture into your microphone.",
  },
  5: {
    domain: "Test 5 of 7 · Planning & Spatial Domain",
    title: "5. Clock Drawing (Set Time to 11:10)",
    instruction: "Draw a circular clock face on the canvas with all 12 numbers and draw the hands showing 11:10.",
    speech_prompt: "Draw a clock face on the canvas with all twelve numbers, and set the hands to show 11:10.",
  },
  6: {
    domain: "Test 6 of 7 · Attention & Processing Speed Domain",
    title: "6. Dot Connecting (1 to 12 Numbers)",
    instruction: "Tap the numbered circles in order from 1 up to 12 as quickly and smoothly as possible.",
    speech_prompt: "Tap the numbered circles in order from 1 up to 12 as quickly and smoothly as you can.",
  },
  7: {
    domain: "Test 7 of 7 · Delayed Memory Domain",
    title: "7. Delayed Word Recall (Recall Earlier 5 Words)",
    instruction: "Without looking back at previous cards, speak the 5 words that were presented in Test 2.",
    speech_prompt: "Now, without looking back, what were the five words you learned earlier in the test? Please speak them aloud into the microphone.",
  },
};

export function switchSection(sectionId) {
  document.querySelectorAll(".page-section").forEach((sec) => {
    sec.classList.toggle("active", sec.dataset.page === sectionId);
  });

  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.section === sectionId);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

export function renderActiveTestStep(stepNum) {
  const meta = TEST_METADATA[stepNum] || TEST_METADATA[1];
  const domEl = document.getElementById("currentTestDomainTag");
  const titleEl = document.getElementById("currentTestTitle");
  const instEl = document.getElementById("currentTestInstruction");
  const subEl = document.getElementById("voiceExaminerSubtitle");

  if (domEl) domEl.textContent = meta.domain;
  if (titleEl) titleEl.textContent = meta.title;
  if (instEl) instEl.textContent = meta.instruction;
  if (subEl) subEl.textContent = `Test ${stepNum} of 7 · Voice examiner ready for verbal response`;

  for (let i = 1; i <= 7; i++) {
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
      stepNum < 7
        ? `Save Test ${stepNum} & Continue →`
        : "Save Test 7 & Complete Session ✓";
  }
}

export function speakInstruction(stepNum, customText = null) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const meta = TEST_METADATA[stepNum] || TEST_METADATA[1];
  const text = customText || meta.speech_prompt || meta.instruction;
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "en-US";
  utter.rate = 0.95;
  utter.pitch = 1.0;
  window.speechSynthesis.speak(utter);
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

  document.getElementById("resOutcomeTag").textContent = session.disclaimer;
  document.getElementById("resOutcomeHeadline").textContent =
    outcomeTitles[session.outcome] || "Session Completed";
  document.getElementById("resOutcomeGentleText").textContent =
    session.outcome_reason || session.disclaimer;

  document.getElementById("resTotalScoreVal").textContent =
    session.total_score !== null ? `${Math.round(session.total_score)}` : "—";
  document.getElementById("resNextStepBadge").textContent =
    `Next Step: ${session.next_step || "Follow up"}`;

  const homeOut = document.getElementById("homeLastOutcomeText");
  if (homeOut) {
    homeOut.textContent = `Score: ${session.total_score}/100 — ${outcomeTitles[session.outcome] || session.outcome}`;
  }
  const homeRetest = document.getElementById("homeNextRetestText");
  if (homeRetest) {
    homeRetest.textContent = session.next_step || "Retest scheduled.";
  }

  const dom = session.domain_scores || {};
  document.getElementById("domOrientation").textContent =
    dom.orientation !== undefined ? `${dom.orientation} / 100` : "—";
  document.getElementById("domMemory").textContent =
    dom.memory !== undefined ? `${dom.memory} / 100` : "—";
  document.getElementById("domLanguage").textContent =
    dom.language !== undefined ? `${dom.language} / 100` : "—";
  document.getElementById("domPlanning").textContent =
    dom.planning !== undefined ? `${dom.planning} / 100` : "—";
  document.getElementById("domAttention").textContent =
    dom.attention !== undefined ? `${dom.attention} / 100` : "—";

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

export function renderDoctorsList(doctors) {
  const container = document.getElementById("doctorsListContainer");
  if (!container) return;

  if (!doctors || doctors.length === 0) {
    container.innerHTML = `
      <div class="finding-card" style="grid-column: 1 / -1;">
        <strong>No verified doctor listings match the current filter</strong>
        <span>Click "+ Add Verified Clinic Listing (Admin)" above to add a verified clinic record.</span>
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
          <button type="button" class="mode-pill" data-share-doc="${doc.id}">
            📤 Share My Report
          </button>
        </div>
      </div>
    `
    )
    .join("");
}

export function renderConfirmedMedicines(medicines, onLogDose) {
  const container = document.getElementById("confirmedMedicinesList");
  const homeMedEl = document.getElementById("homeMedicineQuickText");
  if (!container) return;

  const activeMeds = (medicines || []).filter((m) => m.active);
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
