from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from backend.app.core.auth import get_current_user
from backend.app.core.config import settings
from backend.app.services.ai_client import (
    evaluate_clock_vision_with_ai,
    evaluate_picture_story_with_ai,
    extract_prescription_with_ai,
)

router = APIRouter(prefix="/ai", tags=["AI & Multimodal Services"])


class PictureStoryAIRequest(BaseModel):
    description: str = Field(..., min_length=1)


class ClockVisionAIRequest(BaseModel):
    image_data_uri: str = Field(..., description="Data URI or URL of the drawn clock canvas")


class PrescriptionExtractRequest(BaseModel):
    prescription_text: str = Field(default="")
    image_data_uri: Optional[str] = Field(default=None)


@router.get("/status")
def get_ai_status(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    key = settings.OPENROUTER_API_KEY.strip()
    is_configured = bool(key and key != "your_openrouter_api_key_here")
    masked_key = f"{key[:8]}...{key[-4:]}" if is_configured and len(key) > 12 else ("Configured" if is_configured else "Not Set")
    return {
        "status": "ready" if is_configured else "api_key_required",
        "provider": "OpenRouter",
        "base_url": settings.OPENROUTER_BASE_URL,
        "model": settings.OPENROUTER_MODEL,
        "is_configured": is_configured,
        "key_preview": masked_key,
    }


@router.post("/picture-story")
def analyze_picture_story(
    req: PictureStoryAIRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return evaluate_picture_story_with_ai(req.description)


@router.post("/clock-vision")
def analyze_clock_vision(
    req: ClockVisionAIRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return evaluate_clock_vision_with_ai(req.image_data_uri)


@router.post("/extract-prescription")
def extract_prescription(
    req: PrescriptionExtractRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return extract_prescription_with_ai(req.prescription_text, req.image_data_uri)

