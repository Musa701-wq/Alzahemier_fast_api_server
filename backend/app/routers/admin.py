import csv
import io
from typing import Any, Dict, List
import uuid
from fastapi import APIRouter, Body, Depends, HTTPException, status
from backend.app.core.auth import require_admin
from backend.app.db.repository import db, utc_now_iso
from backend.app.models.schemas import (
    DoctorCreate,
    DoctorResponse,
    DoctorUpdate,
    SafetyResourceCreate,
    ScoringConfigUpdate,
)

router = APIRouter(prefix="/admin", tags=["Admin Management"])


@router.post("/doctors", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
def admin_create_doctor(
    payload: DoctorCreate,
    admin_user: Dict = Depends(require_admin),
) -> DoctorResponse:
    doc_id = str(uuid.uuid4())
    data = payload.model_dump()
    if data.get("verified") and not data.get("last_verified_at"):
        data["last_verified_at"] = utc_now_iso()
    record = {"id": doc_id, **data}
    db.doctors[doc_id] = record
    return DoctorResponse(**record)


@router.patch("/doctors/{doctor_id}", response_model=DoctorResponse)
def admin_update_doctor(
    doctor_id: str,
    payload: DoctorUpdate,
    admin_user: Dict = Depends(require_admin),
) -> DoctorResponse:
    doc = db.doctors.get(doctor_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        if v is not None:
            doc[k] = v
    if updates.get("verified") and not doc.get("last_verified_at"):
        doc["last_verified_at"] = utc_now_iso()
    db.doctors[doctor_id] = doc
    return DoctorResponse(**doc)


@router.delete("/doctors/{doctor_id}")
def admin_delete_doctor(
    doctor_id: str,
    admin_user: Dict = Depends(require_admin),
) -> Dict[str, str]:
    if doctor_id not in db.doctors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )
    db.doctors.pop(doctor_id, None)
    return {"status": "deleted", "doctor_id": doctor_id}


@router.post("/doctors/import")
def admin_import_doctors_csv(
    csv_content: str = Body(..., media_type="text/plain"),
    admin_user: Dict = Depends(require_admin),
) -> Dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_content.strip()))
    imported: List[str] = []

    for row in reader:
        if not row.get("name") or not row.get("phone"):
            continue
        doc_id = str(uuid.uuid4())
        languages = [
            lang.strip()
            for lang in (row.get("languages") or "ur").split("|")
            if lang.strip()
        ]
        days = [
            d.strip()
            for d in (row.get("available_days") or "").split("|")
            if d.strip()
        ]
        verified_flag = str(row.get("verified", "false")).strip().lower() in ("true", "1", "yes")
        record = {
            "id": doc_id,
            "name": row["name"].strip(),
            "specialty": (row.get("specialty") or "neurologist").strip(),
            "qualifications": (row.get("qualifications") or "MBBS").strip(),
            "pmdc_number": (row.get("pmdc_number") or "").strip() or None,
            "clinic_name": (row.get("clinic_name") or "Clinic").strip(),
            "city": (row.get("city") or "Lahore").strip(),
            "area": (row.get("area") or "").strip() or None,
            "address": (row.get("address") or "Clinic Address").strip(),
            "latitude": float(row["latitude"]) if row.get("latitude") else None,
            "longitude": float(row["longitude"]) if row.get("longitude") else None,
            "phone": row["phone"].strip(),
            "email": (row.get("email") or "").strip() or None,
            "fee_pkr": int(row.get("fee_pkr") or 0),
            "mode": (row.get("mode") or "in_person").strip(),
            "languages": languages,
            "years_experience": int(row.get("years_experience") or 0),
            "gender": (row.get("gender") or "").strip() or None,
            "available_days": days,
            "verified": verified_flag,
            "source": (row.get("source") or "csv_import").strip(),
            "last_verified_at": utc_now_iso() if verified_flag else None,
            "active": True,
        }
        db.doctors[doc_id] = record
        imported.append(doc_id)

    return {"imported_count": len(imported), "doctor_ids": imported}


@router.patch("/scoring-config")
def admin_update_scoring_config(
    payload: ScoringConfigUpdate,
    admin_user: Dict = Depends(require_admin),
) -> Dict[str, Any]:
    updated = db.set_scoring_config(payload.key, payload.value)
    return {"key": payload.key, "value": updated, "updated_at": utc_now_iso()}


@router.post("/safety-resources", status_code=status.HTTP_201_CREATED)
def admin_create_safety_resource(
    payload: SafetyResourceCreate,
    admin_user: Dict = Depends(require_admin),
) -> Dict[str, Any]:
    res_id = str(uuid.uuid4())
    record = {
        "id": res_id,
        "label": payload.label.strip(),
        "phone": payload.phone.strip(),
        "description": payload.description.strip(),
        "last_verified_at": payload.last_verified_at or utc_now_iso(),
        "active": payload.active,
    }
    db.safety_resources[res_id] = record
    return record

