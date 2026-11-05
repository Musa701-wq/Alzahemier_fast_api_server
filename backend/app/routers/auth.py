from typing import Dict
from fastapi import APIRouter, Depends, status
from backend.app.core.auth import create_access_token, get_current_user
from backend.app.db.repository import db
from backend.app.models.schemas import AuthResponse, LoginRequest, ProfileResponse, SignupRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest) -> AuthResponse:
    profile = db.create_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        language=payload.language,
        role=payload.role,
    )
    token = create_access_token(profile["id"], profile["role"])
    return AuthResponse(access_token=token, profile=ProfileResponse(**profile))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    profile = db.authenticate_user(payload.email, payload.password)
    token = create_access_token(profile["id"], profile["role"])
    return AuthResponse(access_token=token, profile=ProfileResponse(**profile))


@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: Dict = Depends(get_current_user)) -> ProfileResponse:
    return ProfileResponse(**current_user)

