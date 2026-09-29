"""Zero-provider readiness gate: prove locally that a live generation cannot fail
deterministically before any paid provider request is made.

    python -m app.generation_readiness --employee <id> [--snapshot <path>]
        [--db-verification <path>] [--fixture <path>] [--input-hash <hex>] [--backend-dir <dir>]

Run from services/api (or anywhere with services/api on PYTHONPATH). Settings are resolved
exactly like the backend: the same settings classes, reading `.env` from the backend's
working directory (--backend-dir, else the current directory if it has a .env, else the
repository root), with process environment variables taking precedence.

It never calls a provider: provider adapters are only used to *build* the request bytes.
The pipeline step uses an in-process stand-in that returns the supplied fixture text.
Without --snapshot it performs a read-only preflight against Supabase using the operator's
own access token (SKILLSPRINT_ACCESS_TOKEN); it never writes to the database.

Final line and exit code: READY_FOR_ONE_CONTROLLED_LIVE_GENERATION (0), DB_VERIFICATION_REQUIRED (2) or
BLOCKED: <step> — <reason> (1).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from dotenv import dotenv_values

from .generation_content import (CONTENT_PROMPT_VERSIONS, CONTENT_RESPONSE_MODELS, CONTENT_V400, CONTENT_V401,
                                 CONTENT_V410, CONTENT_V411, CONTENT_V412, CURRENT_CONTENT_VERSION, MINIMAL_CONTENT_VERSIONS,
                                 module_layout, requirement_keys, source_refs)
from .generation_context import input_hash
from .generation_models import GenerationInputSnapshot, PreflightResult
from .generation_output import OnboardingPlan
from .generation_prompt import (MAX_PROVIDER_REQUEST_BYTES, SCHEMA_VERSION, GenerationLimits, SourceKeySettings,
                                _compact_schema, _strict_schema, build_prompt, content_response_schema,
                                content_template_hash, provider_schema_for, selected_prompt_version)
from .generation_provider import (GeminiEnvironment, GroqEnvironment, ProviderFailure, ProviderResult,
                                  groq_request_payload, json_schema_response_format)
from .generation_service import assemble_content, generate_unverified, structural_retry_window
from .generation_runtime import resolve_provider_config, validate_generation_target
from .jev import decide
from .deepseek_provider import DeepSeekEnvironment, deepseek_request_payload
from .nararouter_provider import NaraRouterEnvironment, nararouter_request_payload
from .plan_validator import has_cycle, validate_plan
from .rrm_models import EmployeeContext
from .rrm_rules import applicability, snapshot_hash

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "phase4d_v410_model_content_response.json"
# Deterministic dry-run request id; never reserved in the database.
DRY_RUN_ID = uuid5(NAMESPACE_URL, "skillsprint-ai/generation-readiness/dry-run")
PROJECTION_CONSTRAINTS = {CONTENT_V412: "generation_runs_content_v412_projection_check",
                         CONTENT_V411: "generation_runs_content_v411_projection_check",
                          CONTENT_V410: "generation_runs_content_v410_projection_check",
                          CONTENT_V400: "generation_runs_content_v4_projection_check",
                          CONTENT_V401: "generation_runs_content_v401_projection_check"}
ALLOWED_INPUT_WARNINGS = {("TIMING_UNRESOLVED", "WARNING", "input.timing")}
FINISH_MAX_PLAN_BYTES = 4_194_304
CANARY = "CANARY_READINESS_TEXT_7f3a"
# Backend-owned concepts the content-only model must never be asked to produce.
_DELEGATED = re.compile(r"(^id$|_id$|_ids$|source|stage|requirement_id|mandatory|priority|employee|"
                        r"schema_version|prerequisite|generation_request|locator|chunk|document)")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class Blocked(Exception):
    def __init__(self, step: str, reason: str):
        super().__init__(f"{step} — {reason}")
        self.step, self.reason = step, reason


@dataclass
class GateResult:
    status: str                      # READY_FOR_ONE_CONTROLLED_LIVE_GENERATION | DB_VERIFICATION_REQUIRED | BLOCKED
    final_line: str
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    db_sql: str | None = None


class _Report:
    def __init__(self):
        self.lines: list[str] = []
        self.warnings: list[str] = []
        self.facts: dict = {}

    def section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(title)

    def item(self, key: str, value: object) -> None:
        self.lines.append(f"  {key}: {value}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        self.lines.append(f"  WARNING: {message}")


# --------------------------------------------------------------------------- A. configuration

def _source(name: str, env_file: dict) -> str:
    if any(key.upper() == name for key in os.environ):
        return "process environment"
    value = next((value for key, value in env_file.items() if key.upper() == name), None)
    if value is None:
        return "default"
    return ".env" if str(value).strip() else ".env (blank, so default)"


def _provider_config(provider: str):
    try:
        return resolve_provider_config(provider)
    except ProviderFailure:
        return None


def check_configuration(report: _Report, backend_dir: Path) -> dict:
    report.section("A. Runtime configuration (same settings classes as the backend)")
    env_path = backend_dir / ".env"
    if not env_path.exists():
        raise Blocked("A. runtime configuration",
                      f".env not found in {backend_dir}; the backend reads .env from its working directory")
    env_file = dotenv_values(env_path)
    report.item(".env used", env_path)
    flags = SourceKeySettings()
    for name, value in (("GENERATION_CONTENT_ONLY", flags.generation_content_only),
                        ("GENERATION_SOURCE_KEYS", flags.generation_source_keys)):
        report.item(name, f"{value}  [{_source(name, env_file)}]")
    version = selected_prompt_version()
    report.item("selected prompt version", version)
    report.facts["prompt_version"] = version
    provider = GeminiEnvironment().ai_provider
    report.item("AI_PROVIDER", f"{provider}  [{_source('AI_PROVIDER', env_file)}]")
    config = _provider_config(provider)
    if config is None:
        prefix = {"deepseek": "DEEPSEEK_", "nararouter": "NARAROUTER_", "groq": "GROQ_", "gemini": "GEMINI_"}.get(provider, "")
        missing = [name for name in (prefix + "API_KEY", prefix + "MODEL", prefix + "BASE_URL")
                   if prefix and name != "GEMINI_BASE_URL" and name != "GROQ_BASE_URL"
                   and not (os.environ.get(name) or env_file.get(name))]
        raise Blocked("A. runtime configuration",
                      f"provider '{provider}' is not fully configured (missing or invalid: {', '.join(missing) or 'values'})")
    prefix = {"deepseek": "DEEPSEEK_", "nararouter": "NARAROUTER_", "groq": "GROQ_", "gemini": "GEMINI_"}[provider]
    report.item("model", f"{config.model}  [{_source(prefix + 'MODEL', env_file)}]")
    report.item("timeout_seconds", f"{config.timeout_seconds}  [{_source(prefix + 'TIMEOUT_SECONDS', env_file)}]")
    report.item("max_output_tokens", f"{config.max_output_tokens}  [{_source(prefix + 'MAX_OUTPUT_TOKENS', env_file)}]")
    report.item("temperature", f"{config.temperature}  [{_source(prefix + 'TEMPERATURE', env_file)}]")
    report.item("api key", "set (value not shown)")
    if provider == "nararouter":
        report.item("reasoning_effort (2.x/3.x)",
                    f"{config.reasoning_effort}  [{_source('NARAROUTER_REASONING_EFFORT', env_file)}]")
        report.item("reasoning_effort (content-only)",
                    f"{config.content_reasoning_effort}  [{_source('NARAROUTER_CONTENT_REASONING_EFFORT', env_file)}]")
    if provider == "deepseek":
        report.item("retry policy", "at most 2 total calls; one shared transient/structural retry; 295 s run budget")
    limits = GenerationLimits()
    for name in GenerationLimits.model_fields:
        report.item(name.upper(), f"{getattr(limits, name)}  [{_source(name.upper(), env_file)}]")
    from .generation_persistence import diagnostics_file
    sink = diagnostics_file()
    if sink is None:
        raise Blocked("A. runtime configuration", "GENERATION_DIAGNOSTICS_FILE is blank: a failed live attempt "
                                                  "would leave no durable local diagnostic")
    sink = sink if sink.is_absolute() else backend_dir / sink
    existing = next(parent for parent in (sink, *sink.parents) if parent.exists())
    if not os.access(existing if existing.is_dir() else existing.parent, os.W_OK):
        raise Blocked("A. runtime configuration", f"local diagnostics file is not writable: {sink}")
    report.item("local diagnostics file", f"{sink} (content-free JSON lines, written for every failed attempt)")
    window = structural_retry_window(config.timeout_seconds)
    report.item("structural retry window", f"{window:.1f} s (a format retry needs the first call to finish "
                                            f"within this time)")
    if window < 30:
        report.warn(f"format retry is effectively unreachable: first call must finish within {window:.1f} s; "
                    f"any SCHEMA_INVALID/MALFORMED_JSON is final after one provider call")
    report.facts.update(provider=provider, model=config.model, timeout_seconds=config.timeout_seconds,
                        max_output_tokens=config.max_output_tokens)
    if version != CURRENT_CONTENT_VERSION:
        raise Blocked("A. runtime configuration",
                      f"effective prompt version is {version}, intended {CURRENT_CONTENT_VERSION}; set "
                      f"GENERATION_CONTENT_ONLY=true in {env_path} (or the backend's process environment) "
                      f"and restart the backend")
    try:
        validate_generation_target(config, version)
    except ProviderFailure:
        raise Blocked("A. runtime configuration", "GENERATION_CONFIGURATION_MISMATCH: 4.1.2 requires deepseek/deepseek-flash") from None
    return {"provider": provider, "config": config, "version": version}


# --------------------------------------------------------------------------- B. snapshot

def load_snapshot_file(path: Path) -> GenerationInputSnapshot:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict) and ("input_snapshot" in raw or "snapshot" in raw):
        raw = raw.get("input_snapshot", raw.get("snapshot"))
    if isinstance(raw, str):
        raw = json.loads(raw)
    return GenerationInputSnapshot.model_validate(raw)


async def _live_preflight(employee_id: UUID, token: str) -> PreflightResult:
    """Read-only: the same preflight the API runs, with the operator's own session token."""
    from .config import get_settings
    from .generation_context import preflight
    from .generation_persistence import GenerationStore
    from .models import Principal
    from .rrm_repository import RRMRepository
    from .security import decode_access_token
    from .supabase import SupabaseGateway
    settings = get_settings()
    user_id = decode_access_token(token, settings)
    async with httpx.AsyncClient(timeout=30) as client:
        profile = await SupabaseGateway(str(settings.supabase_url), settings.supabase_anon_key, client).get_profile(
            token, user_id)
        if profile is None:
            raise Blocked("B. snapshot", "the access token has no active profile")
        store = GenerationStore(RRMRepository(str(settings.supabase_url), settings.supabase_anon_key, client))
        return await preflight(Principal(user_id=user_id, token=token, profile=profile), employee_id, store,
                               datetime.now(timezone.utc))


def check_snapshot(report: _Report, employee_id: UUID, snapshot_path: Path | None,
                   expected_hash: str | None) -> GenerationInputSnapshot:
    report.section("B. Snapshot integrity (no provider call)")
    if snapshot_path is not None:
        if not snapshot_path.exists():
            raise Blocked("B. snapshot", f"snapshot file not found: {snapshot_path}")
        try:
            snapshot = load_snapshot_file(snapshot_path)
        except (ValueError, TypeError) as exc:
            raise Blocked("B. snapshot", f"snapshot file is not a valid frozen input ({type(exc).__name__})") from None
        report.item("source", f"snapshot file {snapshot_path.name}")
    else:
        token = os.environ.get("SKILLSPRINT_ACCESS_TOKEN")
        if not token:
            raise Blocked("B. snapshot", "no --snapshot given and SKILLSPRINT_ACCESS_TOKEN is not set for a read-only "
                                         "live preflight")
        result = asyncio.run(_live_preflight(employee_id, token))
        if result.status != "READY" or result.snapshot is None:
            raise Blocked("B. snapshot", f"live preflight blocked: {', '.join(result.blocker_codes) or 'unknown'}")
        snapshot = result.snapshot
        expected_hash = expected_hash or result.input_hash
        report.item("source", "live read-only preflight")
    employee = snapshot.employee
    if employee.employee_id != employee_id:
        raise Blocked("B. snapshot", f"snapshot belongs to employee {employee.employee_id}, not {employee_id}")
    report.item("employee", f"{employee.employee_id} (role {employee.role_code}, {employee.experience})")
    report.item("matrix", f"{snapshot.matrix_id} revision {snapshot.matrix_revision} edit {snapshot.matrix_edit} "
                          f"lock {snapshot.matrix_lock_version}")
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot.matrix_snapshot_hash):
        raise Blocked("B. snapshot", "matrix snapshot hash is not a 64-hex digest")
    stage_set = snapshot.stage_set
    report.item("stage set", f"{stage_set.code} v{stage_set.version} ({stage_set.status}), "
                             f"{len(stage_set.items)} stages")
    sequences = [stage.sequence for stage in stage_set.items]
    if stage_set.status != "ACTIVE" or not stage_set.items or sequences != sorted(set(sequences)):
        raise Blocked("B. snapshot", "stage set is not ACTIVE with strictly increasing stage sequences")
    requirements = snapshot.requirements
    if not requirements:
        raise Blocked("B. snapshot", "no approved requirements")
    context = EmployeeContext(role_id=employee.role_id, department_id=employee.department_id,
                              location_code=employee.location_code, experience=employee.experience)
    not_applicable = [req.code for req in requirements if applicability(req.applicability, context) != "APPLICABLE"]
    if not_applicable:
        raise Blocked("B. snapshot", f"requirements not applicable to this employee: {', '.join(not_applicable)}")
    mandatory = [req for req in requirements if req.mandatory]
    report.item("requirements", f"{len(requirements)} ({len(mandatory)} mandatory)")
    ids = {req.revision_id for req in requirements}
    stage_index = {stage.stage_definition_id: index for index, stage in enumerate(stage_set.items)}
    for req in requirements:
        if req.stage_definition_id is not None and req.stage_definition_id not in stage_index:
            raise Blocked("B. snapshot", f"requirement {req.code} is placed in a stage outside the active set")
    for dependent, prerequisite in snapshot.dependencies:
        if dependent not in ids or prerequisite not in ids:
            raise Blocked("B. snapshot", "a dependency references a requirement outside the snapshot")
    if has_cycle({rid: [p for d, p in snapshot.dependencies if d == rid] for rid in ids}):
        raise Blocked("B. snapshot", "requirement dependencies contain a cycle")
    by_id = {req.revision_id: req for req in requirements}
    for dependent, prerequisite in snapshot.dependencies:
        d, p = by_id[dependent].stage_definition_id, by_id[prerequisite].stage_definition_id
        if d is not None and p is not None and stage_index[p] > stage_index[d]:
            raise Blocked("B. snapshot", f"{by_id[prerequisite].code} (prerequisite) is staged after "
                                         f"{by_id[dependent].code}")
    report.item("dependencies", f"{len(snapshot.dependencies)} (acyclic, stage order valid)")
    evidence_total = 0
    distinct = set()
    for req in requirements:
        try:
            refs = source_refs(req)
        except ValueError:
            raise Blocked("B. snapshot", f"requirement {req.code} has no evidence or more than 100 references") from None
        if any(len(ref["locator"]) > 240 for ref in refs):
            raise Blocked("B. snapshot", f"requirement {req.code} has a locator longer than 240 characters")
        evidence_total += len(refs)
        distinct.update((ref["document_version_id"], ref["chunk_id"], ref["locator"]) for ref in refs)
    report.item("evidence", f"{evidence_total} references, {len(distinct)} distinct chunks/locators")
    try:
        module_layout(snapshot)
    except ValueError as exc:
        raise Blocked("B. snapshot", f"deterministic module layout impossible: {exc}") from None
    computed = input_hash(snapshot)
    report.item("frozen input hash", computed)
    if expected_hash is not None:
        if expected_hash != computed:
            raise Blocked("B. snapshot", "frozen input hash differs from the expected input hash")
        report.item("input hash check", "matches expected")
    else:
        report.item("input hash check", "not compared (pass --input-hash from generation_runs.input_hash)")
    report.facts.update(requirements=len(requirements), mandatory=len(mandatory), stages=len(stage_set.items),
                        dependencies=len(snapshot.dependencies), evidence_refs=evidence_total,
                        evidence_distinct=len(distinct), input_hash=computed)
    return snapshot


# --------------------------------------------------------------------------- C. prompt identity

def _schema_properties(schema: dict) -> list[str]:
    names: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                names.extend(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(schema)
    return names


def _object_depth(schema: dict) -> int:
    defs = schema.get("$defs", {})

    def depth(node, seen=()):
        if not isinstance(node, dict):
            return 0
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[1]
            return 0 if name in seen else depth(defs[name], seen + (name,))
        own = 1 if node.get("type") == "object" and "properties" in node else 0
        children = [depth(value, seen) for key, value in node.get("properties", {}).items()]
        if isinstance(node.get("items"), dict):
            children.append(depth(node["items"], seen))
        children += [depth(option, seen) for option in node.get("anyOf", [])]
        return own + max(children or [0])
    return depth(schema)


def check_prompt(report: _Report, snapshot: GenerationInputSnapshot, version: str):
    report.section("C. Prompt / version identity")
    reserved = build_prompt(snapshot)                                   # what the API reserves
    executed = build_prompt(snapshot, DRY_RUN_ID, version=reserved.prompt_version)  # what generation sends
    again = build_prompt(snapshot, DRY_RUN_ID, version=reserved.prompt_version)
    if (reserved.prompt_version, reserved.template_hash, reserved.projection_hash) != (
            executed.prompt_version, executed.template_hash, executed.projection_hash):
        raise Blocked("C. prompt identity", "reservation and execution would use different prompt contracts")
    if reserved.prompt_version != version:
        raise Blocked("C. prompt identity", f"build_prompt selected {reserved.prompt_version}, expected {version}")
    if executed != again or executed.response_schema != again.response_schema:
        raise Blocked("C. prompt identity", "request construction is not deterministic")
    if executed.template_hash != content_template_hash(version):
        raise Blocked("C. prompt identity", "template hash does not match the recomputed contract hash")
    if executed.schema_version != SCHEMA_VERSION:
        raise Blocked("C. prompt identity", f"persisted schema version {executed.schema_version} != {SCHEMA_VERSION}")
    if not executed.within_budget:
        raise Blocked("C. prompt identity", "projection exceeds the prompt budget (GENERATION_PROJECTION_TOO_LARGE)")
    report.item("prompt version", executed.prompt_version)
    report.item("template hash", executed.template_hash)
    report.item("schema version", executed.schema_version)
    report.item("projection hash", executed.projection_hash)
    report.item("reservation == execution", "same version, template hash and projection hash")
    schema = executed.response_schema or {}
    names = [name for name in _schema_properties(schema) if name != "requirements"]
    delegated = sorted({name for name in names if _DELEGATED.search(name)})
    if '"uuid"' in json.dumps(schema):
        delegated.append("<format uuid>")
    expected_keys = list(requirement_keys(snapshot))
    keyed = list(schema.get("properties", {}).get("requirements", {}).get("properties", {}))
    if keyed != expected_keys:
        raise Blocked("C. prompt identity", f"content schema keys {keyed} do not match requirement keys {expected_keys}")
    if _UUID.search(executed.untrusted_data):
        delegated.append("<uuid in model input>")
    if delegated:
        raise Blocked("C. prompt identity", f"backend-owned fields delegated to the model: {', '.join(delegated)}")
    if version in MINIMAL_CONTENT_VERSIONS:
        model_schema = _strict_schema(_compact_schema(CONTENT_RESPONSE_MODELS[version].model_json_schema()))
        if (schema != content_response_schema(expected_keys, None, version=version)
                or schema.get("$defs") != model_schema.get("$defs")
                or {k: v for k, v in schema["properties"].items() if k != "requirements"}
                != {k: v for k, v in model_schema["properties"].items() if k != "requirements"}
                or schema.get("required") != model_schema.get("required")):
            raise Blocked("C. prompt identity", "provider schema differs from the Pydantic content model")
        report.item("provider schema == Pydantic model", "identical (fields, required, bounds, additionalProperties)")
    if version == CONTENT_V411:
        embedded = re.search(r"\nresponse_json_schema=(.*)$", executed.rules, re.S)
        keys_line = re.search(r"\nrequired_requirement_keys=([^\n]*)\n", executed.rules)
        if embedded is None or keys_line is None:
            raise Blocked("C. prompt identity", "4.1.1 prompt does not carry the required keys and response schema")
        if json.loads(embedded.group(1)) != schema or json.loads(embedded.group(1)) != provider_schema_for(executed):
            raise Blocked("C. prompt identity", "schema in the prompt differs from the response_format schema")
        if [key.strip() for key in keys_line.group(1).split(",")] != expected_keys:
            raise Blocked("C. prompt identity", "required keys in the prompt differ from the frozen requirements")
        report.item("prompt-embedded schema", "== response_format schema == Pydantic model schema")
        report.item("required keys in prompt", keys_line.group(1))
    report.item("model-generated mechanical fields", "none (no ids, stages, requirement mappings, sources, "
                                                     "dependencies, identity, request id, mandatory/priority)")
    report.facts.update(template_hash=executed.template_hash, projection_hash=executed.projection_hash)
    return executed


# --------------------------------------------------------------------------- D. database

def db_verification_sql(version: str, template: str, provider: str, model: str) -> str:
    constraint = PROJECTION_CONSTRAINTS.get(version, "")
    return f"""-- Read-only. Run in the Supabase SQL editor; save the single JSON cell to a file and pass it
-- to --db-verification. Verifies the live reservation function accepts this exact contract.
with f as (
  select pg_get_functiondef('public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)'::regprocedure) as d
)
select json_build_object(
  'checked_prompt_version', '{version}',
  'checked_template_hash', '{template}',
  'checked_provider', '{provider}',
  'checked_model', '{model}',
  'provider_accepted', position('''{provider}''' in d) > 0 and exists (
    select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass
    and conname = 'generation_runs_provider_check'
    and position('''{provider}''' in pg_get_constraintdef(oid)) > 0),
  'pair_accepted', d ~ 'p_prompt_version = ''{version}''\\s+and p_template_hash = ''{template}''',
  'model_accepted', (position('''{model}''' in d) > 0 or '{provider}' = 'gemini') and exists (
    select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass
    and conname = 'generation_runs_model_check'
    and (position('''{model}''' in pg_get_constraintdef(oid)) > 0 or '{provider}' = 'gemini')),
  'max_timeout_seconds', (regexp_match(d, 'timeout_seconds''\\)::numeric not between 1 and (\\d+)'))[1]::int,
  'max_output_tokens_upper', (regexp_match(d, 'max_output_tokens''\\)::numeric not between 256 and (\\d+)'))[1]::int,
  'projection_constraint_present', exists (select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass and conname = '{constraint}'),
  'diagnostics_table_present', to_regclass('public.generation_attempt_diagnostics') is not null,
  'diagnostics_rpc_present', exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                                     where n.nspname = 'public' and p.proname = 'record_generation_attempt_diagnostics'),
  'diagnostics_rpc_executable', coalesce((select has_function_privilege('authenticated', p.oid, 'execute')
                                          from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                                          where n.nspname = 'public'
                                            and p.proname = 'record_generation_attempt_diagnostics'), false),
  'postgrest_schema_reload_trigger_present', exists (select 1 from pg_event_trigger where evtname ilike 'pgrst%')
) as readiness
from f;"""


def _load_db_result(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict) and "readiness" in raw:
        raw = raw["readiness"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("not a JSON object")
    return raw


def check_database(report: _Report, db_path: Path | None, version: str, template: str, provider: str,
                   config) -> tuple[bool, str]:
    report.section("D. Database contract (read-only)")
    sql = db_verification_sql(version, template, provider, config.model)
    if db_path is None:
        report.item("status", "DB_VERIFICATION_REQUIRED (no --db-verification result supplied; not assumed)")
        return False, sql
    try:
        result = _load_db_result(db_path)
    except (OSError, ValueError) as exc:
        raise Blocked("D. database", f"cannot read the DB verification result ({type(exc).__name__})") from None
    checks = {
        "checked_prompt_version": result.get("checked_prompt_version") == version,
        "checked_template_hash": result.get("checked_template_hash") == template,
        "checked_model": result.get("checked_model") == config.model,
        **({"checked_provider": result.get("checked_provider") == provider,
            "provider_accepted": result.get("provider_accepted") is True} if provider == "deepseek" else {}),
        "pair_accepted": result.get("pair_accepted") is True,
        "model_accepted": result.get("model_accepted") is True,
        "timeout bound": isinstance(result.get("max_timeout_seconds"), int)
                         and result["max_timeout_seconds"] >= config.timeout_seconds,
        "max_output_tokens bound": isinstance(result.get("max_output_tokens_upper"), int)
                                   and result["max_output_tokens_upper"] >= config.max_output_tokens,
        "projection constraint": result.get("projection_constraint_present") is True,
        # A failed live call must leave persisted, safe diagnostics (migration 202609280010).
        "diagnostics table": result.get("diagnostics_table_present") is True,
        "diagnostics rpc": result.get("diagnostics_rpc_present") is True,
        "diagnostics rpc executable": result.get("diagnostics_rpc_executable") is True,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise Blocked("D. database", f"the live reservation contract does not accept this run ({', '.join(failed)}); "
                                     f"apply the pending migration and re-run the SQL")
    for name in checks:
        report.item(name, "ok")
    if result.get("postgrest_schema_reload_trigger_present") is not True:
        report.warn("no PostgREST schema-reload event trigger reported: after applying migrations run "
                    "NOTIFY pgrst, 'reload schema'; so new RPCs are reachable")
    return True, sql


# --------------------------------------------------------------------------- E. request measurement

_COMPARISON: dict = {}


def build_prompt_for_comparison(prompt) -> int | None:
    return _COMPARISON.get("v401_request_bytes")


def _request_bytes(prompt, provider: str, config) -> int:
    if provider == "deepseek":
        full = deepseek_request_payload(prompt, config)
    elif provider == "nararouter":
        payload = nararouter_request_payload(prompt, config)
        full = {**payload, "response_format": json_schema_response_format(provider_schema_for(prompt))}
    elif provider == "groq":
        payload = groq_request_payload(prompt, config)
        full = {**payload, "response_format": json_schema_response_format(provider_schema_for(prompt))}
    else:
        full = {"system": prompt.system + "\n" + prompt.rules, "user": prompt.untrusted_data,
                "schema": provider_schema_for(prompt, key_pattern=False)}
    return len(httpx.Request("POST", "https://readiness.invalid", json=full).content)


def measure_request(report: _Report, prompt, provider: str, config, snapshot=None) -> None:
    if snapshot is not None and prompt.prompt_version in MINIMAL_CONTENT_VERSIONS:
        _COMPARISON["v401_request_bytes"] = _request_bytes(build_prompt(snapshot, DRY_RUN_ID, version=CONTENT_V401),
                                                           provider, config)
        _COMPARISON["v410_request_bytes"] = _request_bytes(build_prompt(snapshot, DRY_RUN_ID, version=CONTENT_V410),
                                                           provider, config)
    report.section("E. Exact provider request (built, never sent)")
    if provider == "deepseek":
        payload = full = deepseek_request_payload(prompt, config)
        schema = full["text"]["format"]["schema"]
        system, user = full["instructions"], prompt.untrusted_data
    elif provider == "nararouter":
        payload = nararouter_request_payload(prompt, config)
        schema = provider_schema_for(prompt)
        full = {**payload, "response_format": json_schema_response_format(schema)}
        system, user = payload["messages"][0]["content"], payload["messages"][1]["content"]
    elif provider == "groq":
        payload = groq_request_payload(prompt, config)
        schema = provider_schema_for(prompt)
        full = {**payload, "response_format": json_schema_response_format(schema)}
        system, user = payload["messages"][0]["content"], payload["messages"][1]["content"]
    else:  # gemini, mirroring GeminiProvider.generate
        system, user = prompt.system + "\n" + prompt.rules, prompt.untrusted_data
        payload = {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"responseMimeType": "application/json", "temperature": config.temperature,
                                        "maxOutputTokens": config.max_output_tokens}}
        schema = provider_schema_for(prompt, key_pattern=False)
        full = {**payload, "generationConfig": {**payload["generationConfig"], "responseJsonSchema": schema}}
    guarded = len(httpx.Request("POST", "https://readiness.invalid", json=payload).content)
    total = len(httpx.Request("POST", "https://readiness.invalid", json=full).content)
    schema_bytes = len(json.dumps(schema, separators=(",", ":")).encode())
    if guarded > MAX_PROVIDER_REQUEST_BYTES:
        raise Blocked("E. request", f"request without schema is {guarded} bytes > {MAX_PROVIDER_REQUEST_BYTES} "
                                    f"(the adapter would fail GENERATION_PROJECTION_TOO_LARGE)")
    properties = len(_schema_properties(schema))
    depth = _object_depth(schema)
    report.item("system prompt bytes", len(system.encode()))
    report.item("user/context bytes", len(user.encode()))
    report.item("response schema bytes", schema_bytes)
    report.item("request bytes (adapter size guard)", f"{guarded} / {MAX_PROVIDER_REQUEST_BYTES}")
    report.item("total serialized request bytes", total)
    report.item("approx input tokens (bytes/4)", total // 4)
    report.item("schema properties / object depth", f"{properties} / {depth}")
    report.item("max output tokens", config.max_output_tokens)
    report.item("reasoning effort sent", full.get("reasoning", {}).get("effort", full.get("reasoning_effort", "not sent")))
    if schema_bytes > 8192:
        report.warn(f"response schema is large ({schema_bytes} bytes)")
    if total // 4 > 6000:
        report.warn(f"input is large (~{total // 4} tokens)")
    if depth > 4:
        report.warn(f"response schema nesting depth {depth} exceeds the content-only design (3)")
    if prompt.prompt_version in MINIMAL_CONTENT_VERSIONS:
        previous = build_prompt_for_comparison(prompt)
        if previous is not None:
            ratio = total / previous
            report.item("vs 4.0.1 request bytes", f"{total} vs {previous} ({100 * (1 - ratio):.0f}% smaller)")
            if prompt.prompt_version == CONTENT_V410 and ratio > 0.85:
                raise Blocked("E. request", f"4.1.0 request is not materially smaller than 4.0.1 ({total} vs {previous})")
            if ratio >= 1:
                raise Blocked("E. request", f"request is not smaller than 4.0.1 ({total} vs {previous})")
        base = _COMPARISON.get("v410_request_bytes")
        if prompt.prompt_version == CONTENT_V411 and base is not None:
            growth, allowed = total - base, schema_bytes + 1024  # embedded schema + static rules text
            report.item("vs 4.1.0 request bytes", f"{total} vs {base} (+{growth}; allowed +{allowed}: "
                                                  f"the embedded schema and rules only)")
            if growth > allowed:
                raise Blocked("E. request", f"4.1.1 grew by {growth} bytes over 4.1.0 (allowed {allowed})")
    report.facts.update(request_bytes=total, schema_bytes=schema_bytes, input_tokens=total // 4,
                        schema_properties=properties, schema_depth=depth)


# --------------------------------------------------------------------------- F/G/H. offline pipeline

class _FixtureProvider:
    """In-process stand-in for a provider adapter: returns the fixture text, performs no I/O."""

    def __init__(self, text: str, config):
        self.text, self.config, self.prompts = text, config, []

    async def generate(self, prompt, *, format_retry: bool = False) -> ProviderResult:
        self.prompts.append(prompt)
        return ProviderResult(text=self.text, finish_reason="STOP")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _captured(function):
    logger = logging.getLogger("app.generation_service")
    handler, propagate = _Capture(), logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        return function(), handler.messages
    finally:
        logger.removeHandler(handler)
        logger.propagate = propagate


def adversarial_variants(fixture: dict) -> list[tuple[str, str, str]]:
    """Realistic small-model mistakes against the 4.1.0 content contract:
    (name, response text, expected failure code). Each carries a canary that must never be logged."""
    def variant(change):
        data = json.loads(json.dumps(fixture))
        first = next(iter(data["requirements"]))
        data["requirements"][first]["objective"] = CANARY + " objective"
        change(data, first)
        return json.dumps(data)

    keys = list(fixture["requirements"])
    duplicate = ('{"plan_title": "' + CANARY + '", "requirements": {'
                 + ", ".join(f'"{key}": {json.dumps(value)}' for key, value in fixture["requirements"].items())
                 + f', "{keys[0]}": {json.dumps(fixture["requirements"][keys[0]])}' + "}}")
    return [
        ("missing requirement key", variant(lambda d, k: d["requirements"].pop(keys[-1])), "SCHEMA_INVALID"),
        ("only one requirement entry", variant(lambda d, k: d.update(requirements={k: d["requirements"][k]})),
         "SCHEMA_INVALID"),
        ("duplicate requirement key", duplicate, "MALFORMED_JSON"),
        ("unknown R#", variant(lambda d, k: d["requirements"].update({"R999": d["requirements"][k]})),
         "SCHEMA_INVALID"),
        ("missing objective", variant(lambda d, k: d["requirements"][k].pop("objective")), "SCHEMA_INVALID"),
        ("empty string", variant(lambda d, k: d["requirements"][k].update(task="")), "SCHEMA_INVALID"),
        ("blank title", variant(lambda d, k: d["requirements"][k].update(module_title="   ")), "SCHEMA_INVALID"),
        ("text too long", variant(lambda d, k: d["requirements"][k].update(module_title=CANARY * 10)),
         "SCHEMA_INVALID"),
        ("wrong type", variant(lambda d, k: d["requirements"][k].update(checklist=[CANARY])), "SCHEMA_INVALID"),
        ("null field", variant(lambda d, k: d["requirements"][k].update(quiz_question=None)), "SCHEMA_INVALID"),
        ("quiz with 2 options", variant(lambda d, k: d["requirements"][k].update(quiz_options=[CANARY, "b"])),
         "SCHEMA_INVALID"),
        ("quiz with 4 options", variant(lambda d, k: d["requirements"][k].update(quiz_options=[CANARY, "b", "c", "d"])),
         "SCHEMA_INVALID"),
        ("duplicate quiz options", variant(lambda d, k: d["requirements"][k].update(
            quiz_options=[CANARY, CANARY.lower() + " ", "Other"])), "SCHEMA_INVALID"),
        ("invalid correct index", variant(lambda d, k: d["requirements"][k].update(correct_option_index=3)),
         "SCHEMA_INVALID"),
        ("index as string", variant(lambda d, k: d["requirements"][k].update(correct_option_index="1")),
         "SCHEMA_INVALID"),
        ("extra field (model-supplied id)", variant(lambda d, k: d["requirements"][k].update(module_id=CANARY)),
         "SCHEMA_INVALID"),
        ("removed 4.0.1 field returned", variant(lambda d, k: d["requirements"][k].update(quiz_explanation=CANARY)),
         "SCHEMA_INVALID"),
        ("model-supplied stage structure", variant(lambda d, k: d.update(stages=[CANARY])), "SCHEMA_INVALID"),
        ("requirements as a list", variant(lambda d, k: d.update(requirements=list(d["requirements"].values()))),
         "SCHEMA_INVALID"),
        ("wrapper object", json.dumps({"onboarding_plan": json.loads(variant(lambda d, k: None))}), "SCHEMA_INVALID"),
        ("markdown-wrapped JSON", "```json\n" + variant(lambda d, k: None) + "\n```", "MALFORMED_JSON"),
        ("malformed JSON", variant(lambda d, k: None)[:-7], "MALFORMED_JSON"),
    ]


def check_adversarial(report: _Report, snapshot, fixture: dict, version: str) -> None:
    from .generation_service import StructuralFailure
    report.section("F. Adversarial model outputs (expected safe failures)")
    variants = adversarial_variants(fixture)
    if version == CONTENT_V412:
        for distinct in (False, True):
            data = json.loads(json.dumps(fixture))
            data["plan_title"] = "x"
            for item in data["requirements"].values():
                for name in ("module_title", "objective", "task", "checklist", "quiz_question"):
                    item[name] = "x"
                item["quiz_options"] = ["a", "b", "c"] if distinct else ["a", "a", "a"]
            variants.append(("one-character values; distinct options=" + str(distinct),
                             json.dumps(data), "SCHEMA_INVALID"))
    for name, text, expected in variants:
        def attempt():
            try:
                assemble_content(text, snapshot, DRY_RUN_ID, version)
            except StructuralFailure as exc:
                return exc
            return None
        failure, logs = _captured(attempt)
        code = failure.code if failure else None
        if code != expected:
            raise Blocked("F. adversarial", f"'{name}' produced {code or 'a plan'}, expected {expected}")
        persisted = json.dumps(failure.detail)
        if any(CANARY.lower() in message.lower() for message in logs) or CANARY.lower() in persisted.lower():
            raise Blocked("F. adversarial", f"'{name}' leaked model text into diagnostics")
        detail = failure.detail
        if detail["layer"] == "unspecified" or not (detail["errors"] or detail.get("received")):
            raise Blocked("F. adversarial", f"'{name}' produced no actionable persisted diagnostic")
        first = detail["errors"][0] if detail["errors"] else {}
        report.item(name, f"{code} @ {detail['layer']}: {first.get('loc', '')} {first.get('type', '')}".rstrip()
                    + f" ({detail['error_count']} error(s); persisted diagnostic content-free)")


def run_pipeline(report: _Report, snapshot, prompt, fixture_text: str, config, version: str) -> dict:
    report.section("G. Full zero-provider pipeline")
    provider = _FixtureProvider(fixture_text, config)
    attempts = []

    async def record(item):
        attempts.append(item)

    async def no_sleep(_seconds):
        return None
    preflight = PreflightResult(status="READY", snapshot=snapshot, input_hash=input_hash(snapshot))
    result, logs = _captured(lambda: asyncio.run(generate_unverified(
        preflight, DRY_RUN_ID, provider, no_sleep, on_attempt=record, prompt_version=version)))
    if result.status != "UNVERIFIED" or result.plan is None:
        raise Blocked("G. pipeline", f"known-good fixture failed with {result.error_code} "
                                     f"({'; '.join(logs[:3]) or 'no diagnostics'})")
    sent = provider.prompts[0]
    if (sent.prompt_version, sent.template_hash, sent.projection_hash) != (
            prompt.prompt_version, prompt.template_hash, prompt.projection_hash):
        raise Blocked("G. pipeline", "execution built a different prompt than the reserved one")
    if len(provider.prompts) != 1 or [a.parse_outcome for a in attempts] != ["SCHEMA_VALID"]:
        raise Blocked("G. pipeline", "known-good fixture needed more than one attempt")
    report.item("content schema -> assembly -> OnboardingPlan -> identity/stage/reference checks", "passed")
    plan = result.plan
    frozen_stages = [stage.stage_definition_id for stage in snapshot.stage_set.items]
    if [stage.stage_id for stage in plan.plan.stages] != frozen_stages:
        raise Blocked("G. pipeline", "assembled stages differ from the frozen stage set")
    empty = [stage.label for stage in plan.plan.stages if not stage.modules]
    report.item("stages", f"{len(plan.plan.stages)} frozen stages kept"
                          + (f"; empty (no requirements): {', '.join(empty)}" if empty else ""))
    report.item("modules", sum(len(stage.modules) for stage in plan.plan.stages))
    content = plan.model_dump(mode="json")
    evidence = validate_plan(content, snapshot, DRY_RUN_ID, current_input=True)
    decision = decide(evidence)
    codes = {str(req.revision_id): req.code for req in snapshot.requirements}
    unexpected = [f for f in evidence.findings if (f.code, f.severity, f.location) not in ALLOWED_INPUT_WARNINGS]
    for finding in evidence.findings:
        report.item("finding", f"{finding.code} {finding.severity} {finding.location} "
                               f"{codes.get(str(finding.requirement_id), '')}".rstrip())
    if unexpected or decision.status not in ("VERIFIED", "VERIFIED_WITH_WARNING"):
        raise Blocked("G. pipeline", f"validator/JEV returned {decision.status} with "
                                     f"{', '.join(sorted({f.code for f in unexpected})) or 'no'} unexpected findings")
    if evidence.mandatory_covered != evidence.mandatory_total:
        raise Blocked("G. pipeline", "not every mandatory requirement is covered")
    report.item("mandatory coverage", f"{evidence.mandatory_covered}/{evidence.mandatory_total}")
    report.item("traceability", f"{evidence.generated_items_traceable}/{evidence.generated_items_total}")
    report.item("validator / JEV", f"{decision.status} ({decision.rule}); only input-level warnings")
    report.facts.update(decision=decision.status, findings=len(evidence.findings))
    return content


def persistence_dry_run(report: _Report, snapshot, prompt, content: dict) -> None:
    report.section("H. Persistence dry-run (nothing written)")
    OnboardingPlan.model_validate_json(json.dumps(content))
    size = len(json.dumps(content, separators=(",", ":")).encode())
    digest = snapshot_hash(content)
    checks = {
        "schema_version": content.get("schema_version") == SCHEMA_VERSION,
        "generation_request_id == run id": content.get("generation_request_id") == str(DRY_RUN_ID),
        "employee id": content["employee_context"]["employee_id"] == str(snapshot.employee.employee_id),
        "content hash": re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
        "plan size": size <= FINISH_MAX_PLAN_BYTES,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise Blocked("H. persistence", f"finish_generation_run would reject the plan ({', '.join(failed)})")
    report.item("run / request id", f"{DRY_RUN_ID} (dry-run id; never reserved)")
    report.item("employee id", snapshot.employee.employee_id)
    report.item("schema version", content["schema_version"])
    report.item("content hash", digest)
    report.item("plan size", f"{size} bytes (limit {FINISH_MAX_PLAN_BYTES})")
    report.item("input hash / projection hash", f"{input_hash(snapshot)} / {prompt.projection_hash}")
    report.item("status transition", "QUEUED -> claim -> RUNNING -> finish(postflight hash = input hash, plan, "
                                     "content hash, no error) -> UNVERIFIED")
    report.facts.update(plan_bytes=size, content_hash=digest)


# --------------------------------------------------------------------------- orchestration

def run_gate(employee: str, snapshot: str | None = None, db_verification: str | None = None,
             fixture: str | None = None, input_hash_hex: str | None = None,
             backend_dir: str | None = None) -> GateResult:
    report = _Report()
    snapshot_path = Path(snapshot).resolve() if snapshot else None
    db_path = Path(db_verification).resolve() if db_verification else None
    fixture_path = Path(fixture).resolve() if fixture else DEFAULT_FIXTURE
    if backend_dir:
        directory = Path(backend_dir).resolve()
    else:
        directory = Path.cwd() if (Path.cwd() / ".env").exists() else REPO_ROOT
    previous = Path.cwd()
    db_sql = None
    try:
        employee_id = UUID(employee)
        os.chdir(directory)  # settings read .env relative to the working directory, like the backend
        runtime = check_configuration(report, directory)
        frozen = check_snapshot(report, employee_id, snapshot_path, input_hash_hex)
        prompt = check_prompt(report, frozen, runtime["version"])
        db_ok, db_sql = check_database(report, db_path, runtime["version"], prompt.template_hash,
                                       runtime["provider"], runtime["config"])
        measure_request(report, prompt, runtime["provider"], runtime["config"], frozen)
        if not fixture_path.exists():
            raise Blocked("F. fixture", f"known-good fixture not found: {fixture_path}")
        fixture_text = fixture_path.read_text(encoding="utf-8")
        fixture_data = json.loads(fixture_text)
        expected_keys = set(requirement_keys(frozen))
        if set(fixture_data.get("requirements", {})) != expected_keys:
            raise Blocked("F. fixture", f"fixture keys do not match this snapshot's requirement keys "
                                        f"{sorted(expected_keys, key=lambda k: int(k[1:]))}; pass --fixture")
        report.facts["fixture_bytes"] = len(fixture_text.encode())
        check_adversarial(report, frozen, fixture_data, runtime["version"])
        content = run_pipeline(report, frozen, prompt, fixture_text, runtime["config"], runtime["version"])
        report.item("expected response size (fixture)", f"{len(fixture_text.encode())} bytes "
                                                        f"(~{len(fixture_text.encode()) // 4} tokens)")
        persistence_dry_run(report, frozen, prompt, content)
    except Blocked as exc:
        line = f"BLOCKED: {exc.step} — {exc.reason}"
        return GateResult("BLOCKED", line, report.lines, report.warnings, report.facts, db_sql)
    except ValueError as exc:
        line = f"BLOCKED: input — {type(exc).__name__}: invalid employee id or input"
        return GateResult("BLOCKED", line, report.lines, report.warnings, report.facts, db_sql)
    finally:
        os.chdir(previous)
    if not db_ok:
        return GateResult("DB_VERIFICATION_REQUIRED", "DB_VERIFICATION_REQUIRED", report.lines, report.warnings,
                          report.facts, db_sql)
    return GateResult("READY_FOR_ONE_CONTROLLED_LIVE_GENERATION", "READY_FOR_ONE_CONTROLLED_LIVE_GENERATION", report.lines, report.warnings,
                      report.facts, db_sql)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.generation_readiness",
                                     description="Zero-provider readiness gate for live generation.")
    parser.add_argument("--employee", required=True)
    parser.add_argument("--snapshot", help="exported frozen input snapshot (generation_runs.input_snapshot)")
    parser.add_argument("--db-verification", help="saved JSON result of the printed read-only SQL")
    parser.add_argument("--fixture", help="known-good content-only model response for this snapshot")
    parser.add_argument("--input-hash", help="expected frozen input hash to compare")
    parser.add_argument("--backend-dir", help="directory the backend runs from (where its .env is)")
    args = parser.parse_args(argv)
    try:  # Windows consoles default to a legacy code page; the report uses UTF-8 punctuation.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    result = run_gate(args.employee, args.snapshot, args.db_verification, args.fixture, args.input_hash,
                      args.backend_dir)
    print("SkillSprint generation readiness (no provider is called)")
    for line in result.lines:
        print(line)
    if result.status == "DB_VERIFICATION_REQUIRED" and result.db_sql:
        print("\nRun this read-only SQL in Supabase, save the JSON cell, then re-run with --db-verification <file>:")
        print(result.db_sql)
    print()
    print(result.final_line)
    return {"READY_FOR_ONE_CONTROLLED_LIVE_GENERATION": 0, "DB_VERIFICATION_REQUIRED": 2}.get(result.status, 1)


if __name__ == "__main__":
    sys.exit(main())
