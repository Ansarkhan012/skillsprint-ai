"""Content-only generation 4.0.0: backend-owned structure, prose-only model output.
Offline: no provider, no database. Uses the redacted frozen snapshot of run aaccc0b5."""

import asyncio
import copy
import json
import re
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.generation_content import (CONTENT_PROMPT_VERSION, ID_NAMESPACE, assemble_plan, generated_id,
                                    module_layout, requirement_keys, source_refs, ContentResponse)
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_persistence import GenerationStore
from app.generation_prompt import (PROMPT_VERSION, SOURCE_KEYS_PROMPT_VERSION, SOURCE_KEYS_V31_PROMPT_VERSION,
                                   build_prompt, content_template_hash, provider_schema_for, source_keys_template_hash,
                                   source_keys_v31_template_hash, template_hash)
from app.generation_provider import GeminiProvider, GroqProvider, ProviderConfig, ProviderFailure, ProviderResult, ProviderUsage
from app.generation_service import (AttemptTelemetry, StructuralFailure, assemble_content, generate_unverified,
                                    parse_plan, usage_metadata)
from app.jev import decide
from app.nararouter_provider import (CONTENT_OUTPUT_INSTRUCTIONS, OUTPUT_INSTRUCTIONS, NaraRouterConfig,
                                     NaraRouterEnvironment, NaraRouterProvider, nararouter_request_payload)
from app.plan_validator import has_cycle, validate_plan
from app.rrm_rules import snapshot_hash
from test_contract_v31 import COMPACT_CAPS, V2_HASH, V31_HASH, V3_HASH, schema_errors

FIXTURES = Path(__file__).parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
RUN = UUID("aaccc0b5-e109-432e-88ae-805acd35d96a")
V4_HASH = "d0f338ed27b47e91207d3346fad2b0055f955960b258874804e9b17db8503b43"
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture(autouse=True)
def compact_caps(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)


def snapshot():
    return GenerationInputSnapshot.model_validate(
        json.loads((FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json").read_text(encoding="utf-8")))


def content():
    return json.loads((FIXTURES / "phase4d_v4_expected_content_response.json").read_text(encoding="utf-8"))


class Replay:
    def __init__(self, *outcomes):
        self.outcomes, self.prompts = list(outcomes), []

    async def generate(self, prompt, *, format_retry=False):
        self.prompts.append(prompt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome if isinstance(outcome, ProviderResult) else ProviderResult(text=outcome, finish_reason="STOP")


def run(frozen, *outcomes, attempts=None):
    async def no_sleep(_seconds):
        return None

    async def record(item):
        attempts.append(item)
    return asyncio.run(generate_unverified(
        PreflightResult(status="READY", snapshot=frozen, input_hash=input_hash(frozen)), RUN, Replay(*outcomes),
        no_sleep, on_attempt=record if attempts is not None else None, prompt_version=CONTENT_PROMPT_VERSION))


def modules(plan):
    return [(stage, module) for stage in plan["plan"]["stages"] for module in stage["modules"]]


# --- Real snapshot: complete pipeline ---------------------------------------------------------

def test_real_snapshot_content_passes_every_boundary_to_verified_with_warning():
    frozen, response = snapshot(), content()
    prompt = build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION)
    assert schema_errors(prompt.response_schema, response) == []                       # 1 content schema
    assembled = json.loads(assemble_content(json.dumps(response), frozen, RUN))       # 2 assembly
    plan = parse_plan(json.dumps(assembled), RUN, frozen)                              # 3 Pydantic + parse_plan
    result = run(frozen, json.dumps(response))                                         # 4 API generation path
    assert result.status == "UNVERIFIED" and (result.prompt_version, result.template_hash) == (
        CONTENT_PROMPT_VERSION, V4_HASH)
    assert result.plan == plan
    stored = result.plan.model_dump(mode="json")
    evidence = validate_plan(stored, frozen, RUN, current_input=True)                   # 5 domain validator
    assert [(f.code, f.severity, f.location) for f in evidence.findings] == [
        ("TIMING_UNRESOLVED", "WARNING", "input.timing")] * 6
    assert evidence.mandatory_covered == 6 and decide(evidence).status == "VERIFIED_WITH_WARNING"
    assert stored["schema_version"] == "onboarding-plan/1.0.0"                          # 6 persistence prep
    assert stored["generation_request_id"] == str(RUN) and re.fullmatch(r"[0-9a-f]{64}", snapshot_hash(stored))


def test_assembly_owns_stage_placement_and_all_mechanical_fields():
    frozen = snapshot()
    plan = assemble_plan(ContentResponse.model_validate_json(json.dumps(content())), frozen, RUN)
    requirements = {str(req.revision_id): req for req in frozen.requirements}
    assert [s["stage_id"] for s in plan["plan"]["stages"]] == [str(s.stage_definition_id) for s in frozen.stage_set.items]
    assert len(modules(plan)) == len(frozen.requirements)  # one module per requirement
    for stage, module in modules(plan):
        req = requirements[module["requirement_ids"][0]]
        assert stage["stage_id"] == str(req.stage_definition_id)
        assert (module["mandatory"], module["priority"]) == (req.mandatory, req.priority)
        for node in (module["checklist_items"][0], module["tasks"][0]):
            assert node["due_stage_id"] == stage["stage_id"]
        quiz = module["quizzes"][0]
        key = next(k for k, r in requirement_keys(frozen).items() if str(r.revision_id) == module["requirement_ids"][0])
        index = content()["requirements"][key]["correct_option_index"]
        assert quiz["correct_answer_ids"] == [quiz["options"][index]["option_id"]]
        assert [o["text"] for o in quiz["options"]] == content()["requirements"][key]["quiz_options"]
    assert plan["employee_context"]["employee_id"] == str(frozen.employee.employee_id)


def test_source_rule_every_node_cites_its_requirement_and_its_full_frozen_evidence():
    frozen = snapshot()
    plan = assemble_plan(ContentResponse.model_validate_json(json.dumps(content())), frozen, RUN)
    by_id = {str(req.revision_id): req for req in frozen.requirements}
    for _, module in modules(plan):
        rid = module["requirement_ids"][0]
        expected = source_refs(by_id[rid])
        assert expected == [{"document_version_id": str(e.document_version_id), "chunk_id": str(e.chunk_id),
                             "locator": json.dumps(e.locator, sort_keys=True, separators=(",", ":"))}
                            for e in by_id[rid].evidence]  # all evidence, snapshot order (no duplicates here)
        nodes = [module, *module["learning_objectives"], *module["checklist_items"], *module["tasks"],
                 *module["quizzes"]]
        assert all(node["requirement_ids"] == [rid] and node["source_refs"] == expected for node in nodes)
    evidence = validate_plan(parse_plan(json.dumps(plan), RUN, frozen).model_dump(mode="json"), frozen, RUN,
                             current_input=True)
    assert evidence.generated_items_total == 6 * 5  # module, objective, checklist, task, quiz
    assert evidence.generated_items_traceable == evidence.generated_items_total  # all traceable
    assert evidence.mandatory_items_traceable == evidence.mandatory_items_total > 0


def test_real_dependency_graph_is_wired_correctly_ordered_and_acyclic():
    frozen = snapshot()
    plan = assemble_plan(ContentResponse.model_validate_json(json.dumps(content())), frozen, RUN)
    code = {str(req.revision_id): req.code for req in frozen.requirements}
    by_module = {module["module_id"]: code[module["requirement_ids"][0]] for _, module in modules(plan)}
    prerequisites = {code[m["requirement_ids"][0]]: sorted(by_module[p] for p in m["prerequisite_module_ids"])
                     for _, m in modules(plan)}
    assert prerequisites == {
        "P4D_SECURITY_AWARENESS": [], "P4D_POLICY_ACK": [], "P4D_WORKSTATION_SANDBOX": [],
        "P4D_SECURE_CODING": ["P4D_SECURITY_AWARENESS", "P4D_WORKSTATION_SANDBOX"],
        "P4D_REPO_WORKFLOW": ["P4D_SECURE_CODING"],
        "P4D_FINAL_ASSESSMENT": sorted(["P4D_WORKSTATION_SANDBOX", "P4D_SECURE_CODING", "P4D_REPO_WORKFLOW",
                                        "P4D_SECURITY_AWARENESS", "P4D_POLICY_ACK"])}
    assert not has_cycle({m["module_id"]: m["prerequisite_module_ids"] for _, m in modules(plan)})
    position = {m["module_id"]: index for index, (_, m) in enumerate(modules(plan))}
    assert all(position[p] < position[m["module_id"]] for _, m in modules(plan) for p in m["prerequisite_module_ids"])
    edges = {(str(d), str(p)) for d, p in frozen.dependencies}
    wired = {(m["requirement_ids"][0], next(x["requirement_ids"][0] for _, x in modules(plan) if x["module_id"] == p))
             for _, m in modules(plan) for p in m["prerequisite_module_ids"]}
    assert wired == edges and len(edges) == 8


def test_layout_orders_same_stage_prerequisites_first_and_places_unstaged_after_prerequisites():
    frozen = snapshot()
    reqs = list(frozen.requirements)
    reqs[0], reqs[1] = reqs[1], reqs[0]  # secure coding now precedes its sandbox prerequisite
    final = next(i for i, r in enumerate(reqs) if r.code == "P4D_FINAL_ASSESSMENT")
    reqs[final] = reqs[final].model_copy(update={"stage_definition_id": None})
    layout = module_layout(frozen.model_copy(update={"requirements": tuple(reqs)}))
    codes = [[req.code for req in stage] for stage in layout]
    stage3 = codes[2]
    assert stage3.index("P4D_WORKSTATION_SANDBOX") < stage3.index("P4D_SECURE_CODING")
    assert "P4D_FINAL_ASSESSMENT" in codes[3]  # latest prerequisite (repo workflow) is in stage 4


def test_generated_ids_are_unique_deterministic_and_run_scoped():
    frozen = snapshot()
    parsed = ContentResponse.model_validate_json(json.dumps(content()))
    first, again = assemble_plan(parsed, frozen, RUN), assemble_plan(parsed, frozen, RUN)
    other = assemble_plan(parsed, frozen, UUID(int=1))
    ids = lambda plan: re.findall(r'"(?:module|objective|checklist_item|task|quiz|option)_id": "([^"]+)"',
                                  json.dumps(plan))
    assert ids(first) == ids(again) and len(ids(first)) == len(set(ids(first))) == 6 * 8
    assert not set(ids(first)) & set(ids(other))
    known = {str(r.revision_id) for r in frozen.requirements} | {str(s.stage_definition_id) for s in frozen.stage_set.items}
    assert not set(ids(first)) & known
    module_ids = {m["module_id"] for _, m in modules(first)}
    assert module_ids == {generated_id(RUN, req.revision_id, "module") for req in frozen.requirements}
    assert str(ID_NAMESPACE) == "0f4a7c2e-9d31-5b8e-a6c4-3e2d1f0b9a57"  # pinned: changing it changes every id


# --- The model generates no mechanical values ---------------------------------------------------

def test_content_schema_is_flat_and_contains_no_ids_keys_or_versions():
    frozen = snapshot()
    schema = build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION).response_schema
    text = json.dumps(schema)
    assert '"uuid"' not in text and "source_refs" not in text and "schema_version" not in text
    assert "requirement_ids" not in text and "stage_id" not in text and "_id" not in text.replace("module_", "")
    requirements = schema["properties"]["requirements"]
    assert list(requirements["properties"]) == requirements["required"] == [f"R{i}" for i in range(1, 7)]
    assert requirements["additionalProperties"] is False and schema["additionalProperties"] is False
    item = schema["$defs"]["RequirementContent"]
    assert item["additionalProperties"] is False and sorted(item["required"]) == sorted(item["properties"])
    assert (item["properties"]["quiz_options"]["minItems"], item["properties"]["quiz_options"]["maxItems"]) == (3, 3)
    assert (item["properties"]["correct_option_index"]["minimum"],
            item["properties"]["correct_option_index"]["maximum"]) == (0, 2)
    assert item["properties"]["objective"]["pattern"] == r"\S" and item["properties"]["objective"]["maxLength"] == 200
    gemini = provider_schema_for(build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION), key_pattern=False)
    assert '"pattern"' not in json.dumps(gemini) and '"minimum"' not in json.dumps(gemini)


def test_prompt_is_content_only_and_exposes_no_uuids_to_the_model():
    frozen = snapshot()
    prompt = build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION)
    assert (prompt.prompt_version, prompt.template_hash) == (CONTENT_PROMPT_VERSION, V4_HASH)
    assert content_template_hash() == V4_HASH
    assert not UUID_TEXT.search(prompt.untrusted_data) and "generation_request_id" not in prompt.untrusted_data
    data = json.loads(re.search(r'application/json">\n(.*)\n</untrusted', prompt.untrusted_data, re.S).group(1))
    assert [r["key"] for r in data["requirements"]] == [f"R{i}" for i in range(1, 7)]
    assert next(r for r in data["requirements"] if r["code"] == "P4D_SECURE_CODING")["after"] == ["R1", "R4"]
    for phrase in ("never output ids, codes, source keys or version fields", "exactly one entry per requirement key",
                   "correct_option_index (0, 1 or 2", "never infer missing timing"):
        assert phrase in prompt.rules
    assert prompt.within_budget
    assert "response_schema" not in prompt.model_dump()  # not serialized: historical prompt goldens unaffected


# --- Failure handling: rejected, never repaired ---------------------------------------------------

def _mutated(change):
    data = content()
    change(data)
    return json.dumps(data)


@pytest.mark.parametrize("text,code,diagnostic", [
    (_mutated(lambda d: d["requirements"].pop("R3")), "SCHEMA_INVALID", ("requirements", "R3")),
    (_mutated(lambda d: d["requirements"].update(R9=d["requirements"]["R1"])), "SCHEMA_INVALID",
     ("requirements", "unknown_field")),
    (_mutated(lambda d: d["requirements"]["R2"].update(objective="   ")), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(module_title="")), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(correct_option_index=3)), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(correct_option_index=-1)), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(correct_option_index=True)), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(quiz_options=["A", "B"])), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(quiz_options=["A", "B", "C", "D"])), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(quiz_options=["Yes", "yes ", "No"])), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(module_id=str(UUID(int=5)))), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d.update(schema_version="onboarding-plan/1.0.0")), "SCHEMA_INVALID", None),
    (_mutated(lambda d: d["requirements"]["R2"].update(estimated_minutes=0)), "SCHEMA_INVALID", None),
    ('{"plan_title": "a", "plan_title": "b"}', "MALFORMED_JSON", None),
    (json.dumps(content())[:-1].replace('"R6":', '"R6": {}, "R6":', 1) + "}", "MALFORMED_JSON", None),
    ("{not json", "MALFORMED_JSON", None),
    ("", "EMPTY_RESPONSE", None),
], ids=["missing requirement", "unknown requirement key", "blank prose", "empty title", "index 3", "index -1",
        "index bool", "2 options", "4 options", "duplicate options", "model supplied id", "model supplied version",
        "minutes out of range", "duplicate top-level key", "duplicate requirement key", "malformed json", "empty"])
def test_invalid_content_fails_without_repair(text, code, diagnostic):
    frozen = snapshot()
    with pytest.raises(StructuralFailure) as caught:
        assemble_content(text, frozen, RUN)
    assert caught.value.code == code
    if diagnostic:
        assert any(item["loc"] == diagnostic for item in caught.value.diagnostics)
    attempts = []
    result = run(frozen, text, text, attempts=attempts)  # one format retry, then a terminal failure
    assert result.status == "FAILED" and result.error_code == code and result.plan is None
    assert [a.parse_outcome for a in attempts] == ["SCHEMA_INVALID", "SCHEMA_INVALID"]


def test_retry_with_valid_content_succeeds_and_timeout_is_a_provider_failure():
    frozen = snapshot()
    bad = _mutated(lambda d: d["requirements"].pop("R1"))
    assert run(frozen, bad, json.dumps(content())).status == "UNVERIFIED"
    attempts = []
    result = run(frozen, ProviderFailure("PROVIDER_DEADLINE_EXCEEDED"), attempts=attempts)
    assert (result.status, result.error_code) == ("FAILED", "PROVIDER_DEADLINE_EXCEEDED")
    assert attempts[0].provider_outcome == "TIMEOUT" and attempts[0].usage == {}


# --- Usage telemetry ----------------------------------------------------------------------------

def test_usage_is_mapped_to_the_rpc_allowlist_and_missing_usage_is_allowed():
    frozen = snapshot()
    with_usage = ProviderResult(text=json.dumps(content()), finish_reason="STOP",
                                usage=ProviderUsage(prompt_tokens=2100, completion_tokens=1300, total_tokens=3400))
    attempts = []
    assert run(frozen, with_usage, attempts=attempts).status == "UNVERIFIED"
    assert attempts[0].usage == {"prompt_tokens": 2100, "output_tokens": 1300, "total_tokens": 3400}
    partial = ProviderResult(text="{bad", finish_reason="STOP", usage=ProviderUsage(total_tokens=9))
    attempts = []
    run(frozen, partial, partial, attempts=attempts)
    assert attempts[0].usage == {"total_tokens": 9} and attempts[0].parse_outcome == "SCHEMA_INVALID"
    assert usage_metadata(ProviderResult(text="{}", finish_reason="STOP")) == {}


def test_record_attempt_sends_usage_or_an_empty_object():
    calls = []

    class Capture(GenerationStore):
        async def rpc(self, token, name, payload):
            calls.append((name, payload))
            return 1
    store = object.__new__(Capture)
    base = dict(attempt_type="INITIAL", provider_outcome="RESPONSE", latency_ms=5, response_hash="0" * 64,
                response_size=10, parse_outcome="SCHEMA_VALID")
    asyncio.run(store.record_attempt("t", RUN, AttemptTelemetry(**base, usage={"prompt_tokens": 1, "output_tokens": 2,
                                                                                "total_tokens": 3})))
    asyncio.run(store.record_attempt("t", RUN, AttemptTelemetry(**base)))
    assert calls[0][0] == "record_generation_attempt"
    assert calls[0][1]["p_usage"] == {"prompt_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    assert calls[1][1]["p_usage"] == {}
    assert set(calls[0][1]["p_usage"]) <= {"prompt_tokens", "output_tokens", "total_tokens"}


# --- Provider request construction (never sent) ---------------------------------------------------

def nara_config(**overrides):
    return NaraRouterConfig(provider="nararouter", model="agnes-2.5-flash", api_key=SecretStr("placeholder"),
                            base_url="https://nara.invalid/v1", temperature=0.1, **overrides)


def test_nararouter_v4_request_uses_low_reasoning_and_content_schema_only_for_v4():
    frozen = snapshot()
    v4 = build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION)
    v31 = build_prompt(frozen, RUN, version=SOURCE_KEYS_V31_PROMPT_VERSION)
    payload = nararouter_request_payload(v4, nara_config())
    assert payload["reasoning_effort"] == "low" and payload["temperature"] == 0.1
    assert payload["messages"][0]["content"].endswith(CONTENT_OUTPUT_INSTRUCTIONS)
    old = nararouter_request_payload(v31, nara_config())
    assert "reasoning_effort" not in old and old["messages"][0]["content"].endswith(OUTPUT_INSTRUCTIONS)
    assert nararouter_request_payload(v31, nara_config(reasoning_effort="high"))["reasoning_effort"] == "high"
    assert nararouter_request_payload(v4, nara_config(content_reasoning_effort="medium"))["reasoning_effort"] == "medium"
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await NaraRouterProvider(client, nara_config()).generate(v4)
    result = asyncio.run(scenario())
    assert bodies[0]["response_format"]["json_schema"]["schema"] == v4.response_schema
    assert bodies[0]["response_format"]["json_schema"]["strict"] is False
    assert usage_metadata(result) == {"prompt_tokens": 1, "output_tokens": 2, "total_tokens": 3}


def test_content_reasoning_effort_env_rejects_none_and_defaults_to_low(monkeypatch):
    monkeypatch.setenv("NARAROUTER_API_KEY", "placeholder-key")
    monkeypatch.setenv("NARAROUTER_BASE_URL", "https://nara.invalid/v1")
    monkeypatch.setenv("NARAROUTER_MODEL", "agnes-2.5-flash")
    monkeypatch.setenv("NARAROUTER_REASONING_EFFORT", "")
    monkeypatch.setenv("NARAROUTER_CONTENT_REASONING_EFFORT", "")
    config = NaraRouterEnvironment().adapter_config()
    assert (config.reasoning_effort, config.content_reasoning_effort) == (None, "low")
    monkeypatch.setenv("NARAROUTER_CONTENT_REASONING_EFFORT", "none")
    with pytest.raises(ProviderFailure, match="PROVIDER_CONFIGURATION_FAILED"):
        NaraRouterEnvironment().adapter_config()


def test_groq_and_gemini_send_the_v4_content_schema():
    frozen = snapshot()
    prompt = build_prompt(frozen, RUN, version=CONTENT_PROMPT_VERSION)
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                                                             "content": {"parts": [{"text": "{}"}]}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await GroqProvider(client, ProviderConfig(provider="groq", model="openai/gpt-oss-20b",
                                                      api_key="k")).generate(prompt)
            await GeminiProvider(client, ProviderConfig(model="mock-model", api_key="k")).generate(prompt)
    asyncio.run(scenario())
    assert bodies[0]["response_format"]["json_schema"]["schema"] == prompt.response_schema
    gemini = bodies[1]["generationConfig"]["responseJsonSchema"]
    assert '"pattern"' not in json.dumps(gemini) and list(gemini["properties"]["requirements"]["properties"]) == [
        f"R{i}" for i in range(1, 7)]


# --- Versions, flags and migration ------------------------------------------------------------

def test_flags_select_versions_and_historical_identities_are_unchanged(monkeypatch):
    frozen = snapshot()
    for content_only, source_keys, expected in (("true", "false", (CONTENT_PROMPT_VERSION, V4_HASH)),
                                                ("true", "true", (CONTENT_PROMPT_VERSION, V4_HASH)),
                                                ("false", "true", (SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH)),
                                                ("false", "false", (PROMPT_VERSION, V2_HASH))):
        monkeypatch.setenv("GENERATION_CONTENT_ONLY", content_only)
        monkeypatch.setenv("GENERATION_SOURCE_KEYS", source_keys)
        prompt = build_prompt(frozen, RUN)
        assert (prompt.prompt_version, prompt.template_hash) == expected
    assert (template_hash(), source_keys_template_hash(), source_keys_v31_template_hash()) == (V2_HASH, V3_HASH, V31_HASH)
    for version, expected_hash in ((PROMPT_VERSION, V2_HASH), (SOURCE_KEYS_PROMPT_VERSION, V3_HASH),
                                   (SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH)):
        prompt = build_prompt(frozen, RUN, version=version)
        assert prompt.template_hash == expected_hash and prompt.response_schema is None


def _body(text):
    marker = "create or replace function"
    return text[text.index(marker):text.index("end $$;", text.index(marker))]


def test_v4_migration_adds_exactly_one_pair_and_rejects_every_mix():
    previous = (MIGRATIONS / "202609280007_source_keys_prompt_v31.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "202609280008_content_only_prompt_v4.sql").read_text(encoding="utf-8")
    added = ("\n          or (p_prompt_version = 'phase4d-content-only/4.0.0'\n"
             f"           and p_template_hash = '{V4_HASH}')")
    assert _body(new).replace(added, "").replace("one of four reviewed", "one of three reviewed") == _body(previous)
    assert ("add constraint generation_runs_content_v4_projection_check\n  check (prompt_version <> "
            "'phase4d-content-only/4.0.0' or projection_hash is not null);") in new
    assert "not between 1 and 290" in new and new.lower().count("alter table") == 1
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", new)
    pin = re.search(r"or not coalesce\((.*?), false\)", new, re.S).group(1)
    pairs = set(re.findall(r"\(p_prompt_version = '([^']+)'\s+and p_template_hash = '([0-9a-f]{64})'\)", pin))
    valid = {(PROMPT_VERSION, V2_HASH), (SOURCE_KEYS_PROMPT_VERSION, V3_HASH),
             (SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH), (CONTENT_PROMPT_VERSION, V4_HASH)}
    assert pairs == valid and re.sub(r"\s+", " ", pin).count(" or ") == 3
    versions, hashes = zip(*valid)
    assert all(((v, h) in pairs) is ((v, h) in valid) for v in versions for h in hashes)


def test_api_reserves_v4_and_persists_an_assembled_plan(monkeypatch):
    from fastapi.testclient import TestClient
    from app import generation_api, security
    from app.generation_persistence import get_generation_store
    from app.main import app
    from test_generation_api import Store, actor
    from test_generation_context import EMP
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "true")
    store = Store()
    frozen_employee = EMP

    class Provider:
        def __init__(self):
            self.prompts = []

        async def generate(self, prompt, *, format_retry=False):
            self.prompts.append(prompt)
            keys = [key for key in prompt.response_schema["properties"]["requirements"]["properties"]]
            item = content()["requirements"]["R1"]
            return ProviderResult(text=json.dumps({"plan_title": "Plan", "plan_summary": "Summary.",
                                                   "requirements": {key: item for key in keys}}),
                                  finish_reason="STOP")
    provider = Provider()
    config = ProviderConfig(model="test-model", api_key=SecretStr("test-only-placeholder"))
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_generation_store] = lambda: store
    monkeypatch.setattr(generation_api, "get_provider_bundle", lambda request: (provider, config))
    try:
        with TestClient(app) as client:
            client.post("/api/v1/generation-runs", json={"employee_id": str(frozen_employee)},
                        headers={"Idempotency-Key": "content-only-123"})
    finally:
        app.dependency_overrides.clear()
    reserve = next(payload for name, payload in store.calls if name == "reserve")
    assert (reserve["p_prompt_version"], reserve["p_template_hash"]) == (CONTENT_PROMPT_VERSION, V4_HASH)
    assert provider.prompts[0].prompt_version == CONTENT_PROMPT_VERSION
    assert store.status in ("UNVERIFIED", "STALE_INPUT") and store.last_finish[1]["schema_version"] == \
        "onboarding-plan/1.0.0"
