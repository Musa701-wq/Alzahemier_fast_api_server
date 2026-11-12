from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Auth & Profile Schemas
# ============================================================================
class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1)
    language: Literal["ur", "en"] = "en"


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileResponse(BaseModel):
    id: str
    email: str
    full_name: str
    language: Literal["ur", "en"]
    role: Literal["caregiver"] = "caregiver"
    push_token: Optional[str] = None
    created_at: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile: ProfileResponse


# ============================================================================
# Person & Consent Schemas
# ============================================================================
class PersonCreate(BaseModel):
    name: str = Field(..., min_length=1)
    age: int = Field(..., gt=0, lt=130)
    gender: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    education_level: str = "secondary"
    occupation: str = "retired"
    living_situation: str = "with_family"
    family_history_dementia: bool = False
    medical_conditions: List[str] = []
    observed_symptoms: List[str] = []
    symptom_duration_months: int = Field(default=6, ge=0, le=600)


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = Field(default=None, gt=0, lt=130)
    gender: Optional[str] = None
    city: Optional[str] = None
    education_level: Optional[str] = None
    occupation: Optional[str] = None
    living_situation: Optional[str] = None
    family_history_dementia: Optional[bool] = None
    medical_conditions: Optional[List[str]] = None
    observed_symptoms: Optional[List[str]] = None
    symptom_duration_months: Optional[int] = Field(default=None, ge=0, le=600)


class PersonResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    age: int
    gender: str
    city: str
    education_level: str = "secondary"
    occupation: str = "retired"
    living_situation: str = "with_family"
    family_history_dementia: bool = False
    medical_conditions: List[str] = []
    observed_symptoms: List[str] = []
    symptom_duration_months: int = 6
    created_at: str


class ConsentCreate(BaseModel):
    person_id: str
    type: Literal["audio", "data_processing", "report_sharing", "document_upload"]
    granted: bool = True


class ConsentResponse(BaseModel):
    id: str
    owner_id: str
    person_id: str
    type: str
    granted: bool
    granted_at: str
    revoked_at: Optional[str] = None


# ============================================================================
# Cognitive Test Session & Results Schemas (Tests 1 to 7)
# ============================================================================
class SessionStartRequest(BaseModel):
    person_id: str
    session_mode: Literal["baseline", "post_visit_adaptive"] = "baseline"


class ClockChecklist(BaseModel):
    closed_circle: bool = False
    twelve_numbers: bool = False
    correct_order: bool = False
    correct_spacing: bool = False
    two_hands: bool = False
    hands_match_time: bool = False


class ClockCheckRequest(BaseModel):
    target_time: str = "11:10"
    stroke_data: Optional[Dict[str, Any]] = None
    image_base64: Optional[str] = None


class ClockCheckResponse(BaseModel):
    session_id: str
    target_time: str
    checklist: ClockChecklist
    requires_caregiver_confirmation: bool = True
    disclaimer: str


class TestResultSubmit(BaseModel):
    __test__ = False
    test_number: int = Field(..., ge=1, le=7)
    test_type: Literal[
        "orientation",
        "word_recall_immediate",
        "animal_naming",
        "verbal_fluency_animals",
        "picture_story",
        "clock_drawing",
        "dot_connecting",
        "word_recall_delayed",
    ]
    raw_response: Optional[str] = None
    answers: Optional[Dict[str, Any]] = None
    audio_path: Optional[str] = None
    stroke_data: Optional[Dict[str, Any]] = None
    timing: Optional[Dict[str, Any]] = None
    clock_checklist: Optional[ClockChecklist] = None
    confirmed_by_caregiver: bool = False


class TestMarker(BaseModel):
    __test__ = False
    time_ms: int
    label: str


class TestResultResponse(BaseModel):
    __test__ = False
    id: str
    session_id: str
    test_number: int
    test_type: str
    raw_response: Optional[str] = None
    audio_path: Optional[str] = None
    stroke_data: Optional[Dict[str, Any]] = None
    timing: Optional[Dict[str, Any]] = None
    score: float
    raw_points: float
    max_points: float
    markers: List[Dict[str, Any]] = []
    needs_review: bool = False
    emergency_detected: bool = False
    emergency_resources: List[Dict[str, Any]] = []


class SessionResponse(BaseModel):
    id: str
    person_id: str
    session_date: str
    session_mode: str = "baseline"
    baseline_session_id: Optional[str] = None
    adaptive_context: Optional[Dict[str, Any]] = None
    domain_deltas: Optional[Dict[str, float]] = None
    item_bank_version: int
    item_prompts: Optional[Dict[str, Any]] = None
    total_score: Optional[float] = None
    domain_scores: Dict[str, float] = {}
    outcome: Optional[Literal["looks_fine", "keep_watching", "see_doctor"]] = None
    outcome_reason: Optional[str] = None
    next_step: Optional[str] = None
    score_change_from_last: Optional[float] = None
    watch_domains_highlighted: List[str] = []
    duration_seconds: Optional[int] = None
    completed: bool = False
    disclaimer: str
    results: List[TestResultResponse] = []


# ============================================================================
# Doctors Directory Schemas
# ============================================================================
class DoctorCreate(BaseModel):
    name: str
    specialty: Literal[
        "neurologist",
        "geriatrician",
        "psychiatrist",
        "memory_clinic",
        "general_physician",
    ]
    qualifications: str
    pmdc_number: Optional[str] = None
    clinic_name: str
    city: str
    area: Optional[str] = None
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: str
    email: Optional[str] = None
    fee_pkr: int = Field(..., ge=0)
    mode: Literal["in_person", "online", "both"] = "in_person"
    languages: List[str] = ["ur"]
    years_experience: int = Field(default=0, ge=0)
    gender: Optional[str] = None
    available_days: List[str] = []
    verified: bool = False
    source: str
    last_verified_at: Optional[str] = None
    active: bool = True


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    qualifications: Optional[str] = None
    pmdc_number: Optional[str] = None
    clinic_name: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    fee_pkr: Optional[int] = None
    mode: Optional[str] = None
    languages: Optional[List[str]] = None
    years_experience: Optional[int] = None
    gender: Optional[str] = None
    available_days: Optional[List[str]] = None
    verified: Optional[bool] = None
    source: Optional[str] = None
    last_verified_at: Optional[str] = None
    active: Optional[bool] = None


class DoctorResponse(DoctorCreate):
    id: str


class FavoriteCreate(BaseModel):
    doctor_id: str


class DoctorProblemCreate(BaseModel):
    message: str = Field(..., min_length=3)


# ============================================================================
# Report & Share Schemas
# ============================================================================
class ReportCreate(BaseModel):
    session_id: str
    user_notes: Optional[str] = None
    narrative_text: Optional[str] = None


class ReportShareCreate(BaseModel):
    doctor_id: Optional[str] = None
    shared_via: str = "whatsapp"
    expiry_days: int = Field(default=14, ge=1, le=90)


class ReportResponse(BaseModel):
    id: str
    session_id: Optional[str] = None
    summary_id: Optional[str] = None
    report_type: Literal["session", "monthly"]
    pdf_path: Optional[str] = None
    summary_json: Dict[str, Any]
    share_token: Optional[str] = None
    share_expires_at: Optional[str] = None
    revoked: bool = False
    created_at: str
    disclaimer: str


# ============================================================================
# Post-Visit Stage: Documents, Medicines, Logs & Monthly Summaries
# ============================================================================
class DocumentUploadRequest(BaseModel):
    person_id: str
    doctor_id: Optional[str] = None
    file_path: str
    file_type: Literal["image", "pdf"] = "image"
    visit_date: Optional[str] = None
    findings_text: Optional[str] = None
    tests_advised: Optional[str] = None
    followup_interval_days: Optional[int] = 30
    watch_domains: List[str] = []
    raw_report_text: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    person_id: str
    doctor_id: Optional[str] = None
    file_path: str
    file_type: str
    visit_date: Optional[str] = None
    findings_text: Optional[str] = None
    tests_advised: Optional[str] = None
    followup_interval_days: Optional[int] = 30
    watch_domains: List[str] = []
    extraction_json: Optional[Dict[str, Any]] = None
    uploaded_at: str


class MedicineCreate(BaseModel):
    person_id: str
    document_id: Optional[str] = None
    name: str = Field(..., min_length=1)
    dose: str = Field(..., min_length=1)
    frequency_per_day: int = Field(..., ge=1, le=12)
    reminder_times: List[str] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    instructions: Optional[str] = None
    confirmed_by_user: bool = Field(
        ...,
        description="Must be explicitly True. Unconfirmed medicines are rejected for patient safety.",
    )


class MedicineUpdate(BaseModel):
    dose: Optional[str] = None
    frequency_per_day: Optional[int] = Field(default=None, ge=1, le=12)
    reminder_times: Optional[List[str]] = None
    end_date: Optional[str] = None
    instructions: Optional[str] = None
    active: Optional[bool] = None
    confirmed_by_user: Optional[bool] = None


class MedicineResponse(BaseModel):
    id: str
    person_id: str
    document_id: Optional[str] = None
    name: str
    dose: str
    frequency_per_day: int
    reminder_times: List[str]
    start_date: str
    end_date: Optional[str] = None
    instructions: Optional[str] = None
    active: bool
    confirmed_by_user: bool
    created_at: str
    safety_notice: str


class MedicineLogCreate(BaseModel):
    medicine_id: str
    log_date: Optional[str] = None
    scheduled_time: str = "09:00"
    status: Literal["taken", "skipped", "missed"]
    note: Optional[str] = None


class MedicineLogResponse(BaseModel):
    id: str
    medicine_id: str
    log_date: str
    scheduled_time: str
    status: str
    note: Optional[str] = None
    logged_at: str
    gentle_reminder: Optional[str] = None


class MonthlySummaryGenerateRequest(BaseModel):
    person_id: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    user_notes: List[str] = []


class MonthlySummaryResponse(BaseModel):
    id: str
    person_id: str
    period_start: str
    period_end: str
    adherence_pct: float
    taken_count: int
    skipped_count: int
    missed_count: int
    session_ids: List[str]
    score_change: Optional[float] = None
    watch_domains: List[str] = []
    user_notes: List[str]
    report_id: str
    created_at: str
    disclaimer: str


# ============================================================================
# Safety & Admin Schemas
# ============================================================================
class SafetyResourceCreate(BaseModel):
    label: str
    phone: str
    description: str
    last_verified_at: Optional[str] = None
    active: bool = True


class SafetyCheckRequest(BaseModel):
    text: str


class SafetyCheckResponse(BaseModel):
    emergency_detected: bool
    matched_category: Optional[str] = None
    message: str
    resources: List[Dict[str, Any]] = []


class ScoringConfigUpdate(BaseModel):
    key: str
    value: Dict[str, Any]
