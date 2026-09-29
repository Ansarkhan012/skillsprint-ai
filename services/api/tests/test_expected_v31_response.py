"""Replay of the expected 3.1.0 NaraRouter response for run aaccc0b5 (employee aa02c897)
through the real local pipeline. Offline: no provider, no database.

The snapshot fixture is the run's frozen input with statement/excerpt/quote text redacted;
IDs, stages, dependencies, timing values and locators are unchanged.
"""

import asyncio
import copy
import json
import re
from pathlib import Path
from uuid import UUID

import pytest

from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_prompt import SOURCE_KEYS_V31_PROMPT_VERSION, current_provider_schema, source_key_map
from app.generation_provider import ProviderResult
from app.generation_service import StructuralFailure, expand_source_keys, generate_unverified, parse_plan
from app.jev import decide
from app.plan_validator import validate_plan
from app.rrm_rules import snapshot_hash
from test_contract_v31 import COMPACT_CAPS, V31_HASH, schema_errors

FIXTURES = Path(__file__).parent / "fixtures"
RUN = UUID("aaccc0b5-e109-432e-88ae-805acd35d96a")


def load():
    snapshot = GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))
    response = json.loads((FIXTURES / "phase4d_v31_expected_provider_response.json").read_text(encoding="utf-8"))
    return snapshot, response


@pytest.fixture(autouse=True)
def compact_caps(monkeypatch):
    for name, value in COMPACT_CAPS.items():  # the local .env caps in force for the run
        monkeypatch.setenv(name, value)


def replay(snapshot, response):
    class Provider:
        async def generate(self, prompt, *, format_retry=False):
            return ProviderResult(text=json.dumps(response), finish_reason="STOP")

    async def no_sleep(_seconds):
        return None
    return asyncio.run(generate_unverified(
        PreflightResult(status="READY", snapshot=snapshot, input_hash=input_hash(snapshot)), RUN, Provider(),
        no_sleep, prompt_version=SOURCE_KEYS_V31_PROMPT_VERSION))


def test_fixture_is_the_run_input_shape():
    snapshot, response = load()
    assert str(snapshot.employee.employee_id) == "aa02c897-14d8-4c3c-994a-c707550677ad"
    assert (len(snapshot.requirements), len(snapshot.stage_set.items), len(snapshot.dependencies)) == (6, 5, 8)
    assert list(source_key_map(snapshot)) == [f"S{index}" for index in range(1, 11)]
    assert response["generation_request_id"] == str(RUN)
    assert all(re.fullmatch(r"S[0-9]+", key) for key in re.findall(r'"(S\d+)"', json.dumps(response)))
    assert '"document_version_id"' not in json.dumps(response)  # keys only, before expansion


def test_every_boundary_passes_and_the_best_possible_decision_is_reached():
    snapshot, response = load()
    # 1. what NaraRouter may return under the 3.1.0 schema and compact caps
    assert schema_errors(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION), response) == []
    # 2. source-key expansion from the frozen snapshot
    keys = source_key_map(snapshot)
    expanded = json.loads(expand_source_keys(json.dumps(response), keys, RUN))
    module = expanded["plan"]["stages"][1]["modules"][0]
    assert all(set(ref) == {"document_version_id", "chunk_id", "locator"} for ref in module["source_refs"])
    # 3. Pydantic OnboardingPlan + parse_plan identity/stage/source checks
    parse_plan(json.dumps(expanded), RUN, snapshot)
    # 4. the same generation code path the API runs
    result = replay(snapshot, response)
    assert result.status == "UNVERIFIED" and (result.prompt_version, result.template_hash) == (
        SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH)
    # 5. domain validator + JEV
    content = result.plan.model_dump(mode="json")
    evidence = validate_plan(content, snapshot, RUN, current_input=True)
    assert evidence.structurally_valid and evidence.mandatory_covered == 6
    # Every requirement has STRUCTURED, staged timing, so the validator emits one input-level
    # TIMING_UNRESOLVED warning each regardless of the plan; nothing else is found.
    assert {(item.code, item.severity, item.location) for item in evidence.findings} == {
        ("TIMING_UNRESOLVED", "WARNING", "input.timing")}
    assert len(evidence.findings) == 6
    assert decide(evidence).status == "VERIFIED_WITH_WARNING"
    # 6. finish_generation_run preconditions
    assert content["schema_version"] == "onboarding-plan/1.0.0" and content["generation_request_id"] == str(RUN)
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot_hash(content))
    assert len(json.dumps(content, separators=(",", ":")).encode()) <= 4_194_304


def test_the_warning_is_input_only_the_same_plan_is_verified_without_structured_timing():
    snapshot, response = load()
    untimed = snapshot.model_copy(update={"requirements": tuple(
        req.model_copy(update={"timing": req.timing.model_copy(update={
            "state": "NOT_SPECIFIED", "original_text": None, "trigger": None, "relation": None, "value": None,
            "unit": None, "calendar_basis": None, "evidence": {}})}) for req in snapshot.requirements)})
    result = replay(untimed, response)
    evidence = validate_plan(result.plan.model_dump(mode="json"), untimed, RUN, current_input=True)
    assert not evidence.findings and decide(evidence).status == "VERIFIED"


@pytest.mark.parametrize("mutate,schema_rejects,code", [
    (lambda r: r["plan"]["stages"][1]["modules"][1].update(source_refs=["S2"]), False, "SCHEMA_INVALID"),
    (lambda r: r["plan"]["stages"][1]["modules"][1].update(source_refs=["S11"]), False, "SCHEMA_INVALID"),
    (lambda r: r["plan"]["stages"][1]["modules"][1]["tasks"][0].update(requirement_ids=[]), True, "SCHEMA_INVALID"),
    (lambda r: r["plan"]["stages"][1]["modules"][1]["quizzes"][0].update(correct_answer_ids=[str(UUID(int=7))]),
     False, "SCHEMA_INVALID"),
    (lambda r: r["plan"]["stages"].pop(0), False, "STAGE_CONTRACT_MISMATCH"),
], ids=["key of another requirement", "unknown key", "empty requirement_ids", "answer not an option",
        "missing stage"])
def test_real_input_mutations_are_rejected_not_repaired(mutate, schema_rejects, code):
    snapshot, response = load()
    response = copy.deepcopy(response)
    mutate(response)
    assert bool(schema_errors(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION), response)) is schema_rejects
    result = replay(snapshot, response)
    assert result.status == "FAILED" and result.error_code == code and result.plan is None
