from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Dict
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status
from backend.app.core.auth import get_current_user
from backend.app.core.config import settings
from backend.app.db.repository import db, utc_now_iso
from backend.app.models.schemas import ReportCreate, ReportResponse, ReportShareCreate
from backend.app.services.pdf import generate_report_pdf_bytes
from backend.app.services.report import build_session_report_summary

router = APIRouter(tags=["Clinical Reports & Sharing"])


def _get_report_with_rls(report_id: str, owner_id: str) -> Dict[str, Any]:
    rep = db.reports.get(report_id)
    if not rep:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found.",
        )
    if rep.get("session_id"):
        session = db.test_sessions.get(rep["session_id"])
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
        db.get_person_for_owner(session["person_id"], owner_id)
    elif rep.get("summary_id"):
        summary = db.monthly_summaries.get(rep["summary_id"])
        if not summary:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found.")
        db.get_person_for_owner(summary["person_id"], owner_id)
    return rep


@router.post("/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def create_session_report(
    payload: ReportCreate,
    current_user: Dict = Depends(get_current_user),
) -> ReportResponse:
    session = db.test_sessions.get(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test session not found.",
        )
    person = db.get_person_for_owner(session["person_id"], current_user["id"])
    if not session.get("completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session must be completed before generating a report.",
        )

    results = [r for r in db.test_results.values() if r["session_id"] == session["id"]]
    trend_sessions = sorted(
        (s for s in db.test_sessions.values() if s["person_id"] == person["id"]),
        key=lambda item: item["session_date"],
    )

    summary_json = build_session_report_summary(
        person=person,
        session=session,
        results=results,
        trend_sessions=trend_sessions,
        user_notes=payload.user_notes,
        narrative_text=payload.narrative_text,
    )

    report_id = str(uuid.uuid4())
    pdf_bytes = generate_report_pdf_bytes(summary_json)
    pdf_path = f"reports/{report_id}.pdf"
    db.storage_files[pdf_path] = pdf_bytes

    report = {
        "id": report_id,
        "session_id": session["id"],
        "summary_id": None,
        "report_type": "session",
        "pdf_path": pdf_path,
        "summary_json": summary_json,
        "share_token": None,
        "share_expires_at": None,
        "revoked": False,
        "created_at": utc_now_iso(),
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }
    db.reports[report_id] = report
    return ReportResponse(**report)


@router.get("/reports/{report_id}/pdf")
def download_report_pdf(
    report_id: str,
    current_user: Dict = Depends(get_current_user),
) -> Response:
    rep = _get_report_with_rls(report_id, current_user["id"])
    pdf_path = rep.get("pdf_path")
    pdf_bytes = db.storage_files.get(pdf_path) if pdf_path else None
    if not pdf_bytes:
        pdf_bytes = generate_report_pdf_bytes(rep["summary_json"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="yaadasht_report_{report_id}.pdf"'},
    )


@router.post("/reports/{report_id}/share", response_model=ReportResponse)
def share_report(
    report_id: str,
    payload: ReportShareCreate,
    current_user: Dict = Depends(get_current_user),
) -> ReportResponse:
    rep = _get_report_with_rls(report_id, current_user["id"])

    token = secrets.token_urlsafe(24)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expiry_days)
    ).isoformat()

    rep["share_token"] = token
    rep["share_expires_at"] = expires_at
    rep["revoked"] = False
    db.reports[report_id] = rep

    share_id = str(uuid.uuid4())
    db.report_shares[share_id] = {
        "id": share_id,
        "report_id": report_id,
        "doctor_id": payload.doctor_id,
        "shared_via": payload.shared_via,
        "shared_at": utc_now_iso(),
    }
    return ReportResponse(**rep)


@router.delete("/reports/{report_id}/share", response_model=ReportResponse)
def revoke_report_share(
    report_id: str,
    current_user: Dict = Depends(get_current_user),
) -> ReportResponse:
    rep = _get_report_with_rls(report_id, current_user["id"])
    rep["revoked"] = True
    db.reports[report_id] = rep
    return ReportResponse(**rep)


@router.get("/public/reports/{token}")
def get_public_report(token: str) -> Dict[str, Any]:
    """
    Public read-only report view behind a share token.
    No login required; enforces revocation and 14-day expiry checks.
    """
    matched = None
    for rep in db.reports.values():
        if rep.get("share_token") == token:
            matched = rep
            break

    if not matched:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared report link not found.",
        )

    if matched.get("revoked"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This shared report link has been revoked by the patient.",
        )

    expires_str = matched.get("share_expires_at")
    if expires_str:
        expires_dt = datetime.fromisoformat(expires_str)
        if datetime.now(timezone.utc) > expires_dt:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This shared report link has expired.",
            )

    return {
        "report_id": matched["id"],
        "report_type": matched["report_type"],
        "summary": matched["summary_json"],
        "created_at": matched["created_at"],
        "expires_at": matched["share_expires_at"],
        "read_only": True,
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }

