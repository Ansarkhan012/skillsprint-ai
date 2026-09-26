"""Phase 4C API tests use a fake caller-JWT store and fake provider only."""

import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import generation_api, security
from app import generation_prompt
from app.generation_persistence import get_generation_store
from app.generation_provider import ProviderConfig, ProviderFailure, ProviderResult
from app.main import app
from app.models import AppRole, Principal, Profile
from test_generation_context import EMP, employee, matrix, ready, stages
from test_generation_service import REQUEST, complete_output


def actor(role=AppRole.ADMIN):
    return Principal(user_id=UUID(int=71), token="opaque-test-token", profile=Profile(
        id=UUID(int=72), auth_user_id=UUID(int=71), display_name="Test", status="ACTIVE",
        roles=frozenset({role})))


class Store:
    def __init__(self):
        self.m = matrix()
        self.s = (stages(),)
        self.calls = []
        self.status = "QUEUED"
        self.attempts = []
        self.last_finish = None

    async def employee(self, token, employee_id):
        assert token == "opaque-test-token"
        return employee() if employee_id == EMP else None

    async def approved_matrix(self, token, role_id):
        return self.m

    async def stage_sets(self, token):
        return self.s

    async def rpc(self, token, name, payload):
        self.calls.append((name, payload))
        return str(UUID(int=20))

    async def reserve(self, token, payload):
        self.calls.append(("reserve", payload))
        return {"id": str(REQUEST), "status": self.status, "created": self.status == "QUEUED"}

    async def claim(self, token, run_id):
        self.calls.append(("claim", run_id))
        if self.status != "QUEUED":
            return False
        self.status = "RUNNING"
        return True

    async def record_attempt(self, token, run_id, item):
        self.attempts.append(item)

    async def finish(self, token, run_id, postflight_hash, plan, content_hash, error):
        self.last_finish = (postflight_hash, plan, content_hash, error)
        self.status = "STALE_INPUT" if plan is not None and postflight_hash is None else (
            "UNVERIFIED" if plan is not None else "FAILED")
        return self.status

    async def list_runs(self, token, offset, limit):
        return {"items": [], "offset": offset, "limit": limit, "has_more": False}

    async def detail(self, token, run_id):
        return {"id": str(run_id), "status": self.status, "attempts": len(self.attempts)}


class Provider:
    def __init__(self, response=None, failure=None):
        self.response = response or complete_output()
        self.failure = failure
        self.calls = 0

    async def generate(self, prompt, *, format_retry=False):
        self.calls += 1
        if self.failure:
            raise self.failure
        return ProviderResult(text=json.dumps(self.response), finish_reason="STOP")


@pytest.fixture
def setup(monkeypatch):
    store, provider = Store(), Provider()
    config = ProviderConfig(model="test-model", api_key=SecretStr("test-only-placeholder"))
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_generation_store] = lambda: store
    monkeypatch.setattr(generation_api, "get_provider_bundle", lambda request: (provider, config))
    with TestClient(app) as client:
        yield client, store, provider
    app.dependency_overrides.clear()


def post(client, key="test-key-123"):
    return client.post("/api/v1/generation-runs", json={"employee_id": str(EMP)},
                       headers={"Idempotency-Key": key})


def test_read_only_preflight_uses_real_context_without_provider_or_persistence(setup, monkeypatch):
    client, store, provider = setup
    monkeypatch.setattr(generation_api, "get_provider_bundle",
                        lambda request: pytest.fail("preflight must not initialize provider"))
    response = client.get(f"/api/v1/generation-runs/preflight/{EMP}")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "readiness": "READY", "employee_id": str(EMP), "blocker_codes": [],
        "matrix_id": str(store.m.id), "matrix_revision": store.m.revision,
        "stage_set_id": str(store.s[0].id), "stage_set_version": store.s[0].version,
        "requirement_count": 1, "dependency_count": 0,
        "input_hash": body["input_hash"],
    }
    assert len(body["input_hash"]) == 64
    assert "snapshot" not in body and "evidence" not in body
    assert store.calls == [] and store.attempts == [] and store.last_finish is None
    assert provider.calls == 0


def test_read_only_preflight_propagates_canonical_blocker(setup):
    client, store, provider = setup
    store.m = None
    response = client.get(f"/api/v1/generation-runs/preflight/{EMP}")
    assert response.status_code == 200
    assert response.json() == {
        "readiness": "BLOCKED", "employee_id": str(EMP), "blocker_codes": ["NO_APPROVED_MATRIX"],
        "matrix_id": None, "matrix_revision": None, "stage_set_id": None,
        "stage_set_version": None, "requirement_count": None,
        "dependency_count": None, "input_hash": None,
    }
    assert store.calls == [] and provider.calls == 0


@pytest.mark.parametrize("role,expected", [
    (AppRole.ADMIN, 200), (AppRole.TRAINING_MANAGER, 200),
    (AppRole.REVIEWER, 403), (AppRole.MANAGER, 403), (AppRole.EMPLOYEE, 403),
])
def test_read_only_preflight_preserves_author_rbac(setup, role, expected):
    client, store, provider = setup
    app.dependency_overrides[security.current_principal] = lambda: actor(role)
    assert client.get(f"/api/v1/generation-runs/preflight/{EMP}").status_code == expected
    assert store.calls == [] and provider.calls == 0


def test_read_only_preflight_rejects_unauthenticated(setup):
    client, store, provider = setup
    del app.dependency_overrides[security.current_principal]
    assert client.get(f"/api/v1/generation-runs/preflight/{EMP}").status_code == 401
    assert store.calls == [] and provider.calls == 0


def test_success_is_unverified_with_hashes_and_attempt_provenance(setup):
    client, store, provider = setup
    response = post(client)
    assert response.status_code == 202
    assert response.json()["status"] == "UNVERIFIED"
    assert provider.calls == 1
    assert len(store.attempts) == 1 and store.attempts[0].parse_outcome == "SCHEMA_VALID"
    assert store.last_finish[1]["generation_request_id"] == str(REQUEST)
    assert len(store.last_finish[0]) == len(store.last_finish[2]) == 64
    reserve = store.calls[0][1]
    assert reserve["p_employee"] == str(EMP)
    assert reserve["p_input"]["requirements"][0]["evidence"][0]["excerpt"]
    assert len(reserve["p_input_hash"]) == 64
    assert reserve["p_provider_config"]["projection_hash"] == generation_prompt.build_prompt(
        ready().snapshot).projection_hash
    assert reserve["p_provider_config"]["projection_hash"] != reserve["p_input_hash"]
    assert reserve["p_prompt_version"] == generation_prompt.PROMPT_VERSION
    assert reserve["p_template_hash"] == generation_prompt.template_hash()
    assert "api_key" not in json.dumps(reserve).lower()


def test_oversized_projection_persists_failure_without_provider_call(setup, monkeypatch):
    client, store, provider = setup
    monkeypatch.setattr(generation_prompt, "MAX_PROJECTION_BYTES", 100)
    response = post(client)
    assert response.status_code == 202
    assert response.json() == {"id": str(REQUEST), "status": "FAILED",
                               "error_code": "GENERATION_PROJECTION_TOO_LARGE"}
    assert provider.calls == 0 and store.attempts == []
    assert store.last_finish == (None, None, None, "GENERATION_PROJECTION_TOO_LARGE")
    assert [name for name, _ in store.calls] == ["reserve", "claim"]


def test_groq_run_reservation_pins_actual_provider_and_model(setup, monkeypatch):
    client, store, provider = setup
    groq = ProviderConfig(provider="groq", model="openai/gpt-oss-20b",
                          api_key=SecretStr("test-only-placeholder"))
    monkeypatch.setattr(generation_api, "get_provider_bundle", lambda request: (provider, groq))
    response = post(client)
    assert response.status_code == 202 and response.json()["status"] == "UNVERIFIED"
    reserve = store.calls[0][1]
    assert reserve["p_provider"] == "groq" and reserve["p_model"] == "openai/gpt-oss-20b"
    assert "api_key" not in json.dumps(reserve).lower()
    assert len(store.attempts) == 1 and store.attempts[0].parse_outcome == "SCHEMA_VALID"
    assert store.last_finish[1] is not None


def test_blocked_preflight_makes_no_provider_or_persistence_call(setup):
    client, store, provider = setup
    store.m = None
    response = post(client)
    assert response.status_code == 409
    assert provider.calls == 0 and store.calls == []


def test_replay_does_not_call_provider(setup):
    client, store, provider = setup
    assert post(client).status_code == 202
    assert post(client).json()["idempotent_replay"] is True
    assert provider.calls == 1


def test_stale_postflight_never_publishes_plan(setup):
    client, store, provider = setup
    original = store.approved_matrix
    count = 0

    async def changing(token, role_id):
        nonlocal count
        count += 1
        return await original(token, role_id) if count == 1 else None

    store.approved_matrix = changing
    response = post(client)
    assert response.json()["status"] == "STALE_INPUT"
    assert store.last_finish[0] is None


def test_provider_failure_records_attempt_and_failed_state(setup):
    client, store, provider = setup
    provider.failure = ProviderFailure("PROVIDER_AUTH_FAILED")
    response = post(client)
    assert response.json()["status"] == "FAILED"
    assert store.last_finish[1] is None
    assert len(store.attempts) == 1


def test_malformed_response_retries_then_fails(setup):
    client, store, provider = setup
    provider.response = {"bad": "shape"}
    response = post(client)
    assert response.json()["status"] == "FAILED"
    assert provider.calls == 2 and len(store.attempts) == 2


def test_attempt_persistence_failure_never_reports_false_terminal_state(setup):
    client, store, provider = setup

    async def unavailable(token, run_id, item):
        raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE")

    store.record_attempt = unavailable
    assert post(client).status_code == 503
    assert store.last_finish is None and store.status == "RUNNING"


@pytest.mark.parametrize("role,create,read", [
    (AppRole.ADMIN, 202, 200), (AppRole.TRAINING_MANAGER, 202, 200),
    (AppRole.REVIEWER, 403, 200), (AppRole.MANAGER, 403, 403),
    (AppRole.EMPLOYEE, 403, 403),
])
def test_role_contract(setup, role, create, read):
    client, store, provider = setup
    app.dependency_overrides[security.current_principal] = lambda: actor(role)
    assert post(client).status_code == create
    assert client.get("/api/v1/generation-runs?limit=5").status_code == read
    assert client.get(f"/api/v1/generation-runs/{REQUEST}").status_code == read
    assert client.post("/api/v1/onboarding-stage-sets/bootstrap").status_code == (
        201 if role == AppRole.ADMIN else 403)


def test_page_and_key_validation(setup):
    client, store, provider = setup
    assert client.get("/api/v1/generation-runs?limit=101").status_code == 422
    assert post(client, "x").status_code == 422
    assert provider.calls == 0
