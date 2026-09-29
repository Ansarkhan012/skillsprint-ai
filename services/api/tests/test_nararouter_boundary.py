"""The real backend boundary for run a7e4224d (4.1.0): production NaraRouter adapter with realistic
HTTP envelopes -> extraction -> JSON -> 4.1.0 content model -> assembly -> OnboardingPlan -> validator
-> JEV, and the production store's diagnostics persistence over a mocked PostgREST. No provider call,
no database: every HTTP exchange is an httpx.MockTransport."""

import asyncio
import json
import socket
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.generation_content import CONTENT_V410
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_persistence import GenerationStore
from app.generation_service import AttemptTelemetry, generate_unverified
from app.jev import decide
from app.nararouter_provider import NaraRouterConfig, NaraRouterProvider
from app.plan_validator import validate_plan
from app.rrm_repository import RRMRepository
from test_contract_v31 import COMPACT_CAPS

FIXTURES = Path(__file__).parent / "fixtures"
RUN = UUID("a7e4224d-8b27-4008-a2db-4bbe76a21f70")
CANARY = "CANARY_LIVE_PROSE_b77"
LIVE_USAGE = {"prompt_tokens": 938, "completion_tokens": 562, "total_tokens": 1500}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def snapshot():
    return GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))


def fixture():
    return json.loads((FIXTURES / "phase4d_v410_model_content_response.json").read_text(encoding="utf-8"))


def envelope(content, finish="stop"):
    """An OpenAI-compatible chat.completion body as NaraRouter returns it."""
    return {"id": "chatcmpl-test", "object": "chat.completion", "model": "agnes-2.5-flash",
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": LIVE_USAGE}


def run_adapter(body):
    config = NaraRouterConfig(provider="nararouter", model="agnes-2.5-flash", api_key=SecretStr("placeholder"),
                              base_url="https://nara.invalid/v1", timeout_seconds=290, max_output_tokens=32768,
                              temperature=0.1)
    frozen, attempts, sent = snapshot(), [], []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def record(item):
                attempts.append(item)

            async def no_sleep(_s):
                return None
            return await generate_unverified(PreflightResult(status="READY", snapshot=frozen,
                                                             input_hash=input_hash(frozen)), RUN,
                                             NaraRouterProvider(client, config), no_sleep, on_attempt=record,
                                             prompt_version=CONTENT_V410)
    return asyncio.run(go()), attempts, sent, frozen


# --- the boundary accepts every conforming representation --------------------------------------

@pytest.mark.parametrize("encode", [
    lambda d: json.dumps(d, indent=2, ensure_ascii=False),
    lambda d: json.dumps(d, separators=(",", ":")),
    lambda d: "\n  " + json.dumps(d, indent=2).replace("\n", "\r\n") + "\n",
    lambda d: json.dumps(d, ensure_ascii=True),
    lambda d: json.dumps({"requirements": d["requirements"], "plan_title": d["plan_title"]}),  # key order
], ids=["pretty", "compact", "crlf-and-whitespace", "escaped-unicode", "reordered-keys"])
def test_conforming_provider_response_passes_the_full_production_path(encode):
    result, attempts, sent, frozen = run_adapter(envelope(encode(fixture())))
    assert result.status == "UNVERIFIED" and result.prompt_version == CONTENT_V410
    assert sent[0]["response_format"]["type"] == "json_schema" and sent[0]["reasoning_effort"] == "low"
    assert attempts[0].usage == {"prompt_tokens": 938, "output_tokens": 562, "total_tokens": 1500}
    evidence = validate_plan(result.plan.model_dump(mode="json"), frozen, RUN, current_input=True)
    assert (evidence.mandatory_covered, evidence.mandatory_total) == (6, 6)
    assert evidence.generated_items_traceable == evidence.generated_items_total == 30
    assert decide(evidence).status == "VERIFIED_WITH_WARNING"


# --- the live failure signature is reproduced through the same path ------------------------------

def test_live_signature_partial_response_fails_before_assembly_with_exact_diagnostic():
    data = fixture()
    data["requirements"] = {key: data["requirements"][key] for key in ("R1", "R2", "R3")}
    data["requirements"]["R1"]["objective"] = CANARY
    content = json.dumps(data, indent=2, ensure_ascii=False)
    assert 1400 < len(content.encode()) < 1900  # the size class of the live 1,511-byte response
    result, attempts, _, _ = run_adapter(envelope(content))
    assert (result.status, result.error_code, result.plan) == ("FAILED", "SCHEMA_INVALID", None)
    attempt = attempts[0]
    assert (attempt.provider_outcome, attempt.parse_outcome) == ("RESPONSE", "SCHEMA_INVALID")
    detail = attempt.diagnostics
    assert detail["layer"] == "requirement_keys"
    assert [(e["loc"], e["type"]) for e in detail["errors"]] == [
        ("requirements.R4", "missing_requirement_content"), ("requirements.R5", "missing_requirement_content"),
        ("requirements.R6", "missing_requirement_content")]
    assert detail["received"]["requirement_keys_received"] == 3 and CANARY not in json.dumps(detail)


@pytest.mark.parametrize("content,error,layer", [
    (lambda d: json.dumps({**d, "requirements": [dict(v, key=k) for k, v in d["requirements"].items()]}),
     "SCHEMA_INVALID", "content_model"),
    (lambda d: "```json\n" + json.dumps(d) + "\n```", "MALFORMED_JSON", "content_json"),
    (lambda d: "Here is the plan:\n" + json.dumps(d), "MALFORMED_JSON", "content_json"),
], ids=["input-style list", "markdown fence", "leading prose"])
def test_other_plausible_live_shapes_are_attributed_to_the_right_layer(content, error, layer):
    result, attempts, _, _ = run_adapter(envelope(content(fixture())))
    assert result.error_code == error and attempts[0].diagnostics["layer"] == layer


@pytest.mark.parametrize("body,error", [
    (envelope([{"type": "text", "text": "{}"}]), "PROVIDER_INVALID_RESPONSE"),   # content parts, not a string
    (envelope({"plan_title": "x"}), "PROVIDER_INVALID_RESPONSE"),               # object, not a string
    (envelope(None), "PROVIDER_INVALID_RESPONSE"),
    (envelope("{}", finish="length"), "PROVIDER_TRUNCATED"),
], ids=["content-parts", "content-object", "content-null", "truncated"])
def test_non_string_content_is_a_provider_error_never_schema_invalid(body, error):
    result, attempts, _, _ = run_adapter(body)
    assert result.error_code == error and attempts[0].parse_outcome == "NOT_PARSED"


# --- diagnostics persistence: the defect that lost run a7e4224d's evidence ----------------------

def store_with(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GenerationStore(RRMRepository("https://project.supabase.invalid", "anon-placeholder", client)), client


def failed_attempt():
    data = fixture()
    data["requirements"] = {"R1": data["requirements"]["R1"]}
    data["requirements"]["R1"]["task"] = CANARY
    _, attempts, _, _ = run_adapter(envelope(json.dumps(data)))
    return attempts[0]


@pytest.mark.parametrize("status,body,persisted,code", [
    (204, None, True, None),
    (404, {"code": "PGRST202", "message": "Could not find the function " + CANARY}, False, "PGRST202"),
    (400, {"code": "P0001", "message": "GEN4_INVALID_DIAGNOSTICS"}, False, "GEN4_INVALID_DIAGNOSTICS"),
    (403, {"code": "42501", "message": "permission denied for function " + CANARY}, False, "42501"),
])
def test_every_diagnostics_write_outcome_is_recorded_durably_and_content_free(tmp_path, monkeypatch, caplog,
                                                                            status, body, persisted, code):
    sink = tmp_path / "logs" / "generation_diagnostics.jsonl"
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(sink))
    item = failed_attempt()
    calls = []

    def handler(request):
        name = request.url.path.rsplit("/", 1)[1]
        calls.append(name)
        if name == "record_generation_attempt":
            return httpx.Response(200, json=1)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    store, client = store_with(handler)
    asyncio.run(store.record_attempt("user-token", RUN, item))
    asyncio.run(client.aclose())
    assert calls == ["record_generation_attempt", "record_generation_attempt_diagnostics"]
    line = json.loads(sink.read_text(encoding="utf-8").strip())
    assert (line["run_id"], line["attempt_no"], line["error_code"]) == (str(RUN), 1, "SCHEMA_INVALID")
    assert (line["db_persisted"], line["db_status"], line["db_code"]) == (persisted, status, code)
    assert line["diagnostics"]["layer"] == "requirement_keys"
    assert line["usage"] == {"prompt_tokens": 938, "output_tokens": 562, "total_tokens": 1500}
    text = sink.read_text(encoding="utf-8") + caplog.text
    assert CANARY not in text and "user-token" not in text and "anon-placeholder" not in text
    if not persisted:
        assert f"db_status={status} db_code={code}" in caplog.text


def test_non_integer_attempt_number_is_no_longer_skipped_silently(tmp_path, monkeypatch, caplog):
    sink = tmp_path / "diag.jsonl"
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(sink))
    calls = []

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json=[{"record_generation_attempt": 1}])  # unexpected PostgREST shape
    store, client = store_with(handler)
    asyncio.run(store.record_attempt("t", RUN, failed_attempt()))
    asyncio.run(client.aclose())
    assert calls == ["record_generation_attempt"]
    line = json.loads(sink.read_text(encoding="utf-8"))
    assert line["db_persisted"] is False and line["db_code"] == "ATTEMPT_NUMBER_NOT_INTEGER:list"
    assert "generation_attempt_diagnostics_not_persisted" in caplog.text


def test_successful_attempts_write_nothing_extra(tmp_path, monkeypatch):
    sink = tmp_path / "diag.jsonl"
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(sink))
    calls = []

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json=1)
    store, client = store_with(handler)
    ok = AttemptTelemetry(attempt_type="INITIAL", provider_outcome="RESPONSE", latency_ms=7833,
                          response_hash="ab" * 32, response_size=1511, parse_outcome="SCHEMA_VALID")
    asyncio.run(store.record_attempt("t", RUN, ok))
    asyncio.run(client.aclose())
    assert calls == ["record_generation_attempt"] and not sink.exists()


def test_local_file_failure_never_breaks_generation(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(blocker / "diag.jsonl"))
    store, client = store_with(lambda request: httpx.Response(200, json=1) if request.url.path.endswith(
        "record_generation_attempt") else httpx.Response(204))
    asyncio.run(store.record_attempt("t", RUN, failed_attempt()))
    asyncio.run(client.aclose())
    assert "generation_local_diagnostics_not_written" in caplog.text


def test_gate_blocks_when_local_diagnostics_are_disabled(tmp_path, monkeypatch):
    from app import generation_readiness as gate
    from test_readiness import EMPLOYEE, SNAPSHOT_FILE, backend_env  # noqa: F401
    directory = tmp_path / "backend"
    directory.mkdir()
    (directory / ".env").write_text("\n".join([
        "AI_PROVIDER=nararouter", "NARAROUTER_API_KEY=placeholder", "NARAROUTER_BASE_URL=https://n.invalid/v1",
        "NARAROUTER_MODEL=agnes-2.5-flash", "NARAROUTER_TIMEOUT_SECONDS=290", "GENERATION_CONTENT_ONLY=true", ""]),
        encoding="utf-8")
    for name in ("AI_PROVIDER", "NARAROUTER_API_KEY", "NARAROUTER_BASE_URL", "NARAROUTER_MODEL",
                 "NARAROUTER_TIMEOUT_SECONDS", "GENERATION_CONTENT_ONLY", "GENERATION_SOURCE_KEYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", "")
    result = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), backend_dir=str(directory))
    assert result.final_line.startswith("BLOCKED: A. runtime configuration") and "GENERATION_DIAGNOSTICS_FILE" in result.final_line
