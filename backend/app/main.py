import mimetypes
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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
SCENE_IMAGES_DIR = ROOT_DIR / "uploads" / "scene_images"
SCENE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


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

    @application.get("/assets/{asset_path:path}", include_in_schema=False)
    def serve_asset(asset_path: str):
        target = (ASSETS_DIR / asset_path).resolve()
        if not str(target).startswith(str(ASSETS_DIR.resolve())) or not target.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")
        mime_type, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".js":
            mime_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            mime_type = "text/css; charset=utf-8"
        return Response(
            content=target.read_bytes(),
            media_type=mime_type or "application/octet-stream",
            headers=NO_CACHE_HEADERS,
        )

    @application.get("/scene-images/{filename}", include_in_schema=False)
    def serve_scene_image(filename: str):
        target = (SCENE_IMAGES_DIR / filename).resolve()
        if not str(target).startswith(str(SCENE_IMAGES_DIR.resolve())) or not target.is_file():
            raise HTTPException(status_code=404, detail="Scene image not found")
        mime_type, _ = mimetypes.guess_type(str(target))
        return Response(
            content=target.read_bytes(),
            media_type=mime_type or "image/jpeg",
            headers=NO_CACHE_HEADERS,
        )

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
            return Response(
                content=index_file.read_bytes(),
                media_type="text/html; charset=utf-8",
                headers=NO_CACHE_HEADERS,
            )
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
