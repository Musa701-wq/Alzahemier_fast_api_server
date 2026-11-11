from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from backend.app.core.auth import create_access_token, get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import AuthResponse, LoginRequest, ProfileResponse, SignupRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])


class EmailAccessRequest(BaseModel):
    email: str = Field(..., min_length=3)
    mode: str = Field(default="login", description="'login' or 'register'")
    full_name: Optional[str] = Field(default="Caregiver Account")


@router.post("/email-access")
def email_access(payload: EmailAccessRequest) -> Dict[str, Any]:
    norm_email = payload.email.strip().lower()
    existing_profile = None
    for prof in db.profiles.values():
        if prof.get("email", "").strip().lower() == norm_email:
            existing_profile = prof
            break

    if payload.mode == "login":
        if not existing_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email in the database. Please register below.",
            )
        token = create_access_token(existing_profile["id"])
        person = db.get_person_by_owner(existing_profile["id"])
        return {
            "exists": True,
            "access_token": token,
            "profile": existing_profile,
            "person": person,
        }

    # mode == 'register': if email already has a saved person in DB, tell user to login!
    if existing_profile:
        person = db.get_person_by_owner(existing_profile["id"])
        if person:
            token = create_access_token(existing_profile["id"])
            return {
                "already_registered": True,
                "access_token": token,
                "profile": existing_profile,
                "person": person,
                "message": "This email is already registered in the database. Loading your existing profile and tests.",
            }
        token = create_access_token(existing_profile["id"])
        return {
            "already_registered": False,
            "access_token": token,
            "profile": existing_profile,
            "person": None,
        }

    new_profile = db.create_user(
        email=norm_email,
        password="password123",
        full_name=payload.full_name or norm_email.split("@")[0],
        language="en",
    )
    token = create_access_token(new_profile["id"])
    return {
        "already_registered": False,
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
