import base64
import io
import time
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from backend.app.core.auth import get_current_user
from backend.app.core.config import settings
from backend.app.db.repository import db
from backend.app.services.ai_client import (
    evaluate_clock_vision_with_ai,
    evaluate_picture_story_with_ai,
    extract_prescription_with_ai,
)

router = APIRouter(prefix="/ai", tags=["AI & Multimodal Services"])

VOICE_RECORDINGS_DIR = Path(__file__).resolve().parents[3] / "uploads" / "voice_recordings"
VOICE_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


class PictureStoryAIRequest(BaseModel):
    description: str = Field(..., min_length=1)


class ClockVisionAIRequest(BaseModel):
    image_data_uri: str = Field(..., description="Data URI or URL of the drawn clock canvas")
    target_time: str = Field(default="11:10")
    stroke_data: Optional[Dict[str, Any]] = Field(default=None)


class PrescriptionExtractRequest(BaseModel):
    prescription_text: str = Field(default="")
    image_data_uri: Optional[str] = Field(default=None)


class AudioTranscribeRequest(BaseModel):
    audio_wav_base64: str = Field(..., description="Base64-encoded WAV audio recorded from microphone")
    duration_seconds: float = Field(default=0.0)
    speaking_seconds: float = Field(default=0.0)
    pause_ms: int = Field(default=0)
    step_number: int = Field(default=1)


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
        "database": db.get_db_status(),
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
    return evaluate_clock_vision_with_ai(
        image_data_uri=req.image_data_uri,
        target_time=req.target_time,
        stroke_data=req.stroke_data,
    )


@router.post("/extract-prescription")
def extract_prescription(
    req: PrescriptionExtractRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return extract_prescription_with_ai(req.prescription_text, req.image_data_uri)


@router.post("/transcribe-audio")
def transcribe_recorded_audio(
    req: AudioTranscribeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    raw_b64 = req.audio_wav_base64.strip()
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    wav_bytes = base64.b64decode(raw_b64)
    filename = f"voice_step{req.step_number}_{int(time.time() * 1000)}.wav"
    file_path = VOICE_RECORDINGS_DIR / filename
    try:
        file_path.write_bytes(wav_bytes)
    except Exception:
        pass

    transcript_text = ""
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = recognizer.record(source)
        transcript_text = recognizer.recognize_google(audio_data, language="en-US")
    except Exception:
        transcript_text = ""

    return {
        "transcript": transcript_text.strip(),
        "duration_seconds": round(req.duration_seconds, 2),
        "speaking_seconds": round(req.speaking_seconds, 2),
        "pause_ms": int(req.pause_ms),
        "file_path": f"uploads/voice_recordings/{filename}",
    }
