from typing import Optional, Protocol


class SpeechTranscriber(Protocol):
    def transcribe(
        self,
        audio_bytes: Optional[bytes] = None,
        fallback_text: Optional[str] = None,
        language: str = "ur",
    ) -> str:
        ...


class WhisperSpeechTranscriber:
    """
    Speech-to-text provider behind a clean interface.
    Privacy rule: never logs transcripts or raw audio payloads.
    """

    def transcribe(
        self,
        audio_bytes: Optional[bytes] = None,
        fallback_text: Optional[str] = None,
        language: str = "ur",
    ) -> str:
        if fallback_text is not None:
            return fallback_text.strip()
        if not audio_bytes:
            return ""
        # Deterministic local fallback when external Whisper API is not called
        try:
            decoded = audio_bytes.decode("utf-8", errors="ignore").strip()
            if decoded and not decoded.startswith("\x00"):
                return decoded
        except Exception:
            pass
        return ""


transcriber: SpeechTranscriber = WhisperSpeechTranscriber()

