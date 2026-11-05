# Yaadasht

Yaadasht is a home cognitive screening and care-continuity platform. It guides a user or caregiver through 7 recorded cognitive tests in about 15 minutes, computes rule-based domain scores, tracks longitudinal score trends, and provides plain-language guidance on whether to relax, keep watching, or consult a specialist.

When a specialist consultation is advised, the platform helps the family locate verified neurologists, geriatricians, and memory clinics in their city, call the clinic directly, and share a one-page clinical summary report (PDF or expiring read-only link). After a doctor visit, families can upload the doctor's prescription report, confirm prescribed medicines, log daily adherence (Taken or Skipped), and generate monthly follow-up reports.

## Scope and Safety Boundaries

- **Screening Aid Only**: Yaadasht does not diagnose Alzheimer's disease or any medical condition. Every session result and generated report includes a mandatory screening-aid disclaimer.
- **Medication Safety**: The application never prescribes, recommends, or modifies medicine dosages. Reminders are only created after the user explicitly confirms each medicine line from their own doctor's report.
- **No Doctor Accounts**: Doctors do not need to sign up or log in. They receive a phone call from the family and a one-page PDF or read-only web report.

## Repository Structure

```text
yaadasht/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI application entrypoint
│   │   ├── core/
│   │   │   ├── config.py          # Environment settings
│   │   │   └── auth.py            # JWT authentication & role dependencies
│   │   ├── db/
│   │   │   └── repository.py      # Supabase / local data repository & RLS enforcement
│   │   ├── models/
│   │   │   └── schemas.py         # Pydantic request & response schemas
│   │   ├── routers/
│   │   │   ├── auth.py            # Signup, login, current user profile
│   │   │   ├── profiles.py        # Persons & consent management
│   │   │   ├── sessions.py        # Session start, completion, clock-check & history
│   │   │   ├── results.py         # Per-test (1-7) result recording & scoring
│   │   │   ├── reports.py         # PDF generation, share tokens & public report view
│   │   │   ├── doctors.py         # Doctor directory search, filters & favorites
│   │   │   ├── post_visit.py      # Doctor documents, confirmed medicines & monthly summaries
│   │   │   ├── reminders.py       # Medicine & retest reminders
│   │   │   ├── safety.py          # Emergency phrase detection & verified resources
│   │   │   └── admin.py           # Admin doctor management, CSV import & scoring config
│   │   └── services/
│   │       ├── transcribe.py      # Speech-to-text interface (Whisper)
│   │       ├── scoring.py         # Rule-based scoring for all 7 cognitive tests
│   │       ├── clock_check.py     # Vision checklist interface for test 5
│   │       ├── outcome.py         # Three-outcome evaluator & override rules
│   │       ├── report.py          # One-page report builder & anti-hallucination checker
│   │       ├── pdf.py             # Single-page PDF document generator
│   │       ├── reminders.py       # Daily medicine & follow-up retest scheduler
│   │       └── safety.py          # Emergency phrase scanner
│   └── tests/                     # Unit & integration test suite
├── supabase/
│   ├── migrations/
│   │   └── 001_initial_schema.sql # Database tables & Row Level Security policies
│   └── seed/
│       └── doctors_template.csv   # Empty CSV template for admin doctor imports
├── requirements.txt
└── README.md
```

## Setup and Running

### 1. Environment Setup

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Run the FastAPI Server

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

### 3. Run Tests

```bash
pytest -v
```
