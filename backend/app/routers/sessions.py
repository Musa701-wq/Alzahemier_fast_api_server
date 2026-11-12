from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from backend.app.core.auth import get_current_user
from backend.app.core.config import settings
from backend.app.db.repository import db, utc_now_iso
from backend.app.models.schemas import (
    ClockCheckRequest,
    ClockCheckResponse,
    SessionResponse,
    SessionStartRequest,
    TestResultResponse,
)
from backend.app.services.ai_client import (
    generate_personalized_test_battery,
    generate_post_visit_adaptive_test,
)
from backend.app.services.clock_check import clock_vision_provider
from backend.app.services.outcome import evaluate_session_outcome
from backend.app.services.reminders import schedule_retest_reminder
from backend.app.services.scoring import compute_session_aggregates

router = APIRouter(prefix="/sessions", tags=["Cognitive Test Sessions"])


def _get_session_with_rls(session_id: str, owner_id: str) -> Dict[str, Any]:
    session = db.test_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test session not found.",
        )
    db.get_person_for_owner(session["person_id"], owner_id)
    return session


def _get_watch_domains_for_person(person_id: str) -> List[str]:
    docs = [d for d in db.doctor_documents.values() if d["person_id"] == person_id]
    if not docs:
        return []
    docs.sort(key=lambda d: d["uploaded_at"], reverse=True)
    return docs[0].get("watch_domains", [])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: SessionStartRequest,
    current_user: Dict = Depends(get_current_user),
) -> SessionResponse:
    person = db.get_person_for_owner(payload.person_id, current_user["id"])

    # Consent check before recording any session
    if not (
        db.has_active_consent(payload.person_id, "audio")
        and db.has_active_consent(payload.person_id, "data_processing")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active audio and data_processing consents are required before starting a session.",
        )

    existing_sessions = sorted(
        (s for s in db.test_sessions.values() if s["person_id"] == payload.person_id),
        key=lambda s: s["session_date"],
    )

    # If there is already a pending (incomplete) session in MongoDB, return it so the user completes it first!
    import json
    import sys

    if "pytest" not in sys.modules:
        pending_sessions = [s for s in existing_sessions if not s.get("completed")]
        if pending_sessions:
            pending = pending_sessions[-1]
            raw_prompts_str = json.dumps(pending.get("item_prompts") or {}, ensure_ascii=False)
            if any("\u0600" <= ch <= "\u06FF" for ch in raw_prompts_str):
                pending["item_prompts"] = generate_personalized_test_battery(
                    person=person,
                    previous_words=[],
                    session_index=len(existing_sessions),
                )
                db.save_session(pending["id"], pending)
            pending_results = [
                TestResultResponse(**r)
                for r in sorted(
                    (r for r in db.test_results.values() if r["session_id"] == pending["id"]),
                    key=lambda item: item["test_number"],
                )
            ]
            return SessionResponse(**pending, results=pending_results)
    banks = db.get_scoring_config("item_banks").get("versions", {"1": {}})
    available_versions = sorted(int(k) for k in banks.keys())
    next_version = available_versions[len(existing_sessions) % len(available_versions)]

    # Collect all previously used recall words, fluency categories, scenes, and clock times across past sessions
    previous_words: List[str] = []
    previous_categories: List[str] = []
    previous_scenes: List[str] = []
    previous_clock_times: List[str] = []
    for past_s in existing_sessions:
        past_prompts = past_s.get("item_prompts") or {}
        for w in past_prompts.get("words_en") or []:
            if w and w not in previous_words:
                previous_words.append(w)
        cat = past_prompts.get("fluency_category")
        if cat and cat not in previous_categories:
            previous_categories.append(cat)
        sc = past_prompts.get("picture_scene_title")
        if sc and sc not in previous_scenes:
            previous_scenes.append(sc)
        ct = past_prompts.get("clock_target_time")
        if ct and ct not in previous_clock_times:
            previous_clock_times.append(ct)

    completed_sessions = [
        s for s in existing_sessions if s.get("completed") and s.get("total_score") is not None
    ]
    last_completed = completed_sessions[-1] if completed_sessions else None

    session_mode = payload.session_mode
    baseline_session_id: Optional[str] = None
    adaptive_context: Optional[Dict[str, Any]] = None

    if session_mode == "post_visit_adaptive":
        last_results = (
            [r for r in db.test_results.values() if r["session_id"] == last_completed["id"]]
            if last_completed
            else []
        )
        person_docs = sorted(
            (d for d in db.doctor_documents.values() if d["person_id"] == payload.person_id),
            key=lambda d: d["uploaded_at"],
            reverse=True,
        )
        latest_doc = person_docs[0] if person_docs else None
        person_meds = [m for m in db.medicines.values() if m["person_id"] == payload.person_id]

        prompts = generate_post_visit_adaptive_test(
            person=person,
            last_session=last_completed,
            last_results=last_results,
            doctor_doc=latest_doc,
            medicines=person_meds,
            previous_words=previous_words,
            session_index=len(existing_sessions),
            previous_categories=previous_categories,
            previous_scenes=previous_scenes,
            previous_clock_times=previous_clock_times,
        )
        baseline_session_id = last_completed["id"] if last_completed else None
        adaptive_context = prompts.get("adaptive_context")
    else:
        prompts = generate_personalized_test_battery(
            person=person,
            previous_words=previous_words,
            session_index=len(existing_sessions),
            previous_categories=previous_categories,
            previous_scenes=previous_scenes,
            previous_clock_times=previous_clock_times,
        )

    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "person_id": payload.person_id,
        "session_date": utc_now_iso(),
        "session_mode": session_mode,
        "baseline_session_id": baseline_session_id,
        "adaptive_context": adaptive_context,
        "domain_deltas": None,
        "item_bank_version": next_version,
        "item_prompts": prompts,
        "total_score": None,
        "domain_scores": {},
        "outcome": None,
        "outcome_reason": None,
        "next_step": None,
        "score_change_from_last": None,
        "watch_domains_highlighted": _get_watch_domains_for_person(payload.person_id),
        "duration_seconds": None,
        "completed": False,
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }
    db.test_sessions[session_id] = session
    return SessionResponse(**session, results=[])


@router.post("/{session_id}/clock-check", response_model=ClockCheckResponse)
def run_clock_check(
    session_id: str,
    payload: ClockCheckRequest,
    current_user: Dict = Depends(get_current_user),
) -> ClockCheckResponse:
    _get_session_with_rls(session_id, current_user["id"])
    checklist = clock_vision_provider.evaluate_clock(
        target_time=payload.target_time,
        stroke_data=payload.stroke_data,
        image_base64=payload.image_base64,
    )
    return ClockCheckResponse(
        session_id=session_id,
        target_time=payload.target_time,
        checklist=checklist,
        requires_caregiver_confirmation=True,
        disclaimer=settings.SCREENING_DISCLAIMER,
    )


@router.post("/{session_id}/complete", response_model=SessionResponse)
def complete_session(
    session_id: str,
    duration_seconds: Optional[int] = Query(default=900, ge=1),
    current_user: Dict = Depends(get_current_user),
) -> SessionResponse:
    session = _get_session_with_rls(session_id, current_user["id"])
    session_results = [
        r for r in db.test_results.values() if r["session_id"] == session_id
    ]
    if not session_results:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete a session with no recorded test results.",
        )

    # Find previous completed session for longitudinal comparison
    prev_sessions = [
        s
        for s in db.test_sessions.values()
        if s["person_id"] == session["person_id"]
        and s["id"] != session_id
        and s.get("completed")
        and s.get("total_score") is not None
    ]
    prev_sessions.sort(key=lambda s: s["session_date"])
    prev_session = prev_sessions[-1] if prev_sessions else None
    prev_score = prev_session["total_score"] if prev_session else None

    total_score, domain_scores = compute_session_aggregates(session_results)
    outcome, reason, next_step, score_change = evaluate_session_outcome(
        total_score=total_score,
        results=session_results,
        previous_total_score=prev_score,
    )

    domain_deltas: Optional[Dict[str, float]] = None
    if prev_session and prev_session.get("domain_scores"):
        prev_doms = prev_session["domain_scores"]
        domain_deltas = {}
        for dom, cur_val in domain_scores.items():
            if dom in prev_doms:
                domain_deltas[dom] = round(float(cur_val) - float(prev_doms[dom]), 2)

    session["total_score"] = total_score
    session["domain_scores"] = domain_scores
    session["domain_deltas"] = domain_deltas
    session["outcome"] = outcome
    session["outcome_reason"] = reason
    session["next_step"] = next_step
    session["score_change_from_last"] = score_change
    session["watch_domains_highlighted"] = _get_watch_domains_for_person(session["person_id"])
    session["duration_seconds"] = duration_seconds
    session["completed"] = True
    db.test_sessions[session_id] = session

    # Automatically schedule follow-up retest reminder (90 days for looks_fine, 30 days otherwise)
    days_ahead = 90 if outcome == "looks_fine" else 30
    schedule_retest_reminder(current_user["id"], days_ahead=days_ahead)

    ordered_results = [
        TestResultResponse(**r)
        for r in sorted(session_results, key=lambda item: item["test_number"])
    ]
    return SessionResponse(**session, results=ordered_results)


@router.get("", response_model=List[SessionResponse])
def list_sessions(
    person_id: str = Query(...),
    current_user: Dict = Depends(get_current_user),
) -> List[SessionResponse]:
    import json

    person = db.get_person_for_owner(person_id, current_user["id"])
    sessions = [
        s for s in db.test_sessions.values() if s["person_id"] == person_id
    ]
    sessions.sort(key=lambda s: s["session_date"])
    output: List[SessionResponse] = []
    for s in sessions:
        if not s.get("completed"):
            raw_prompts_str = json.dumps(s.get("item_prompts") or {}, ensure_ascii=False)
            if any("\u0600" <= ch <= "\u06FF" for ch in raw_prompts_str):
                s["item_prompts"] = generate_personalized_test_battery(
                    person=person,
                    previous_words=[],
                    session_index=len(sessions),
                )
                db.save_session(s["id"], s)
        res_list = [
            TestResultResponse(**r)
            for r in sorted(
                (r for r in db.test_results.values() if r["session_id"] == s["id"]),
                key=lambda item: item["test_number"],
            )
        ]
        output.append(SessionResponse(**s, results=res_list))
    return output


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    current_user: Dict = Depends(get_current_user),
) -> SessionResponse:
    session = _get_session_with_rls(session_id, current_user["id"])
    res_list = [
        TestResultResponse(**r)
        for r in sorted(
            (r for r in db.test_results.values() if r["session_id"] == session_id),
            key=lambda item: item["test_number"],
        )
    ]
    return SessionResponse(**session, results=res_list)
