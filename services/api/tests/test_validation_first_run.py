"""First independent validation of a persisted 4.1.2 (DeepSeek) plan: the real
validate_persisted_plan + ValidationRepository over a mocked PostgREST. No GenAI provider and no
network: provider generate() methods and DNS are refused."""

import asyncio
import json
import socket
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException

import app.validation_service as validation_service
from app.generation_content import CONTENT_V412, ContentResponseV412, assemble_plan
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_output import OnboardingPlan
from app.generation_prompt import build_prompt
from app.models import AppRole
from app.rrm_repository import RRMRepository
from app.rrm_rules import snapshot_hash
from app.validation_repository import ValidationRepository
from test_contract_v31 import COMPACT_CAPS

FIXTURES = Path(__file__).parent / "fixtures"
ACTOR = UUID("11111111-2222-4333-8444-555555555555")


@pytest.fixture(autouse=True)
def no_provider_no_network(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)

    def refuse(*args, **kwargs):
        raise AssertionError("a GenAI provider or the network was used by validation")
    from app.generation_provider import GeminiProvider, GroqProvider
    from app.nararouter_provider import NaraRouterProvider
    providers = [GeminiProvider, GroqProvider, NaraRouterProvider]
    try:
        from app.deepseek_provider import DeepSeekProvider
        providers.append(DeepSeekProvider)
    except ImportError:
        pass
    for provider in providers:
        monkeypatch.setattr(provider, "generate", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def persisted_412_plan():
    """A 4.1.2 plan exactly as the database returns it (JSON round-trip), with its run row."""
    snapshot = GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))
    content = json.loads((FIXTURES / "phase4d_v410_model_content_response.json").read_text(encoding="utf-8"))
    for item in content["requirements"].values():  # meet the 4.1.2 quality floors
        for key in ("objective", "task", "checklist", "quiz_question"):
            item[key] += " This follows the approved requirement."
        item["module_title"] += " module"
    content["plan_title"] = "Beginner Engineering Onboarding Plan"
    run_id, plan_id = uuid4(), uuid4()
    plan = OnboardingPlan.model_validate_json(json.dumps(assemble_plan(
        ContentResponseV412.model_validate_json(json.dumps(content)), snapshot, run_id)))
    stored = json.loads(json.dumps(plan.model_dump(mode="json")))
    prompt = build_prompt(snapshot, run_id, version=CONTENT_V412)
    run = {"id": str(run_id), "employee_id": str(snapshot.employee.employee_id), "employee_profile_id": None,
           "created_by": str(ACTOR), "status": "UNVERIFIED", "completed_at": "2026-09-29T06:00:00+00:00",
           "input_snapshot": json.loads(json.dumps(snapshot.model_dump(mode="json"))),
           "input_hash": input_hash(snapshot), "projection_hash": prompt.projection_hash,
           "prompt_version": CONTENT_V412, "template_hash": prompt.template_hash, "provider": "deepseek",
           "model": "deepseek-flash", "schema_version": "onboarding-plan/1.0.0"}
    row = {"id": str(plan_id), "run_id": str(run_id), "status": "UNVERIFIED",
           "schema_version": "onboarding-plan/1.0.0", "content": stored, "content_hash": snapshot_hash(stored)}
    return snapshot, row, run


class Principal:
    def __init__(self, roles=(AppRole.TRAINING_MANAGER,), profile_id=ACTOR):
        self.token = "user-token"
        self.profile = type("Profile", (), {"status": "ACTIVE", "roles": set(roles), "id": profile_id})()


def emulate_record_python_validation(run, plan, result):
    """The guards of record_python_validation (202609280002) applied to the payload."""
    evidence, decision = result["evidence"], result["decision"]
    ok = (result["validator_version"] == evidence["validator_version"] == "python-validator/1.0.0"
          and (result["input_hash"], result["projection_hash"], result["content_hash"])
          == (run["input_hash"], run["projection_hash"], plan["content_hash"])
          and isinstance(evidence["findings"], list) and len(evidence["findings"]) <= 2000
          and decision["version"] == "jev/1.0.0")
    if decision["status"] in ("VERIFIED", "VERIFIED_WITH_WARNING"):
        ok = ok and (evidence["structurally_valid"] is True and evidence["current_input"] is True
                     and 0 < evidence["mandatory_total"] == evidence["mandatory_covered"]
                     and all(f["severity"] == "WARNING" for f in evidence["findings"]))
    return ok


def validate(monkeypatch, rpc_reply, *, plan_row=None, run_row=None, principal=None, current=True):
    snapshot, plan, run = persisted_412_plan()
    plan, run = plan_row(plan) if plan_row else plan, run_row(run) if run_row else run
    calls = {"rpc": [], "payloads": []}

    def handler(request):
        table = request.url.path.rsplit("/", 1)[1]
        if request.method == "GET":
            return httpx.Response(200, json=[plan] if table == "generated_plans" else [run])
        body = json.loads(request.content)
        calls["rpc"].append(table)
        calls["payloads"].append(body)
        assert request.headers["authorization"] == "Bearer trusted-placeholder"  # backend-only credential
        status, reply = rpc_reply(body)
        return httpx.Response(status, json=reply)

    async def preflight(principal, employee_id, repository, when):
        frozen = snapshot if current else snapshot.model_copy(update={"matrix_revision": 99})
        return PreflightResult(status="READY", snapshot=frozen.model_copy(update={"as_of": when}), input_hash="x")
    monkeypatch.setattr(validation_service, "preflight", preflight)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repository = ValidationRepository(RRMRepository("https://db.invalid", "anon", client), "trusted-placeholder")
            return await validation_service.validate_persisted_plan(principal or Principal(), UUID(plan["id"]),
                                                                    repository)
    return asyncio.run(go()), calls, plan, run


def ok_reply(body):
    return 200, {"validation_run_id": str(uuid4()), "idempotent_replay": False,
                 "decision": body["p_result"]["decision"]["status"]}


# --- the production scenario ---------------------------------------------------------------------

def test_first_validation_of_a_412_plan_succeeds_and_persists(monkeypatch):
    result, calls, plan, run = validate(monkeypatch, ok_reply)
    assert calls["rpc"] == ["record_python_validation"]
    payload = calls["payloads"][0]
    assert payload["p_actor"] == str(ACTOR) and payload["p_plan"] == plan["id"]
    assert payload["p_result"]["decision"]["status"] == "VERIFIED_WITH_WARNING"
    evidence = payload["p_result"]["evidence"]
    assert (evidence["mandatory_covered"], evidence["mandatory_total"]) == (6, 6)
    assert evidence["generated_items_traceable"] == evidence["generated_items_total"] == 30
    assert emulate_record_python_validation(run, plan, payload["p_result"])  # the DB would accept it
    assert result["decision"] == "VERIFIED_WITH_WARNING"


def test_repeat_validation_is_an_idempotent_replay(monkeypatch):
    replay = lambda body: (200, {"validation_run_id": "00000000-0000-4000-8000-000000000001",
                                  "idempotent_replay": True, "decision": "VERIFIED_WITH_WARNING"})
    result, calls, _, _ = validate(monkeypatch, replay)
    assert result["idempotent_replay"] is True and calls["rpc"] == ["record_python_validation"]


def test_result_is_deterministic_so_concurrent_duplicates_replay_not_conflict(monkeypatch):
    digests = []

    def capture(body):
        digests.append(json.dumps({k: v for k, v in body["p_result"].items()
                                   if k not in ("started_at", "completed_at")}, sort_keys=True))
        return ok_reply(body)
    validate(monkeypatch, capture)
    validate(monkeypatch, capture)
    # Same persisted plan (fresh ids per build) -> compare only what the DB digests.
    first, second = (json.loads(d) for d in digests)
    assert first["decision"] == second["decision"] and first["evidence"]["findings"] == second["evidence"]["findings"]


# --- every database rejection now names itself (was one opaque VALIDATION_STATE_CONFLICT) ----------

@pytest.mark.parametrize("upstream_status,message,status,code", [
    (400, "VAL5_INVALID_INPUT", 409, "VALIDATION_RESULT_REJECTED"),
    (409, "VAL5_STALE_INPUT", 409, "VALIDATION_STALE_INPUT"),
    (409, "VAL5_IDEMPOTENCY_CONFLICT", 409, "VALIDATION_IDEMPOTENCY_CONFLICT"),
    (403, "VAL5_FORBIDDEN", 403, "VALIDATION_FORBIDDEN"),
    (400, "new row violates check constraint", 409, "VALIDATION_STATE_CONFLICT"),  # unknown: unchanged fallback
])
def test_database_rejections_are_reported_with_their_own_safe_code(monkeypatch, caplog, upstream_status, message,
                                                                  status, code):
    reply = lambda body: (upstream_status, {"code": "22023", "message": message, "details": "SECRET_SQL_DETAIL"})
    with pytest.raises(HTTPException) as caught:
        validate(monkeypatch, reply)
    assert (caught.value.status_code, caught.value.detail) == (status, code)
    assert "validation_persistence_rejected" in caplog.text and "SECRET_SQL_DETAIL" not in caplog.text
    assert "new row violates" not in caplog.text


# --- state machine, provenance and RBAC --------------------------------------------------------------

@pytest.mark.parametrize("plan_row,run_row", [
    (lambda p: {**p, "status": "VERIFIED"}, None),
    (None, lambda r: {**r, "status": "FAILED"}),
    (None, lambda r: {**r, "completed_at": None}),
])
def test_only_unverified_completed_plans_can_be_validated(monkeypatch, plan_row, run_row):
    with pytest.raises(HTTPException) as caught:
        validate(monkeypatch, ok_reply, plan_row=plan_row, run_row=run_row)
    assert (caught.value.status_code, caught.value.detail) == (409, "VALIDATION_REQUIRES_UNVERIFIED_PLAN")


def test_tampered_content_is_rejected_before_persistence(monkeypatch):
    tamper = lambda p: {**p, "content_hash": "0" * 64}
    with pytest.raises(HTTPException) as caught:
        validate(monkeypatch, ok_reply, plan_row=tamper)
    assert caught.value.detail == "VALIDATION_PROVENANCE_INVALID"


def test_changed_ground_truth_is_recorded_as_not_current_not_verified(monkeypatch):
    _, calls, _, _ = validate(monkeypatch, ok_reply, current=False)
    result = calls["payloads"][0]["p_result"]
    assert result["evidence"]["current_input"] is False and result["decision"]["status"] != "VERIFIED_WITH_WARNING"


@pytest.mark.parametrize("roles,profile,detail,status", [
    ((AppRole.REVIEWER,), ACTOR, "FORBIDDEN_ROLE", 403),
    ((AppRole.TRAINING_MANAGER,), UUID(int=7), "VALIDATION_FORBIDDEN", 403),
])
def test_rbac_is_still_enforced(monkeypatch, roles, profile, detail, status):
    with pytest.raises(HTTPException) as caught:
        validate(monkeypatch, ok_reply, principal=Principal(roles, profile))
    assert (caught.value.status_code, caught.value.detail) == (status, detail)


def test_admin_may_validate_another_authors_plan(monkeypatch):
    result, _, _, _ = validate(monkeypatch, ok_reply, principal=Principal((AppRole.ADMIN,), UUID(int=8)))
    assert result["decision"] == "VERIFIED_WITH_WARNING"


def test_validation_code_path_imports_no_generation_provider():
    import ast
    import app.validation_service as module
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not imported & {"generation_provider", "nararouter_provider", "deepseek_provider", "generation_service"}
