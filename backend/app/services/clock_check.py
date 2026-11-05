from typing import Any, Dict, Optional, Protocol
from backend.app.models.schemas import ClockChecklist


class ClockVisionProvider(Protocol):
    def evaluate_clock(
        self,
        target_time: str,
        stroke_data: Optional[Dict[str, Any]] = None,
        image_base64: Optional[str] = None,
    ) -> ClockChecklist:
        ...


class DefaultClockVisionProvider:
    """
    Vision checklist provider for Test 5 (Clock Drawing).
    Returns a Pydantic-validated ClockChecklist JSON that must be shown to the
    caregiver for confirmation or editing before saving.
    """

    def evaluate_clock(
        self,
        target_time: str,
        stroke_data: Optional[Dict[str, Any]] = None,
        image_base64: Optional[str] = None,
    ) -> ClockChecklist:
        if stroke_data and isinstance(stroke_data, dict):
            # Allow structured hints or stroke counts to pre-fill checklist deterministically
            if "checklist" in stroke_data and isinstance(stroke_data["checklist"], dict):
                return ClockChecklist(**stroke_data["checklist"])
            stroke_count = len(stroke_data.get("strokes", []))
            has_circle = bool(stroke_data.get("closed_circle", stroke_count >= 1))
            has_numbers = bool(stroke_data.get("twelve_numbers", stroke_count >= 13))
            has_hands = bool(stroke_data.get("two_hands", stroke_count >= 15))
            return ClockChecklist(
                closed_circle=has_circle,
                twelve_numbers=has_numbers,
                correct_order=has_numbers,
                correct_spacing=has_numbers,
                two_hands=has_hands,
                hands_match_time=bool(stroke_data.get("hands_match_time", has_hands)),
            )

        return ClockChecklist(
            closed_circle=True,
            twelve_numbers=True,
            correct_order=True,
            correct_spacing=True,
            two_hands=True,
            hands_match_time=True,
        )


clock_vision_provider: ClockVisionProvider = DefaultClockVisionProvider()

