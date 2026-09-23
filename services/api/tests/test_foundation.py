from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import AppRole, Profile
from app.security import decode_access_token
from app.supabase import get_gateway


class FakeGateway:
    def __init__(self, profile: Profile | None):
        self.profile = profile

    async def get_profile(self, token, user_id):
        return self.profile

    async def request(self, token, table, params):
        return []

    async def create(self, token, table, payload):
        return {"id": str(uuid4()), **payload}


def profile(*roles: AppRole, status="ACTIVE") -> Profile:
    return Profile(
        id=uuid4(), auth_user_id=uuid4(), display_name="Test User",
        status=status, roles=frozenset(roles),
    )


def client_with(monkeypatch, test_profile):
    from app import security
    monkeypatch.setattr(security, "decode_access_token", lambda token, settings: test_profile.auth_user_id if test_profile else uuid4())
    app.dependency_overrides[get_gateway] = lambda: FakeGateway(test_profile)
    return TestClient(app)


PROTECTED_ROUTES = [
    ("GET", "/api/v1/me", None, {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER, AppRole.EMPLOYEE}),
    ("GET", "/api/v1/admin/check", None, {AppRole.ADMIN}),
    ("GET", "/api/v1/departments", None, {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER}),
    ("GET", "/api/v1/roles", None, {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER}),
    ("GET", "/api/v1/employees", None, {AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER}),
    ("POST", "/api/v1/departments", {"code": "TEST_DEP", "name": "Test Department"}, {AppRole.ADMIN}),
    ("POST", "/api/v1/roles", {"code": "TEST_ROLE", "name": "Test Role"}, {AppRole.ADMIN, AppRole.TRAINING_MANAGER}),
    ("POST", "/api/v1/employees", {
        "employee_code": "TEST_EMP", "role_id": str(uuid4()),
        "department_id": str(uuid4()), "experience_level": "BEGINNER",
        "joining_date": "2026-01-01",
    }, {AppRole.ADMIN, AppRole.TRAINING_MANAGER}),
]


@pytest.mark.parametrize("method,path,payload,allowed", PROTECTED_ROUTES)
def test_complete_protected_route_role_matrix(monkeypatch, method, path, payload, allowed):
    for role in AppRole:
        with client_with(monkeypatch, profile(role)) as client:
            response = client.request(method, path, headers={"Authorization": "Bearer fake"}, json=payload)
        app.dependency_overrides.clear()
        expected = (201 if method == "POST" else 200) if role in allowed else 403
        assert response.status_code == expected, (method, path, role, response.text)


@pytest.mark.parametrize("method,path,payload,allowed", PROTECTED_ROUTES)
def test_every_protected_route_rejects_unauthenticated(method, path, payload, allowed):
    with TestClient(app) as client:
        response = client.request(method, path, json=payload)
    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize("method,path,payload,allowed", PROTECTED_ROUTES)
@pytest.mark.parametrize("test_profile", [None, profile(AppRole.ADMIN, status="INACTIVE")], ids=["missing", "inactive"])
def test_every_protected_route_rejects_missing_or_inactive_profile(monkeypatch, method, path, payload, allowed, test_profile):
    with client_with(monkeypatch, test_profile) as client:
        response = client.request(method, path, headers={"Authorization": "Bearer fake"}, json=payload)
    app.dependency_overrides.clear()
    assert response.status_code == 403, (method, path, response.text)
    assert response.json()["code"] == "PROFILE_INACTIVE_OR_MISSING"


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "skillsprint-api"}


def test_protected_rejects_missing_token():
    with TestClient(app) as client:
        response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_admin_allowed_and_employee_forbidden(monkeypatch):
    with client_with(monkeypatch, profile(AppRole.ADMIN)) as client:
        allowed = client.get("/api/v1/admin/check", headers={"Authorization": "Bearer fake"})
    app.dependency_overrides.clear()
    with client_with(monkeypatch, profile(AppRole.EMPLOYEE)) as client:
        forbidden = client.get("/api/v1/admin/check", headers={"Authorization": "Bearer fake"})
    app.dependency_overrides.clear()
    assert allowed.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"


def test_missing_and_inactive_profiles_denied(monkeypatch):
    for item in (None, profile(AppRole.ADMIN, status="INACTIVE"), profile(status="ACTIVE")):
        with client_with(monkeypatch, item) as client:
            response = client.get("/api/v1/me", headers={"Authorization": "Bearer fake"})
        app.dependency_overrides.clear()
        assert response.status_code == 403


def test_role_access_matrix(monkeypatch):
    cases = [
        (AppRole.ADMIN, 200, 200),
        (AppRole.TRAINING_MANAGER, 200, 200),
        (AppRole.REVIEWER, 200, 200),
        (AppRole.MANAGER, 200, 200),
        (AppRole.EMPLOYEE, 403, 403),
    ]
    for role, departments_status, employees_status in cases:
        with client_with(monkeypatch, profile(role)) as client:
            headers = {"Authorization": "Bearer fake"}
            assert client.get("/api/v1/departments", headers=headers).status_code == departments_status
            assert client.get("/api/v1/employees", headers=headers).status_code == employees_status
        app.dependency_overrides.clear()


def test_mutation_permissions_and_validation(monkeypatch):
    role_payload = {"code": "SUPPORT", "name": "Support"}
    with client_with(monkeypatch, profile(AppRole.TRAINING_MANAGER)) as client:
        headers = {"Authorization": "Bearer fake"}
        assert client.post("/api/v1/roles", headers=headers, json=role_payload).status_code == 201
        assert client.post("/api/v1/departments", headers=headers, json={"code": "OPS", "name": "Operations"}).status_code == 403
        assert client.post("/api/v1/roles", headers=headers, json={"code": "bad space", "name": "Bad"}).status_code == 422
    app.dependency_overrides.clear()
    with client_with(monkeypatch, profile(AppRole.REVIEWER)) as client:
        assert client.post("/api/v1/roles", headers={"Authorization": "Bearer fake"}, json=role_payload).status_code == 403
    app.dependency_overrides.clear()


def test_malformed_token_rejected_before_profile_lookup():
    from app.config import Settings
    from fastapi import HTTPException
    import pytest

    settings = Settings(supabase_url="https://example.supabase.co", supabase_anon_key="public")
    with pytest.raises(HTTPException) as exc:
        decode_access_token("not-a-jwt", settings)
    assert exc.value.status_code == 401


def test_jwt_signature_audience_and_role(monkeypatch):
    import time
    from types import SimpleNamespace

    import jwt
    import pytest
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi import HTTPException

    from app import security
    from app.config import Settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(security, "jwks_client", lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))
    settings = Settings(supabase_url="https://example.supabase.co", supabase_anon_key="public")
    user_id = uuid4()
    claims = {
        "sub": str(user_id), "aud": "authenticated", "role": "authenticated",
        "iss": "https://example.supabase.co/auth/v1", "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    assert decode_access_token(token, settings) == user_id
    for changed in ({"aud": "wrong"}, {"role": "anon"}, {"exp": int(time.time()) - 1}):
        invalid = jwt.encode({**claims, **changed}, key, algorithm="RS256")
        with pytest.raises(HTTPException) as exc:
            decode_access_token(invalid, settings)
        assert exc.value.status_code == 401


def test_malformed_profile_data_denied(monkeypatch):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from app.supabase import SupabaseGateway

    user_id = uuid4()
    gateway = SupabaseGateway("https://example.supabase.co", "public")

    async def bad_response(token, table, params):
        if table == "profiles":
            return [{"id": str(uuid4()), "auth_user_id": str(user_id), "display_name": "Test", "status": "ACTIVE"}]
        return [{"role": "UNKNOWN_ROLE"}]

    monkeypatch.setattr(gateway, "request", bad_response)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway.get_profile("token", user_id))
    assert exc.value.status_code == 403
