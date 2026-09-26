"""Product reads exercise JWT forwarding and authorization without live services."""
from uuid import UUID
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
from app import security
from app.main import app
from app.models import AppRole
from app.supabase import get_gateway
from app.validation_repository import ValidationRepository, get_validation_repository
from app.rrm_repository import RRMRepository
from test_generation_api import actor

ID = UUID(int=900)


class Reads:
    def __init__(self): self.calls = []
    async def request(self, token, table, params):
        self.calls.append((token, table, params))
        return [{"id": str(ID), "employee_code": "TEST_ONLY"}] if table == "employees" else []
    async def list_runs(self, token, offset, limit):
        self.calls.append((token, offset, limit))
        return {"items": [], "offset": offset, "limit": limit, "has_more": False}


@pytest.mark.parametrize("path,allowed", [
    (f"/api/v1/employees/{ID}", {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER}),
    ("/api/v1/audit-events", {AppRole.ADMIN}),
    ("/api/v1/validation-runs", {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER}),
])
def test_product_read_role_matrix_and_caller_token(path, allowed):
    try:
        for role in AppRole:
            store = Reads()
            app.dependency_overrides[security.current_principal] = lambda role=role: actor(role)
            app.dependency_overrides[get_gateway] = lambda: store
            app.dependency_overrides[get_validation_repository] = lambda: store
            with TestClient(app) as client:
                response = client.get(path)
            assert response.status_code == (200 if role in allowed else 403)
            assert bool(store.calls) == (role in allowed)
            if store.calls: assert store.calls[0][0] == "opaque-test-token"
    finally: app.dependency_overrides.clear()


@pytest.mark.parametrize("path", [f"/api/v1/employees/{ID}", "/api/v1/audit-events", "/api/v1/validation-runs"])
def test_product_reads_require_auth(path):
    with TestClient(app) as client: assert client.get(path).status_code == 401


def test_employee_projection_and_bounded_pagination():
    store = Reads()
    try:
        app.dependency_overrides[security.current_principal] = lambda: actor()
        app.dependency_overrides[get_gateway] = lambda: store
        with TestClient(app) as client:
            assert client.get("/api/v1/employees?offset=30&limit=30").status_code == 200
            params = store.calls[0][2]
            assert params["offset"] == "30" and params["limit"] == "30"
            assert "experience_level" in params["select"] and "joining_date" in params["select"]
            assert "profiles(display_name)" in params["select"]
            for path in ("employees", "roles", "departments", "audit-events"):
                assert client.get(f"/api/v1/{path}?limit=1000").status_code == 422
            assert client.get("/api/v1/audit-events").status_code == 200
            audit = store.calls[-1][2]
            assert "occurred_at" in audit["select"]
            assert not any(x in audit["select"] for x in ("metadata", "reason", "*"))
    finally: app.dependency_overrides.clear()


def test_validation_listing_is_select_only_under_user_jwt():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"id": str(ID)}, {"id": str(UUID(int=901))}])
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repo = ValidationRepository(RRMRepository("https://invalid.local", "test-public", client), "unused-trusted")
            result = await repo.list_runs("caller-test", 2, 1)
            assert len(result["items"]) == 1 and result["has_more"]
    asyncio.run(scenario())
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].headers["Authorization"] == "Bearer caller-test"
    assert calls[0].url.params["offset"] == "2"
    assert calls[0].url.path.endswith("/validation_runs")


def test_generation_employee_filter_preserves_caller_rls_and_pagination():
    from app.generation_persistence import GenerationStore
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = GenerationStore(RRMRepository("https://invalid.local", "test-public", client))
            await store.list_runs("caller-test", 30, 30, employee_id=ID)
    asyncio.run(scenario())
    assert calls[0].headers["Authorization"] == "Bearer caller-test"
    assert calls[0].url.params["employee_id"] == f"eq.{ID}"
    assert calls[0].url.params["offset"] == "30"
    assert calls[0].method == "GET"
