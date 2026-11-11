import base64
import hashlib
import hmac
import json
from typing import Dict, Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from backend.app.core.config import settings
from backend.app.db.repository import db

bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, role: str = "caregiver") -> str:
    payload = {"sub": user_id, "role": "caregiver"}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    sig = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        b64_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{b64_payload}.{sig}"


def decode_access_token(token: str) -> Dict[str, str]:
    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format.",
        )
    b64_payload, provided_sig = parts
    expected_sig = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        b64_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature.",
        )
    padded = b64_payload + "=" * (-len(b64_payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token payload.",
        ) from exc
    return data


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    authorization: Optional[str] = Header(default=None, include_in_schema=False),
) -> Dict:
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Bearer token.",
        )
    claims = decode_access_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim.",
        )
    profile = db.get_profile(user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User profile not found.",
        )
    return profile
