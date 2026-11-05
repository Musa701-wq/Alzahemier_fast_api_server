from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Dict, List
from fastapi import HTTPException, status
from backend.app.db.repository import db, utc_now_iso


MEDICINE_SAFETY_NOTICE = (
    "Yaadasht only reminds you of medicines confirmed from your own doctor's report. "
    "Never double, skip, or change a dose without asking your doctor or pharmacist."
)


def schedule_medicine_reminders(owner_id: str, medicine: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Creates daily reminder entries strictly for user-confirmed medicines.
    """
    if not medicine.get("confirmed_by_user"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot schedule reminders for unconfirmed medicines.",
        )

    times = medicine.get("reminder_times") or ["09:00"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created: List[Dict[str, Any]] = []

    for hhmm in times:
        rem_id = str(uuid.uuid4())
        due_iso = f"{today_str}T{hhmm}:00+00:00"
        rem = {
            "id": rem_id,
            "owner_id": owner_id,
            "type": "medicine",
            "medicine_id": medicine["id"],
            "due_at": due_iso,
            "sent": False,
        }
        db.reminders[rem_id] = rem
        created.append(rem)

    return created


def schedule_retest_reminder(owner_id: str, days_ahead: int = 30) -> Dict[str, Any]:
    """
    Creates a follow-up cognitive retest reminder (default 90 days for looks_fine,
    30 days for keep_watching or post-visit follow-up).
    """
    rem_id = str(uuid.uuid4())
    due_dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    rem = {
        "id": rem_id,
        "owner_id": owner_id,
        "type": "retest",
        "medicine_id": None,
        "due_at": due_dt.isoformat(),
        "sent": False,
    }
    db.reminders[rem_id] = rem
    return rem

