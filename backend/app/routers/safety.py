from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from backend.app.core.auth import get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import SafetyCheckRequest, SafetyCheckResponse
from backend.app.services.safety import check_text_for_emergency

router = APIRouter(prefix="/safety", tags=["Safety & Emergency Resources"])


@router.get("/resources")
def list_safety_resources(current_user: Dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    return [
        res for res in db.safety_resources.values() if res.get("active", True)
    ]


@router.post("/check", response_model=SafetyCheckResponse)
def run_safety_check(
    payload: SafetyCheckRequest,
    current_user: Dict = Depends(get_current_user),
) -> SafetyCheckResponse:
    result = check_text_for_emergency(payload.text)
    return SafetyCheckResponse(**result)

