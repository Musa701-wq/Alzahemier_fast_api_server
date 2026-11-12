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
    scene_title: str = Field(default="")
    target_items: Optional[list[str]] = Field(default=None)


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
    return evaluate_picture_story_with_ai(
        req.description,
        scene_title=req.scene_title,
        target_items=req.target_items,
    )


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


def _pcm16le_to_flac(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    import struct

    n_samples = len(pcm_bytes) // 2
    out = bytearray(b"fLaC")
    out.extend(b"\x80\x00\x00\x22")
    block_size = 4096
    out.extend(struct.pack(">HH", block_size, block_size))
    out.extend(b"\x00\x00\x00\x00\x00\x00")
    sr_ch_bps = (sample_rate << 12) | (0 << 9) | (15 << 4) | ((n_samples >> 32) & 0x0F)
    out.extend(struct.pack(">II", sr_ch_bps, n_samples & 0xFFFFFFFF))
    out.extend(b"\x00" * 16)

    def crc8(data: bytes) -> int:
        crc = 0
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
        return crc

    def crc16(data: bytes) -> int:
        crc = 0
        for b in data:
            crc ^= b << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x8005) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
        return crc

    def utf8_uint(v: int) -> bytes:
        if v < 0x80:
            return bytes([v])
        if v < 0x800:
            return bytes([0xC0 | (v >> 6), 0x80 | (v & 0x3F)])
        return bytes([0xE0 | (v >> 12), 0x80 | ((v >> 6) & 0x3F), 0x80 | (v & 0x3F)])

    frame_num = 0
    for offset in range(0, n_samples, block_size):
        chunk = pcm_bytes[offset * 2 : (offset + block_size) * 2]
        cur_samples = len(chunk) // 2
        if cur_samples == 0:
            break
        hdr = bytearray([0xFF, 0xF8, 0x75, 0x08])
        hdr.extend(utf8_uint(frame_num))
        hdr.extend(struct.pack(">H", cur_samples - 1))
        hdr.append(crc8(hdr))
        sub = bytearray([0x02])
        samples_le = struct.unpack("<" + "h" * cur_samples, chunk)
        sub.extend(struct.pack(">" + "h" * cur_samples, *samples_le))
        frame_data = bytes(hdr + sub)
        out.extend(frame_data)
        out.extend(struct.pack(">H", crc16(frame_data)))
        frame_num += 1
    return bytes(out)


def _ensure_windows_mic_unmuted() -> Dict[str, Any]:
    """Ensure the Windows default capture microphone is not OS-muted and has 100% gain."""
    import sys

    if sys.platform != "win32":
        return {"ok": True}
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

            def __init__(self, s: str):
                u = uuid.UUID(s)
                super().__init__(
                    u.time_low,
                    u.time_mid,
                    u.time_hi_version,
                    (wintypes.BYTE * 8)(*u.bytes[8:]),
                )

        clsid_enum = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
        iid_enum = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
        iid_vol = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")

        enumerator = ctypes.c_void_p()
        if (
            ole32.CoCreateInstance(
                ctypes.byref(clsid_enum),
                None,
                23,
                ctypes.byref(iid_enum),
                ctypes.byref(enumerator),
            )
            != 0
            or not enumerator.value
        ):
            return {"ok": False}

        vt_enum = ctypes.cast(
            ctypes.cast(enumerator, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        get_default = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(vt_enum[4])

        unmuted_any = False
        for role in (0, 1, 2):
            dev = ctypes.c_void_p()
            if get_default(enumerator, 1, role, ctypes.byref(dev)) == 0 and dev.value:
                vt_dev = ctypes.cast(
                    ctypes.cast(dev, ctypes.POINTER(ctypes.c_void_p))[0],
                    ctypes.POINTER(ctypes.c_void_p),
                )
                activate = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.POINTER(GUID),
                    wintypes.DWORD,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p),
                )(vt_dev[3])
                ep_vol = ctypes.c_void_p()
                if (
                    activate(dev, ctypes.byref(iid_vol), 23, None, ctypes.byref(ep_vol)) == 0
                    and ep_vol.value
                ):
                    vt_vol = ctypes.cast(
                        ctypes.cast(ep_vol, ctypes.POINTER(ctypes.c_void_p))[0],
                        ctypes.POINTER(ctypes.c_void_p),
                    )
                    set_vol = ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p
                    )(vt_vol[7])
                    get_vol = ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)
                    )(vt_vol[9])
                    set_mute = ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p
                    )(vt_vol[14])
                    get_mute = ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)
                    )(vt_vol[15])

                    muted = wintypes.BOOL()
                    vol = ctypes.c_float()
                    get_mute(ep_vol, ctypes.byref(muted))
                    get_vol(ep_vol, ctypes.byref(vol))
                    if muted.value:
                        set_mute(ep_vol, False, None)
                        unmuted_any = True
                    if vol.value < 0.9:
                        set_vol(ep_vol, ctypes.c_float(1.0), None)
        return {"ok": True, "unmuted": unmuted_any}
    except Exception:
        return {"ok": False}


_ensure_windows_mic_unmuted()


@router.post("/ensure-mic-ready")
def ensure_mic_ready() -> Dict[str, Any]:
    return _ensure_windows_mic_unmuted()


def _transcribe_wav_bytes_google(wav_bytes: bytes, wav_file_path: Optional[Path] = None, language: str = "en-US") -> str:
    import json
    import struct
    import subprocess
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    import speech_recognition as sr

    with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
        audio_data = sr.Recognizer().record(source)

    raw_pcm = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
    n_samples = len(raw_pcm) // 2
    if n_samples > 0:
        samples = struct.unpack("<" + "h" * n_samples, raw_pcm)
        max_amp = max((abs(s) for s in samples), default=0)
        if 15 < max_amp < 22000:
            gain = min(35.0, 26000.0 / float(max_amp))
            boosted = [max(-32767, min(32767, int(s * gain))) for s in samples]
            raw_pcm = struct.pack("<" + "h" * n_samples, *boosted)

    flac_bytes = _pcm16le_to_flac(raw_pcm, 16000)
    for lang_code in (language, "en-PK"):
        params = urlencode(
            {
                "client": "chromium",
                "lang": lang_code,
                "key": "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw",
                "pFilter": 0,
            }
        )
        url = f"http://www.google.com/speech-api/v2/recognize?{params}"

        for payload_bytes, content_type in (
            (flac_bytes, "audio/x-flac; rate=16000"),
            (raw_pcm, "audio/l16; rate=16000"),
        ):
            try:
                req = Request(url, data=payload_bytes, headers={"Content-Type": content_type})
                with urlopen(req, timeout=8) as resp:
                    resp_text = resp.read().decode("utf-8", errors="ignore")
                for line in resp_text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    results = data.get("result") or []
                    if results and results[0].get("alternative"):
                        txt = str(results[0]["alternative"][0].get("transcript", "")).strip()
                        if txt:
                            return txt
            except Exception:
                pass

    # 2. Fallback to Windows built-in SAPI SpeechRecognitionEngine if offline
    if wav_file_path and wav_file_path.exists():
        try:
            escaped_path = str(wav_file_path.resolve()).replace("'", "''")
            ps_script = (
                "Add-Type -AssemblyName System.Speech; "
                "$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
                "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
                f"$r.SetInputToWaveFile('{escaped_path}'); "
                "$res = $r.Recognize(); "
                "if ($res) { Write-Output $res.Text }; "
                "$r.Dispose()"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_script],
                text=True,
                timeout=8,
            ).strip()
            if out:
                return out
        except Exception:
            pass

    return ""


@router.post("/transcribe-audio")
def transcribe_recorded_audio(
    req: AudioTranscribeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_windows_mic_unmuted()
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
        transcript_text = _transcribe_wav_bytes_google(wav_bytes, wav_file_path=file_path, language="en-US")
    except Exception as exc:
        print(f"[STT WARNING] {exc}")
        transcript_text = ""

    return {
        "transcript": transcript_text.strip(),
        "duration_seconds": round(req.duration_seconds, 2),
        "speaking_seconds": round(req.speaking_seconds, 2),
        "pause_ms": int(req.pause_ms),
        "file_path": f"uploads/voice_recordings/{filename}",
    }
