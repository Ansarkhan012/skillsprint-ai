"""Short source keys (GENERATION_SOURCE_KEYS): flag-off equivalence, key mapping and expansion."""

import asyncio
import copy
import json
import re
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app import generation_api
from app.generation_context import input_hash
from app.generation_models import PreflightResult
from app.generation_prompt import (PROMPT_VERSION, PROVIDER_OUTPUT_SCHEMA, PROVIDER_RULES, SOURCE_KEYS_PROMPT_VERSION,
                                   SOURCE_KEYS_PROVIDER_RULES, build_prompt, current_provider_schema,
                                   source_key_map, source_keys_enabled, source_keys_template_hash, template_hash)
from app.generation_provider import GeminiProvider, GroqProvider, ProviderConfig, ProviderResult
from app.generation_service import StructuralFailure, expand_source_keys, generate_unverified, retry_feedback
from app.nararouter_provider import NaraRouterConfig, NaraRouterProvider
from app.rrm_rules import canonical_json
from test_generation_api import Store, actor
from test_generation_context import CHUNK, REQ, VERSION, ready
from test_generation_service import REQUEST, complete_output

V2_HASH = "11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc"
V3_HASH = "5bb4fcd13076012b87dcc58381cf74209ae3910dba8e449d035cc6d49cb388b4"
# Computed from commit 8a2d5a5 (before this feature) with the same fixture: flag-off output
# must stay byte-identical to it.
GOLDEN_PROMPT_SHA = "146904d5f61648bf7f8f4f8a16e1318891b21b9fa3076ba3bb0f8ae2423d3028"
GOLDEN_SCHEMA_SHA = "dc641daf8b63a3a9bc7745756b59ed7f250c8ab8cabaf7bbfe3c83e66c4d69d3"
GOLDEN_CAPPED_SCHEMA_SHA = "32be02be7bc374ad4de2ee884bea9e8560ec7310f77ae7f52c3282fe2ecc9d4f"
REQ2 = UUID(int=501)
VERSION2 = UUID(int=502)
CHUNK2, CHUNK3 = UUID(int=503), UUID(int=504)


def sha(text):
    return sha256(text.encode("utf-8")).hexdigest()


def multi_document_snapshot():
    """REQ cites (VERSION, CHUNK); REQ2 cites a chunk in a second document plus the shared one."""
    original = ready().snapshot
    first = original.requirements[0]
    shared = first.evidence[0]
    other = shared.model_copy(update={"document_version_id": VERSION2, "chunk_id": CHUNK2,
                                      "locator": {"kind": "docx", "paragraph": 7, "section_path": ["Access", "MFA"]},
                                      "excerpt": "Enable   multi-factor\nauthentication. " + "x" * 300})
    later = shared.model_copy(update={"document_version_id": VERSION2, "chunk_id": CHUNK3,
                                      "locator": {"kind": "pdf", "page": 3}, "excerpt": "Report incidents."})
    second = first.model_copy(update={"revision_id": REQ2, "code": "MFA", "sequence": first.sequence + 1,
                                      "evidence": (other, shared, later)})
    return original.model_copy(update={"requirements": (first, second)})


def keyed(output, keys, requirement_ids=None):
    """Replace every source_refs list in complete_output() with short keys."""
    output = copy.deepcopy(output)

    def walk(node):
        if isinstance(node, dict):
            if "source_refs" in node:
                node["source_refs"] = list(keys)
                if requirement_ids is not None:
                    node["requirement_ids"] = [str(item) for item in requirement_ids]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(output)
    return output


class RecordingProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    async def generate(self, prompt, *, format_retry=False):
        self.prompts.append(prompt)
        return ProviderResult(text=self.responses.pop(0), finish_reason="STOP")


def run(provider, snapshot=None, source_keys=True):
    snapshot = snapshot or ready().snapshot
    preflight = PreflightResult(status="READY", snapshot=snapshot, input_hash=input_hash(snapshot))

    async def no_sleep(_seconds):
        return None
    return asyncio.run(generate_unverified(preflight, REQUEST, provider, no_sleep, source_keys=source_keys))


# --- Flag OFF: today's contract, byte for byte ------------------------------------------

def test_flag_defaults_off_and_off_path_is_byte_identical_to_pre_feature_commit(monkeypatch):
    monkeypatch.delenv("GENERATION_SOURCE_KEYS", raising=False)
    monkeypatch.chdir(Path(__file__).parent)  # no .env here: pure default
    assert source_keys_enabled() is False
    prompt = build_prompt(ready().snapshot, REQUEST)
    assert (prompt.prompt_version, prompt.template_hash) == ("phase4d-compact-context/2.0.0", V2_HASH)
    assert PROMPT_VERSION == "phase4d-compact-context/2.0.0" and template_hash() == V2_HASH
    assert prompt.rules == PROVIDER_RULES and '"source_refs"' in prompt.untrusted_data
    assert "source_keys" not in prompt.untrusted_data and "evidence" not in json.loads(
        prompt.untrusted_data.split("\n", 2)[2].rsplit("\n", 1)[0])
    assert sha(prompt.model_dump_json()) == GOLDEN_PROMPT_SHA
    assert build_prompt(ready().snapshot, REQUEST, source_keys=False) == prompt
    monkeypatch.setenv("GENERATION_SOURCE_KEYS", "false")
    assert build_prompt(ready().snapshot, REQUEST) == prompt
    monkeypatch.setenv("GENERATION_SOURCE_KEYS", "")
    assert build_prompt(ready().snapshot, REQUEST) == prompt


def test_flag_off_provider_schema_is_unchanged_uncapped_and_capped(monkeypatch):
    assert current_provider_schema() is PROVIDER_OUTPUT_SCHEMA
    assert current_provider_schema(PROMPT_VERSION) is PROVIDER_OUTPUT_SCHEMA
    assert sha(canonical_json(current_provider_schema(PROMPT_VERSION))) == GOLDEN_SCHEMA_SHA
    assert PROVIDER_OUTPUT_SCHEMA["$defs"]["SourceRef"]["required"] == ["chunk_id", "document_version_id", "locator"]
    for name in ("OBJECTIVES", "TASKS", "CHECKLIST", "QUIZ"):
        monkeypatch.setenv(f"GENERATION_MAX_{name}_PER_MODULE", "1")
    for name in ("KEY_CONCEPTS", "ACTIVITIES", "SCENARIOS", "ASSESSMENTS", "COMPLETION_CRITERIA"):
        monkeypatch.setenv(f"GENERATION_MAX_{name}_PER_MODULE", "0")
    assert sha(canonical_json(current_provider_schema(PROMPT_VERSION))) == GOLDEN_CAPPED_SCHEMA_SHA


def test_flag_off_generation_never_expands_and_keeps_full_source_refs():
    provider = RecordingProvider(json.dumps(complete_output()))
    result = run(provider, source_keys=False)
    assert result.status == "UNVERIFIED" and result.prompt_version == PROMPT_VERSION
    assert result.template_hash == V2_HASH
    ref = result.plan.plan.stages[0].modules[0].source_refs[0]
    assert (ref.document_version_id, ref.chunk_id) == (VERSION, CHUNK)
    # Keys are not accepted on the 2.0.0 path: they are simply schema-invalid there.
    provider = RecordingProvider(*[json.dumps(keyed(complete_output(), ["S1"]))] * 2)
    assert run(provider, source_keys=False).error_code == "SCHEMA_INVALID"


# --- Mapping and prompt (flag ON) -------------------------------------------------------

def test_key_map_is_deterministic_globally_unique_and_derived_from_frozen_snapshot():
    snapshot = multi_document_snapshot()
    keys = source_key_map(snapshot)
    assert keys == source_key_map(multi_document_snapshot())
    assert list(keys) == ["S1", "S2", "S3"]  # shared chunk appears once across documents
    s1, s2, s3 = keys.values()
    assert (s1.document_version_id, s1.chunk_id) == (str(VERSION), str(CHUNK))
    assert s1.locator == canonical_json(snapshot.requirements[0].evidence[0].locator)
    assert s1.requirement_ids == {str(REQ), str(REQ2)}
    assert (s2.document_version_id, s2.chunk_id, s2.requirement_ids) == (str(VERSION2), str(CHUNK2), {str(REQ2)})
    assert s3.requirement_ids == {str(REQ2)} and s3.section == "page 3"
    labels = {item.document_version_id: item.document_label for item in keys.values()}
    assert labels == {str(min(VERSION, VERSION2)): "D1", str(max(VERSION, VERSION2)): "D2"}
    assert s2.section == "Access > MFA"
    assert s2.excerpt == ("Enable multi-factor authentication. " + "x" * 300)[:100]


def test_flag_on_prompt_has_v3_contract_evidence_table_and_no_full_refs():
    snapshot = multi_document_snapshot()
    prompt = build_prompt(snapshot, REQUEST, source_keys=True)
    assert (prompt.prompt_version, prompt.template_hash) == (SOURCE_KEYS_PROMPT_VERSION, V3_HASH)
    assert source_keys_template_hash() == V3_HASH != template_hash()
    assert prompt.rules == SOURCE_KEYS_PROVIDER_RULES and "evidence keys" in prompt.rules
    assert prompt.context_hash == input_hash(snapshot)  # snapshot/input hash contract untouched
    data = json.loads(prompt.untrusted_data.split("\n", 2)[2].rsplit("\n", 1)[0])
    assert data["projection_version"] == "generation-projection/3.0.0"
    assert [req["source_keys"] for req in data["requirements"]] == [["S1"], ["S2", "S1", "S3"]]
    assert all("source_refs" not in req for req in data["requirements"])
    labels = {str(min(VERSION, VERSION2)): "D1", str(max(VERSION, VERSION2)): "D2"}
    assert data["evidence"][1].startswith(f"S2 -> {labels[str(VERSION2)]} | Access > MFA | Enable multi-factor")
    assert str(CHUNK2) not in prompt.untrusted_data and str(VERSION2) not in prompt.untrusted_data
    assert build_prompt(snapshot, REQUEST, source_keys=True) == prompt
    assert prompt.within_budget


# --- Provider schemas (flag ON) ---------------------------------------------------------

def _source_ref_nodes(schema):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict) and "source_refs" in node["properties"]:
                found.append(node["properties"]["source_refs"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(schema)
    return found


def test_flag_on_schema_is_key_array_with_pattern_and_leaves_default_untouched():
    before = canonical_json(PROVIDER_OUTPUT_SCHEMA)
    schema = current_provider_schema(SOURCE_KEYS_PROMPT_VERSION)
    nodes = _source_ref_nodes(schema)
    assert len(nodes) == len(_source_ref_nodes(PROVIDER_OUTPUT_SCHEMA)) > 5
    assert all(node == {"type": "array", "items": {"type": "string", "pattern": "^S[0-9]+$"}, "minItems": 1}
               for node in nodes)
    assert "SourceRef" not in schema["$defs"]
    gemini = current_provider_schema(SOURCE_KEYS_PROMPT_VERSION, key_pattern=False)
    assert all(node == {"type": "array", "items": {"type": "string"}, "minItems": 1}
               for node in _source_ref_nodes(gemini))
    assert '"pattern"' not in json.dumps(gemini)
    assert canonical_json(PROVIDER_OUTPUT_SCHEMA) == before
    # Other constraints are kept: module learning content still requires one item.
    assert schema["$defs"]["Module"]["properties"]["tasks"]["minItems"] == 1


def _capture(handler_body):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=handler_body)
    return bodies, handler


def test_nararouter_and_groq_receive_pattern_but_gemini_does_not(monkeypatch):
    prompt = build_prompt(ready().snapshot, REQUEST, source_keys=True)
    chat = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    nara_bodies, nara = _capture(chat)
    groq_bodies, groq = _capture(chat)
    gem_bodies, gem = _capture({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(nara)) as client:
            config = NaraRouterConfig(provider="nararouter", model="agnes-3-flash",
                                      api_key=SecretStr("placeholder"), base_url="https://nara.invalid/v1")
            await NaraRouterProvider(client, config).generate(prompt)
        async with httpx.AsyncClient(transport=httpx.MockTransport(groq)) as client:
            await GroqProvider(client, ProviderConfig(provider="groq", model="openai/gpt-oss-20b",
                                                      api_key="k")).generate(prompt)
        async with httpx.AsyncClient(transport=httpx.MockTransport(gem)) as client:
            await GeminiProvider(client, ProviderConfig(model="mock-model", api_key="k")).generate(prompt)
    asyncio.run(scenario())
    for body in (nara_bodies[0], groq_bodies[0]):
        nodes = _source_ref_nodes(body["response_format"]["json_schema"]["schema"])
        assert nodes and all(node["items"] == {"type": "string", "pattern": "^S[0-9]+$"}
                             and node["minItems"] == 1 for node in nodes)
    gemini_schema = gem_bodies[0]["generationConfig"]["responseJsonSchema"]
    nodes = _source_ref_nodes(gemini_schema)
    assert nodes and all(node == {"type": "array", "items": {"type": "string"}, "minItems": 1} for node in nodes)
    assert '"pattern"' not in json.dumps(gemini_schema)


# --- Expansion before parse_plan --------------------------------------------------------

def test_single_key_expands_to_exact_frozen_reference_and_plan_matches_full_ref_run():
    keys_run = run(RecordingProvider(json.dumps(keyed(complete_output(), ["S1"]))))
    full_run = run(RecordingProvider(json.dumps(complete_output())), source_keys=False)
    assert keys_run.status == "UNVERIFIED"
    assert (keys_run.prompt_version, keys_run.template_hash) == (SOURCE_KEYS_PROMPT_VERSION, V3_HASH)
    assert keys_run.plan == full_run.plan  # the rest of the app sees today's objects


def test_valid_multi_source_multi_document_expansion():
    snapshot = multi_document_snapshot()
    keys = source_key_map(snapshot)
    output = keyed(complete_output(snapshot), ["S2", "S1", "S3"], [REQ2])
    text = expand_source_keys(json.dumps(output), keys)
    module = json.loads(text)["plan"]["stages"][0]["modules"][0]
    assert module["source_refs"] == [
        {"document_version_id": keys[k].document_version_id, "chunk_id": keys[k].chunk_id,
         "locator": keys[k].locator} for k in ("S2", "S1", "S3")]
    result = run(RecordingProvider(json.dumps(output)), snapshot)
    assert result.status == "UNVERIFIED"
    refs = result.plan.plan.stages[0].modules[0].source_refs
    assert [(ref.document_version_id, ref.chunk_id) for ref in refs] == [
        (VERSION2, CHUNK2), (VERSION, CHUNK), (VERSION2, CHUNK3)]
    # A key shared by two requirements is valid for an item citing either (or both).
    both = keyed(complete_output(snapshot), ["S1"], [REQ, REQ2])
    assert json.loads(expand_source_keys(json.dumps(both), keys))["plan"]["stages"][0]["modules"][0][
        "source_refs"][0]["chunk_id"] == str(CHUNK)


@pytest.mark.parametrize("refs,owners,kind", [
    (["S999"], [REQ], "unknown_source_key"),
    (["S1", "S999"], [REQ], "unknown_source_key"),
    (["s1"], [REQ], "unknown_source_key"),
    ([{"document_version_id": str(VERSION), "chunk_id": str(CHUNK), "locator": "{}"}], [REQ], "unknown_source_key"),
    (["S2"], [REQ], "source_key_wrong_requirement"),      # S2 is evidence only for REQ2
    (["S1", "S3"], [REQ], "source_key_wrong_requirement"),
    (["S1"], [], "source_key_wrong_requirement"),
])
def test_bad_keys_fail_schema_invalid_without_correction(refs, owners, kind):
    snapshot = multi_document_snapshot()
    output = keyed(complete_output(snapshot), refs, owners)
    with pytest.raises(StructuralFailure) as caught:
        expand_source_keys(json.dumps(output), source_key_map(snapshot))
    assert caught.value.code == "SCHEMA_INVALID"
    assert caught.value.diagnostics and all(item["type"] == kind for item in caught.value.diagnostics
                                            if item["type"] == kind)
    assert any(item["type"] == kind for item in caught.value.diagnostics)
    assert len(caught.value.diagnostics) <= 5
    first = caught.value.diagnostics[0]["loc"]
    assert first[:4] == ("plan", "stages", 0, "modules") and "source_refs" in first
    # Sanitized retry feedback names the path and type, never the key text itself.
    feedback = retry_feedback(caught.value)
    assert kind in feedback and "S999" not in feedback and str(VERSION) not in feedback


def test_hallucinated_key_fails_run_after_one_retry_and_is_never_silently_fixed():
    bad = json.dumps(keyed(complete_output(), ["S7"]))
    provider = RecordingProvider(bad, bad)
    result = run(provider)
    assert result.status == "FAILED" and result.error_code == "SCHEMA_INVALID" and result.plan is None
    assert len(provider.prompts) == 2
    assert "unknown_source_key" in provider.prompts[1].rules
    # A retry that fixes the key succeeds normally.
    provider = RecordingProvider(bad, json.dumps(keyed(complete_output(), ["S1"])))
    assert run(provider).status == "UNVERIFIED"


def test_malformed_and_empty_responses_keep_todays_failure_codes():
    keys = source_key_map(ready().snapshot)
    assert expand_source_keys("", keys) == ""
    assert expand_source_keys("{not json", keys) == "{not json"
    for text, code in (("", "EMPTY_RESPONSE"), ("{not json", "MALFORMED_JSON")):
        result = run(RecordingProvider(text, text))
        assert result.error_code == code


# --- Reservation uses build_prompt's metadata --------------------------------------------

class KeyedProvider:
    def __init__(self):
        self.prompts = []

    async def generate(self, prompt, *, format_retry=False):
        self.prompts.append(prompt)
        return ProviderResult(text=json.dumps(keyed(complete_output(), ["S1"])), finish_reason="STOP")


@pytest.mark.parametrize("flag,version,expected_hash", [
    ("true", SOURCE_KEYS_PROMPT_VERSION, V3_HASH), ("false", PROMPT_VERSION, V2_HASH)])
def test_reservation_records_the_prompt_contract_build_prompt_selected(monkeypatch, flag, version, expected_hash):
    from fastapi.testclient import TestClient
    from app import security
    from app.generation_persistence import get_generation_store
    from app.main import app
    monkeypatch.setenv("GENERATION_SOURCE_KEYS", flag)
    store, provider = Store(), KeyedProvider()
    seen = []
    original = generation_api.build_prompt

    def spy(*args, **kwargs):
        seen.append(original(*args, **kwargs))
        return seen[-1]
    monkeypatch.setattr(generation_api, "build_prompt", spy)
    config = ProviderConfig(model="test-model", api_key=SecretStr("test-only-placeholder"))
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_generation_store] = lambda: store
    monkeypatch.setattr(generation_api, "get_provider_bundle", lambda request: (provider, config))
    try:
        with TestClient(app) as client:
            client.post("/api/v1/generation-runs", json={"employee_id": str(ready().snapshot.employee.employee_id)},
                        headers={"Idempotency-Key": "source-keys-123"})
    finally:
        app.dependency_overrides.clear()
    reserve = next(payload for name, payload in store.calls if name == "reserve")
    assert (reserve["p_prompt_version"], reserve["p_template_hash"]) == (version, expected_hash)
    assert (reserve["p_prompt_version"], reserve["p_template_hash"]) == (seen[0].prompt_version,
                                                                         seen[0].template_hash)
    assert provider.prompts[0].prompt_version == version
    if flag == "true":
        plan = store.last_finish[1]
        assert store.status == "UNVERIFIED" and plan is not None
        # Persistence receives today's full reference object, never a key.
        assert plan["plan"]["stages"][0]["modules"][0]["source_refs"][0] == {
            "document_version_id": str(VERSION), "chunk_id": str(CHUNK),
            "locator": canonical_json(ready().snapshot.requirements[0].evidence[0].locator)}
    else:
        assert store.last_finish[3] == "SCHEMA_INVALID"  # keys are never accepted on 2.0.0


# --- Migration contract ---------------------------------------------------------------

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def _body(text):
    marker = "create or replace function"
    return text[text.index(marker):text.index("end $$;", text.index(marker))]


def test_v3_migration_changes_only_the_prompt_pin_and_adds_projection_check():
    previous = (MIGRATIONS / "202609280005_generation_timeout_290.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "202609280006_source_keys_prompt_v3.sql").read_text(encoding="utf-8")
    pin = re.search(r"     -- Exactly one of two.*?, false\)\n", new, re.S)
    assert pin
    old_pin = ("     or p_prompt_version is distinct from 'phase4d-compact-context/2.0.0'\n"
               f"     or p_template_hash is distinct from '{V2_HASH}'\n")
    assert _body(new).replace(pin.group(0), old_pin) == _body(previous)
    assert "not between 1 and 290" in new
    assert ("add constraint generation_runs_compact_v3_projection_check\n  check (prompt_version <> "
            "'phase4d-compact-context/3.0.0' or projection_hash is not null);") in new
    assert "\nbegin;" in new and new.rstrip().endswith("commit;") and new.count("end $$;") == 1
    assert new.lower().count("alter table") == 1
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", new)
    assert "security definer set search_path = ''" in new


def _pin_accepts(sql, version, hash_):
    """Evaluate the migration's pin predicate for one (version, hash) with SQL NULL semantics."""
    pin = re.search(r"or not coalesce\((.*?), false\)", sql, re.S).group(1)
    pairs = re.findall(r"\(p_prompt_version = '([^']+)'\s+and p_template_hash = '([0-9a-f]{64})'\)", pin)
    assert len(pairs) == 2 and re.sub(r"\s+", " ", pin).count(" or ") == 1
    if version is None or hash_ is None:
        # (NULL = x and ...) or (...) is NULL or false; coalesce(..., false) -> reject.
        return False
    return (version, hash_) in pairs


def test_v3_migration_accepts_exactly_the_two_reviewed_pairs():
    sql = (MIGRATIONS / "202609280006_source_keys_prompt_v3.sql").read_text(encoding="utf-8")
    assert _pin_accepts(sql, PROMPT_VERSION, template_hash())
    assert _pin_accepts(sql, SOURCE_KEYS_PROMPT_VERSION, source_keys_template_hash())
    assert not _pin_accepts(sql, PROMPT_VERSION, source_keys_template_hash())
    assert not _pin_accepts(sql, SOURCE_KEYS_PROMPT_VERSION, template_hash())
    assert not _pin_accepts(sql, None, template_hash())
    assert not _pin_accepts(sql, SOURCE_KEYS_PROMPT_VERSION, None)
    assert not _pin_accepts(sql, "phase4d-compact-context/4.0.0", source_keys_template_hash())
