from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from backend.app.core.auth import create_access_token, get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import AuthResponse, LoginRequest, ProfileResponse, SignupRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])


class EmailAccessRequest(BaseModel):
    email: Optional[str] = Field(default="")
    mode: str = Field(default="login", description="'login' or 'register'")
    full_name: Optional[str] = Field(default="")


class CheckExistingUserRequest(BaseModel):
    email: Optional[str] = Field(default="")
    name: Optional[str] = Field(default="")


def _find_existing_user_and_person(email: str = "", name: str = ""):
    norm_email = (email or "").strip().lower()
    norm_name = (name or "").strip().lower()

    matched_profile = None
    matched_person = None

    # 1. Check by email in profiles
    if norm_email and "@" in norm_email and not norm_email.endswith("@yaadasht.local"):
        for prof in db.profiles.values():
            if prof.get("email", "").strip().lower() == norm_email:
                matched_profile = prof
                matched_person = db.get_person_by_owner(prof["id"])
                if matched_person:
                    break

    # 2. Check by patient name (or email stored on person/owner) in persons collection
    if not matched_person and norm_name and len(norm_name) >= 2:
        for p in db.persons.values():
            if p.get("name", "").strip().lower() == norm_name:
                matched_person = p
                matched_profile = db.profiles.get(p["owner_id"])
                break

    # 3. Also allow login input where user typed patient name into the email/login box
    if not matched_person and norm_email and "@" not in norm_email and len(norm_email) >= 2:
        for p in db.persons.values():
            if p.get("name", "").strip().lower() == norm_email:
                matched_person = p
                matched_profile = db.profiles.get(p["owner_id"])
                break

    return matched_profile, matched_person


@router.post("/check-existing")
def check_existing_user(payload: CheckExistingUserRequest) -> Dict[str, Any]:
    prof, person = _find_existing_user_and_person(email=payload.email or "", name=payload.name or "")
    if not prof and not person:
        return {"exists": False}

    owner_id = prof["id"] if prof else person["owner_id"]
    if not person and prof:
        person = db.get_person_by_owner(owner_id)

    # Only flag as existing saved patient if a person record or non-guest email exists
    if not person and (not prof or prof.get("email", "").endswith("@yaadasht.local")):
        return {"exists": False}

    sessions = db.list_sessions(person["id"], owner_id) if person else []
    email_val = prof.get("email", "") if prof else ""
    if email_val.endswith("@yaadasht.local"):
        email_val = ""

    return {
        "exists": True,
        "email": email_val,
        "person_name": person.get("name") if person else (prof.get("full_name") if prof else "Saved Patient"),
        "age": person.get("age") if person else None,
        "city": person.get("city") if person else None,
        "session_count": len(sessions),
    }


@router.post("/email-access")
def email_access(payload: EmailAccessRequest) -> Dict[str, Any]:
    norm_email = (payload.email or "").strip().lower()
    norm_name = (payload.full_name or "").strip()

    existing_profile, existing_person = _find_existing_user_and_person(
        email=norm_email,
        name=norm_name if payload.mode != "login" else (norm_name or norm_email),
    )

    if payload.mode == "login":
        if not existing_profile and not existing_person:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this Email or Patient Name in the database.",
            )
        owner_id = existing_profile["id"] if existing_profile else existing_person["owner_id"]
        if not existing_profile:
            existing_profile = db.profiles.get(owner_id) or {
                "id": owner_id,
                "email": norm_email or "user@yaadasht.local",
                "full_name": existing_person.get("name", "Caregiver"),
            }
        if not existing_person:
            existing_person = db.get_person_by_owner(owner_id)
        token = create_access_token(
            owner_id,
            email=existing_profile.get("email", norm_email),
            full_name=existing_profile.get("full_name", norm_name),
        )
        return {
            "exists": True,
            "already_registered": True,
            "email": existing_profile.get("email", norm_email),
            "access_token": token,
            "profile": existing_profile,
            "person": existing_person,
        }

    # mode == 'register': if email or patient name already has a saved person in DB, tell user to login!
    if existing_profile or existing_person:
        owner_id = existing_profile["id"] if existing_profile else existing_person["owner_id"]
        person = existing_person or db.get_person_by_owner(owner_id)
        prof = existing_profile or db.profiles.get(owner_id) or {
            "id": owner_id,
            "email": norm_email,
            "full_name": norm_name or (person.get("name") if person else "Caregiver"),
        }
        if person:
            token = create_access_token(
                owner_id,
                email=prof.get("email", norm_email),
                full_name=prof.get("full_name", norm_name),
            )
            return {
                "already_registered": True,
                "email": prof.get("email", norm_email),
                "access_token": token,
                "profile": prof,
                "person": person,
                "message": "This user is already registered in the database. Please login instead of filling the form again.",
            }
        token = create_access_token(
            owner_id,
            email=prof.get("email", norm_email),
            full_name=prof.get("full_name", norm_name),
        )
        return {
            "already_registered": False,
            "email": prof.get("email", norm_email),
            "access_token": token,
            "profile": prof,
            "person": None,
        }

    if not norm_email or "@" not in norm_email:
        norm_email = f"user_{norm_name.lower().replace(' ', '_') or 'patient'}@yaadasht.local"

    new_profile = db.create_user(
        email=norm_email,
        password="password123",
        full_name=norm_name or norm_email.split("@")[0],
        language="en",
    )
    token = create_access_token(
        new_profile["id"],
        email=new_profile["email"],
        full_name=new_profile["full_name"],
    )
    return {
        "already_registered": False,
        "email": new_profile["email"],
        "access_token": token,
        "profile": new_profile,
        "person": None,
    }


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest) -> AuthResponse:
    profile = db.create_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        language=payload.language,
    )
    token = create_access_token(profile["id"])
    return AuthResponse(access_token=token, profile=ProfileResponse(**profile))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    profile = db.authenticate_user(payload.email, payload.password)
    token = create_access_token(profile["id"])
    return AuthResponse(access_token=token, profile=ProfileResponse(**profile))


@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: Dict = Depends(get_current_user)) -> ProfileResponse:
    return ProfileResponse(**current_user)
