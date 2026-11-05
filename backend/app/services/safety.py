from typing import Any, Dict, List, Optional
from backend.app.db.repository import db


def check_text_for_emergency(text: Optional[str]) -> Dict[str, Any]:
    """
    Scans spoken transcript or typed note for emergency phrases
    (self-harm, abuse, missing or unresponsive person).
    Emergency contact numbers are loaded strictly from the admin-managed
    safety_resources table and are never hardcoded.
    """
    active_resources: List[Dict[str, Any]] = [
        res for res in db.safety_resources.values() if res.get("active", True)
    ]

    if not text or not text.strip():
        return {
            "emergency_detected": False,
            "matched_category": None,
            "message": "No safety concern detected.",
            "resources": [],
        }

    normalized = text.strip().lower()
    phrase_groups = db.get_scoring_config("emergency_phrases")

    for category, phrases in phrase_groups.items():
        for phrase in phrases:
            if phrase.lower() in normalized:
                return {
                    "emergency_detected": True,
                    "matched_category": category,
                    "message": (
                        "An urgent safety concern was detected. If someone is in immediate danger, "
                        "please contact an emergency helpline or local hospital immediately."
                    ),
                    "resources": active_resources,
                }

    return {
        "emergency_detected": False,
        "matched_category": None,
        "message": "No safety concern detected.",
        "resources": [],
    }

