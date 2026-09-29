"""Source keys 3.1.0: the provider schema matches OnboardingPlan, ownership is explicit,
and malformed output is rejected at the earliest layer. Offline only; no provider calls."""

import asyncio
import copy
import json
import re
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from app.generation_context import input_hash
from app.generation_models import PreflightResult
from app.generation_output import OnboardingPlan
from app.generation_prompt import (PROMPT_VERSION, SOURCE_KEYS_PROMPT_VERSION, SOURCE_KEYS_V31_PROMPT_VERSION,
                                   SOURCE_KEYS_V31_PROVIDER_RULES, _compact_schema, build_prompt,
                                   current_provider_schema, source_key_map, source_keys_template_hash,
                                   source_keys_v31_template_hash, strict_provider_schema, template_hash)
from app.generation_provider import GeminiProvider, GroqProvider, ProviderConfig, ProviderResult
from app.generation_service import StructuralFailure, expand_source_keys, generate_unverified, parse_plan
from app.jev import decide
from app.plan_validator import validate_plan
from app.rrm_rules import canonical_json
from test_validation import RUN, fixture as validation_fixture

V2_HASH = "11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc"
V3_HASH = "5bb4fcd13076012b87dcc58381cf74209ae3910dba8e449d035cc6d49cb388b4"
V31_HASH = "c4c9349fa689a281d392f0d03a6e275aeef6ef59130c23447d2a28e2bce1c58f"
# Historical 3.0.0 outputs, computed at 55af6ee (before 3.1.0) with the same fixtures.
V3_GOLDEN = {"prompt": "fb0b86b12d3cdfb2b465c9c2e4a7586cdf04db78222bf69b41080439f642713f",
             "nara": "196d7e7a0d0c1be479471a8fb8114c314a45a5eb6daff4107610ff4631a5b07a",
             "gemini": "b74613a2d14865fb96b8c6eb56ec736b53b02f68db4cd9d4895d789bd8d257a6",
             "capped": "d4ffb5dd3900b3a5c3a847d02d76bd77a1f56f85d9a4a048c1dbebc5c52e52c6"}
COMPACT_CAPS = {**{f"GENERATION_MAX_{name}_PER_MODULE": "1" for name in ("OBJECTIVES", "TASKS", "CHECKLIST", "QUIZ")},
                **{f"GENERATION_MAX_{name}_PER_MODULE": "0" for name in
                   ("KEY_CONCEPTS", "ACTIVITIES", "SCENARIOS", "ASSESSMENTS", "COMPLETION_CRITERIA")},
                "GENERATION_MAX_TEXT_LENGTH": "200"}
BOUNDS = ("type", "format", "enum", "minItems", "maxItems", "minLength", "maxLength", "pattern",
          "minimum", "maximum", "additionalProperties")


def sha(text):
    from hashlib import sha256
    return sha256(text.encode("utf-8")).hexdigest()


# --- A tiny JSON Schema checker for exactly the keywords we send (no dependency) ----------

def schema_errors(schema, value, node=None, path="$"):
    node = schema if node is None else node
    if "$ref" in node:
        return schema_errors(schema, value, schema["$defs"][node["$ref"].rsplit("/", 1)[1]], path)
    if "anyOf" in node:
        options = [schema_errors(schema, value, option, path) for option in node["anyOf"]]
        return [] if any(not errors for errors in options) else [f"{path}: anyOf"]
    errors = []
    kind = node.get("type")
    checks = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return [f"{path}: type"]
    if kind in checks and not isinstance(value, checks[kind]):
        return [f"{path}: type"]
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: enum")
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", 10 ** 9):
            errors.append(f"{path}: length")
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(f"{path}: pattern")
        if node.get("format") == "uuid":
            try:
                UUID(value)
            except ValueError:
                errors.append(f"{path}: format")
        if node.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{path}: format")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < node.get("minimum", -10 ** 18) or value > node.get("maximum", 10 ** 18):
            errors.append(f"{path}: range")
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", 10 ** 9):
            errors.append(f"{path}: items")
        for index, item in enumerate(value):
            errors += schema_errors(schema, item, node.get("items", {}), f"{path}[{index}]")
    if isinstance(value, dict):
        properties = node.get("properties", {})
        errors += [f"{path}.{name}: required" for name in node.get("required", []) if name not in value]
        if node.get("additionalProperties") is False:
            errors += [f"{path}.{name}: additional" for name in value if name not in properties]
        for name, item in value.items():
            if name in properties:
                errors += schema_errors(schema, item, properties[name], f"{path}.{name}")
    return errors


# --- 1. Contract diff: every expressible Pydantic rule is in the NaraRouter schema ----------

def _resolve(schema, node):
    return schema["$defs"][node["$ref"].rsplit("/", 1)[1]] if "$ref" in node else node


def contract_diff(provider):
    """Rows (path, rule, pydantic, provider, verdict) for every constraint of every node."""
    pydantic = _compact_schema(OnboardingPlan.model_json_schema())
    rows = []

    def compare(pyd, prov, path):
        if "$ref" in pyd:
            return
        if path.endswith(".source_refs"):
            rows.append((path, "source_refs", "SourceRef objects (min 1, max 100)", json.dumps(prov),
                         "REPLACED: S# keys, expanded by Python before Pydantic"))
            return
        for rule in BOUNDS:
            wanted = pyd.get(rule, [pyd["const"]] if rule == "enum" and "const" in pyd else None)
            if wanted is None:
                continue
            got = prov.get(rule)
            verdict = ("MATCH" if got == wanted else
                       "STRICTER" if rule == "minItems" and isinstance(got, int) and got > wanted else "MISMATCH")
            rows.append((path, rule, wanted, got, verdict))
        for rule in ("minItems", "minLength", "minimum"):  # provider-only rules may only add strictness
            if rule not in pyd and rule in prov:
                rows.append((path, rule, None, prov[rule], "STRICTER"))
        if "required" in pyd:
            missing = sorted(set(pyd["required"]) - set(prov.get("required", [])))
            rows.append((path, "required", sorted(pyd["required"]), "all properties",
                         "MISMATCH" if missing else "STRICTER" if set(prov["required"]) > set(pyd["required"])
                         else "MATCH"))
        for left, right in zip(pyd.get("anyOf", []), prov.get("anyOf", [])):
            compare(left, right, path + "|")
        if "items" in pyd:
            compare(pyd["items"], prov["items"], path + "[]")
        for name, item in pyd.get("properties", {}).items():
            compare(item, prov["properties"][name], f"{path}.{name}")

    for name, definition in pydantic["$defs"].items():
        if name != "SourceRef":
            compare(definition, provider["$defs"][name], name)
    compare({key: value for key, value in pydantic.items() if key != "$defs"}, provider, "OnboardingPlan")
    return rows


def test_nararouter_schema_carries_every_expressible_pydantic_constraint():
    rows = contract_diff(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION))
    assert rows and not [row for row in rows if row[4] == "MISMATCH"]
    stricter = {(row[0], row[1]) for row in rows if row[4] == "STRICTER"}
    assert {("Module.learning_objectives", "minItems"), ("Module.tasks", "minItems"),
            ("Module.checklist_items", "minItems"), ("Module.quizzes", "minItems")} <= stricter
    assert len([row for row in rows if row[4].startswith("REPLACED")]) == 11
    # The 3.0.0 schema, by contrast, dropped these bounds; that is the gap 3.1.0 closes.
    old = [row for row in contract_diff(current_provider_schema(SOURCE_KEYS_PROMPT_VERSION)) if row[4] == "MISMATCH"]
    assert {"minItems", "minLength", "pattern", "minimum", "maximum", "maxItems"} <= {row[1] for row in old}


def test_compact_caps_only_tighten_the_strict_schema(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)
    rows = contract_diff(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION))
    for path, rule, wanted, got, verdict in rows:
        if verdict == "MISMATCH":  # only caps may differ, and only downwards
            assert rule in ("maxItems", "maxLength") and got <= wanted, (path, rule, wanted, got)
    schema = current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION)
    module = schema["$defs"]["Module"]["properties"]
    assert (module["tasks"]["minItems"], module["tasks"]["maxItems"]) == (1, 1)
    assert module["key_concepts"]["maxItems"] == 0 and module["title"]["maxLength"] == 200
    assert module["title"]["minLength"] == 1 and module["title"]["pattern"] == r"\S"


GROUNDED = ("Objective", "KeyConcept", "Activity", "ChecklistItem", "Task", "Scenario", "Quiz",
            "RubricRow", "Assessment", "CompletionCriterion", "Module")


def test_named_constraints_from_the_failed_runs_are_now_sent():
    schema = current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION)
    defs = schema["$defs"]
    for name in GROUNDED:
        properties = defs[name]["properties"]
        assert properties["requirement_ids"]["minItems"] == 1
        assert properties["requirement_ids"]["items"]["format"] == "uuid"
        assert properties["source_refs"] == {"type": "array", "minItems": 1, "maxItems": 100,
                                             "items": {"type": "string", "pattern": "^S[0-9]+$"}}
        assert defs[name]["additionalProperties"] is False
        assert sorted(defs[name]["required"]) == sorted(properties)
    assert defs["Quiz"]["properties"]["options"]["minItems"] == 2
    assert defs["Quiz"]["properties"]["correct_answer_ids"]["minItems"] == 1
    assert (defs["Module"]["properties"]["estimated_minutes"]["minimum"],
            defs["Module"]["properties"]["estimated_minutes"]["maximum"]) == (1, 10080)
    assert (defs["RubricRow"]["properties"]["weight_percent"]["minimum"],
            defs["RubricRow"]["properties"]["weight_percent"]["maximum"]) == (0, 100)
    assert defs["Assessment"]["properties"]["rubric"]["minItems"] == 1
    assert defs["Plan"]["properties"]["stages"]["minItems"] == 1
    for name, prop in (("Objective", "statement"), ("Task", "description"), ("Quiz", "question"),
                       ("QuizOption", "text"), ("Module", "title"), ("ChecklistItem", "responsible_role")):
        node = defs[name]["properties"][prop]
        assert node["minLength"] == 1 and node["pattern"] == r"\S"
    assert defs["Task"]["properties"]["completion_criteria"]["items"]["pattern"] == r"\S"
    assert "SourceRef" not in defs


def test_gemini_31_schema_sends_no_pattern_and_groq_gets_the_strict_schema():
    gemini = current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION, key_pattern=False)
    assert '"pattern"' not in json.dumps(gemini) and '"minimum"' not in json.dumps(gemini)
    assert current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION) == strict_like()
    import httpx
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
                                                             "content": {"parts": [{"text": "{}"}]}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

    prompt = build_prompt(validation_fixture()[0], RUN, source_keys=True)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await GroqProvider(client, ProviderConfig(provider="groq", model="openai/gpt-oss-20b",
                                                      api_key="k")).generate(prompt)
            await GeminiProvider(client, ProviderConfig(model="mock-model", api_key="k")).generate(prompt)
    asyncio.run(scenario())
    assert bodies[0]["response_format"]["json_schema"]["schema"] == strict_like()
    assert '"pattern"' not in json.dumps(bodies[1]["generationConfig"]["responseJsonSchema"])


def strict_like():
    return current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION, key_pattern=True)


# --- Prompt: ownership and Python-only rules --------------------------------------------

def _projection(prompt):
    return json.loads(re.search(r'application/json">\n(.*)\n</untrusted', prompt.untrusted_data, re.S).group(1))


def test_each_requirement_lists_exactly_its_allowed_sources():
    from test_source_keys import shared_evidence_snapshot
    snapshot = shared_evidence_snapshot()
    keys = source_key_map(snapshot)
    data = _projection(build_prompt(snapshot, RUN, source_keys=True))
    assert data["projection_version"] == "generation-projection/3.1.0"
    for requirement in data["requirements"]:
        assert "source_keys" not in requirement and "source_refs" not in requirement
        assert requirement["allowed_sources"] == [key for key, item in keys.items()
                                                  if requirement["revision_id"] in item.requirement_ids]
        assert len(requirement["allowed_sources"]) == 4
    assert len(data["evidence"]) == len(keys) == 9


def test_rules_state_ownership_multi_requirement_and_python_only_rules_compactly():
    rules = SOURCE_KEYS_V31_PROVIDER_RULES
    for phrase in ("source_refs: only S# keys from allowed_sources of the item's own requirement_ids",
                   "(any of them if several)", "a key merely present in evidence is never allowed",
                   "every grounded item has >=1 requirement_ids",
                   "is a new UUID used once in the whole plan",
                   "correct_answer_ids are option_ids of the same quiz",
                   "rubric weight_percent sums to exactly 100 per assessment",
                   "due_stage_id is a plan stage_id", "no blank text"):
        assert phrase in rules
    assert "copy matching document_version_id,chunk_id,locator" not in rules
    base = build_prompt(validation_fixture()[0], RUN, version=SOURCE_KEYS_PROMPT_VERSION).rules
    assert len(rules) - len(base) < 700  # compact: a few hundred bytes of rules


# --- Versions -----------------------------------------------------------------------------

def test_versions_and_hashes_are_distinct_deterministic_and_historical_ones_unchanged(monkeypatch):
    snapshot = validation_fixture()[0]
    assert (template_hash(), source_keys_template_hash(), source_keys_v31_template_hash()) == (
        V2_HASH, V3_HASH, V31_HASH)
    assert source_keys_v31_template_hash() == V31_HASH
    for flag, expected in (("true", (SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH)), ("false", (PROMPT_VERSION, V2_HASH))):
        monkeypatch.setenv("GENERATION_SOURCE_KEYS", flag)
        prompt = build_prompt(snapshot, RUN)
        assert (prompt.prompt_version, prompt.template_hash) == expected
    with pytest.raises(ValueError, match="UNKNOWN_PROMPT_VERSION"):
        build_prompt(snapshot, RUN, version="phase4d-compact-context/9.9.9")


def test_historical_v3_prompt_and_schemas_are_byte_identical(monkeypatch):
    from test_source_keys import multi_document_snapshot
    prompt = build_prompt(multi_document_snapshot(), UUID(int=90), version=SOURCE_KEYS_PROMPT_VERSION)
    assert (prompt.prompt_version, prompt.template_hash) == (SOURCE_KEYS_PROMPT_VERSION, V3_HASH)
    assert sha(prompt.model_dump_json()) == V3_GOLDEN["prompt"]
    assert sha(canonical_json(current_provider_schema(SOURCE_KEYS_PROMPT_VERSION))) == V3_GOLDEN["nara"]
    assert sha(canonical_json(current_provider_schema(SOURCE_KEYS_PROMPT_VERSION, key_pattern=False))) == \
        V3_GOLDEN["gemini"]
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)
    assert sha(canonical_json(current_provider_schema(SOURCE_KEYS_PROMPT_VERSION))) == V3_GOLDEN["capped"]


# --- Migration ----------------------------------------------------------------------------

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def _body(text):
    marker = "create or replace function"
    return text[text.index(marker):text.index("end $$;", text.index(marker))]


def test_v31_migration_only_adds_the_exact_31_pair_and_its_projection_check():
    previous = (MIGRATIONS / "202609280006_source_keys_prompt_v3.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "202609280007_source_keys_prompt_v31.sql").read_text(encoding="utf-8")
    added = ("\n          or (p_prompt_version = 'phase4d-compact-context/3.1.0'\n"
             f"           and p_template_hash = '{V31_HASH}')")
    normalized = _body(new).replace(added, "").replace("one of three reviewed", "one of two reviewed")
    assert normalized == _body(previous)
    assert ("add constraint generation_runs_compact_v31_projection_check\n  check (prompt_version <> "
            "'phase4d-compact-context/3.1.0' or projection_hash is not null);") in new
    assert "not between 1 and 290" in new and new.count("end $$;") == 1
    assert "\nbegin;" in new and new.rstrip().endswith("commit;") and new.lower().count("alter table") == 1
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", new)


def _accepts(sql, version, hash_):
    pin = re.search(r"or not coalesce\((.*?), false\)", sql, re.S).group(1)
    pairs = re.findall(r"\(p_prompt_version = '([^']+)'\s+and p_template_hash = '([0-9a-f]{64})'\)", pin)
    assert len(pairs) == 3 and re.sub(r"\s+", " ", pin).count(" or ") == 2
    return version is not None and hash_ is not None and (version, hash_) in pairs


def test_v31_migration_accepts_exactly_three_pairs_and_rejects_every_mix():
    sql = (MIGRATIONS / "202609280007_source_keys_prompt_v31.sql").read_text(encoding="utf-8")
    pairs = {PROMPT_VERSION: V2_HASH, SOURCE_KEYS_PROMPT_VERSION: V3_HASH, SOURCE_KEYS_V31_PROMPT_VERSION: V31_HASH}
    for version in pairs:
        for owner, hash_ in pairs.items():
            assert _accepts(sql, version, hash_) is (owner == version), (version, owner)
        assert not _accepts(sql, version, None)
    assert not _accepts(sql, None, V31_HASH)
    assert not _accepts(sql, "phase4d-compact-context/3.2.0", V31_HASH)


# --- 8. Offline end-to-end: valid v3.1 response -> expansion -> Pydantic -> validator -------

def valid_v31_response():
    """The validator's VERIFIED 6-requirement/8-edge/5-stage plan, as a compact-capped 3.1.0
    provider response: S# keys, one objective/checklist/task/quiz per module."""
    frozen, plan = validation_fixture()
    keys = source_key_map(frozen)
    plan = copy.deepcopy(plan)
    counter = iter(range(10_000, 20_000))
    for stage in plan["plan"]["stages"]:
        for module in stage["modules"]:
            requirement = module["requirement_ids"][0]
            allowed = [key for key, item in keys.items() if requirement in item.requirement_ids]
            grounded = {"requirement_ids": [requirement], "source_refs": allowed}
            module["source_refs"] = allowed
            option_a, option_b = (str(UUID(int=next(counter))) for _ in range(2))
            module.update({
                "learning_objectives": [{**grounded, "objective_id": str(UUID(int=next(counter))),
                                         "statement": "Explain the approved obligation."}],
                "key_concepts": [], "activities": [], "scenarios": [], "assessments": [], "completion_criteria": [],
                "checklist_items": [{**grounded, "checklist_item_id": str(UUID(int=next(counter))),
                                     "activity": "Complete the approved activity.", "required": True,
                                     "due_stage_id": stage["stage_id"], "responsible_role": "Employee"}],
                "tasks": [{**grounded, "task_id": str(UUID(int=next(counter))), "description": "Do the activity.",
                           "expected_outcome": "Activity completed.", "completion_criteria": ["Completed"],
                           "difficulty": "BEGINNER", "due_stage_id": stage["stage_id"]}],
                "quizzes": [{**grounded, "quiz_id": str(UUID(int=next(counter))), "question_type": "SINGLE_CHOICE",
                             "question": "Which action is required?",
                             "options": [{"option_id": option_a, "text": "Complete it"},
                                         {"option_id": option_b, "text": "Skip it"}],
                             "correct_answer_ids": [option_a], "explanation": "It is mandatory.",
                             "difficulty": "BEGINNER"}]})
    plan["insufficient_information"] = []
    return frozen, plan


class Replay:
    def __init__(self, *texts):
        self.texts, self.prompts = list(texts), []

    async def generate(self, prompt, *, format_retry=False):
        self.prompts.append(prompt)
        return ProviderResult(text=self.texts.pop(0), finish_reason="STOP")


def run_pipeline(frozen, response):
    """provider output -> expansion -> Pydantic/parse_plan (generate_unverified) -> validator -> JEV."""
    provider = Replay(json.dumps(response), json.dumps(response))
    preflight = PreflightResult(status="READY", snapshot=frozen, input_hash=input_hash(frozen))

    async def no_sleep(_seconds):
        return None
    result = asyncio.run(generate_unverified(preflight, RUN, provider, no_sleep,
                                             prompt_version=SOURCE_KEYS_V31_PROMPT_VERSION))
    if result.plan is None:
        return result, None, None
    evidence = validate_plan(result.plan.model_dump(mode="json"), frozen, RUN, current_input=True)
    return result, evidence, decide(evidence)


def test_offline_end_to_end_valid_v31_response_is_verified(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)
    frozen, response = valid_v31_response()
    schema = current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION)
    assert schema_errors(schema, response) == []  # the provider is allowed to return it
    result, evidence, decision = run_pipeline(frozen, response)
    assert result.status == "UNVERIFIED" and result.provider_calls == 1
    assert (result.prompt_version, result.template_hash) == (SOURCE_KEYS_V31_PROMPT_VERSION, V31_HASH)
    refs = result.plan.plan.stages[0].modules[0].source_refs
    assert all(isinstance(ref.locator, str) and ref.chunk_id for ref in refs)  # full objects after expansion
    assert decision.status == "VERIFIED" and not evidence.findings and evidence.mandatory_covered == 6


def _module(plan, index=0):
    return [module for stage in plan["plan"]["stages"] for module in stage["modules"]][index]


def _set(path_setter):
    def mutate(plan, frozen):
        path_setter(plan, frozen)
    return mutate


# (name, mutation, rejected by provider schema?, expected pipeline error code, detail check)
MUTATIONS = [
    ("empty requirement_ids", lambda p, f: _module(p)["tasks"][0].update(requirement_ids=[]),
     True, "SCHEMA_INVALID"),
    ("blank text", lambda p, f: _module(p)["tasks"][0].update(description="   "), True, "SCHEMA_INVALID"),
    ("empty text", lambda p, f: _module(p)["quizzes"][0].update(question=""), True, "SCHEMA_INVALID"),
    ("one quiz option", lambda p, f: _module(p)["quizzes"][0].update(
        options=_module(p)["quizzes"][0]["options"][:1]), True, "SCHEMA_INVALID"),
    ("estimated_minutes 0", lambda p, f: _module(p).update(estimated_minutes=0), True, "SCHEMA_INVALID"),
    ("estimated_minutes too high", lambda p, f: _module(p).update(estimated_minutes=10081), True, "SCHEMA_INVALID"),
    ("lowercase key", lambda p, f: _module(p).update(source_refs=["s1"]), True, "SCHEMA_INVALID"),
    ("empty source_refs", lambda p, f: _module(p)["tasks"][0].update(source_refs=[]), True, "SCHEMA_INVALID"),
    ("extra field", lambda p, f: _module(p).update(notes="x"), True, "SCHEMA_INVALID"),
    ("invalid uuid", lambda p, f: _module(p).update(module_id="not-a-uuid"), True, "SCHEMA_INVALID"),
    ("bad enum", lambda p, f: _module(p).update(priority="URGENT"), True, "SCHEMA_INVALID"),
    # Schema-valid but semantically invalid: caught by Python, never repaired.
    ("unknown S# key", lambda p, f: _module(p).update(source_refs=["S99"]), False, "SCHEMA_INVALID"),
    ("key owned by another requirement", lambda p, f: _module(p).update(
        source_refs=[_module(p, 1)["source_refs"][0]]), False, "SCHEMA_INVALID"),
    ("answer not an option", lambda p, f: _module(p)["quizzes"][0].update(
        correct_answer_ids=[str(UUID(int=1))]), False, "SCHEMA_INVALID"),
    ("duplicate generated id", lambda p, f: _module(p)["tasks"][0].update(
        task_id=_module(p)["learning_objectives"][0]["objective_id"]), False, "SCHEMA_INVALID"),
    ("unknown due stage", lambda p, f: _module(p)["tasks"][0].update(due_stage_id=str(UUID(int=2))),
     False, "UNKNOWN_STAGE_REF"),
    ("unknown requirement", lambda p, f: _module(p)["tasks"][0].update(requirement_ids=[str(UUID(int=3))]),
     False, "SCHEMA_INVALID"),
    ("wrong employee", lambda p, f: p["employee_context"].update(role_id=str(UUID(int=4))),
     False, "CONTEXT_IDENTITY_MISMATCH"),
]


@pytest.mark.parametrize("name,mutate,schema_rejects,code", MUTATIONS, ids=[item[0] for item in MUTATIONS])
def test_malformed_outputs_fail_at_the_earliest_layer(monkeypatch, name, mutate, schema_rejects, code):
    for key, value in COMPACT_CAPS.items():
        monkeypatch.setenv(key, value)
    frozen, response = valid_v31_response()
    mutate(response, frozen)
    assert bool(schema_errors(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION), response)) is schema_rejects
    result, _, _ = run_pipeline(frozen, response)
    assert result.status == "FAILED" and result.error_code == code and result.plan is None


def test_rubric_rules_uncapped_schema_range_and_python_total(monkeypatch):
    frozen, response = valid_v31_response()
    module = _module(response)
    grounded = {"requirement_ids": module["requirement_ids"], "source_refs": module["source_refs"]}
    row = {**grounded, "criterion_id": str(UUID(int=30_001)), "criterion": "Accuracy", "weight_percent": 100,
           "expected_performance": "Correct", "pass_condition": "Pass"}
    module["assessments"] = [{**grounded, "assessment_id": str(UUID(int=30_002)), "assessment_type": "KNOWLEDGE",
                              "title": "Check", "instructions": "Answer.", "rubric": [row], "pass_condition": "Pass"}]
    schema = current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION)  # uncapped: assessments allowed
    assert schema_errors(schema, response) == []
    assert run_pipeline(frozen, response)[2].status == "VERIFIED"
    row["weight_percent"] = 101
    assert schema_errors(schema, response)  # range is schema-enforced
    row["weight_percent"] = 90
    assert schema_errors(schema, response) == []  # the total is not; Python rejects it
    assert run_pipeline(frozen, response)[0].error_code == "SCHEMA_INVALID"


def test_validator_still_catches_semantic_gaps_after_parsing(monkeypatch):
    for key, value in COMPACT_CAPS.items():
        monkeypatch.setenv(key, value)
    frozen, response = valid_v31_response()
    for stage in response["plan"]["stages"]:  # drop one mandatory requirement's module
        stage["modules"] = [module for module in stage["modules"] if module["module_id"] != str(UUID(int=605))]
        for module in stage["modules"]:
            module["prerequisite_module_ids"] = [item for item in module["prerequisite_module_ids"]
                                                 if item != str(UUID(int=605))]
    assert schema_errors(current_provider_schema(SOURCE_KEYS_V31_PROMPT_VERSION), response) == []
    result, evidence, decision = run_pipeline(frozen, response)
    assert result.status == "UNVERIFIED"  # structurally valid ...
    assert decision.status != "VERIFIED" and evidence.findings  # ... but the validator rejects it


def test_expansion_is_exact_and_parse_plan_accepts_only_expanded_output(monkeypatch):
    frozen, response = valid_v31_response()
    keys = source_key_map(frozen)
    expanded = json.loads(expand_source_keys(json.dumps(response), keys, RUN))
    module = _module(expanded)
    assert module["source_refs"] == [{"document_version_id": keys[key].document_version_id,
                                      "chunk_id": keys[key].chunk_id, "locator": keys[key].locator}
                                     for key in _module(response)["source_refs"]]
    parse_plan(json.dumps(expanded), RUN, frozen)
    with pytest.raises(StructuralFailure, match="SCHEMA_INVALID"):  # keys never reach Pydantic unexpanded
        parse_plan(json.dumps(response), RUN, frozen)
