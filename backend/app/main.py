from pathlib import Path
from typing import Dict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.app.core.config import settings
from backend.app.routers import (
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

    @application.middleware("http")
    async def disable_static_cache(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/assets"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    if ASSETS_DIR.exists():
        application.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    @application.get("/health", tags=["System Health"])
    def health_check() -> Dict[str, object]:
        from backend.app.db.repository import db

        return {
            "status": "ok",
            "app_name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "database": db.get_db_status(),
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
    application.include_router(ai.router)

    return application


app = create_application()
