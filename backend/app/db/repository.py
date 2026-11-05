from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import uuid
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_SCORING_CONFIG: Dict[str, Dict[str, Any]] = {
    "outcome_thresholds": {
        "looks_fine_min": 75.0,
        "keep_watching_min": 55.0,
        "keep_watching_drop": 10.0,
        "see_doctor_drop": 15.0,
        "delayed_recall_override_max": 1,
        "orientation_errors_override_min": 2,
    },
    "item_banks": {
        "versions": {
            "1": {
                "words_en": ["river", "mango", "window", "lantern", "carpet"],
                "words_ur": ["دریا", "آم", "کھڑکی", "لالٹین", "قالین"],
                "words_roman_ur": ["darya", "aam", "khirki", "laltain", "qaleen"],
                "picture_scene": "courtyard_tea_scene",
                "picture_target_items": [
                    "charpoy",
                    "teapot",
                    "cup",
                    "tree",
                    "sparrow",
                    "grandmother",
                    "child",
                    "book",
                    "courtyard",
                    "bucket",
                    "چارپائی",
                    "چائے",
                    "پیالی",
                    "درخت",
                    "چڑیا",
                    "دادی",
                    "بچہ",
                    "کتاب",
                    "صحن",
                    "بالٹی",
                ],
                "clock_target_time": "11:10",
                "dot_count": 12,
            },
            "2": {
                "words_en": ["garden", "mirror", "pigeon", "pillow", "bridge"],
                "words_ur": ["باغ", "آئینہ", "کبوتر", "تکیہ", "پل"],
                "words_roman_ur": ["baagh", "aaina", "kabootar", "takiya", "pul"],
                "picture_scene": "market_stall_scene",
                "picture_target_items": [
                    "cart",
                    "apples",
                    "scale",
                    "shopkeeper",
                    "umbrella",
                    "basket",
                    "cat",
                    "bicycle",
                    "lantern",
                    "bench",
                    "ریڑھی",
                    "سیب",
                    "ترازو",
                    "دکاندار",
                    "چھتری",
                    "ٹوککری",
                    "بلی",
                    "سائیکل",
                ],
                "clock_target_time": "02:45",
                "dot_count": 12,
            },
            "3": {
                "words_en": ["cloud", "kettle", "bangle", "stair", "orange"],
                "words_ur": ["بادل", "کیتلی", "چوڑی", "سیڑھی", "مالٹا"],
                "words_roman_ur": ["baadal", "ketli", "choori", "seerhi", "malta"],
                "picture_scene": "park_morning_scene",
                "picture_target_items": [
                    "bench",
                    "fountain",
                    "walking_stick",
                    "flowers",
                    "pigeon",
                    "grandfather",
                    "boy",
                    "kite",
                    "path",
                    "gate",
                    "بینچ",
                    "فوارہ",
                    "چھڑی",
                    "پھول",
                    "کبوتر",
                    "دادا",
                    "لڑکا",
                    "پتنگ",
                ],
                "clock_target_time": "08:20",
                "dot_count": 12,
            },
        }
    },
    "animal_lexicon": {
        "target_count_for_max_score": 15,
        "valid_animals": [
            # English
            "cat", "dog", "cow", "buffalo", "goat", "sheep", "horse", "donkey",
            "camel", "lion", "tiger", "elephant", "monkey", "deer", "bear", "wolf",
            "fox", "rabbit", "mouse", "rat", "squirrel", "crow", "sparrow", "pigeon",
            "parrot", "peacock", "eagle", "hen", "rooster", "duck", "fish", "frog",
            "snake", "turtle", "giraffe", "zebra", "leopard",
            # Roman Urdu
            "billi", "kutta", "gaaye", "bhains", "bakri", "bher", "ghora", "gadha",
            "oont", "sher", "cheetah", "haathi", "bandar", "hiran", "reech", "bheriya",
            "lomri", "khargosh", "chooha", "gilheri", "kawwa", "chiriya", "kabootar",
            "tota", "mor", "uqab", "murghi", "murgha", "battakh", "machli", "mendak",
            "saanp", "kachwa",
            # Urdu
            "بلی", "کتا", "گائے", "بھینس", "بکری", "بھیڑ", "گھوڑا", "گدھا",
            "اونٹ", "شیر", "چیتا", "ہاتھی", "بندر", "ہرن", "ریچھ", "بھیڑیا",
            "لومڑی", "خرگوش", "چوہا", "گلہری", "کوا", "چڑیا", "کبوتر",
            "طوطا", "مور", "عقاب", "مرغی", "مرغا", "بطخ", "مچھلی", "مینڈک",
            "سانپ", "کھچوا",
        ],
    },
    "picture_story_rules": {
        "max_items_target": 6,
        "min_words_for_full_fluency": 25,
        "long_pause_threshold_ms": 5000,
        "pause_penalty_points": 2.0,
    },
    "clock_drawing_rules": {
        "weights": {
            "closed_circle": 1.5,
            "twelve_numbers": 2.0,
            "correct_order": 1.5,
            "correct_spacing": 1.5,
            "two_hands": 1.5,
            "hands_match_time": 2.0,
        }
    },
    "dot_connecting_rules": {
        "target_dots": 12,
        "optimal_time_seconds": 35.0,
        "max_time_seconds": 120.0,
        "penalty_per_error": 1.5,
    },
    "emergency_phrases": {
        "self_harm": [
            "kill myself", "end my life", "suicide", "want to die",
            "khudkushi", "mar jana chahta", "apni jaan", "خودکشی",
        ],
        "abuse": [
            "hitting me", "beats me", "locked in room", "physical abuse",
            "mujhe maarte hain", "tashaddud", "تشدد",
        ],
        "missing_or_unresponsive": [
            "person is missing", "unconscious", "not breathing", "unresponsive",
            "behosh", "saans nahi", "gumshuda", "بے ہوش", "لاپتہ",
        ],
    },
}


class YaadashtRepository:
    """
    Repository enforcing Row Level Security (RLS) semantics for all 17 Yaadasht tables.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.credentials: Dict[str, Dict[str, str]] = {}
        self.persons: Dict[str, Dict[str, Any]] = {}
        self.consents: Dict[str, Dict[str, Any]] = {}
        self.test_sessions: Dict[str, Dict[str, Any]] = {}
        self.test_results: Dict[str, Dict[str, Any]] = {}
        self.scoring_config: Dict[str, Dict[str, Any]] = deepcopy(DEFAULT_SCORING_CONFIG)
        self.reports: Dict[str, Dict[str, Any]] = {}
        self.report_shares: Dict[str, Dict[str, Any]] = {}
        self.doctors: Dict[str, Dict[str, Any]] = {}
        self.favorite_doctors: Dict[str, Dict[str, Any]] = {}
        self.doctor_problem_reports: Dict[str, Dict[str, Any]] = {}
        self.doctor_documents: Dict[str, Dict[str, Any]] = {}
        self.medicines: Dict[str, Dict[str, Any]] = {}
        self.medicine_logs: Dict[str, Dict[str, Any]] = {}
        self.monthly_summaries: Dict[str, Dict[str, Any]] = {}
        self.reminders: Dict[str, Dict[str, Any]] = {}
        self.safety_resources: Dict[str, Dict[str, Any]] = {}
        self.storage_files: Dict[str, bytes] = {}

    # ------------------------------------------------------------------
    # Auth & Profiles
    # ------------------------------------------------------------------
    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        language: str = "ur",
        role: str = "user",
    ) -> Dict[str, Any]:
        norm_email = email.strip().lower()
        for cred in self.credentials.values():
            if cred["email"] == norm_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="An account with this email already exists.",
                )
        user_id = str(uuid.uuid4())
        now = utc_now_iso()
        profile = {
            "id": user_id,
            "email": norm_email,
            "full_name": full_name.strip(),
            "language": language,
            "role": role,
            "push_token": None,
            "created_at": now,
        }
        self.profiles[user_id] = profile
        self.credentials[user_id] = {
            "email": norm_email,
            "password_hash": self._hash_password(password),
        }
        return deepcopy(profile)

    def authenticate_user(self, email: str, password: str) -> Dict[str, Any]:
        norm_email = email.strip().lower()
        pw_hash = self._hash_password(password)
        for user_id, cred in self.credentials.items():
            if cred["email"] == norm_email and cred["password_hash"] == pw_hash:
                return deepcopy(self.profiles[user_id])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        prof = self.profiles.get(user_id)
        return deepcopy(prof) if prof else None

    # ------------------------------------------------------------------
    # Persons & RLS Enforcement
    # ------------------------------------------------------------------
    def create_person(self, owner_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        for existing in self.persons.values():
            if existing["owner_id"] == owner_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="One person profile per account is supported in v1.",
                )
        person_id = str(uuid.uuid4())
        person = {
            "id": person_id,
            "owner_id": owner_id,
            "name": data["name"].strip(),
            "age": data["age"],
            "gender": data["gender"].strip(),
            "city": data["city"].strip(),
            "created_at": utc_now_iso(),
        }
        self.persons[person_id] = person
        return deepcopy(person)

    def get_person_by_owner(self, owner_id: str) -> Optional[Dict[str, Any]]:
        for person in self.persons.values():
            if person["owner_id"] == owner_id:
                return deepcopy(person)
        return None

    def get_person_for_owner(self, person_id: str, owner_id: str) -> Dict[str, Any]:
        person = self.persons.get(person_id)
        if not person or person["owner_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Person profile not found or access denied by RLS.",
            )
        return deepcopy(person)

    def update_person(self, person_id: str, owner_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        person = self.get_person_for_owner(person_id, owner_id)
        for k, v in updates.items():
            if v is not None and k in ("name", "age", "gender", "city"):
                person[k] = v
        self.persons[person_id] = person
        return deepcopy(person)

    def delete_person_and_all_data(self, person_id: str, owner_id: str) -> Dict[str, int]:
        """Deletes person, all sessions, results, audio/document storage files, medicines, and reports."""
        self.get_person_for_owner(person_id, owner_id)
        deleted_counts = {"sessions": 0, "results": 0, "files": 0, "medicines": 0, "reports": 0}

        # Consents
        consent_ids = [cid for cid, c in self.consents.items() if c["person_id"] == person_id]
        for cid in consent_ids:
            self.consents.pop(cid, None)

        # Sessions & Results & Reports
        session_ids = [sid for sid, s in self.test_sessions.items() if s["person_id"] == person_id]
        for sid in session_ids:
            deleted_counts["sessions"] += 1
            self.test_sessions.pop(sid, None)
            rids = [rid for rid, r in self.test_results.items() if r["session_id"] == sid]
            for rid in rids:
                res = self.test_results.pop(rid, None)
                deleted_counts["results"] += 1
                if res and res.get("audio_path") and res["audio_path"] in self.storage_files:
                    self.storage_files.pop(res["audio_path"], None)
                    deleted_counts["files"] += 1
            rep_ids = [repid for repid, rep in self.reports.items() if rep.get("session_id") == sid]
            for repid in rep_ids:
                rep = self.reports.pop(repid, None)
                deleted_counts["reports"] += 1
                if rep and rep.get("pdf_path") and rep["pdf_path"] in self.storage_files:
                    self.storage_files.pop(rep["pdf_path"], None)
                    deleted_counts["files"] += 1

        # Documents & Medicines & Logs
        doc_ids = [did for did, d in self.doctor_documents.items() if d["person_id"] == person_id]
        for did in doc_ids:
            doc = self.doctor_documents.pop(did, None)
            if doc and doc.get("file_path") and doc["file_path"] in self.storage_files:
                self.storage_files.pop(doc["file_path"], None)
                deleted_counts["files"] += 1

        med_ids = [mid for mid, m in self.medicines.items() if m["person_id"] == person_id]
        for mid in med_ids:
            self.medicines.pop(mid, None)
            deleted_counts["medicines"] += 1
            log_ids = [lid for lid, l in self.medicine_logs.items() if l["medicine_id"] == mid]
            for lid in log_ids:
                self.medicine_logs.pop(lid, None)

        # Monthly summaries
        sum_ids = [msid for msid, ms in self.monthly_summaries.items() if ms["person_id"] == person_id]
        for msid in sum_ids:
            self.monthly_summaries.pop(msid, None)

        self.persons.pop(person_id, None)
        return deleted_counts

    # ------------------------------------------------------------------
    # Consents
    # ------------------------------------------------------------------
    def create_consent(self, owner_id: str, person_id: str, consent_type: str, granted: bool = True) -> Dict[str, Any]:
        self.get_person_for_owner(person_id, owner_id)
        cid = str(uuid.uuid4())
        consent = {
            "id": cid,
            "owner_id": owner_id,
            "person_id": person_id,
            "type": consent_type,
            "granted": granted,
            "granted_at": utc_now_iso(),
            "revoked_at": None if granted else utc_now_iso(),
        }
        self.consents[cid] = consent
        return deepcopy(consent)

    def revoke_consent(self, consent_id: str, owner_id: str) -> Dict[str, Any]:
        consent = self.consents.get(consent_id)
        if not consent or consent["owner_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Consent record not found or access denied.",
            )
        consent["granted"] = False
        consent["revoked_at"] = utc_now_iso()
        return deepcopy(consent)

    def has_active_consent(self, person_id: str, consent_type: str) -> bool:
        for c in self.consents.values():
            if c["person_id"] == person_id and c["type"] == consent_type and c["granted"] and not c["revoked_at"]:
                return True
        return False

    # ------------------------------------------------------------------
    # Scoring Config
    # ------------------------------------------------------------------
    def get_scoring_config(self, key: str) -> Dict[str, Any]:
        return deepcopy(self.scoring_config.get(key, {}))

    def set_scoring_config(self, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        self.scoring_config[key] = deepcopy(value)
        return deepcopy(value)


db = YaadashtRepository()

