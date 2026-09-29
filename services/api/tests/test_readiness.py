"""Pre-live remediation: current content-only contract (4.0.1), safe structural diagnostics,
retry reachability and the zero-provider readiness gate. Offline; no provider, no database."""

import asyncio
import copy
import json
import logging
import re
import socket
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app import generation_readiness as gate
from app.generation_content import (CONTENT_V400, CONTENT_V401, CONTENT_V410, CURRENT_CONTENT_VERSION, ContentResponse,
                                    RequirementContent, RequirementContentV400, assemble_plan, requirement_keys)
from app.generation_context import input_hash
from app.generation_models import GenerationInputSnapshot, PreflightResult
from app.generation_output import OnboardingPlan
from app.generation_prompt import (PROMPT_VERSION, SOURCE_KEYS_V31_PROMPT_VERSION, build_prompt,
                                   content_template_hash, selected_prompt_version)
from app.generation_provider import GeminiProvider, GroqProvider, ProviderResult
from app.generation_service import (RUN_BUDGET_SECONDS, StructuralFailure, assemble_content, generate_unverified,
                                    parse_plan, structural_retry_window)
from app.nararouter_provider import NaraRouterProvider
from test_contract_v31 import COMPACT_CAPS

FIXTURES = Path(__file__).parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
SNAPSHOT_FILE = FIXTURES / "phase4d_v31_frozen_snapshot_redacted.json"
# 4.0.1 contract tests keep the 4.0.1 fixture; live-path/gate tests use the current 4.1.0 fixture.
MODEL_FIXTURE = FIXTURES / "phase4d_v401_model_content_response.json"
CURRENT_FIXTURE = FIXTURES / "phase4d_v410_model_content_response.json"
EMPLOYEE = "aa02c897-14d8-4c3c-994a-c707550677ad"
RUN = UUID("aaccc0b5-e109-432e-88ae-805acd35d96a")
V400_HASH = "d0f338ed27b47e91207d3346fad2b0055f955960b258874804e9b17db8503b43"
V401_HASH = "83c231d9c9647da559d57e6ece4680ef8f8902c6e38c1e484ae59888eb91b00a"
V410_HASH = "f4edf5d50196fe8d4635a95cef1164bbd85215f31f90f58aa08390fed8c6d5fa"
V411_HASH = "aba61f714140480ebcaee45f0d779c78f7165b51e487aecc902a97babd727d15"
# The live contract; bump here when the current version changes.
CURRENT, CURRENT_HASH = "phase4d-content-only/4.1.1", V411_HASH
READY = "READY_FOR_ONE_CONTROLLED_LIVE_GENERATION"
CANARY = "CANARY_POLICY_TEXT_do_not_log"


@pytest.fixture(autouse=True)
def compact_caps(monkeypatch):
    for name, value in COMPACT_CAPS.items():
        monkeypatch.setenv(name, value)


def snapshot():
    return GenerationInputSnapshot.model_validate(json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8")))


def model_fixture():
    return json.loads(MODEL_FIXTURE.read_text(encoding="utf-8"))


def current_fixture():
    return json.loads(CURRENT_FIXTURE.read_text(encoding="utf-8"))


def assembled(content=None, frozen=None, request_id=RUN):
    return assemble_plan(ContentResponse.model_validate_json(json.dumps(content or model_fixture())),
                         frozen or snapshot(), request_id)


def modules(plan):
    return [m for stage in plan["plan"]["stages"] for m in stage["modules"]]


# --- 3. content contract review ------------------------------------------------------------------

def test_401_content_bounds_equal_the_final_contract_except_intentional_ones():
    item = RequirementContent.model_json_schema()["properties"]
    final = OnboardingPlan.model_json_schema()["$defs"]
    assert (item["estimated_minutes"]["minimum"], item["estimated_minutes"]["maximum"]) == (
        final["Module"]["properties"]["estimated_minutes"]["minimum"],
        final["Module"]["properties"]["estimated_minutes"]["maximum"])
    assert item["task_completion_criteria"]["maxItems"] == final["Task"]["properties"]["completion_criteria"]["maxItems"]
    # Intentional content-generation bounds: exactly 3 options (index mapping), distinct options.
    assert (item["quiz_options"]["minItems"], item["quiz_options"]["maxItems"]) == (3, 3)
    old = RequirementContentV400.model_json_schema()["properties"]  # 4.0.0 is frozen as it was
    assert (old["estimated_minutes"]["minimum"], old["estimated_minutes"]["maximum"]) == (5, 480)
    assert old["task_completion_criteria"]["maxItems"] == 3


def test_401_accepts_valid_final_plans_that_400_wrongly_rejected():
    data = model_fixture()  # R2: 600 minutes and 5 completion criteria, both valid final-plan values
    ContentResponse.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError):
        from app.generation_content import ContentResponseV400
        ContentResponseV400.model_validate_json(json.dumps(data))
    plan = OnboardingPlan.model_validate_json(json.dumps(assembled()))
    assert any(m.estimated_minutes == 600 and len(m.tasks[0].completion_criteria) == 5
               for stage in plan.plan.stages for m in stage.modules)


def test_hashes_all_versions_are_distinct_and_historical_ones_unchanged():
    assert content_template_hash(CONTENT_V400) == V400_HASH
    assert content_template_hash(CONTENT_V401) == V401_HASH
    assert content_template_hash(CONTENT_V410) == V410_HASH
    assert content_template_hash(CURRENT) == CURRENT_HASH
    assert CURRENT_CONTENT_VERSION == CURRENT == "phase4d-content-only/4.1.1"


# --- 7. structure the model cannot control -------------------------------------------------------

def test_real_snapshot_request_is_current_content_only(monkeypatch):
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "true")
    prompt = build_prompt(snapshot(), RUN)
    assert (prompt.prompt_version, prompt.template_hash) == (CURRENT, CURRENT_HASH)
    assert list(prompt.response_schema["properties"]["requirements"]["properties"]) == [f"R{i}" for i in range(1, 7)]
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", prompt.untrusted_data)


def test_empty_orientation_stage_is_kept_in_the_final_plan():
    frozen = snapshot()
    plan = assembled()
    assert [s["stage_id"] for s in plan["plan"]["stages"]] == [str(s.stage_definition_id) for s in frozen.stage_set.items]
    assert plan["plan"]["stages"][0]["label"] == "Orientation" and plan["plan"]["stages"][0]["modules"] == []
    parse_plan(json.dumps(plan), RUN, frozen)  # the stage contract holds by construction


@pytest.mark.parametrize("field", ["stages", "module_id", "requirement_ids", "source_refs", "prerequisite_module_ids",
                                   "due_stage_id", "mandatory", "priority", "generation_request_id"])
def test_model_cannot_supply_backend_owned_fields(field):
    data = model_fixture()
    target = data if field in ("stages", "generation_request_id") else data["requirements"]["R1"]
    target[field] = "anything"
    with pytest.raises(StructuralFailure) as caught:
        assemble_content(json.dumps(data), snapshot(), RUN, CONTENT_V401)
    assert caught.value.code == "SCHEMA_INVALID"
    assert caught.value.detail["errors"][0]["type"] == "extra_forbidden"  # rejected for the field itself


def test_requirement_mapping_sources_ids_and_dependencies_ignore_model_content():
    frozen = snapshot()
    data = model_fixture()
    swapped = copy.deepcopy(data)
    swapped["requirements"]["R1"], swapped["requirements"]["R2"] = data["requirements"]["R2"], data["requirements"]["R1"]
    a, b = assembled(data), assembled(swapped)
    mechanical = lambda plan: [(m["module_id"], m["requirement_ids"], m["source_refs"], m["prerequisite_module_ids"],
                                m["quizzes"][0]["quiz_id"], [o["option_id"] for o in m["quizzes"][0]["options"]])
                               for m in modules(plan)]
    assert mechanical(a) == mechanical(b)  # only prose moved; every mechanical value is identical
    assert [m["title"] for m in modules(a)] != [m["title"] for m in modules(b)]
    by_req = {str(r.revision_id): r for r in frozen.requirements}
    for module in modules(a):
        req = by_req[module["requirement_ids"][0]]
        assert len(module["source_refs"]) == len({(e.document_version_id, e.chunk_id) for e in req.evidence})


def test_generated_ids_come_only_from_run_and_requirement():
    ids = lambda plan: re.findall(r'"(?:module|objective|checklist_item|task|quiz|option)_id": "([^"]+)"', json.dumps(plan))
    data = model_fixture()
    changed = copy.deepcopy(data)
    for item in changed["requirements"].values():
        item["module_title"] += " (edited)"
    assert ids(assembled(data)) == ids(assembled(changed))
    assert not set(ids(assembled(data))) & set(ids(assembled(data, request_id=UUID(int=7))))


# --- 7. flag precedence and version drift ------------------------------------------------------

@pytest.mark.parametrize("content_only,source_keys,expected", [
    ("true", "false", CURRENT), ("true", "true", CURRENT), ("false", "true", SOURCE_KEYS_V31_PROMPT_VERSION),
    ("false", "false", PROMPT_VERSION), ("", "true", SOURCE_KEYS_V31_PROMPT_VERSION)])
def test_runtime_flag_precedence(monkeypatch, content_only, source_keys, expected):
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", content_only)
    monkeypatch.setenv("GENERATION_SOURCE_KEYS", source_keys)
    assert selected_prompt_version() == expected == build_prompt(snapshot()).prompt_version


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GENERATION_CONTENT_ONLY=false\nGENERATION_SOURCE_KEYS=true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GENERATION_CONTENT_ONLY", raising=False)
    monkeypatch.delenv("GENERATION_SOURCE_KEYS", raising=False)
    assert selected_prompt_version() == SOURCE_KEYS_V31_PROMPT_VERSION      # .env value
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "true")
    assert selected_prompt_version() == CURRENT                         # process env wins


def test_reservation_and_execution_versions_cannot_drift(monkeypatch):
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "true")
    frozen = snapshot()
    reserved = build_prompt(frozen)
    monkeypatch.setenv("GENERATION_CONTENT_ONLY", "false")  # flag flips between reservation and execution

    class Provider:
        prompts = []

        async def generate(self, prompt, *, format_retry=False):
            self.prompts.append(prompt)
            return ProviderResult(text=CURRENT_FIXTURE.read_text(encoding="utf-8"), finish_reason="STOP")

    async def no_sleep(_s):
        return None
    provider = Provider()
    result = asyncio.run(generate_unverified(PreflightResult(status="READY", snapshot=frozen,
                                                             input_hash=input_hash(frozen)), RUN, provider, no_sleep,
                                             prompt_version=reserved.prompt_version))
    assert result.status == "UNVERIFIED"
    assert (provider.prompts[0].prompt_version, provider.prompts[0].template_hash) == (
        reserved.prompt_version, reserved.template_hash) == (CURRENT, CURRENT_HASH)


# --- 2/7. structured, content-free diagnostics -----------------------------------------------------

def _plan_json(mutate=None):
    plan = json.loads(json.dumps(assembled()))  # independent nodes, like a parsed provider response
    if mutate:
        mutate(plan)
    return json.dumps(plan)


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("mutate,code,expected", [
    (lambda p: p.update(generation_request_id=str(UUID(int=9))), "REQUEST_ID_MISMATCH",
     ['"path": "generation_request_id"', '"reason": "request_id_differs"']),
    (lambda p: p["employee_context"].update(location_code="ZZZ", joining_date="2001-01-01"), "CONTEXT_IDENTITY_MISMATCH",
     ['"fields": ["location_code", "joining_date"]']),
    (lambda p: p["plan"]["stages"].pop(0), "STAGE_CONTRACT_MISMATCH",
     ['"expected_count": 5', '"actual_count": 4', '"missing_expected_indexes": [0]']),
    (lambda p: p["plan"]["stages"][1].update(label=CANARY, sequence=9), "STAGE_CONTRACT_MISMATCH",
     ['"index": 1', '"label"', "sequence:expected=2,actual=9"]),
    (lambda p: p["plan"]["stages"].reverse(), "STAGE_CONTRACT_MISMATCH", ['stage_id:other_frozen_stage']),
    (lambda p: modules(p)[0]["tasks"][0].update(requirement_ids=[str(UUID(int=3))]), "UNKNOWN_REQUIREMENT_REF",
     ['"path": "plan.stages.1.modules.0.tasks.0.requirement_ids.0"', "not_in_frozen_requirements"]),
    (lambda p: modules(p)[0]["quizzes"][0]["source_refs"][0].update(locator=json.dumps({"canary": CANARY})),
     "UNKNOWN_SOURCE_REF", ['"path": "plan.stages.1.modules.0.quizzes.0.source_refs.0"', "locator_differs"]),
    (lambda p: modules(p)[0]["checklist_items"][0].update(due_stage_id=str(UUID(int=4))), "UNKNOWN_STAGE_REF",
     ['"path": "plan.stages.1.modules.0.checklist_items.0.due_stage_id"', "not_a_frozen_stage"]),
])
def test_structural_failures_log_safe_structured_diagnostics(caplog, mutate, code, expected):
    frozen = snapshot()
    with pytest.raises(StructuralFailure) as caught:
        parse_plan(_plan_json(mutate), RUN, frozen)
    assert caught.value.code == code
    line = next(m for m in _warnings(caplog) if m.startswith("generation_structural_failure"))
    assert f"run_id={RUN} code={code}" in line
    for fragment in expected:
        assert fragment in line
    for secret in (CANARY, "ZZZ", "2001-01-01", "Orientation", "Policies"):
        assert secret not in line  # no model text, labels or employee values


def test_assembly_input_errors_are_logged_and_coded(caplog):
    frozen = snapshot()
    bad = frozen.model_copy(update={"requirements": (frozen.requirements[0].model_copy(update={"evidence": ()}),
                                                     *frozen.requirements[1:])})
    with pytest.raises(StructuralFailure) as caught:
        assemble_content(json.dumps(model_fixture()), bad, RUN, CONTENT_V401)
    assert caught.value.code == "ASSEMBLY_INPUT_INVALID"
    assert any("code=ASSEMBLY_INPUT_INVALID" in m and "source_refs_out_of_bounds" in m for m in _warnings(caplog))


def test_content_and_pydantic_diagnostics_never_leak_model_or_document_text(caplog):
    frozen = snapshot()
    data = model_fixture()
    data["requirements"]["R1"]["objective"] = "   "
    data["requirements"]["R2"]["quiz_options"] = [CANARY, CANARY.upper(), "x"]
    data["requirements"]["R99"] = data["requirements"]["R3"]
    for text in (json.dumps(data), json.dumps({**model_fixture(), "notes": CANARY}), CANARY + "{"):
        with pytest.raises(StructuralFailure):
            assemble_content(text, frozen, RUN, CONTENT_V401)
    logged = "\n".join(_warnings(caplog))
    assert "generation_schema_invalid" in logged
    for secret in (CANARY, CANARY.upper(), *[e.excerpt[:25] for r in frozen.requirements for e in r.evidence]):
        assert secret not in logged


# --- 4. retry reachability (documented, unchanged) -------------------------------------------------

@pytest.mark.parametrize("first_call_seconds,expected_calls", [(4.0, 2), (5.0, 2), (5.5, 1), (74.0, 1)])
def test_structural_retry_is_reachable_only_within_the_budget_window(monkeypatch, first_call_seconds, expected_calls):
    import app.generation_service as service
    assert structural_retry_window(290) == RUN_BUDGET_SECONDS - 290 == 5.0
    clock = {"now": 0.0}
    monkeypatch.setattr(service, "perf_counter", lambda: clock["now"])

    class Config:
        timeout_seconds = 290

    class Slow:
        config = Config()
        calls = 0

        async def generate(self, prompt, *, format_retry=False):
            Slow.calls += 1
            clock["now"] += first_call_seconds
            return ProviderResult(text="{not json", finish_reason="STOP")

    async def no_sleep(_s):
        return None
    frozen = snapshot()
    result = asyncio.run(generate_unverified(PreflightResult(status="READY", snapshot=frozen,
                                                             input_hash=input_hash(frozen)), RUN, Slow(), no_sleep,
                                             prompt_version=CONTENT_V401))
    assert result.error_code == "MALFORMED_JSON" and Slow.calls == expected_calls


# --- 5/6. readiness gate -----------------------------------------------------------------------------

def db_result(tmp_path, **overrides):
    data = {"checked_prompt_version": CURRENT, "checked_template_hash": CURRENT_HASH, "checked_provider": "nararouter",
            "checked_model": "agnes-2.5-flash", "pair_accepted": True, "model_accepted": True,
            "max_timeout_seconds": 290, "max_output_tokens_upper": 65536, "projection_constraint_present": True,
            "diagnostics_table_present": True, "diagnostics_rpc_present": True,
            "diagnostics_rpc_executable": True, "postgrest_schema_reload_trigger_present": True, **overrides}
    path = tmp_path / "db.json"
    path.write_text(json.dumps([{"readiness": data}]), encoding="utf-8")
    return path


@pytest.fixture
def backend_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GENERATION_DIAGNOSTICS_FILE", str(tmp_path / "diag" / "generation_diagnostics.jsonl"))
    """A backend directory with a .env like the real one (placeholder key, no secrets)."""
    directory = tmp_path / "backend"
    directory.mkdir()
    (directory / ".env").write_text("\n".join([
        "AI_PROVIDER=nararouter", "NARAROUTER_API_KEY=placeholder-not-a-secret",
        "NARAROUTER_BASE_URL=https://nararouter.invalid/v1", "NARAROUTER_MODEL=agnes-2.5-flash",
        "NARAROUTER_TIMEOUT_SECONDS=290", "NARAROUTER_MAX_OUTPUT_TOKENS=32768", "NARAROUTER_TEMPERATURE=0.1",
        "GENERATION_SOURCE_KEYS=true", "GENERATION_CONTENT_ONLY=true", ""]), encoding="utf-8")
    for name in ("AI_PROVIDER", "NARAROUTER_API_KEY", "NARAROUTER_BASE_URL", "NARAROUTER_MODEL",
                 "NARAROUTER_TIMEOUT_SECONDS", "NARAROUTER_MAX_OUTPUT_TOKENS", "NARAROUTER_TEMPERATURE",
                 "NARAROUTER_REASONING_EFFORT", "NARAROUTER_CONTENT_REASONING_EFFORT",
                 "GENERATION_CONTENT_ONLY", "GENERATION_SOURCE_KEYS"):
        monkeypatch.delenv(name, raising=False)
    return directory


@pytest.fixture
def no_network(monkeypatch):
    """Any provider call or socket use fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("network or provider used during readiness")
    for provider in (NaraRouterProvider, GroqProvider, GeminiProvider):
        monkeypatch.setattr(provider, "generate", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    # DNS and outbound connections; asyncio's local self-pipe (socketpair) stays usable.
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_gate_passes_the_real_snapshot_with_db_verification(backend_env, tmp_path, no_network):
    result = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), str(db_result(tmp_path)), backend_dir=str(backend_env))
    assert result.final_line == READY, result.final_line
    facts = result.facts
    frozen = snapshot()
    assert (facts["requirements"], facts["stages"], facts["dependencies"]) == (
        len(frozen.requirements), len(frozen.stage_set.items), len(frozen.dependencies)) == (6, 5, 8)
    assert (facts["prompt_version"], facts["template_hash"]) == (CURRENT, CURRENT_HASH)
    assert facts["decision"] == "VERIFIED_WITH_WARNING" and facts["findings"] == 6
    assert facts["schema_depth"] == 3 and facts["request_bytes"] < 24_576
    text = "\n".join(result.lines)
    assert "empty (no requirements): Orientation" in text and "placeholder-not-a-secret" not in text
    assert any("retry" in warning for warning in result.warnings)


def test_gate_requires_db_verification_and_never_assumes_it(backend_env, no_network):
    result = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), backend_dir=str(backend_env))
    assert result.status == "DB_VERIFICATION_REQUIRED" and result.final_line == "DB_VERIFICATION_REQUIRED"
    assert CURRENT_HASH in result.db_sql and "generation_runs_content_v411_projection_check" in result.db_sql
    assert "pg_get_functiondef" in result.db_sql and not re.search(r"(?i)\b(insert|update|delete|alter)\b",
                                                                    result.db_sql)


@pytest.mark.parametrize("override,reason", [
    ({"pair_accepted": False}, "pair_accepted"), ({"projection_constraint_present": False}, "projection constraint"),
    ({"checked_template_hash": V401_HASH}, "checked_template_hash"), ({"max_timeout_seconds": 180}, "timeout bound"),
    ({"model_accepted": False}, "model_accepted"), ({"diagnostics_rpc_present": False}, "diagnostics rpc"),
    ({"diagnostics_table_present": False}, "diagnostics table"),
    ({"diagnostics_rpc_executable": False}, "diagnostics rpc executable")])
def test_gate_blocks_when_the_database_does_not_accept_the_contract(backend_env, tmp_path, no_network, override, reason):
    result = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), str(db_result(tmp_path, **override)),
                           backend_dir=str(backend_env))
    assert result.final_line.startswith("BLOCKED: D. database") and reason in result.final_line


@pytest.mark.parametrize("env_line,expected", [
    ("GENERATION_CONTENT_ONLY=false", SOURCE_KEYS_V31_PROMPT_VERSION), ("GENERATION_CONTENT_ONLY=", SOURCE_KEYS_V31_PROMPT_VERSION)])
def test_gate_refuses_a_non_current_prompt_version(backend_env, tmp_path, no_network, env_line, expected):
    env = backend_env / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("GENERATION_CONTENT_ONLY=true", env_line), encoding="utf-8")
    result = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), str(db_result(tmp_path)), backend_dir=str(backend_env))
    assert result.final_line.startswith("BLOCKED: A. runtime configuration")
    assert expected in result.final_line and CURRENT in result.final_line


def test_gate_blocks_wrong_employee_missing_config_and_bad_fixture(backend_env, tmp_path, no_network):
    wrong = gate.run_gate("00000000-0000-0000-0000-000000000001", str(SNAPSHOT_FILE), backend_dir=str(backend_env))
    assert wrong.final_line.startswith("BLOCKED: B. snapshot")
    fixture = tmp_path / "fixture.json"
    data = current_fixture()
    data["requirements"].pop("R6")
    fixture.write_text(json.dumps(data), encoding="utf-8")
    mismatched = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), fixture=str(fixture), backend_dir=str(backend_env))
    assert mismatched.final_line.startswith("BLOCKED: F. fixture")
    env = backend_env / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace("NARAROUTER_API_KEY=placeholder-not-a-secret\n", ""),
                   encoding="utf-8")
    missing = gate.run_gate(EMPLOYEE, str(SNAPSHOT_FILE), backend_dir=str(backend_env))
    assert missing.final_line.startswith("BLOCKED: A. runtime configuration") and "NARAROUTER_API_KEY" in missing.final_line


def test_gate_without_snapshot_needs_an_operator_token(backend_env, no_network, monkeypatch):
    monkeypatch.delenv("SKILLSPRINT_ACCESS_TOKEN", raising=False)
    result = gate.run_gate(EMPLOYEE, None, backend_dir=str(backend_env))
    assert result.final_line.startswith("BLOCKED: B. snapshot") and "SKILLSPRINT_ACCESS_TOKEN" in result.final_line


def test_gate_adversarial_fixtures_fail_at_the_expected_boundary():
    frozen = snapshot()
    variants = gate.adversarial_variants(current_fixture())
    assert len(variants) >= 20
    for name, text, expected in variants:
        with pytest.raises(StructuralFailure) as caught:
            assemble_content(text, frozen, RUN, CONTENT_V410)
        assert caught.value.code == expected, name


def test_gate_cli_prints_a_single_final_status_and_exit_code(backend_env, tmp_path, no_network, capsys):
    code = gate.main(["--employee", EMPLOYEE, "--snapshot", str(SNAPSHOT_FILE),
                      "--db-verification", str(db_result(tmp_path)), "--backend-dir", str(backend_env)])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and out[-1] == READY
    code = gate.main(["--employee", EMPLOYEE, "--snapshot", str(SNAPSHOT_FILE), "--backend-dir", str(backend_env)])
    assert code == 2 and capsys.readouterr().out.strip().splitlines()[-1] == "DB_VERIFICATION_REQUIRED"


def test_db_sql_regexes_match_the_migration_function_text():
    """The SQL runs only in Supabase; its patterns are checked here against the migration source."""
    body = (MIGRATIONS / "202609280009_content_only_prompt_v401.sql").read_text(encoding="utf-8")
    sql = gate.db_verification_sql(CONTENT_V401, V401_HASH, "nararouter", "agnes-2.5-flash")
    pair = re.search(r"d ~ '(.*?)',\n", sql).group(1).replace("''", "'")
    assert re.search(pair, body)
    timeout = re.search(r"regexp_match\(d, '(timeout.*?)'\)\)", sql).group(1).replace("''", "'")
    assert re.search(timeout, body).group(1) == "290"
    tokens = re.search(r"regexp_match\(d, '(max_output.*?)'\)\)", sql).group(1).replace("''", "'")
    assert re.search(tokens, body).group(1) == "65536"
    assert "'agnes-2.5-flash'" in body and "generation_runs_content_v401_projection_check" in body
    older = (MIGRATIONS / "202609280008_content_only_prompt_v4.sql").read_text(encoding="utf-8")
    assert not re.search(pair, older)  # before 0009 the 4.0.1 pair is not accepted


# --- 8. migration 0009 -------------------------------------------------------------------------------

def test_401_migration_adds_exactly_one_pair_and_keeps_bounds():
    def body(text):
        marker = "create or replace function"
        return text[text.index(marker):text.index("end $$;", text.index(marker))]
    previous = (MIGRATIONS / "202609280008_content_only_prompt_v4.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "202609280009_content_only_prompt_v401.sql").read_text(encoding="utf-8")
    added = ("\n          or (p_prompt_version = 'phase4d-content-only/4.0.1'\n"
             f"           and p_template_hash = '{V401_HASH}')")
    assert body(new).replace(added, "").replace("one of five reviewed", "one of four reviewed") == body(previous)
    assert "not between 1 and 290" in new and "not between 256 and 65536" in new
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", new)
    pin = re.search(r"or not coalesce\((.*?), false\)", new, re.S).group(1)
    pairs = set(re.findall(r"\(p_prompt_version = '([^']+)'\s+and p_template_hash = '([0-9a-f]{64})'\)", pin))
    assert (CONTENT_V401, V401_HASH) in pairs and (CONTENT_V400, V400_HASH) in pairs and len(pairs) == 5
    versions, hashes = zip(*pairs)
    assert all(((v, h) in pairs) is (versions.index(v) == hashes.index(h)) for v in versions for h in hashes)
