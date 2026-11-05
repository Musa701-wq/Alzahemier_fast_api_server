from typing import Any, Dict, List, Optional, Tuple
from backend.app.core.config import settings
from backend.app.db.repository import db


def evaluate_session_outcome(
    total_score: float,
    results: List[Dict[str, Any]],
    previous_total_score: Optional[float] = None,
) -> Tuple[str, str, str, Optional[float]]:
    """
    Evaluates one of the three outcomes from Section 6 using thresholds in scoring_config:
    - looks_fine: Total >= 75 and no override -> Retest in 3 months
    - keep_watching: Total 55 to 74, or fall of >= 10 points -> Retest in 1 month, show tips
    - see_doctor: Total < 55, or fall of >= 15 points, or delayed recall <= 1/5 together
      with >= 2 orientation errors -> Open Doctors page, offer report

    Returns (outcome, gentle_reason_with_disclaimer, next_step, score_change_from_last).
    """
    cfg = db.get_scoring_config("outcome_thresholds")
    looks_fine_min = float(cfg.get("looks_fine_min", 75.0))
    keep_watching_min = float(cfg.get("keep_watching_min", 55.0))
    keep_watching_drop = float(cfg.get("keep_watching_drop", 10.0))
    see_doctor_drop = float(cfg.get("see_doctor_drop", 15.0))
    delayed_recall_override_max = float(cfg.get("delayed_recall_override_max", 1.0))
    orientation_errors_override_min = float(cfg.get("orientation_errors_override_min", 2.0))

    score_change: Optional[float] = None
    score_drop: float = 0.0
    if previous_total_score is not None:
        score_change = round(total_score - float(previous_total_score), 2)
        score_drop = round(float(previous_total_score) - total_score, 2)

    by_num = {r["test_number"]: r for r in results}
    orientation_res = by_num.get(1)
    delayed_res = by_num.get(7)

    orientation_errors = 0.0
    if orientation_res is not None:
        raw_pts = float(orientation_res.get("raw_points", (orientation_res["score"] / 100.0) * 5.0))
        orientation_errors = max(0.0, 5.0 - raw_pts)

    delayed_raw_pts: Optional[float] = None
    if delayed_res is not None:
        delayed_raw_pts = float(delayed_res.get("raw_points", (delayed_res["score"] / 100.0) * 5.0))

    override_triggered = (
        delayed_raw_pts is not None
        and delayed_raw_pts <= delayed_recall_override_max
        and orientation_errors >= orientation_errors_override_min
    )

    disclaimer = settings.SCREENING_DISCLAIMER

    if total_score < keep_watching_min or score_drop >= see_doctor_drop or override_triggered:
        outcome = "see_doctor"
        next_step = "Open Doctors page, offer report"
        if override_triggered:
            notice = (
                "Delayed word recall and orientation responses were lower today. "
                "Sharing this recorded session with a specialist is recommended. "
                "If the person was tired or unwell, you may also retake the session after a rest."
            )
        elif score_drop >= see_doctor_drop:
            notice = (
                f"Overall session performance dropped by {score_drop} points compared with the previous session. "
                "Consulting a doctor and sharing this report is recommended."
            )
        else:
            notice = (
                "Several tasks were challenging today. Sharing this session summary with a doctor "
                "can help establish a clear baseline."
            )
        return outcome, f"{notice} {disclaimer}", next_step, score_change

    if total_score < looks_fine_min or score_drop >= keep_watching_drop:
        outcome = "keep_watching"
        next_step = "Retest in 1 month, show tips"
        if score_drop >= keep_watching_drop:
            notice = (
                f"Total score changed by {score_change} points since the last session. "
                "We suggest keeping an eye on daily routine and taking another session in 1 month."
            )
        else:
            notice = (
                "Most responses were steady, with mild difficulty on a few tasks today. "
                "We suggest retesting in 1 month and reviewing the home routine tips."
            )
        return outcome, f"{notice} {disclaimer}", next_step, score_change

    outcome = "looks_fine"
    next_step = "Retest in 3 months"
    notice = (
        "Responses across today's session were steady. "
        "We recommend taking the next check-in session in 3 months."
    )
    return outcome, f"{notice} {disclaimer}", next_step, score_change

