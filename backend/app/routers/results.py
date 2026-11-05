from typing import Dict
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from backend.app.core.auth import get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import TestResultResponse, TestResultSubmit
from backend.app.services.safety import check_text_for_emergency
from backend.app.services.scoring import (
    score_animal_naming,
    score_clock_drawing,
    score_dot_connecting,
    score_orientation,
    score_picture_story,
    score_word_recall,
)
from backend.app.services.transcribe import transcriber

router = APIRouter(prefix="/sessions", tags=["Cognitive Test Results"])


EXPECTED_TEST_TYPES = {
    1: "orientation",
    2: "word_recall_immediate",
    3: "animal_naming",
    4: "picture_story",
    5: "clock_drawing",
    6: "dot_connecting",
    7: "word_recall_delayed",
}


@router.post(
    "/{session_id}/results",
    response_model=TestResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_test_result(
    session_id: str,
    payload: TestResultSubmit,
    current_user: Dict = Depends(get_current_user),
) -> TestResultResponse:
    session = db.test_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test session not found.",
        )
    person = db.get_person_for_owner(session["person_id"], current_user["id"])

    expected_type = EXPECTED_TEST_TYPES.get(payload.test_number)
    if payload.test_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Test {payload.test_number} must have test_type '{expected_type}'.",
        )

    transcript = transcriber.transcribe(fallback_text=payload.raw_response)
    version = session.get("item_bank_version", 1)

    if payload.test_number == 1:
        norm_score, raw_pts, max_pts, markers = score_orientation(
            answers=payload.answers,
            raw_response=transcript,
            person_city=person["city"],
        )
    elif payload.test_number == 2:
        norm_score, raw_pts, max_pts, markers = score_word_recall(
            transcript=transcript,
            item_bank_version=version,
        )
    elif payload.test_number == 3:
        norm_score, raw_pts, max_pts, markers = score_animal_naming(
            transcript=transcript,
        )
    elif payload.test_number == 4:
        norm_score, raw_pts, max_pts, markers = score_picture_story(
            transcript=transcript,
            item_bank_version=version,
            timing=payload.timing,
        )
    elif payload.test_number == 5:
        norm_score, raw_pts, max_pts, markers = score_clock_drawing(
            checklist=payload.clock_checklist,
        )
    elif payload.test_number == 6:
        norm_score, raw_pts, max_pts, markers = score_dot_connecting(
            timing=payload.timing,
        )
    elif payload.test_number == 7:
        norm_score, raw_pts, max_pts, markers = score_word_recall(
            transcript=transcript,
            item_bank_version=version,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid test number.",
        )

    safety_check = check_text_for_emergency(transcript)

    if payload.audio_path:
        db.storage_files[payload.audio_path] = b"recorded-audio-placeholder"

    # Replace existing test_number entry if retried within the same session
    existing_id = None
    for rid, existing in db.test_results.items():
        if existing["session_id"] == session_id and existing["test_number"] == payload.test_number:
            existing_id = rid
            break

    result_id = existing_id or str(uuid.uuid4())
    needs_review = payload.test_number == 5 and not payload.confirmed_by_caregiver

    record = {
        "id": result_id,
        "session_id": session_id,
        "test_number": payload.test_number,
        "test_type": payload.test_type,
        "raw_response": transcript,
        "audio_path": payload.audio_path,
        "stroke_data": payload.stroke_data,
        "timing": payload.timing,
        "score": norm_score,
        "raw_points": raw_pts,
        "max_points": max_pts,
        "markers": markers,
        "needs_review": needs_review,
        "emergency_detected": safety_check["emergency_detected"],
        "emergency_resources": safety_check["resources"],
    }
    db.test_results[result_id] = record
    return TestResultResponse(**record)

