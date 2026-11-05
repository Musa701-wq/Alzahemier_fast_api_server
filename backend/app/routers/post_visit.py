from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from backend.app.core.auth import get_current_user
from backend.app.core.config import settings
from backend.app.db.repository import db, utc_now_iso
from backend.app.models.schemas import (
    DocumentResponse,
    DocumentUploadRequest,
    MedicineCreate,
    MedicineLogCreate,
    MedicineLogResponse,
    MedicineResponse,
    MedicineUpdate,
    MonthlySummaryGenerateRequest,
    MonthlySummaryResponse,
)
from backend.app.services.pdf import generate_report_pdf_bytes
from backend.app.services.reminders import (
    MEDICINE_SAFETY_NOTICE,
    schedule_medicine_reminders,
    schedule_retest_reminder,
)

router = APIRouter(tags=["Post-Visit Care, Medicines & Monthly Summary"])


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_doctor_document(
    payload: DocumentUploadRequest,
    current_user: Dict = Depends(get_current_user),
) -> DocumentResponse:
    db.get_person_for_owner(payload.person_id, current_user["id"])

    doc_id = str(uuid.uuid4())
    db.storage_files[payload.file_path] = (payload.raw_report_text or "doctor-report-binary").encode(
        "utf-8"
    )

    doc = {
        "id": doc_id,
        "person_id": payload.person_id,
        "doctor_id": payload.doctor_id,
        "file_path": payload.file_path,
        "file_type": payload.file_type,
        "visit_date": payload.visit_date or date.today().isoformat(),
        "findings_text": payload.findings_text,
        "tests_advised": payload.tests_advised,
        "followup_interval_days": payload.followup_interval_days or 30,
        "watch_domains": payload.watch_domains or [],
        "extraction_json": None,
        "uploaded_at": utc_now_iso(),
    }
    db.doctor_documents[doc_id] = doc

    # Schedule follow-up retest based on doctor's report interval (default 30 days)
    schedule_retest_reminder(
        current_user["id"],
        days_ahead=int(doc["followup_interval_days"] or 30),
    )
    return DocumentResponse(**doc)


@router.post("/documents/{document_id}/extract")
def extract_doctor_document_prefill(
    document_id: str,
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Optional AI pre-fill of findings, medicines, and follow-up advice from an
    uploaded doctor report.
    Safety rule: Never saved to the medicines table without explicit user confirmation.
    """
    doc = db.doctor_documents.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor document not found.",
        )
    db.get_person_for_owner(doc["person_id"], current_user["id"])

    extraction = {
        "findings_suggestion": doc.get("findings_text") or "Follow-up memory evaluation advised.",
        "followup_interval_days": doc.get("followup_interval_days") or 30,
        "watch_domains": doc.get("watch_domains") or ["memory", "orientation"],
        "candidate_medicines": [],
        "requires_user_confirmation": True,
        "safety_warning": (
            "Please check every medicine name, dose, and time against the original "
            "doctor's report before confirming. Nothing is saved until you confirm."
        ),
    }
    doc["extraction_json"] = extraction
    db.doctor_documents[document_id] = doc
    return extraction


@router.post("/medicines", response_model=MedicineResponse, status_code=status.HTTP_201_CREATED)
def create_confirmed_medicine(
    payload: MedicineCreate,
    current_user: Dict = Depends(get_current_user),
) -> MedicineResponse:
    db.get_person_for_owner(payload.person_id, current_user["id"])

    if not payload.confirmed_by_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Medicine cannot be saved unless confirmed_by_user is True. "
                "Please verify each line against the doctor's prescription."
            ),
        )

    # If a newer doctor report is being used, keep old medicines from previous documents in history (active=False)
    if payload.document_id:
        for existing in db.medicines.values():
            if (
                existing["person_id"] == payload.person_id
                and existing.get("document_id")
                and existing.get("document_id") != payload.document_id
            ):
                existing["active"] = False

    med_id = str(uuid.uuid4())
    reminder_times = payload.reminder_times or ["09:00"]
    medicine = {
        "id": med_id,
        "person_id": payload.person_id,
        "document_id": payload.document_id,
        "name": payload.name.strip(),
        "dose": payload.dose.strip(),
        "frequency_per_day": payload.frequency_per_day,
        "reminder_times": reminder_times,
        "start_date": payload.start_date or date.today().isoformat(),
        "end_date": payload.end_date,
        "instructions": payload.instructions,
        "active": True,
        "confirmed_by_user": True,
        "created_at": utc_now_iso(),
        "safety_notice": MEDICINE_SAFETY_NOTICE,
    }
    db.medicines[med_id] = medicine
    schedule_medicine_reminders(current_user["id"], medicine)
    return MedicineResponse(**medicine)


@router.patch("/medicines/{medicine_id}", response_model=MedicineResponse)
def update_medicine(
    medicine_id: str,
    payload: MedicineUpdate,
    current_user: Dict = Depends(get_current_user),
) -> MedicineResponse:
    med = db.medicines.get(medicine_id)
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medicine not found.",
        )
    db.get_person_for_owner(med["person_id"], current_user["id"])

    updates = payload.model_dump(exclude_unset=True)
    if "confirmed_by_user" in updates and not updates["confirmed_by_user"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirmed_by_user cannot be set to False on an active medicine.",
        )

    for k, v in updates.items():
        if v is not None:
            med[k] = v
    med["safety_notice"] = MEDICINE_SAFETY_NOTICE
    db.medicines[medicine_id] = med
    return MedicineResponse(**med)


@router.get("/medicines", response_model=List[MedicineResponse])
def list_medicines(
    person_id: str = Query(...),
    include_history: bool = Query(default=True),
    current_user: Dict = Depends(get_current_user),
) -> List[MedicineResponse]:
    db.get_person_for_owner(person_id, current_user["id"])
    meds = [m for m in db.medicines.values() if m["person_id"] == person_id]
    if not include_history:
        meds = [m for m in meds if m.get("active", True)]
    return [MedicineResponse(**{**m, "safety_notice": MEDICINE_SAFETY_NOTICE}) for m in meds]


@router.post("/medicine-logs", response_model=MedicineLogResponse, status_code=status.HTTP_201_CREATED)
def log_medicine_dose(
    payload: MedicineLogCreate,
    current_user: Dict = Depends(get_current_user),
) -> MedicineLogResponse:
    med = db.medicines.get(payload.medicine_id)
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medicine not found.",
        )
    db.get_person_for_owner(med["person_id"], current_user["id"])

    log_id = str(uuid.uuid4())
    gentle_reminder = None
    if payload.status in ("skipped", "missed"):
        gentle_reminder = (
            f"Dose of {med['name']} ({med['dose']}) at {payload.scheduled_time} was marked as {payload.status}. "
            "Please follow your doctor's instructions for the next scheduled time and never double a dose."
        )

    record = {
        "id": log_id,
        "medicine_id": payload.medicine_id,
        "log_date": payload.log_date or date.today().isoformat(),
        "scheduled_time": payload.scheduled_time,
        "status": payload.status,
        "note": payload.note,
        "logged_at": utc_now_iso(),
        "gentle_reminder": gentle_reminder,
    }
    db.medicine_logs[log_id] = record
    return MedicineLogResponse(**record)


@router.get("/medicine-logs", response_model=List[MedicineLogResponse])
def list_medicine_logs(
    person_id: str = Query(...),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    current_user: Dict = Depends(get_current_user),
) -> List[MedicineLogResponse]:
    db.get_person_for_owner(person_id, current_user["id"])
    person_med_ids = {
        m["id"] for m in db.medicines.values() if m["person_id"] == person_id
    }
    logs = [l for l in db.medicine_logs.values() if l["medicine_id"] in person_med_ids]
    if from_date:
        logs = [l for l in logs if l["log_date"] >= from_date]
    if to_date:
        logs = [l for l in logs if l["log_date"] <= to_date]
    logs.sort(key=lambda l: (l["log_date"], l["scheduled_time"]))
    return [MedicineLogResponse(**l) for l in logs]


@router.post(
    "/summaries/monthly/generate",
    response_model=MonthlySummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_monthly_summary(
    payload: MonthlySummaryGenerateRequest,
    current_user: Dict = Depends(get_current_user),
) -> MonthlySummaryResponse:
    person = db.get_person_for_owner(payload.person_id, current_user["id"])
    today_iso = date.today().isoformat()
    period_start = payload.period_start or today_iso
    period_end = payload.period_end or today_iso

    person_med_ids = {
        m["id"] for m in db.medicines.values() if m["person_id"] == payload.person_id
    }
    logs = [
        l
        for l in db.medicine_logs.values()
        if l["medicine_id"] in person_med_ids and period_start <= l["log_date"] <= period_end
    ]

    taken_count = sum(1 for l in logs if l["status"] == "taken")
    skipped_count = sum(1 for l in logs if l["status"] == "skipped")
    missed_count = sum(1 for l in logs if l["status"] == "missed")
    total_logs = len(logs)
    adherence_pct = round((taken_count / total_logs) * 100.0, 2) if total_logs > 0 else 100.0

    completed_sessions = sorted(
        (
            s
            for s in db.test_sessions.values()
            if s["person_id"] == payload.person_id
            and s.get("completed")
            and s.get("total_score") is not None
        ),
        key=lambda item: item["session_date"],
    )
    session_ids = [s["id"] for s in completed_sessions]
    score_change: Optional[float] = None
    if len(completed_sessions) >= 2:
        score_change = round(
            float(completed_sessions[-1]["total_score"])
            - float(completed_sessions[0]["total_score"]),
            2,
        )

    docs = sorted(
        (d for d in db.doctor_documents.values() if d["person_id"] == payload.person_id),
        key=lambda d: d["uploaded_at"],
        reverse=True,
    )
    watch_domains = docs[0].get("watch_domains", []) if docs else []

    summary_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    latest_score = completed_sessions[-1]["total_score"] if completed_sessions else None
    latest_outcome = completed_sessions[-1]["outcome"] if completed_sessions else None

    monthly_report_json = {
        "patient": {
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "city": person["city"],
        },
        "period_start": period_start,
        "period_end": period_end,
        "adherence_pct": adherence_pct,
        "taken_count": taken_count,
        "skipped_count": skipped_count,
        "missed_count": missed_count,
        "total_score": latest_score,
        "outcome": latest_outcome,
        "score_change": score_change,
        "watch_domains": watch_domains,
        "user_notes": payload.user_notes,
        "footer": "Generated from a home screening, not a diagnosis.",
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }

    pdf_bytes = generate_report_pdf_bytes(monthly_report_json)
    pdf_path = f"reports/{report_id}.pdf"
    db.storage_files[pdf_path] = pdf_bytes

    db.reports[report_id] = {
        "id": report_id,
        "session_id": completed_sessions[-1]["id"] if completed_sessions else None,
        "summary_id": summary_id,
        "report_type": "monthly",
        "pdf_path": pdf_path,
        "summary_json": monthly_report_json,
        "share_token": None,
        "share_expires_at": None,
        "revoked": False,
        "created_at": utc_now_iso(),
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }

    summary_record = {
        "id": summary_id,
        "person_id": payload.person_id,
        "period_start": period_start,
        "period_end": period_end,
        "adherence_pct": adherence_pct,
        "taken_count": taken_count,
        "skipped_count": skipped_count,
        "missed_count": missed_count,
        "session_ids": session_ids,
        "score_change": score_change,
        "watch_domains": watch_domains,
        "user_notes": payload.user_notes,
        "report_id": report_id,
        "created_at": utc_now_iso(),
        "disclaimer": settings.SCREENING_DISCLAIMER,
    }
    db.monthly_summaries[summary_id] = summary_record
    return MonthlySummaryResponse(**summary_record)


@router.get("/summaries/monthly", response_model=List[MonthlySummaryResponse])
def list_monthly_summaries(
    person_id: str = Query(...),
    current_user: Dict = Depends(get_current_user),
) -> List[MonthlySummaryResponse]:
    db.get_person_for_owner(person_id, current_user["id"])
    items = [
        MonthlySummaryResponse(**ms)
        for ms in db.monthly_summaries.values()
        if ms["person_id"] == person_id
    ]
    return items

