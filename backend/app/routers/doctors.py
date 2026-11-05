from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from backend.app.core.auth import get_current_user
from backend.app.db.repository import db, utc_now_iso
from backend.app.models.schemas import DoctorProblemCreate, DoctorResponse, FavoriteCreate

router = APIRouter(tags=["Doctors Directory & Favorites"])


@router.get("/doctors", response_model=List[DoctorResponse])
def list_doctors(
    city: Optional[str] = Query(default=None),
    specialty: Optional[str] = Query(default=None),
    min_fee: Optional[int] = Query(default=None, ge=0),
    max_fee: Optional[int] = Query(default=None, ge=0),
    mode: Optional[str] = Query(default=None),
    gender: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    min_experience: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Dict = Depends(get_current_user),
) -> List[DoctorResponse]:
    docs = [d for d in db.doctors.values() if d.get("active", True)]

    if city:
        docs = [d for d in docs if d["city"].lower() == city.strip().lower()]
    if specialty:
        docs = [d for d in docs if d["specialty"].lower() == specialty.strip().lower()]
    if min_fee is not None:
        docs = [d for d in docs if d.get("fee_pkr", 0) >= min_fee]
    if max_fee is not None:
        docs = [d for d in docs if d.get("fee_pkr", 0) <= max_fee]
    if mode:
        docs = [d for d in docs if d["mode"] in (mode, "both")]
    if gender:
        docs = [d for d in docs if (d.get("gender") or "").lower() == gender.strip().lower()]
    if language:
        docs = [
            d
            for d in docs
            if any(lang.lower() == language.strip().lower() for lang in d.get("languages", []))
        ]
    if min_experience is not None:
        docs = [d for d in docs if d.get("years_experience", 0) >= min_experience]

    sliced = docs[offset : offset + limit]
    return [DoctorResponse(**d) for d in sliced]


@router.get("/doctors/{doctor_id}", response_model=DoctorResponse)
def get_doctor(
    doctor_id: str,
    current_user: Dict = Depends(get_current_user),
) -> DoctorResponse:
    doc = db.doctors.get(doctor_id)
    if not doc or not doc.get("active", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )
    return DoctorResponse(**doc)


@router.post("/favorites", status_code=status.HTTP_201_CREATED)
def add_favorite_doctor(
    payload: FavoriteCreate,
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    if payload.doctor_id not in db.doctors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )
    for fav in db.favorite_doctors.values():
        if fav["owner_id"] == current_user["id"] and fav["doctor_id"] == payload.doctor_id:
            return fav

    fav_id = str(uuid.uuid4())
    fav = {
        "id": fav_id,
        "owner_id": current_user["id"],
        "doctor_id": payload.doctor_id,
    }
    db.favorite_doctors[fav_id] = fav
    return fav


@router.delete("/favorites/{doctor_id}")
def remove_favorite_doctor(
    doctor_id: str,
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, str]:
    to_remove = None
    for fid, fav in db.favorite_doctors.items():
        if fav["owner_id"] == current_user["id"] and fav["doctor_id"] == doctor_id:
            to_remove = fid
            break
    if not to_remove:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favorite entry not found.",
        )
    db.favorite_doctors.pop(to_remove, None)
    return {"status": "removed", "doctor_id": doctor_id}


@router.post("/doctors/{doctor_id}/report-problem", status_code=status.HTTP_201_CREATED)
def report_doctor_problem(
    doctor_id: str,
    payload: DoctorProblemCreate,
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    if doctor_id not in db.doctors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )
    prob_id = str(uuid.uuid4())
    record = {
        "id": prob_id,
        "doctor_id": doctor_id,
        "owner_id": current_user["id"],
        "message": payload.message.strip(),
        "status": "open",
        "created_at": utc_now_iso(),
    }
    db.doctor_problem_reports[prob_id] = record
    return record

