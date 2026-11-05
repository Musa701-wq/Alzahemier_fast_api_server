from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from backend.app.core.auth import get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import (
    ConsentCreate,
    ConsentResponse,
    PersonCreate,
    PersonResponse,
    PersonUpdate,
)

router = APIRouter(tags=["Persons & Consents"])


@router.post("/persons", response_model=PersonResponse, status_code=status.HTTP_201_CREATED)
def create_person(
    payload: PersonCreate,
    current_user: Dict = Depends(get_current_user),
) -> PersonResponse:
    person = db.create_person(current_user["id"], payload.model_dump())
    return PersonResponse(**person)


@router.get("/persons/me", response_model=PersonResponse)
def get_my_person(current_user: Dict = Depends(get_current_user)) -> PersonResponse:
    person = db.get_person_by_owner(current_user["id"])
    if not person:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No person profile exists for this account yet.",
        )
    return PersonResponse(**person)


@router.patch("/persons/{person_id}", response_model=PersonResponse)
def update_person(
    person_id: str,
    payload: PersonUpdate,
    current_user: Dict = Depends(get_current_user),
) -> PersonResponse:
    updated = db.update_person(person_id, current_user["id"], payload.model_dump(exclude_unset=True))
    return PersonResponse(**updated)


@router.delete("/persons/{person_id}")
def delete_person(
    person_id: str,
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    deleted_counts = db.delete_person_and_all_data(person_id, current_user["id"])
    return {
        "status": "deleted",
        "person_id": person_id,
        "deleted_counts": deleted_counts,
    }


@router.post("/consents", response_model=ConsentResponse, status_code=status.HTTP_201_CREATED)
def grant_consent(
    payload: ConsentCreate,
    current_user: Dict = Depends(get_current_user),
) -> ConsentResponse:
    consent = db.create_consent(
        owner_id=current_user["id"],
        person_id=payload.person_id,
        consent_type=payload.type,
        granted=payload.granted,
    )
    return ConsentResponse(**consent)


@router.delete("/consents/{consent_id}", response_model=ConsentResponse)
def revoke_consent(
    consent_id: str,
    current_user: Dict = Depends(get_current_user),
) -> ConsentResponse:
    consent = db.revoke_consent(consent_id, current_user["id"])
    return ConsentResponse(**consent)

