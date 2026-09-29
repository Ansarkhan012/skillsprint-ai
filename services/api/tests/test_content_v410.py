"""4.1.0 demo-minimal content contract: one call, all requirements, 7 model-written fields per
requirement; everything else owned by Python. Offline only (no provider, no network)."""

import asyncio
import json
import re
import socket
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.generation_content import (CONTENT_V401, CONTENT_V410, DEFAULT_MODULE_MINUTES, ContentResponseV410,
                                    RequirementContentV410, assemble_plan)
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_output import OnboardingPlan
from app.generation_prompt import (EVIDENCE_EXCERPT_CHARS, MAX_EVIDENCE_PER_REQUIREMENT, _compact_schema,
                                   _strict_schema, build_prompt, content_response_schema, provider_schema_for)
from app.generation_provider import GeminiProvider, GroqProvider, ProviderResult
from app.generation_service import StructuralFailure, assemble_content, generate_unverified, parse_plan
from app.jev import decide
from app.nararouter_provider import NaraRouterConfig, NaraRouterProvider, nararouter_request_payload
from app.plan_validator import validate_plan
from app.rrm_rules import snapshot_hash
from test_contract_v31 import COMPACT_CAPS

FIXTURES = Path(__file__).parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RUN = UUID("aaccc0b5-e109-432e-88ae-805acd35d96a")
V401_HASH = "83c231d9c9647da559d57e6ece4680ef8f8902c6e38c1e484ae59888eb91b00a"
V410_HASH = "f4edf5d50196fe8d4635a95cef1164bbd85215f31f90f58aa08390fed8c6d5fa"
CANARY = "CANARY_MODEL_PROSE_m41"
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)

    def refuse(*args, **kwargs):
        raise AssertionError("provider or network used")
    for provider in (NaraRouterProvider, GroqProvider, GeminiProvider):
        monkeypatch.setattr(provider, "generate", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def snapshot():
    return GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))


def fixture_text():
    return (FIXTURES / "phase4d_v410_model_content_response.json").read_text(encoding="utf-8")


def fixture():
    return json.loads(fixture_text())


# --- contract: provider schema == Pydantic model --------------------------------------------------

def test_provider_schema_is_the_pydantic_model_schema_exactly():
    keys = [f"R{i}" for i in range(1, 7)]
    sent = content_response_schema(keys, version=CONTENT_V410)
    model = _strict_schema(_compact_schema(ContentResponseV410.model_json_schema()))
    assert sent["$defs"] == model["$defs"]
    assert sent["required"] == model["required"] == ["plan_title", "requirements"]
    assert sent["properties"]["plan_title"] == model["properties"]["plan_title"]
    requirements = sent["properties"]["requirements"]
    assert requirements["required"] == list(requirements["properties"]) == keys
    assert requirements["additionalProperties"] is False and sent["additionalProperties"] is False
    item = sent["$defs"]["RequirementContentV410"]
    assert sorted(item["required"]) == sorted(item["properties"]) == sorted(
        ["module_title", "objective", "task", "checklist", "quiz_question", "quiz_options", "correct_option_index"])
    assert item["additionalProperties"] is False
    expected = {"module_title": 120, "objective": 400, "task": 400, "checklist": 240, "quiz_question": 400}
    for name, limit in expected.items():
        assert item["properties"][name] == {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}
    options = item["properties"]["quiz_options"]
    assert (options["minItems"], options["maxItems"], options["uniqueItems"]) == (3, 3, True)
    assert options["items"] == {"type": "string", "minLength": 1, "maxLength": 160, "pattern": r"\S"}
    assert item["properties"]["correct_option_index"] == {"type": "integer", "minimum": 0, "maximum": 2}
    assert not any("null" in json.dumps(node) for node in item["properties"].values())  # nothing nullable


def test_environment_text_cap_does_not_desynchronise_4_1_0(monkeypatch):
    monkeypatch.setenv("GENERATION_MAX_TEXT_LENGTH", "50")
    prompt = build_prompt(snapshot(), RUN, version=CONTENT_V410)
    assert prompt.response_schema == content_response_schema([f"R{i}" for i in range(1, 7)], version=CONTENT_V410)
    gemini = provider_schema_for(prompt, key_pattern=False)
    assert not re.search(r'"(pattern|minLength|maxLength|minItems|maxItems|minimum|maximum|uniqueItems)"',
                         json.dumps(gemini))


def test_every_python_bound_fits_the_final_plan_contract():
    final = OnboardingPlan.model_json_schema()["$defs"]
    item = RequirementContentV410.model_json_schema()["properties"]
    assert item["module_title"]["maxLength"] <= final["Module"]["properties"]["title"]["maxLength"]
    assert item["quiz_options"]["items"]["maxLength"] <= final["QuizOption"]["properties"]["text"]["maxLength"]
    for name in ("objective", "task", "checklist", "quiz_question"):
        assert item[name]["maxLength"] <= 4000


# --- minimal input and source grounding -------------------------------------------------------------

def test_model_input_is_minimal_and_grounded():
    frozen = snapshot()
    prompt = build_prompt(frozen, RUN, version=CONTENT_V410)
    data = json.loads(re.search(r'application/json">\n(.*)\n</untrusted', prompt.untrusted_data, re.S).group(1))
    assert set(data) == {"projection_version", "experience_level", "requirements"}
    assert data["experience_level"] == frozen.employee.experience
    for entry, req in zip(data["requirements"], frozen.requirements):
        assert set(entry) <= {"key", "code", "statement", "timing", "evidence"}
        assert entry["statement"] == req.statement and entry["code"] == req.code
        assert 1 <= len(entry["evidence"]) <= MAX_EVIDENCE_PER_REQUIREMENT
        assert all(len(text) <= EVIDENCE_EXCERPT_CHARS for text in entry["evidence"])
        assert entry["timing"].startswith("within ") and "day" in entry["timing"]
        owned = {" ".join(e.excerpt.split())[:EVIDENCE_EXCERPT_CHARS] for e in req.evidence}
        assert set(entry["evidence"]) <= owned  # only this requirement's approved evidence
    assert not UUID_TEXT.search(prompt.untrusted_data)
    for forbidden in ("stage", "after", "mandatory", "priority", "obligation_type", "role_code", "location"):
        assert f'"{forbidden}"' not in prompt.untrusted_data
    for phrase in ("exactly one JSON object", "no markdown", "exactly one entry for each key R1..Rn",
                   "do not invent policies, rules or deadlines", "Do not output ids"):
        assert phrase in prompt.rules
    assert prompt.template_hash == V410_HASH and prompt.within_budget


def test_most_specific_evidence_is_chosen_first():
    frozen = snapshot()
    owners = {}
    for req in frozen.requirements:
        for e in req.evidence:
            owners.setdefault((e.document_version_id, e.chunk_id), set()).add(req.revision_id)
    prompt = build_prompt(frozen, RUN, version=CONTENT_V410)
    data = json.loads(re.search(r'application/json">\n(.*)\n</untrusted', prompt.untrusted_data, re.S).group(1))
    for entry, req in zip(data["requirements"], frozen.requirements):
        specific = [e for e in req.evidence if len(owners[(e.document_version_id, e.chunk_id)]) == 1]
        if specific:
            assert " ".join(specific[0].excerpt.split())[:EVIDENCE_EXCERPT_CHARS] == entry["evidence"][0]


def test_request_is_materially_smaller_than_4_0_1():
    frozen = snapshot()
    config = NaraRouterConfig(provider="nararouter", model="agnes-2.5-flash", api_key="placeholder",
                              base_url="https://nara.invalid/v1", temperature=0.1, max_output_tokens=32768,
                              timeout_seconds=290)

    def size(version):
        prompt = build_prompt(frozen, RUN, version=version)
        payload = nararouter_request_payload(prompt, config)
        from app.generation_provider import json_schema_response_format
        return len(httpx.Request("POST", "https://x.invalid", json={
            **payload, "response_format": json_schema_response_format(provider_schema_for(prompt))}).content)
    assert size(CONTENT_V410) < 0.75 * size(CONTENT_V401)
    assert nararouter_request_payload(build_prompt(frozen, RUN, version=CONTENT_V410), config)["reasoning_effort"] == "low"


# --- hand-written model responses (not produced by our assembler) -----------------------------------

def edit(change):
    data = fixture()
    data["requirements"]["R2"]["objective"] = CANARY + " objective"
    change(data["requirements"]["R2"], data)
    return json.dumps(data)


CASES = [
    ("missing objective", edit(lambda r, d: r.pop("objective")), "SCHEMA_INVALID", "content_model",
     ("requirements.R2.objective", "missing")),
    ("quiz with 2 options", edit(lambda r, d: r.update(quiz_options=["Yes", "No"])), "SCHEMA_INVALID",
     "content_model", ("requirements.R2.quiz_options", "too_short")),
    ("quiz with 4 options", edit(lambda r, d: r.update(quiz_options=["A", "B", "C", "D"])), "SCHEMA_INVALID",
     "content_model", ("requirements.R2.quiz_options", "too_long")),
    ("invalid correct index", edit(lambda r, d: r.update(correct_option_index=3)), "SCHEMA_INVALID",
     "content_model", ("requirements.R2.correct_option_index", "less_than_equal")),
    ("extra field", edit(lambda r, d: r.update(quiz_explanation="Because.")), "SCHEMA_INVALID", "content_model",
     ("requirements.R2.quiz_explanation", "extra_forbidden")),
    ("markdown-wrapped JSON", "```json\n" + fixture_text() + "\n```", "MALFORMED_JSON", "content_json",
     ("", "invalid_json")),
    ("wrapper object", '{"response": ' + fixture_text() + "}", "SCHEMA_INVALID", "content_model",
     ("unknown_field", "extra_forbidden")),  # a model-invented key name is masked, never echoed
    ("empty string", edit(lambda r, d: r.update(task="")), "SCHEMA_INVALID", "content_model",
     ("requirements.R2.task", "string_too_short")),
    ("overly long text", edit(lambda r, d: r.update(module_title=CANARY * 6)), "SCHEMA_INVALID", "content_model",
     ("requirements.R2.module_title", "string_too_long")),
    ("wrong type", edit(lambda r, d: r.update(checklist=["Do it"])), "SCHEMA_INVALID", "content_model",
     ("requirements.R2.checklist", "string_type")),
    ("duplicate options", edit(lambda r, d: r.update(quiz_options=["None", "none ", "Both"])), "SCHEMA_INVALID",
     "content_model", ("requirements.R2", "value_error")),
    ("missing requirement", edit(lambda r, d: d["requirements"].pop("R6")), "SCHEMA_INVALID", "requirement_keys",
     ("requirements.R6", "missing_requirement_content")),
    ("removed 4.0.1 plan_summary returned", edit(lambda r, d: d.update(plan_summary="x")), "SCHEMA_INVALID",
     "content_model", ("plan_summary", "extra_forbidden")),
]


def test_valid_minimal_response_passes():
    parsed = ContentResponseV410.model_validate_json(fixture_text())
    assert len(parsed.requirements) == 6
    json.loads(assemble_content(fixture_text(), snapshot(), RUN, CONTENT_V410))


@pytest.mark.parametrize("name,text,code,layer,first", CASES, ids=[c[0] for c in CASES])
def test_invalid_responses_fail_at_the_intended_layer_with_safe_diagnostics(caplog, name, text, code, layer, first):
    with pytest.raises(StructuralFailure) as caught:
        assemble_content(text, snapshot(), RUN, CONTENT_V410)
    detail = caught.value.detail
    assert caught.value.code == code and detail["layer"] == layer
    assert (detail["errors"][0]["loc"], detail["errors"][0]["type"]) == first
    assert CANARY not in json.dumps(detail) and CANARY not in caplog.text


# --- deterministic assembly: Python-owned and derived fields ------------------------------------------

def test_python_derives_every_field_the_model_no_longer_writes():
    frozen = snapshot()
    plan = assemble_plan(ContentResponseV410.model_validate_json(fixture_text()), frozen, RUN)
    by_id = {str(r.revision_id): r for r in frozen.requirements}
    content = fixture()["requirements"]
    keys = {str(r.revision_id): f"R{i}" for i, r in enumerate(frozen.requirements, 1)}
    for stage in plan["plan"]["stages"]:
        for module in stage["modules"]:
            req = by_id[module["requirement_ids"][0]]
            ai = content[keys[str(req.revision_id)]]
            assert module["purpose"] == req.statement and module["estimated_minutes"] == DEFAULT_MODULE_MINUTES
            task, quiz = module["tasks"][0], module["quizzes"][0]
            assert (module["title"], module["learning_objectives"][0]["statement"], task["description"],
                    module["checklist_items"][0]["activity"], quiz["question"]) == (
                ai["module_title"], ai["objective"], ai["task"], ai["checklist"], ai["quiz_question"])
            assert [o["text"] for o in quiz["options"]] == ai["quiz_options"]
            assert quiz["correct_answer_ids"] == [quiz["options"][ai["correct_option_index"]]["option_id"]]
            # Derived text uses only trusted requirement data (its code); no model prose, no new facts.
            for derived in (task["expected_outcome"], *task["completion_criteria"], quiz["explanation"]):
                assert req.code in derived
                assert not any(value in derived for value in (ai["module_title"], ai["task"], ai["objective"]))
    assert plan["plan"]["summary"] == ("Onboarding plan for role PHASE4D_ENGINEER covering 6 approved "
                                       "requirements across 5 stages.")


# --- full offline pipeline on the real snapshot ---------------------------------------------------------

def test_full_pipeline_real_snapshot_reaches_verified_with_warning():
    frozen = snapshot()
    ContentResponseV410.model_validate_json(fixture_text())                                     # content parse
    assembled = json.loads(assemble_content(fixture_text(), frozen, RUN, CONTENT_V410))         # assembly
    plan = parse_plan(json.dumps(assembled), RUN, frozen)                                        # final model + checks
    assert [s.stage_id for s in plan.plan.stages] == [s.stage_definition_id for s in frozen.stage_set.items]
    assert plan.plan.stages[0].modules == ()                                                      # empty Orientation kept

    class Stub:
        async def generate(self, prompt, *, format_retry=False):
            return ProviderResult(text=fixture_text(), finish_reason="STOP")

    async def no_sleep(_s):
        return None
    result = asyncio.run(generate_unverified(PreflightResult(status="READY", snapshot=frozen,
                                                             input_hash=input_hash(frozen)), RUN, Stub(), no_sleep,
                                             prompt_version=CONTENT_V410))
    assert result.status == "UNVERIFIED" and result.plan == plan and result.template_hash == V410_HASH
    content = result.plan.model_dump(mode="json")
    evidence = validate_plan(content, frozen, RUN, current_input=True)                         # validator
    assert (evidence.mandatory_covered, evidence.mandatory_total) == (6, 6)                     # coverage
    assert evidence.generated_items_traceable == evidence.generated_items_total == 30            # traceability
    assert [(f.code, f.severity, f.location) for f in evidence.findings] == [
        ("TIMING_UNRESOLVED", "WARNING", "input.timing")] * 6
    assert decide(evidence).status == "VERIFIED_WITH_WARNING"                                    # JEV
    assert content["schema_version"] == "onboarding-plan/1.0.0" and content["generation_request_id"] == str(RUN)
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot_hash(content))                                 # persistence prep
    assert len(json.dumps(content, separators=(",", ":")).encode()) <= 4_194_304


# --- migration 202609280011 ------------------------------------------------------------------------------

def test_410_migration_adds_exactly_one_pair():
    def body(text):
        marker = "create or replace function"
        return text[text.index(marker):text.index("end $$;", text.index(marker))]
    previous = (MIGRATIONS / "202609280009_content_only_prompt_v401.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "202609280011_content_only_prompt_v410.sql").read_text(encoding="utf-8")
    added = ("\n          or (p_prompt_version = 'phase4d-content-only/4.1.0'\n"
             f"           and p_template_hash = '{V410_HASH}')")
    assert body(new).replace(added, "").replace("one of six reviewed", "one of five reviewed") == body(previous)
    assert ("add constraint generation_runs_content_v410_projection_check\n  check (prompt_version <> "
            "'phase4d-content-only/4.1.0' or projection_hash is not null);") in new
    assert "not between 1 and 290" in new and "'agnes-2.5-flash'" in new
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", new)
    pin = re.search(r"or not coalesce\((.*?), false\)", new, re.S).group(1)
    pairs = set(re.findall(r"\(p_prompt_version = '([^']+)'\s+and p_template_hash = '([0-9a-f]{64})'\)", pin))
    assert len(pairs) == 6 and (CONTENT_V410, V410_HASH) in pairs and (CONTENT_V401, V401_HASH) in pairs
    versions, hashes = zip(*pairs)
    assert all(((v, h) in pairs) is (versions.index(v) == hashes.index(h)) for v in versions for h in hashes)
