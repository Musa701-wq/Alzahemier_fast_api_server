import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings


@pytest.mark.anyio
async def test_health_check_endpoint():
    """Verify health endpoint returns status ok and correct app info."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"{settings.API_V1_STR}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app_name"] == settings.PROJECT_NAME
        assert data["version"] == settings.VERSION


@pytest.mark.anyio
async def test_root_redirect_to_docs():
    """Verify root route redirects to Swagger UI docs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/")
        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
