from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import uuid
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from backend.app.core.config import settings
from backend.app.db.seed_data import build_seed_doctors, build_seed_safety_resources

logger = logging.getLogger("yaadasht.db")

LOCAL_DB_STORE_PATH = Path(__file__).resolve().parents[3] / "uploads" / "yaadasht_db_store.json"
LOCAL_DB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
_LOCAL_DB_CACHE: Dict[str, Dict[str, Any]] = {}


def _load_local_db_cache() -> Dict[str, Dict[str, Any]]:
    global _LOCAL_DB_CACHE
    if "pytest" in sys.modules:
        return {}
    if _LOCAL_DB_CACHE:
        return _LOCAL_DB_CACHE
    if LOCAL_DB_STORE_PATH.exists():
        try:
            raw = json.loads(LOCAL_DB_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _LOCAL_DB_CACHE = raw
        except Exception as exc:
            logger.debug("Local DB load notice: %s", exc)
    return _LOCAL_DB_CACHE


def _save_local_db_collection(col_name: Optional[str], data_dict: Dict[str, Any]) -> None:
    if not col_name or "pytest" in sys.modules:
        return
    if col_name in ("doctors", "scoring_config", "safety_resources"):
        return
    try:
        cache = _load_local_db_cache()
        cache[col_name] = dict(data_dict)
        LOCAL_DB_STORE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Local DB save notice: %s", exc)


class MongoSyncedDict(dict):
    """
    Dictionary backed by a MongoDB collection when MongoDB is connected,
    plus automatic local disk persistence (uploads/yaadasht_db_store.json)
    so user accounts, JWT profiles, patients, and test sessions survive restarts.
    """

    def __init__(self, collection=None, initial: Optional[Dict[str, Any]] = None, col_name: Optional[str] = None):
        super().__init__()
        self._col = collection
        self._col_name = col_name or (getattr(collection, "name", None) if collection is not None else None)

        if self._col_name and "pytest" not in sys.modules:
            cache = _load_local_db_cache()
            saved_col = cache.get(self._col_name)
            if isinstance(saved_col, dict):
                for k, v in saved_col.items():
                    super().__setitem__(str(k), v)

        if self._col is not None:
            try:
                for doc in self._col.find({}, {"_id": 0}):
                    doc_key = doc.get("_key_id") or doc.get("id") or doc.get("_key")
                    if doc_key:
                        if "_val" in doc:
                            super().__setitem__(str(doc_key), doc["_val"])
                        else:
                            clean_doc = {k: v for k, v in doc.items() if k != "_key_id"}
                            super().__setitem__(str(doc_key), clean_doc)
            except Exception as exc:
                logger.warning("MongoDB collection load notice: %s", exc)
        if initial:
            missing_docs = []
            for k, v in initial.items():
                if k not in self:
                    super().__setitem__(str(k), v)
                    if self._col is not None:
                        if isinstance(v, dict) and "id" in v:
                            payload = {dk: dv for dk, dv in v.items() if dk != "_id"}
                        else:
                            payload = {"_key": str(k), "_val": v}
                        missing_docs.append({"_key_id": str(k), **payload})
            if missing_docs and self._col is not None:
                try:
                    for doc_item in missing_docs:
                        self._col.replace_one(
                            {"_key_id": doc_item["_key_id"]},
                            doc_item,
                            upsert=True,
                        )
                except Exception as exc:
                    logger.debug("MongoDB seed notice: %s", exc)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        _save_local_db_collection(self._col_name, self)
        if self._col is not None:
            try:
                if isinstance(value, dict) and "id" in value:
                    payload = {k: v for k, v in value.items() if k != "_id"}
                else:
                    payload = {"_key": str(key), "_val": value}
                self._col.replace_one({"_key_id": str(key)}, {"_key_id": str(key), **payload}, upsert=True)
            except Exception as exc:
                logger.debug("MongoDB write notice: %s", exc)

    def pop(self, key: str, *args) -> Any:
        res = super().pop(key, *args)
        _save_local_db_collection(self._col_name, self)
        if self._col is not None:
            try:
                self._col.delete_one({"_key_id": str(key)})
            except Exception as exc:
                logger.debug("MongoDB delete notice: %s", exc)
        return res


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
    Repository enforcing Row Level Security (RLS) semantics for all 17 Yaadasht tables,
    backed by MongoDB when MONGODB_URI is reachable.
    """

    def __init__(self) -> None:
        self._mongo_client = None
        self._mongo_db = None
        self.mongo_connected = False
        self._init_mongo()
        self.reset(clear_mongo=False)

    def _init_mongo(self) -> None:
        uri = (settings.MONGODB_URI or "").strip()
        if not uri or "pytest" in sys.modules:
            return
        try:
            from pymongo import MongoClient

            client = MongoClient(uri, serverSelectionTimeoutMS=2500, connectTimeoutMS=2500, socketTimeoutMS=4000)
            client.admin.command("ping")
            self._mongo_client = client
            self._mongo_db = client[settings.MONGODB_DB_NAME or "yaadasht_db"]
            self.mongo_connected = True
            logger.info("Connected to MongoDB database '%s'", settings.MONGODB_DB_NAME)
        except Exception as exc:
            self._mongo_client = None
            self._mongo_db = None
            self.mongo_connected = False
            logger.info("MongoDB not reachable at '%s' (%s); using persistent disk store.", uri, exc)

    def _col(self, name: str):
        return self._mongo_db[name] if (self.mongo_connected and self._mongo_db is not None) else None

    def get_db_status(self) -> Dict[str, Any]:
        return {
            "engine": "mongodb" if self.mongo_connected else "persistent_disk_store",
            "mongodb_connected": self.mongo_connected,
            "mongodb_uri_configured": bool((settings.MONGODB_URI or "").strip()),
            "database_name": settings.MONGODB_DB_NAME,
        }

    def reset(self, clear_mongo: bool = False) -> None:
        if clear_mongo and self.mongo_connected and self._mongo_db is not None:
            for col_name in (
                "profiles", "credentials", "persons", "consents", "test_sessions",
                "test_results", "scoring_config", "reports", "report_shares",
                "doctors", "favorite_doctors", "doctor_problem_reports",
                "doctor_documents", "medicines", "medicine_logs",
                "monthly_summaries", "reminders", "safety_resources",
            ):
                try:
                    self._mongo_db[col_name].delete_many({})
                except Exception:
                    pass

        self.profiles: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("profiles"), col_name="profiles")
        self.credentials: Dict[str, Dict[str, str]] = MongoSyncedDict(self._col("credentials"), col_name="credentials")
        self.persons: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("persons"), col_name="persons")
        self.consents: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("consents"), col_name="consents")
        self.test_sessions: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("test_sessions"), col_name="test_sessions")
        self.test_results: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("test_results"), col_name="test_results")
        self.scoring_config: Dict[str, Dict[str, Any]] = MongoSyncedDict(
            self._col("scoring_config"), initial=deepcopy(DEFAULT_SCORING_CONFIG), col_name="scoring_config"
        )
        self.reports: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("reports"), col_name="reports")
        self.report_shares: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("report_shares"), col_name="report_shares")
        self.doctors: Dict[str, Dict[str, Any]] = MongoSyncedDict(
            self._col("doctors"), initial=build_seed_doctors(), col_name="doctors"
        )
        self.favorite_doctors: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("favorite_doctors"), col_name="favorite_doctors")
        self.doctor_problem_reports: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("doctor_problem_reports"), col_name="doctor_problem_reports")
        self.doctor_documents: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("doctor_documents"), col_name="doctor_documents")
        self.medicines: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("medicines"), col_name="medicines")
        self.medicine_logs: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("medicine_logs"), col_name="medicine_logs")
        self.monthly_summaries: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("monthly_summaries"), col_name="monthly_summaries")
        self.reminders: Dict[str, Dict[str, Any]] = MongoSyncedDict(self._col("reminders"), col_name="reminders")
        self.safety_resources: Dict[str, Dict[str, Any]] = MongoSyncedDict(
            self._col("safety_resources"), initial=build_seed_safety_resources(), col_name="safety_resources"
        )
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
        language: str = "en",
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
            "role": "caregiver",
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
            "education_level": (data.get("education_level") or "secondary").strip(),
            "occupation": (data.get("occupation") or "retired").strip(),
            "living_situation": (data.get("living_situation") or "with_family").strip(),
            "family_history_dementia": bool(data.get("family_history_dementia", False)),
            "medical_conditions": list(data.get("medical_conditions") or []),
            "observed_symptoms": list(data.get("observed_symptoms") or []),
            "symptom_duration_months": int(data.get("symptom_duration_months") or 6),
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
        allowed_fields = (
            "name",
            "age",
            "gender",
            "city",
            "education_level",
            "occupation",
            "living_situation",
            "family_history_dementia",
            "medical_conditions",
            "observed_symptoms",
            "symptom_duration_months",
        )
        for k, v in updates.items():
            if v is not None and k in allowed_fields:
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

