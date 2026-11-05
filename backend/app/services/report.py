import re
from typing import Any, Dict, List, Optional, Set
from fastapi import HTTPException, status
from backend.app.core.config import settings


def _extract_numeric_tokens(text: str) -> List[float]:
    if not text:
        return []
    matches = re.findall(r"(?<![a-zA-Z_])-?\d+(?:\.\d+)?", text)
    out: List[float] = []
    for m in matches:
        try:
            out.append(round(float(m), 2))
        except ValueError:
            pass
    return out


def _collect_allowed_numbers(data: Any) -> Set[float]:
    allowed: Set[float] = set()
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        val = round(float(data), 2)
        allowed.add(val)
        allowed.add(float(int(round(val))))
    elif isinstance(data, str):
        for num in _extract_numeric_tokens(data):
            allowed.add(num)
            allowed.add(float(int(round(num))))
    elif isinstance(data, dict):
        for v in data.values():
            allowed.update(_collect_allowed_numbers(v))
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            allowed.update(_collect_allowed_numbers(item))
    return allowed


def verify_narrative_numbers(narrative_text: str, authoritative_record: Dict[str, Any]) -> bool:
    """
    Section 8 Anti-Hallucination Rule:
    Any text written by the LLM may only restate numbers present in the data,
    and a check compares every number in the text to the database before saving.
    Raises HTTPException(422) if an unverified number is present.
    """
    if not narrative_text or not narrative_text.strip():
        return True

    allowed = _collect_allowed_numbers(authoritative_record)
    found = _extract_numeric_tokens(narrative_text)

    for num in found:
        if num not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Anti-hallucination check failed: number {num} in narrative text "
                    "does not exist in the authoritative database record."
                ),
            )
    return True


def build_session_report_summary(
    person: Dict[str, Any],
    session: Dict[str, Any],
    results: List[Dict[str, Any]],
    trend_sessions: List[Dict[str, Any]],
    user_notes: Optional[str] = None,
    narrative_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Builds the structured one-page session report dictionary and verifies
    that any narrative text strictly matches database numbers.
    """
    per_test_lines = []
    for res in sorted(results, key=lambda r: r["test_number"]):
        per_test_lines.append(
            {
                "test_number": res["test_number"],
                "test_type": res["test_type"],
                "score": res["score"],
                "raw_points": res.get("raw_points", 0.0),
                "max_points": res.get("max_points", 10.0),
                "markers": res.get("markers", []),
            }
        )

    trend_points = [
        {
            "session_id": s["id"],
            "session_date": s["session_date"],
            "total_score": s["total_score"],
        }
        for s in trend_sessions
        if s.get("completed") and s.get("total_score") is not None
    ]

    summary_data: Dict[str, Any] = {
        "patient": {
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "city": person["city"],
        },
        "session_id": session["id"],
        "session_date": session["session_date"],
        "total_score": session["total_score"],
        "score_change_from_last": session.get("score_change_from_last"),
        "domain_scores": session.get("domain_scores", {}),
        "outcome": session.get("outcome"),
        "outcome_plain_words": session.get("outcome_reason"),
        "per_test_breakdown": per_test_lines,
        "trend": trend_points,
        "user_notes": user_notes or "",
        "footer": "Generated from a home screening, not a diagnosis.",
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }

    if narrative_text:
        verify_narrative_numbers(narrative_text, summary_data)
        summary_data["narrative_summary"] = narrative_text
    else:
        default_narrative = (
            f"Session total score is {session['total_score']} for patient aged {person['age']}."
        )
        verify_narrative_numbers(default_narrative, summary_data)
        summary_data["narrative_summary"] = default_narrative

    return summary_data

