"""Forensics for run 038d8126: every 4.0.1 SCHEMA_INVALID layer, persisted safe diagnostics,
leak prevention and capping. Offline: provider methods and outbound network are refused."""

import asyncio
import json
import logging
import re
import socket
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from app.generation_content import CONTENT_V401, ContentResponse, assemble_plan
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_persistence import GenerationStore
from app.generation_prompt import build_prompt
from app.generation_provider import GeminiProvider, GroqProvider, ProviderResult
from app.generation_service import (MAX_DIAGNOSTIC_BYTES, MAX_DIAGNOSTIC_ERRORS, AttemptTelemetry, StructuralFailure,
                                    assemble_content, failure_detail, generate_unverified, parse_plan)
from app.nararouter_provider import NaraRouterProvider
from test_contract_v31 import COMPACT_CAPS, schema_errors

FIXTURES = Path(__file__).parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RUN = UUID("038d8126-1f74-49cc-a8a0-28a79ee9716f")
CANARY = "CANARY_GENERATED_PROSE_x91"
EVIDENCE_CANARY = "CANARY_POLICY_EXCERPT_q52"
SECRET_CANARY = "sk-CANARY-SECRET-z07"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("NARAROUTER_API_KEY", SECRET_CANARY)

    def refuse(*args, **kwargs):
        raise AssertionError("provider or network used")
    for provider in (NaraRouterProvider, GroqProvider, GeminiProvider):
        monkeypatch.setattr(provider, "generate", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def snapshot(with_canary=False):
    frozen = GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))
    if not with_canary:
        return frozen
    requirements = tuple(req.model_copy(update={
        "statement": EVIDENCE_CANARY + " statement",
        "evidence": tuple(e.model_copy(update={"excerpt": EVIDENCE_CANARY + " excerpt"}) for e in req.evidence)})
        for req in frozen.requirements)
    return frozen.model_copy(update={"requirements": requirements})


def fixture():
    return json.loads((FIXTURES / "phase4d_v401_model_content_response.json").read_text(encoding="utf-8"))


def mutated(change):
    data = fixture()
    for item in data["requirements"].values():
        item["objective"] = CANARY + " objective"
    change(data)
    return json.dumps(data)


def failure(text, frozen=None):
    with pytest.raises(StructuralFailure) as caught:
        assemble_content(text, frozen or snapshot(), RUN, CONTENT_V401)
    return caught.value


def assert_safe(detail, logs=""):
    text = json.dumps(detail) + logs
    for secret in (CANARY, EVIDENCE_CANARY, SECRET_CANARY):
        assert secret.lower() not in text.lower()
    assert len(json.dumps(detail, sort_keys=True).encode()) <= MAX_DIAGNOSTIC_BYTES


# --- 2/5. every 4.0.1 SCHEMA_INVALID layer, with the rejecting layer identified ----------------------

AGNES_MISTAKES = [
    # name, response text, provider-schema rejects?, code, layer, first error (loc, type)
    ("omitted R#", mutated(lambda d: d["requirements"].pop("R3")), True, "SCHEMA_INVALID", "requirement_keys",
     ("requirements.R3", "missing_requirement_content")),
    ("extra R#", mutated(lambda d: d["requirements"].update(R7=d["requirements"]["R1"])), True, "SCHEMA_INVALID",
     "requirement_keys", ("requirements.unknown_field", "unknown_requirement_key")),
    ("requirement missing one field", mutated(lambda d: d["requirements"]["R2"].pop("checklist_activity")), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.checklist_activity", "missing")),
    ("empty string", mutated(lambda d: d["requirements"]["R2"].update(quiz_question="")), True, "SCHEMA_INVALID",
     "content_model", ("requirements.R2.quiz_question", "string_too_short")),
    ("string over max", mutated(lambda d: d["requirements"]["R2"].update(quiz_options=[CANARY * 10, "b", "c"])),
     True, "SCHEMA_INVALID", "content_model", ("requirements.R2.quiz_options.0", "string_too_long")),
    ("minutes out of range", mutated(lambda d: d["requirements"]["R2"].update(estimated_minutes=20000)), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.estimated_minutes", "less_than_equal")),
    ("objectives as a list", mutated(lambda d: d["requirements"]["R2"].update(objective=[CANARY, CANARY])), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.objective", "string_type")),
    ("missing task", mutated(lambda d: [d["requirements"]["R2"].pop(f) for f in (
        "task_description", "task_expected_outcome", "task_completion_criteria")]), True, "SCHEMA_INVALID",
     "content_model", ("requirements.R2.task_description", "missing")),
    ("criteria too many", mutated(lambda d: d["requirements"]["R2"].update(task_completion_criteria=["c"] * 21)),
     True, "SCHEMA_INVALID", "content_model", ("requirements.R2.task_completion_criteria", "too_long")),
    ("quiz missing", mutated(lambda d: [d["requirements"]["R2"].pop(f) for f in (
        "quiz_question", "quiz_options", "correct_option_index", "quiz_explanation")]), True, "SCHEMA_INVALID",
     "content_model", ("requirements.R2.quiz_question", "missing")),
    ("2 options", mutated(lambda d: d["requirements"]["R2"].update(quiz_options=["a", "b"])), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.quiz_options", "too_short")),
    ("4 options", mutated(lambda d: d["requirements"]["R2"].update(quiz_options=["a", "b", "c", "d"])), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.quiz_options", "too_long")),
    ("correct index 3", mutated(lambda d: d["requirements"]["R2"].update(correct_option_index=3)), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.correct_option_index", "less_than_equal")),
    ("null where string expected", mutated(lambda d: d["requirements"]["R2"].update(module_purpose=None)), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.module_purpose", "string_type")),
    ("null where list expected", mutated(lambda d: d["requirements"]["R2"].update(task_completion_criteria=None)),
     True, "SCHEMA_INVALID", "content_model", ("requirements.R2.task_completion_criteria", "tuple_type")),
    ("unexpected property", mutated(lambda d: d["requirements"]["R2"].update(notes=CANARY)), True,
     "SCHEMA_INVALID", "content_model", ("requirements.R2.unknown_field", "extra_forbidden")),
    ("wrapper object", json.dumps({"plan": json.loads(mutated(lambda d: None))}), True, "SCHEMA_INVALID",
     "content_model", ("plan", "extra_forbidden")),
    ("requirements as a list", mutated(lambda d: d.update(requirements=list(d["requirements"].values()))), True,
     "SCHEMA_INVALID", "content_model", ("requirements", "dict_type")),
    # Schema-valid but semantically invalid: only the Python content model can see it.
    ("duplicate options (case/space only)", mutated(lambda d: (d["requirements"]["R2"].update(
        quiz_options=["Yes", " yes", "No"]), d["requirements"]["R1"].update(module_purpose="Short enough."))), False, "SCHEMA_INVALID", "content_model",
     ("requirements.R2", "value_error")),
    ("markdown fenced JSON", "```json\n" + mutated(lambda d: None) + "\n```", True, "MALFORMED_JSON",
     "content_json", ("", "invalid_json")),
]


@pytest.mark.parametrize("name,text,schema_rejects,code,layer,first", AGNES_MISTAKES, ids=[m[0] for m in AGNES_MISTAKES])
def test_each_realistic_mistake_is_rejected_at_its_layer_with_a_safe_actionable_diagnostic(
        caplog, monkeypatch, name, text, schema_rejects, code, layer, first):
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "true")
    frozen = snapshot(with_canary=True)
    schema = build_prompt(frozen, RUN).response_schema
    try:
        decoded = json.loads(text)
    except ValueError:
        decoded = None
    if decoded is not None:  # the 4.0.1 schema NaraRouter receives; it is not enforced (strict: false)
        assert bool(schema_errors(schema, decoded)) is schema_rejects
    caught = failure(text, frozen)
    assert caught.code == code
    detail = caught.detail
    assert detail["layer"] == layer and detail["code"] == code and detail["error_count"] >= 1
    assert (detail["errors"][0]["loc"], detail["errors"][0]["type"]) == first
    assert_safe(detail, caplog.text)


def test_six_valid_requirements_with_one_semantic_violation_names_the_requirement():
    data = fixture()
    data["requirements"]["R5"]["quiz_options"] = ["Within 1 day", "within 1 DAY", "Later"]
    detail = failure(json.dumps(data)).detail
    assert detail["errors"] == [{"loc": "requirements.R5", "type": "value_error",
                                 "msg": "Value error, DUPLICATE_QUIZ_OPTION"}]
    assert detail["received"]["requirement_keys_received"] == 6 and detail["received"]["missing_requirement_keys"] == []


def test_response_shape_is_described_by_counts_and_our_own_key_names_only():
    data = fixture()
    data["requirements"] = {"R1": data["requirements"]["R1"], "R2": data["requirements"]["R2"]}
    data[CANARY] = "x"  # a model-invented top-level key is counted, never echoed
    detail = failure(json.dumps(data)).detail
    received = detail["received"]
    assert received["requirement_keys_expected"] == 6 and received["requirement_keys_received"] == 2
    assert received["missing_requirement_keys"] == ["R3", "R4", "R5", "R6"]
    assert received["top_level_keys"] == ["plan_summary", "plan_title", "requirements"]
    assert received["unknown_top_level_keys"] == 1 and received["entry_field_counts"] == {"R1": 12, "R2": 12}
    assert_safe(detail)


def test_post_assembly_and_structural_layers_also_carry_details():
    frozen = snapshot()
    plan = assemble_plan(ContentResponse.model_validate_json(json.dumps(fixture())), frozen, RUN)
    plan["plan"]["stages"].pop(0)
    with pytest.raises(StructuralFailure) as caught:
        parse_plan(json.dumps(plan), RUN, frozen)
    assert caught.value.detail["layer"] == "plan_structure"
    assert caught.value.detail["errors"][0]["missing_expected_indexes"] == [0]
    plan = assemble_plan(ContentResponse.model_validate_json(json.dumps(fixture())), frozen, RUN)
    plan["plan"]["stages"][1]["modules"][0]["estimated_minutes"] = 0
    with pytest.raises(StructuralFailure) as caught:
        parse_plan(json.dumps(plan), RUN, frozen)
    assert caught.value.detail["layer"] == "onboarding_plan"
    assert caught.value.detail["errors"][0]["loc"] == "plan.stages.1.modules.0.estimated_minutes"
    bad = frozen.model_copy(update={"requirements": (frozen.requirements[0].model_copy(update={"evidence": ()}),
                                                     *frozen.requirements[1:])})
    assert failure(json.dumps(fixture()), bad).detail["layer"] == "content_assembly"


# --- 6. capping, persistence, leak prevention -------------------------------------------------------

def test_diagnostics_are_capped_in_count_and_size():
    many = [{"loc": f"requirements.R{i}.quiz_options", "type": "too_short", "msg": "x" * 150} for i in range(50)]
    detail = failure_detail("content_model", "SCHEMA_INVALID", many, {"bytes": 1847, "type": "dict"})
    assert len(detail["errors"]) <= MAX_DIAGNOSTIC_ERRORS and detail["truncated"] is True
    assert detail["error_count"] == 50
    assert len(json.dumps(detail, sort_keys=True).encode()) <= MAX_DIAGNOSTIC_BYTES
    small = failure_detail("content_model", "SCHEMA_INVALID", many[:2])
    assert "truncated" not in small and small["error_count"] == 2
    data = fixture()
    for item in data["requirements"].values():  # 6 x many errors -> still bounded
        for key in list(item):
            item[key] = None
    detail = failure(json.dumps(data)).detail
    assert detail["error_count"] > MAX_DIAGNOSTIC_ERRORS and detail["truncated"] is True
    assert set(detail) <= {"layer", "code", "error_count", "errors", "received", "truncated"}


def run_with_attempts(text, frozen=None):
    frozen = frozen or snapshot()
    attempts = []

    class Stub:
        async def generate(self, prompt, *, format_retry=False):
            return ProviderResult(text=text, finish_reason="STOP")

    async def record(item):
        attempts.append(item)

    async def no_sleep(_s):
        return None
    result = asyncio.run(generate_unverified(PreflightResult(status="READY", snapshot=frozen,
                                                             input_hash=input_hash(frozen)), RUN, Stub(), no_sleep,
                                             on_attempt=record, prompt_version=CONTENT_V401))
    return result, attempts


def test_failed_attempt_carries_diagnostics_and_success_is_unchanged():
    result, attempts = run_with_attempts(mutated(lambda d: d["requirements"]["R4"].update(quiz_options=["a"])),
                                         snapshot(with_canary=True))
    assert result.error_code == "SCHEMA_INVALID"
    detail = attempts[0].diagnostics
    assert detail["layer"] == "content_model" and detail["errors"][0]["loc"] == "requirements.R4.quiz_options"
    assert detail["errors"][0]["type"] == "too_short"
    assert_safe(detail)
    ok, attempts = run_with_attempts(json.dumps(fixture()))
    assert ok.status == "UNVERIFIED" and attempts[0].diagnostics == {} and attempts[0].parse_outcome == "SCHEMA_VALID"


class Capture(GenerationStore):
    def __init__(self, fail_diagnostics=False):
        self.calls, self.fail = [], fail_diagnostics

    async def rpc(self, token, name, payload):
        self.calls.append((name, payload))
        if name == "record_generation_attempt":
            return 1
        if self.fail:
            raise HTTPException(503, "GENERATION_DATA_UNAVAILABLE")
        return None


BASE = dict(attempt_type="INITIAL", provider_outcome="RESPONSE", latency_ms=110906, response_hash="9b" * 32,
            response_size=1847, parse_outcome="SCHEMA_INVALID", error_code="SCHEMA_INVALID",
            usage={"prompt_tokens": 1627, "output_tokens": 2371, "total_tokens": 3998})


def test_diagnostics_are_persisted_linked_to_the_attempt(caplog):
    detail = failure(mutated(lambda d: d["requirements"].pop("R6"))).detail
    store = Capture()
    asyncio.run(store.record_attempt("token", RUN, AttemptTelemetry(**BASE, diagnostics=detail)))
    assert [name for name, _ in store.calls] == ["record_generation_attempt", "record_generation_attempt_diagnostics"]
    assert store.calls[1][1] == {"p_run": str(RUN), "p_attempt": 1, "p_diagnostics": detail}
    assert "p_diagnostics" not in store.calls[0][1]  # the original attempt RPC is unchanged


def test_diagnostics_persistence_is_best_effort_and_never_breaks_generation(caplog):
    store = Capture(fail_diagnostics=True)  # e.g. migration 202609280010 not applied
    asyncio.run(store.record_attempt("token", RUN, AttemptTelemetry(**BASE, diagnostics={"layer": "x",
                                                                                         "code": "SCHEMA_INVALID"})))
    assert any("generation_attempt_diagnostics_not_persisted" in r.getMessage() for r in caplog.records)
    store = Capture()
    asyncio.run(store.record_attempt("token", RUN, AttemptTelemetry(**{**BASE, "parse_outcome": "SCHEMA_VALID",
                                                                        "error_code": None})))
    assert [name for name, _ in store.calls] == ["record_generation_attempt"]  # nothing extra on success


def test_historical_attempts_without_diagnostics_still_deserialize():
    old = AttemptTelemetry.model_validate({"attempt_type": "INITIAL", "provider_outcome": "RESPONSE", "latency_ms": 5,
                                           "parse_outcome": "SCHEMA_INVALID", "error_code": "SCHEMA_INVALID"})
    assert old.diagnostics == {} and old.usage == {}


def test_failure_detail_never_contains_secrets_evidence_or_prose(caplog):
    frozen = snapshot(with_canary=True)
    texts = [mutated(lambda d: d["requirements"].pop("R1")), mutated(lambda d: d.update(extra=CANARY)),
             CANARY + "{", json.dumps({CANARY: CANARY}), mutated(lambda d: d["requirements"]["R3"].update(
                 quiz_options=[CANARY, CANARY.lower(), "z"]))]
    for text in texts:
        assert_safe(failure(text, frozen).detail, caplog.text)


# --- migration 202609280010 ------------------------------------------------------------------------

def test_diagnostics_migration_is_additive_append_only_and_guarded():
    sql = (MIGRATIONS / "202609280010_generation_attempt_diagnostics.sql").read_text(encoding="utf-8")
    assert "create table public.generation_attempt_diagnostics" in sql
    assert "references public.generation_attempts(run_id, attempt_no)" in sql
    assert "pg_column_size(diagnostics) <= 8192" in sql
    assert "generation_attempt_diagnostics_immutable before update or delete" in sql
    assert "enable row level security" in sql and "for select to authenticated" in sql
    assert "revoke all on public.generation_attempt_diagnostics from public, anon, authenticated, service_role" in sql
    assert "v_run.created_by <> v_actor or v_run.status <> 'RUNNING'" in sql
    assert "parse_outcome = 'SCHEMA_INVALID'" in sql and "security definer set search_path = ''" in sql
    keys = set(re.search(r"k not in \(([^)]*)\)", sql).group(1).replace("'", "").split(","))
    produced = set(failure_detail("l", "SCHEMA_INVALID", [{"loc": "a", "type": "b"}] * 30, {"bytes": 1}))
    assert produced <= keys  # everything the backend sends is accepted
    assert "jsonb_array_length(p_diagnostics->'errors') > 20" in sql and MAX_DIAGNOSTIC_ERRORS == 20
    assert not re.search(r"(?im)^\s*alter table public\.generation_attempts\b", sql)
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop)\b", sql)
