-- Yaadasht v2 Database Schema and Row Level Security Policies
-- Postgres / Supabase Migration 001

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Profiles (linked to auth.users)
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY,
    full_name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ur' CHECK (language IN ('ur', 'en')),
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    push_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Persons (one tested person per account in v1)
CREATE TABLE IF NOT EXISTS persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    age INTEGER NOT NULL CHECK (age > 0 AND age < 130),
    gender TEXT NOT NULL,
    city TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id)
);

-- 3. Consents
CREATE TABLE IF NOT EXISTS consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('audio', 'data_processing', 'report_sharing', 'document_upload')),
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

-- 4. Test Sessions
CREATE TABLE IF NOT EXISTS test_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    session_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_bank_version INTEGER NOT NULL DEFAULT 1,
    total_score NUMERIC(5, 2),
    domain_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome TEXT CHECK (outcome IN ('looks_fine', 'keep_watching', 'see_doctor')),
    outcome_reason TEXT,
    duration_seconds INTEGER,
    completed BOOLEAN NOT NULL DEFAULT FALSE
);

-- 5. Test Results (Tests 1 to 7)
CREATE TABLE IF NOT EXISTS test_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES test_sessions(id) ON DELETE CASCADE,
    test_number INTEGER NOT NULL CHECK (test_number BETWEEN 1 AND 7),
    test_type TEXT NOT NULL,
    raw_response TEXT,
    audio_path TEXT,
    stroke_data JSONB,
    timing JSONB,
    score NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    markers JSONB NOT NULL DEFAULT '[]'::jsonb,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (session_id, test_number)
);

-- 6. Scoring Configuration (Thresholds, Word Lists, Rule Limits)
CREATE TABLE IF NOT EXISTS scoring_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Doctors Directory
CREATE TABLE IF NOT EXISTS doctors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    specialty TEXT NOT NULL CHECK (specialty IN ('neurologist', 'geriatrician', 'psychiatrist', 'memory_clinic', 'general_physician')),
    qualifications TEXT NOT NULL,
    pmdc_number TEXT,
    clinic_name TEXT NOT NULL,
    city TEXT NOT NULL,
    area TEXT,
    address TEXT NOT NULL,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    phone TEXT NOT NULL,
    email TEXT,
    fee_pkr INTEGER CHECK (fee_pkr >= 0),
    mode TEXT NOT NULL DEFAULT 'in_person' CHECK (mode IN ('in_person', 'online', 'both')),
    languages TEXT[] NOT NULL DEFAULT ARRAY['ur'],
    years_experience INTEGER NOT NULL DEFAULT 0,
    gender TEXT,
    available_days TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT NOT NULL,
    last_verified_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 8. Favorite Doctors
CREATE TABLE IF NOT EXISTS favorite_doctors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    doctor_id UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    UNIQUE (owner_id, doctor_id)
);

-- 9. Doctor Problem Reports
CREATE TABLE IF NOT EXISTS doctor_problem_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. Reports (Session & Monthly)
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES test_sessions(id) ON DELETE CASCADE,
    summary_id UUID,
    report_type TEXT NOT NULL CHECK (report_type IN ('session', 'monthly')),
    pdf_path TEXT,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    share_token TEXT UNIQUE,
    share_expires_at TIMESTAMPTZ,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. Report Shares Log
CREATE TABLE IF NOT EXISTS report_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    doctor_id UUID REFERENCES doctors(id) ON DELETE SET NULL,
    shared_via TEXT NOT NULL,
    shared_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. Doctor Documents (Post-Visit Uploaded Reports)
CREATE TABLE IF NOT EXISTS doctor_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    doctor_id UUID REFERENCES doctors(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('image', 'pdf')),
    visit_date DATE,
    findings_text TEXT,
    tests_advised TEXT,
    followup_interval_days INTEGER DEFAULT 30,
    watch_domains TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    extraction_json JSONB,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. Prescribed Medicines (Requires Explicit User Confirmation)
CREATE TABLE IF NOT EXISTS medicines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    document_id UUID REFERENCES doctor_documents(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    dose TEXT NOT NULL,
    frequency_per_day INTEGER NOT NULL CHECK (frequency_per_day > 0 AND frequency_per_day <= 12),
    reminder_times TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date DATE,
    instructions TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    confirmed_by_user BOOLEAN NOT NULL CHECK (confirmed_by_user = TRUE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. Daily Medicine Logs
CREATE TABLE IF NOT EXISTS medicine_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medicine_id UUID NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
    log_date DATE NOT NULL DEFAULT CURRENT_DATE,
    scheduled_time TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('taken', 'skipped', 'missed')),
    note TEXT,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 15. Monthly Summaries
CREATE TABLE IF NOT EXISTS monthly_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    adherence_pct NUMERIC(5, 2) NOT NULL DEFAULT 0,
    session_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    score_change NUMERIC(5, 2),
    user_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 16. Reminders (Medicine & Retest)
CREATE TABLE IF NOT EXISTS reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('medicine', 'retest')),
    medicine_id UUID REFERENCES medicines(id) ON DELETE CASCADE,
    due_at TIMESTAMPTZ NOT NULL,
    sent BOOLEAN NOT NULL DEFAULT FALSE
);

-- 17. Safety Resources (Admin Managed, Never Hardcoded)
CREATE TABLE IF NOT EXISTS safety_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label TEXT NOT NULL,
    phone TEXT NOT NULL,
    description TEXT NOT NULL,
    last_verified_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE persons ENABLE ROW LEVEL SECURITY;
ALTER TABLE consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE scoring_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctors ENABLE ROW LEVEL SECURITY;
ALTER TABLE favorite_doctors ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctor_problem_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctor_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE medicines ENABLE ROW LEVEL SECURITY;
ALTER TABLE medicine_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE safety_resources ENABLE ROW LEVEL SECURITY;

-- User Isolation Policies
CREATE POLICY profiles_self_access ON profiles
    FOR ALL USING (id = auth.uid()) WITH CHECK (id = auth.uid());

CREATE POLICY persons_owner_access ON persons
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY consents_owner_access ON consents
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY sessions_owner_access ON test_sessions
    FOR ALL USING (
        person_id IN (SELECT id FROM persons WHERE owner_id = auth.uid())
    );

CREATE POLICY results_owner_access ON test_results
    FOR ALL USING (
        session_id IN (
            SELECT ts.id FROM test_sessions ts
            JOIN persons p ON p.id = ts.person_id
            WHERE p.owner_id = auth.uid()
        )
    );

CREATE POLICY favorites_owner_access ON favorite_doctors
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY problem_reports_owner_access ON doctor_problem_reports
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY reports_owner_access ON reports
    FOR ALL USING (
        session_id IN (
            SELECT ts.id FROM test_sessions ts
            JOIN persons p ON p.id = ts.person_id
            WHERE p.owner_id = auth.uid()
        )
    );

CREATE POLICY documents_owner_access ON doctor_documents
    FOR ALL USING (
        person_id IN (SELECT id FROM persons WHERE owner_id = auth.uid())
    );

CREATE POLICY medicines_owner_access ON medicines
    FOR ALL USING (
        person_id IN (SELECT id FROM persons WHERE owner_id = auth.uid())
    );

CREATE POLICY medicine_logs_owner_access ON medicine_logs
    FOR ALL USING (
        medicine_id IN (
            SELECT m.id FROM medicines m
            JOIN persons p ON p.id = m.person_id
            WHERE p.owner_id = auth.uid()
        )
    );

CREATE POLICY monthly_summaries_owner_access ON monthly_summaries
    FOR ALL USING (
        person_id IN (SELECT id FROM persons WHERE owner_id = auth.uid())
    );

CREATE POLICY reminders_owner_access ON reminders
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

-- Shared Read-Only Tables for Signed-In Users, Writable Only by Admins
CREATE POLICY doctors_read_authenticated ON doctors
    FOR SELECT USING (auth.uid() IS NOT NULL AND active = TRUE);

CREATE POLICY doctors_write_admin ON doctors
    FOR ALL USING (
        EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
    );

CREATE POLICY safety_read_authenticated ON safety_resources
    FOR SELECT USING (auth.uid() IS NOT NULL AND active = TRUE);

CREATE POLICY safety_write_admin ON safety_resources
    FOR ALL USING (
        EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
    );

CREATE POLICY scoring_config_read_authenticated ON scoring_config
    FOR SELECT USING (auth.uid() IS NOT NULL);

CREATE POLICY scoring_config_write_admin ON scoring_config
    FOR ALL USING (
        EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
    );

