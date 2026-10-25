# Alzheimer's Disease Staging Backend

FastAPI backend server for Alzheimer's Disease staging from brain MRI scans using explainable deep learning techniques.

---

## 🛠️ Project Structure (Section 1 - Initial Server Setup)

```text
Alzheimer’s/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   └── health.py       # Health check route
│   │       └── api.py              # Main V1 router
│   ├── core/
│   │   ├── config.py               # Application settings
│   │   └── logging.py              # Logging setup
│   ├── schemas/
│   │   └── health.py               # Pydantic schemas
│   └── main.py                     # FastAPI application factory
├── tests/
│   └── test_health.py              # Health endpoint unit tests
├── .gitignore                      # Git ignore rules
├── requirements.txt                # Base dependencies
└── README.md
```

---

## 🚀 Getting Started

### 1. Create and Activate Virtual Environment

```bash
python -m venv .venv
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Development Server

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Interactive Documentation

Once the server is running, visit:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 🧪 Running Tests

```bash
pytest -v
```
