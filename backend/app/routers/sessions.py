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
    db.get_person_for_owner(payload.person_id, current_user["id"])

    # Consent check before recording any session
    if not (
        db.has_active_consent(payload.person_id, "audio")
        and db.has_active_consent(payload.person_id, "data_processing")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active audio and data_processing consents are required before starting a session.",
        )

    existing_sessions = [
        s for s in db.test_sessions.values() if s["person_id"] == payload.person_id
    ]
    banks = db.get_scoring_config("item_banks").get("versions", {"1": {}})
    available_versions = sorted(int(k) for k in banks.keys())
    next_version = available_versions[len(existing_sessions) % len(available_versions)]
    prompts = banks.get(str(next_version), {})

    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "person_id": payload.person_id,
        "session_date": utc_now_iso(),
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
    prev_score = prev_sessions[-1]["total_score"] if prev_sessions else None

    total_score, domain_scores = compute_session_aggregates(session_results)
    outcome, reason, next_step, score_change = evaluate_session_outcome(
        total_score=total_score,
        results=session_results,
        previous_total_score=prev_score,
    )

    session["total_score"] = total_score
    session["domain_scores"] = domain_scores
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
    db.get_person_for_owner(person_id, current_user["id"])
    sessions = [
        s for s in db.test_sessions.values() if s["person_id"] == person_id
    ]
    sessions.sort(key=lambda s: s["session_date"])
    output: List[SessionResponse] = []
    for s in sessions:
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

