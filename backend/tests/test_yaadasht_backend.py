from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from backend.app.db.repository import db
from backend.app.main import app
from backend.app.models.schemas import (
    ClockCheckRequest,
    ClockChecklist,
    ConsentCreate,
    DoctorCreate,
    DoctorProblemCreate,
    DocumentUploadRequest,
    FavoriteCreate,
    LoginRequest,
    MedicineCreate,
    MedicineLogCreate,
    MonthlySummaryGenerateRequest,
    PersonCreate,
    PersonUpdate,
    ReportCreate,
    ReportShareCreate,
    SafetyCheckRequest,
    SafetyResourceCreate,
    ScoringConfigUpdate,
    SessionStartRequest,
    SignupRequest,
    TestResultSubmit,
)
from backend.app.routers import (
    admin,
    auth,
    doctors,
    post_visit,
    profiles,
    reminders,
    reports,
    results,
    safety,
    sessions,
)
from backend.app.services.outcome import evaluate_session_outcome
from backend.app.services.report import verify_narrative_numbers
from backend.app.services.scoring import (
    compute_session_aggregates,
    score_animal_naming,
    score_clock_drawing,
    score_dot_connecting,
    score_orientation,
    score_picture_story,
    score_word_recall,
)


@pytest.fixture(autouse=True)
def reset_database():
    db.reset()
    yield
    db.reset()


# ============================================================================
# 1. Unit Tests for the 7 Cognitive Tests Scoring Rules
# ============================================================================
class TestScoringEngine:
    def test_test1_orientation_scoring_english_and_urdu(self):
        ref_dt = datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc)  # Monday, Jan 12, Winter
        answers = {
            "day": "پیر",
            "date": "12",
            "month": "جنوری",
            "season": "sardi",
            "city": "Lahore",
        }
        norm, raw, max_pts, markers = score_orientation(
            answers=answers,
            raw_response=None,
            person_city="Lahore",
            reference_dt=ref_dt,
        )
        assert raw == 5.0
        assert max_pts == 5.0
        assert norm == 100.0
        assert markers == []

    def test_test2_and_7_word_recall_bilingual_fuzzy(self):
        # Version 1 words: river (دریا), mango (آم), window (کھڑکی), lantern (لالٹین), carpet (قالین)
        transcript = "دریا aam window laltain قالین"
        norm, raw, max_pts, markers = score_word_recall(transcript, item_bank_version=1)
        assert raw == 5.0
        assert norm == 100.0
        assert markers == []

        partial_transcript = "river mango"
        norm2, raw2, _, markers2 = score_word_recall(partial_transcript, item_bank_version=1)
        assert raw2 == 2.0
        assert norm2 == 40.0
        assert len(markers2) == 3

    def test_test3_animal_naming_unique_count_and_scaling(self):
        animals_15 = (
            "billi kutta gaaye bhains bakri bher ghora gadha "
            "oont sher cheetah haathi bandar hiran reech billi kutta"
        )
        norm, raw, max_pts, markers = score_animal_naming(animals_15)
        assert raw == 10.0
        assert norm == 100.0
        assert any("repeated_animals:2" in m["label"] for m in markers)

        animals_6 = "cat dog lion شیر بلی گائے"  # cat/بلی and lion/شیر and cow/گائے are distinct strings in lexicon
        norm_partial, raw_partial, _, _ = score_animal_naming("cat dog cow goat sheep horse")
        assert raw_partial == 4.0
        assert norm_partial == 40.0

    def test_test4_picture_story_items_fluency_and_pause_penalty(self):
        story = (
            "In the courtyard grandmother is sitting on a charpoy near a tree "
            "holding a teapot and cup while a child reads a book and a sparrow watches "
            "from the branch on a sunny morning."
        )
        norm_no_pause, raw_no_pause, _, _ = score_picture_story(
            transcript=story,
            item_bank_version=1,
            timing={"longest_pause_ms": 1200},
        )
        assert raw_no_pause == 10.0
        assert norm_no_pause == 100.0

        norm_long_pause, raw_long_pause, _, markers = score_picture_story(
            transcript=story,
            item_bank_version=1,
            timing={"longest_pause_ms": 6500},
        )
        assert raw_long_pause == 8.0
        assert norm_long_pause == 80.0
        assert any("long_pause_ms:6500" in m["label"] for m in markers)

    def test_test5_clock_drawing_checklist_scoring(self):
        full_chk = ClockChecklist(
            closed_circle=True,
            twelve_numbers=True,
            correct_order=True,
            correct_spacing=True,
            two_hands=True,
            hands_match_time=True,
        )
        norm, raw, _, markers = score_clock_drawing(full_chk)
        assert raw == 10.0
        assert norm == 100.0
        assert markers == []

        partial_chk = ClockChecklist(
            closed_circle=True,
            twelve_numbers=True,
            correct_order=False,
            correct_spacing=False,
            two_hands=True,
            hands_match_time=False,
        )
        norm2, raw2, _, markers2 = score_clock_drawing(partial_chk)
        assert raw2 == 5.0
        assert norm2 == 50.0
        assert len(markers2) == 3

    def test_test6_dot_connecting_time_and_errors(self):
        norm, raw, _, _ = score_dot_connecting(
            {"duration_seconds": 28.0, "errors": 0, "completed_dots": 12}
        )
        assert raw == 10.0
        assert norm == 100.0

        norm_err, raw_err, _, _ = score_dot_connecting(
            {"duration_seconds": 28.0, "errors": 2, "completed_dots": 12}
        )
        assert raw_err == 7.0
        assert norm_err == 70.0


# ============================================================================
# 2. Unit Tests for Three Outcomes and Override Rules
# ============================================================================
class TestOutcomeEvaluation:
    def test_looks_fine_outcome(self):
        res = [
            {"test_number": 1, "score": 80.0, "raw_points": 4.0},
            {"test_number": 7, "score": 80.0, "raw_points": 4.0},
        ]
        outcome, reason, next_step, change = evaluate_session_outcome(82.0, res)
        assert outcome == "looks_fine"
        assert next_step == "Retest in 3 months"
        assert "Screening aid only" in reason
        assert change is None

    def test_keep_watching_by_score_or_10_point_drop(self):
        res = [
            {"test_number": 1, "score": 80.0, "raw_points": 4.0},
            {"test_number": 7, "score": 60.0, "raw_points": 3.0},
        ]
        outcome1, _, next_step1, _ = evaluate_session_outcome(65.0, res)
        assert outcome1 == "keep_watching"
        assert "1 month" in next_step1

        # High total score (78) but dropped by 12 points from previous 90 -> keep_watching
        outcome2, _, _, change2 = evaluate_session_outcome(78.0, res, previous_total_score=90.0)
        assert outcome2 == "keep_watching"
        assert change2 == -12.0

    def test_see_doctor_by_low_total_or_15_point_drop_or_override(self):
        res_normal = [
            {"test_number": 1, "score": 80.0, "raw_points": 4.0},
            {"test_number": 7, "score": 60.0, "raw_points": 3.0},
        ]
        # Total below 55
        outcome_low, _, _, _ = evaluate_session_outcome(48.0, res_normal)
        assert outcome_low == "see_doctor"

        # Drop of 16 points from previous session (even if current score is 76)
        outcome_drop, _, _, change = evaluate_session_outcome(
            76.0, res_normal, previous_total_score=92.0
        )
        assert outcome_drop == "see_doctor"
        assert change == -16.0

        # Override rule: Total is 78 (>= 75), but delayed recall <= 1 of 5 AND orientation errors >= 2 (raw <= 3)
        res_override = [
            {"test_number": 1, "score": 60.0, "raw_points": 3.0},  # 2 orientation errors
            {"test_number": 7, "score": 20.0, "raw_points": 1.0},  # 1 of 5 delayed recall
        ]
        outcome_ovr, reason_ovr, next_step_ovr, _ = evaluate_session_outcome(78.0, res_override)
        assert outcome_ovr == "see_doctor"
        assert "Open Doctors page" in next_step_ovr
        assert "Screening aid only" in reason_ovr


# ============================================================================
# 3. Anti-Hallucination Report Number Verification Tests
# ============================================================================
class TestAntiHallucinationRule:
    def test_verify_narrative_numbers_accepts_database_numbers_and_rejects_hallucinations(self):
        db_record = {
            "patient": {"name": "abdul sattar", "age": 68},
            "total_score": 72.5,
            "domain_scores": {"memory": 60.0, "orientation": 80.0},
        }
        valid_text = "Patient aged 68 achieved a total score of 72.5 with memory at 60 and orientation at 80."
        assert verify_narrative_numbers(valid_text, db_record) is True

        hallucinated_text = "Patient aged 68 achieved a score of 91.5 across 14 sessions."
        with pytest.raises(HTTPException) as exc_info:
            verify_narrative_numbers(hallucinated_text, db_record)
        assert exc_info.value.status_code == 422
        assert "Anti-hallucination check failed" in exc_info.value.detail


# ============================================================================
# 4. Row Level Security (RLS) & End-to-End Stage 1, 2, 3 Workflow Tests
# ============================================================================
class TestEndToEndAndRLS:
    def test_rls_blocks_cross_user_access(self):
        user_a = auth.signup(
            SignupRequest(email="usera@example.com", password="password123", full_name="User A")
        ).profile.model_dump()
        user_b = auth.signup(
            SignupRequest(email="userb@example.com", password="password123", full_name="User B")
        ).profile.model_dump()

        person_a = profiles.create_person(
            PersonCreate(name="Ahmad", age=70, gender="male", city="Lahore"),
            current_user=user_a,
        )

        # User B must never read, update, or delete User A's person profile
        with pytest.raises(HTTPException) as exc_read:
            db.get_person_for_owner(person_a.id, user_b["id"])
        assert exc_read.value.status_code == 404

        with pytest.raises(HTTPException) as exc_patch:
            profiles.update_person(
                person_a.id,
                PersonUpdate(city="Karachi"),
                current_user=user_b,
            )
        assert exc_patch.value.status_code == 404

        with pytest.raises(HTTPException) as exc_del:
            profiles.delete_person(person_a.id, current_user=user_b)
        assert exc_del.value.status_code == 404

    def test_full_pre_visit_doctor_and_post_visit_lifecycle(self):
        # 1. Signup Caregiver User & Admin User
        user = auth.signup(
            SignupRequest(email="family@example.com", password="password123", full_name="Sara Khan")
        ).profile.model_dump()
        admin_user = auth.signup(
            SignupRequest(
                email="admin@example.com",
                password="password123",
                full_name="Admin",
                role="admin",
            )
        ).profile.model_dump()

        # 2. Create Person Profile & Grant Required Consents
        person = profiles.create_person(
            PersonCreate(name="Tariq Mehmood", age=71, gender="male", city="Lahore"),
            current_user=user,
        )
        for ctype in ("audio", "data_processing", "report_sharing", "document_upload"):
            profiles.grant_consent(
                ConsentCreate(person_id=person.id, type=ctype, granted=True),
                current_user=user,
            )

        # 3. Start Guided Session & Submit All 7 Tests
        session = sessions.start_session(
            SessionStartRequest(person_id=person.id),
            current_user=user,
        )
        assert session.item_bank_version == 1

        # Test 1: Orientation (2 correct -> 3 errors)
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=1,
                test_type="orientation",
                answers={"correct_count": 2},
            ),
            current_user=user,
        )
        # Test 2: Immediate Word Recall
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=2,
                test_type="word_recall_immediate",
                raw_response="river mango",
                audio_path="audio/s1_t2.webm",
            ),
            current_user=user,
        )
        # Test 3: Animal Naming
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=3,
                test_type="animal_naming",
                raw_response="billi kutta gaaye bakri sher",
            ),
            current_user=user,
        )
        # Test 4: Picture Story
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=4,
                test_type="picture_story",
                raw_response="grandmother on charpoy with cup and teapot",
                timing={"longest_pause_ms": 6000},
            ),
            current_user=user,
        )
        # Test 5: Clock Drawing Vision Check + Submission
        clock_chk = sessions.run_clock_check(
            session.id,
            ClockCheckRequest(target_time="11:10", stroke_data={"strokes": [1, 2, 3]}),
            current_user=user,
        )
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=5,
                test_type="clock_drawing",
                clock_checklist=clock_chk.checklist,
                confirmed_by_caregiver=True,
            ),
            current_user=user,
        )
        # Test 6: Dot Connecting
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=6,
                test_type="dot_connecting",
                timing={"duration_seconds": 75.0, "errors": 3, "completed_dots": 12},
            ),
            current_user=user,
        )
        # Test 7: Delayed Word Recall (only 1 word recalled)
        results.submit_test_result(
            session.id,
            TestResultSubmit(
                test_number=7,
                test_type="word_recall_delayed",
                raw_response="river",
            ),
            current_user=user,
        )

        # Complete Session -> Expect 'see_doctor'
        completed = sessions.complete_session(
            session.id,
            duration_seconds=840,
            current_user=user,
        )
        assert completed.completed is True
        assert completed.outcome == "see_doctor"

        # Starting a second session rotates item bank version to 2
        session_2 = sessions.start_session(
            SessionStartRequest(person_id=person.id),
            current_user=user,
        )
        assert session_2.item_bank_version == 2

        # 4. Stage 2: Admin Adds Verified Doctor, User Filters & Shares Report
        doc_created = admin.admin_create_doctor(
            DoctorCreate(
                name="Dr. Ayesha Siddiqui",
                specialty="neurologist",
                qualifications="MBBS, FCPS (Neurology)",
                pmdc_number="PMDC-44521-P",
                clinic_name="Lahore Neuro & Memory Clinic",
                city="Lahore",
                address="Jail Road, Lahore",
                phone="+92-42-35550199",
                fee_pkr=3000,
                mode="both",
                languages=["ur", "en"],
                years_experience=12,
                gender="female",
                available_days=["Mon", "Wed", "Fri"],
                verified=True,
                source="public_clinic_directory",
            ),
            admin_user=admin_user,
        )
        found_docs = doctors.list_doctors(
            city="Lahore",
            specialty="neurologist",
            min_fee=None,
            max_fee=5000,
            mode=None,
            gender=None,
            language="ur",
            min_experience=5,
            limit=20,
            offset=0,
            current_user=user,
        )
        assert len(found_docs) == 1
        assert found_docs[0].id == doc_created.id

        # Create Report, Download PDF, Create Share Link & Verify Public Access
        rep = reports.create_session_report(
            ReportCreate(
                session_id=completed.id,
                user_notes="Forgets recent conversations in the evening.",
            ),
            current_user=user,
        )
        pdf_resp = reports.download_report_pdf(rep.id, current_user=user)
        assert pdf_resp.body.startswith(b"%PDF-1.4")

        shared_rep = reports.share_report(
            rep.id,
            ReportShareCreate(doctor_id=doc_created.id, shared_via="whatsapp"),
            current_user=user,
        )
        assert shared_rep.share_token is not None

        public_view = reports.get_public_report(shared_rep.share_token)
        assert public_view["read_only"] is True
        assert public_view["summary"]["total_score"] == completed.total_score

        # Revoke share link -> Public endpoint must return 410 Gone
        reports.revoke_report_share(rep.id, current_user=user)
        with pytest.raises(HTTPException) as exc_revoked:
            reports.get_public_report(shared_rep.share_token)
        assert exc_revoked.value.status_code == 410

        # 5. Stage 3: Post-Visit Document Upload, Medicine Confirmation & Monthly Summary
        doc_upload = post_visit.upload_doctor_document(
            DocumentUploadRequest(
                person_id=person.id,
                doctor_id=doc_created.id,
                file_path="documents/visit_1.jpg",
                file_type="image",
                findings_text="Mild memory recall difficulty; monitor monthly.",
                followup_interval_days=30,
                watch_domains=["memory", "orientation"],
            ),
            current_user=user,
        )

        # Unconfirmed medicine MUST be rejected
        with pytest.raises(HTTPException) as exc_unconfirmed:
            post_visit.create_confirmed_medicine(
                MedicineCreate(
                    person_id=person.id,
                    document_id=doc_upload.id,
                    name="Donepezil",
                    dose="5mg",
                    frequency_per_day=1,
                    reminder_times=["21:00"],
                    confirmed_by_user=False,
                ),
                current_user=user,
            )
        assert exc_unconfirmed.value.status_code == 400

        # Confirmed medicine succeeds and creates reminder
        med = post_visit.create_confirmed_medicine(
            MedicineCreate(
                person_id=person.id,
                document_id=doc_upload.id,
                name="Donepezil",
                dose="5mg",
                frequency_per_day=1,
                reminder_times=["21:00"],
                instructions="Take after dinner as prescribed by doctor.",
                confirmed_by_user=True,
            ),
            current_user=user,
        )
        assert med.confirmed_by_user is True

        # Log Taken and Skipped doses
        log1 = post_visit.log_medicine_dose(
            MedicineLogCreate(medicine_id=med.id, scheduled_time="21:00", status="taken"),
            current_user=user,
        )
        assert log1.gentle_reminder is None

        log2 = post_visit.log_medicine_dose(
            MedicineLogCreate(
                medicine_id=med.id,
                scheduled_time="21:00",
                status="skipped",
                note="Patient was asleep early",
            ),
            current_user=user,
        )
        assert "never double a dose" in log2.gentle_reminder.lower()

        # Generate Monthly Summary & Monthly Report
        monthly = post_visit.generate_monthly_summary(
            MonthlySummaryGenerateRequest(
                person_id=person.id,
                user_notes=["Sleeping better this week"],
            ),
            current_user=user,
        )
        assert monthly.adherence_pct == 50.0
        assert monthly.taken_count == 1
        assert monthly.skipped_count == 1
        assert monthly.report_id in db.reports

        # 6. Delete Person & Verify All Data and Storage Files Are Wiped
        del_res = profiles.delete_person(person.id, current_user=user)
        assert del_res["status"] == "deleted"
        assert db.get_person_by_owner(user["id"]) is None
        assert len(db.storage_files) == 0


# ============================================================================
# 5. Safety Emergency Phrase Detection Tests
# ============================================================================
class TestSafetyEmergencyDetection:
    def test_emergency_phrases_trigger_safety_card_with_admin_resources(self):
        admin_user = auth.signup(
            SignupRequest(
                email="safetyadmin@example.com",
                password="password123",
                full_name="Safety Admin",
                role="admin",
            )
        ).profile.model_dump()

        admin.admin_create_safety_resource(
            SafetyResourceCreate(
                label="Emergency Rescue Helpline",
                phone="1122",
                description="National emergency ambulance and rescue service",
            ),
            admin_user=admin_user,
        )

        # Urdu / Roman Urdu / English emergency phrase triggers
        for phrase in ("I want to end my life", "mar jana chahta hoon", "مریض بے ہوش ہے"):
            resp = safety.run_safety_check(
                SafetyCheckRequest(text=phrase),
                current_user=admin_user,
            )
            assert resp.emergency_detected is True
            assert len(resp.resources) == 1
            assert resp.resources[0]["phone"] == "1122"

        safe_resp = safety.run_safety_check(
            SafetyCheckRequest(text="Today the weather in Lahore is pleasant."),
            current_user=admin_user,
        )
        assert safe_resp.emergency_detected is False
        assert safe_resp.resources == []


def test_openapi_routes_registered():
    paths = app.openapi()["paths"]
    expected_paths = [
        "/health",
        "/auth/signup",
        "/auth/login",
        "/persons",
        "/persons/me",
        "/consents",
        "/sessions",
        "/sessions/{session_id}/results",
        "/sessions/{session_id}/clock-check",
        "/sessions/{session_id}/complete",
        "/reports",
        "/reports/{report_id}/pdf",
        "/reports/{report_id}/share",
        "/public/reports/{token}",
        "/doctors",
        "/favorites",
        "/documents",
        "/medicines",
        "/medicine-logs",
        "/summaries/monthly/generate",
        "/reminders",
        "/safety/resources",
        "/admin/doctors",
        "/admin/doctors/import",
        "/admin/scoring-config",
    ]
    for path in expected_paths:
        assert path in paths, f"Missing expected route {path}"


def test_ai_endpoints_and_openrouter_configuration():
    paths = app.openapi()["paths"]
    assert "/ai/status" in paths
    assert "/ai/picture-story" in paths
    assert "/ai/clock-vision" in paths
    assert "/ai/extract-prescription" in paths

    from backend.app.routers.ai import (
        ClockVisionAIRequest,
        PictureStoryAIRequest,
        PrescriptionExtractRequest,
        analyze_clock_vision,
        analyze_picture_story,
        extract_prescription,
        get_ai_status,
    )

    dummy_user = {"id": "test_user_id", "email": "test@example.com"}

    # 1. AI Status check
    status = get_ai_status(current_user=dummy_user)
    assert "status" in status
    assert status["provider"] == "OpenRouter"

    # 2. Picture Story AI Evaluation (safe fallback / AI response)
    res_story = analyze_picture_story(
        PictureStoryAIRequest(description="A courtyard scene with grandmother having tea under the green tree."),
        current_user=dummy_user,
    )
    assert "themes_identified" in res_story
    assert "semantic_score" in res_story

    # 3. Clock Vision AI Evaluation
    res_clock = analyze_clock_vision(
        ClockVisionAIRequest(image_data_uri="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
        current_user=dummy_user,
    )
    assert "checklist" in res_clock
    assert "closed_circle" in res_clock["checklist"]

    # 4. Prescription Extraction AI
    res_rx = extract_prescription(
        PrescriptionExtractRequest(prescription_text="Prescribed Donepezil 5mg once daily at bedtime. Follow up in 30 days."),
        current_user=dummy_user,
    )
    assert "findings_summary" in res_rx
    assert "medicines" in res_rx


