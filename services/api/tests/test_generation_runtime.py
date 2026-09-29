"""Configuration-only tests: no live generation or network transport is allowed."""
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import generation_api, security
from app.deepseek_provider import DeepSeekProvider
from app.generation_content import CONTENT_V412
from app.generation_persistence import get_generation_store
from app.generation_provider import ProviderConfig, ProviderFailure
from app.generation_readiness import _provider_config, check_configuration, _Report, Blocked
from app.generation_runtime import (resolve_provider_config, resolve_generation_runtime,
                                    runtime_diagnostic, log_runtime_diagnostic)
from app.main import app
from app.nararouter_provider import NaraRouterProvider
from test_generation_api import Store, actor
from test_generation_context import EMP

CANARY = "secret-runtime-canary-do-not-print"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "AI_PROVIDER=deepseek\nDEEPSEEK_MODEL=deepseek-flash\nDEEPSEEK_API_KEY=" + CANARY +
        "\nGENERATION_CONTENT_ONLY=true\n")
    for name in ("AI_PROVIDER", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY", "GENERATION_CONTENT_ONLY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(tmp_path / "diagnostics.jsonl"))
    monkeypatch.setenv("NARAROUTER_API_KEY", CANARY)
    monkeypatch.setenv("NARAROUTER_MODEL", "agnes-2.5-flash")
    monkeypatch.setenv("NARAROUTER_BASE_URL", "https://nara.invalid/v1")
    def refuse(*a, **k):
        pytest.fail("outbound transport is forbidden")
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    yield tmp_path


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supabase_http=object())))


@pytest.mark.parametrize("selection,kind,model", [
    ("deepseek", DeepSeekProvider, "deepseek-flash"),
    ("nararouter", NaraRouterProvider, "agnes-2.5-flash"),
])
def test_explicit_provider_selection(monkeypatch, selection, kind, model):
    monkeypatch.setenv("AI_PROVIDER", selection)
    provider, config = generation_api.get_provider_bundle(request())
    assert isinstance(provider, kind)
    assert (config.provider, config.model) == (selection, model)


@pytest.mark.parametrize("name,value", [
    ("DEEPSEEK_API_KEY", ""), ("DEEPSEEK_MODEL", "agnes-2.5-flash"), ("AI_PROVIDER", "unknown"),
])
def test_invalid_deepseek_never_falls_back(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(HTTPException) as exc:
        generation_api.get_provider_bundle(request())
    assert exc.value.detail == "GENERATION_PROVIDER_NOT_CONFIGURED"


def test_readiness_and_api_share_resolver(isolated):
    _, api_config = generation_api.get_provider_bundle(request())
    runtime_config, version = resolve_generation_runtime()
    ready = check_configuration(_Report(), isolated)
    assert api_config == runtime_config == _provider_config("deepseek") == ready["config"]
    assert ready["version"] == version == CONTENT_V412
    assert ready["provider"] == "deepseek"


def test_precedence_and_per_request_resolution(monkeypatch):
    assert resolve_provider_config().provider == "deepseek"  # durable .env
    monkeypatch.setenv("AI_PROVIDER", "nararouter")
    assert resolve_provider_config().provider == "nararouter"  # inherited process env wins
    with pytest.raises(ProviderFailure, match="GENERATION_CONFIGURATION_MISMATCH"):
        resolve_generation_runtime()
    monkeypatch.delenv("AI_PROVIDER")
    assert resolve_generation_runtime()[0].provider == "deepseek"


def test_startup_and_serving_process_diagnostic_never_expose_secrets(caplog):
    caplog.set_level(logging.INFO, logger="skillsprint.generation")
    with TestClient(app) as client:
        response = client.get("/api/v1/generation-config")
    assert response.status_code == 200
    assert response.json() == {
        "ai_provider": "deepseek", "ai_model": "deepseek-flash",
        "generation_mode": "content-only", "prompt_target": CONTENT_V412}
    messages = [r.getMessage() for r in caplog.records if r.name == "skillsprint.generation"]
    assert messages == ["AI provider: deepseek", "AI model: deepseek-flash",
                        "Generation mode: content-only", "Prompt target: " + CONTENT_V412]
    assert CANARY not in caplog.text + response.text
    assert "Authorization" not in caplog.text + response.text


def test_mismatch_is_visible_without_generation(monkeypatch, caplog, isolated):
    monkeypatch.setenv("AI_PROVIDER", "nararouter")
    with TestClient(app) as client:
        response = client.get("/api/v1/generation-config")
    assert response.status_code == 503
    assert response.json()["code"] == "GENERATION_CONFIGURATION_MISMATCH"
    with pytest.raises(Blocked, match="GENERATION_CONFIGURATION_MISMATCH"):
        check_configuration(_Report(), isolated)
    assert CANARY not in caplog.text + response.text


@pytest.mark.parametrize("provider,model", [
    ("nararouter", "agnes-2.5-flash"), ("gemini", "test-model"),
    ("deepseek", "wrong-model"),
])
def test_mismatch_refuses_reservation_and_provider(monkeypatch, provider, model):
    store = Store()
    config = ProviderConfig(provider=provider, model=model, api_key=SecretStr(CANARY))
    class NeverProvider:
        async def generate(self, *a, **k):
            pytest.fail("generation must never be reached")
    monkeypatch.setattr(generation_api, "get_provider_bundle", lambda request: (NeverProvider(), config))
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_generation_store] = lambda: store
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/generation-runs", json={"employee_id": str(EMP)},
                                   headers={"Idempotency-Key": "config-guard-test"})
        assert response.status_code == 503
        assert response.json()["code"] == "GENERATION_CONFIGURATION_MISMATCH"
        assert response.json()["generation_retry_safe"] is True
        assert store.calls == [] and store.attempts == [] and store.last_finish is None
    finally:
        app.dependency_overrides.clear()


def test_correct_config_reaches_reservation_without_generation(monkeypatch):
    store = Store()
    async def reserve(token, payload):
        assert (payload["p_provider"], payload["p_model"], payload["p_prompt_version"]) == (
            "deepseek", "deepseek-flash", CONTENT_V412)
        raise HTTPException(409, "TEST_STOP_BEFORE_GENERATION")
    monkeypatch.setattr(store, "reserve", reserve)
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_generation_store] = lambda: store
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/generation-runs", json={"employee_id": str(EMP)},
                                   headers={"Idempotency-Key": "config-guard-test"})
        assert response.status_code == 409
        assert response.json()["code"] == "TEST_STOP_BEFORE_GENERATION"
    finally:
        app.dependency_overrides.clear()
