from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from backend.app.core.auth import get_current_user
from backend.app.db.repository import db

router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.get("")
def list_my_reminders(current_user: Dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    items = [
        rem for rem in db.reminders.values() if rem["owner_id"] == current_user["id"]
    ]
    items.sort(key=lambda r: r["due_at"])
    return items


@router.post("/dispatch-due")
def dispatch_due_reminders(current_user: Dict = Depends(get_current_user)) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    dispatched = 0
    for rem in db.reminders.values():
        if rem["owner_id"] == current_user["id"] and not rem["sent"] and rem["due_at"] <= now_iso:
            rem["sent"] = True
            dispatched += 1
    return {"dispatched_count": dispatched}

