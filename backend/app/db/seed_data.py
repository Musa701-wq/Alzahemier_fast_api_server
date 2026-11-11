"""
Built-in reference data for the single-role (caregiver) app.

There is no admin panel. The doctor directory and emergency helplines are
maintained by the developer in this file (or in a CSV file) and are loaded
into the database every time the server starts.

To add real, verified doctors: fill in `supabase/seed/doctors.csv` using the
same columns as `supabase/seed/doctors_template.csv`. Rows from that file are
loaded automatically. If the file is missing or empty, SAMPLE_DOCTORS is used.
"""

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[3]
DOCTORS_CSV_PATH = ROOT_DIR / "supabase" / "seed" / "doctors.csv"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Real public emergency number in Pakistan (Rescue 1122).
SAFETY_RESOURCES: List[Dict[str, Any]] = [
    {
        "label": "Rescue 1122 Emergency",
        "phone": "1122",
        "description": "24/7 emergency ambulance and rescue service",
        "active": True,
    },
]

# PLACEHOLDER DATA ONLY. These are not real doctors and are marked unverified.
# Replace them with real, verified entries in supabase/seed/doctors.csv.
SAMPLE_DOCTORS: List[Dict[str, Any]] = [
    {
        "name": "Dr. Ayesha Siddiqui (Sample)",
        "specialty": "neurologist",
        "qualifications": "MBBS, FCPS (Neurology)",
        "pmdc_number": None,
        "clinic_name": "Lahore Neuro & Memory Clinic",
        "city": "Lahore",
        "address": "Jail Road, Gulberg, Lahore",
        "phone": "+92-42-0000000",
        "fee_pkr": 3000,
        "mode": "both",
        "languages": ["ur", "en"],
        "years_experience": 14,
        "gender": "female",
        "available_days": ["Mon", "Wed", "Fri"],
    },
    {
        "name": "Dr. Kamran Raza (Sample)",
        "specialty": "geriatrician",
        "qualifications": "MBBS, MRCP (Geriatric Medicine)",
        "pmdc_number": None,
        "clinic_name": "Karachi Senior Memory Care Center",
        "city": "Karachi",
        "address": "Clifton Block 5, Karachi",
        "phone": "+92-21-0000000",
        "fee_pkr": 3500,
        "mode": "in_person",
        "languages": ["ur", "en"],
        "years_experience": 18,
        "gender": "male",
        "available_days": ["Tue", "Thu", "Sat"],
    },
    {
        "name": "Dr. Salman Tariq (Sample)",
        "specialty": "memory_clinic",
        "qualifications": "MBBS, Diploma in Behavioral Neurology",
        "pmdc_number": None,
        "clinic_name": "Islamabad Memory & Brain Care Clinic",
        "city": "Islamabad",
        "address": "F-8 Markaz, Islamabad",
        "phone": "+92-51-0000000",
        "fee_pkr": 2800,
        "mode": "both",
        "languages": ["ur", "en"],
        "years_experience": 10,
        "gender": "male",
        "available_days": ["Mon", "Thu", "Sat"],
    },
]


def _split(value: str) -> List[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def _doctor_record(data: Dict[str, Any], source: str, verified: bool) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": data["name"],
        "specialty": data.get("specialty") or "neurologist",
        "qualifications": data.get("qualifications") or "MBBS",
        "pmdc_number": data.get("pmdc_number") or None,
        "clinic_name": data.get("clinic_name") or "Clinic",
        "city": data.get("city") or "",
        "area": data.get("area") or None,
        "address": data.get("address") or "",
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "phone": data["phone"],
        "email": data.get("email") or None,
        "fee_pkr": int(data.get("fee_pkr") or 0),
        "mode": data.get("mode") or "in_person",
        "languages": data.get("languages") or ["ur"],
        "years_experience": int(data.get("years_experience") or 0),
        "gender": data.get("gender") or None,
        "available_days": data.get("available_days") or [],
        "verified": verified,
        "source": source,
        "last_verified_at": _now_iso() if verified else None,
        "active": True,
    }


def load_doctors_from_csv(path: Path = DOCTORS_CSV_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("name") or not row.get("phone"):
                continue
            data = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            data["languages"] = _split(row.get("languages", "")) or ["ur"]
            data["available_days"] = _split(row.get("available_days", ""))
            data["latitude"] = float(row["latitude"]) if row.get("latitude") else None
            data["longitude"] = float(row["longitude"]) if row.get("longitude") else None
            verified = str(row.get("verified", "")).strip().lower() in ("true", "1", "yes")
            records.append(_doctor_record(data, row.get("source") or "csv_seed", verified))
    return records


def build_seed_doctors() -> Dict[str, Dict[str, Any]]:
    records = load_doctors_from_csv()
    if not records:
        records = [_doctor_record(d, "sample_placeholder", verified=False) for d in SAMPLE_DOCTORS]
    return {r["id"]: r for r in records}


def build_seed_safety_resources() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for res in SAFETY_RESOURCES:
        res_id = str(uuid.uuid4())
        out[res_id] = {"id": res_id, "last_verified_at": _now_iso(), **res}
    return out

