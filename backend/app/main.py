from pathlib import Path
from typing import Dict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.app.core.config import settings
from backend.app.routers import (
    admin,
    ai,
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

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if ASSETS_DIR.exists():
        application.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    @application.get("/health", tags=["System Health"])
    def health_check() -> Dict[str, str]:
        return {
            "status": "ok",
            "app_name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "disclaimer": settings.SCREENING_DISCLAIMER,
        }

    @application.get("/", include_in_schema=False)
    def serve_frontend():
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"message": "Yaadasht API is running. Visit /docs for OpenAPI documentation."})

    application.include_router(auth.router)
    application.include_router(profiles.router)
    application.include_router(sessions.router)
    application.include_router(results.router)
    application.include_router(reports.router)
    application.include_router(doctors.router)
    application.include_router(post_visit.router)
    application.include_router(reminders.router)
    application.include_router(safety.router)
    application.include_router(admin.router)
    application.include_router(ai.router)

    return application


app = create_application()
