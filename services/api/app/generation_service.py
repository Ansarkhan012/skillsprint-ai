"""In-memory Phase 4B generation; no persistence, validation, or JEV decision."""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from hashlib import sha256
from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from .generation_content import (CONTENT_PROMPT_VERSIONS, CONTENT_RESPONSE_MODELS, CURRENT_CONTENT_VERSION,
                                 assemble_plan, requirement_keys)
from .generation_context import input_hash
from .generation_models import GenerationInputSnapshot, PreflightResult
from .generation_output import OnboardingPlan
from .generation_prompt import SOURCE_KEY_PROMPT_VERSIONS, SourceKey, build_prompt, source_key_map
from .generation_provider import GenerationProvider, ProviderFailure
from .rrm_rules import canonical_json

_LOG = logging.getLogger(__name__)
_SAFE_FIELD_NAMES = frozenset({
    "schema_version", "generation_request_id", "employee_context", "employee_id", "role_id",
    "department_id", "experience_level", "location_code", "joining_date", "plan", "title",
    "summary", "stages", "stage_id", "label", "sequence", "target_start_day",
    "target_end_day", "modules", "module_id", "purpose", "category", "mandatory",
    "priority", "difficulty", "estimated_minutes", "prerequisite_module_ids",
    "learning_objectives", "objective_id", "statement", "key_concepts", "concept_id",
    "activities", "activity_id", "instructions", "expected_outcome", "checklist_items",
    "checklist_item_id", "activity", "required", "due_stage_id", "responsible_role",
    "tasks", "task_id", "description", "completion_criteria", "scenarios", "scenario_id",
    "prompt", "expected_actions", "success_criteria", "quizzes", "quiz_id",
    "question_type", "question", "options", "option_id", "text", "correct_answer_ids",
    "explanation", "assessments", "assessment_id", "assessment_type", "rubric",
    "criterion_id", "criterion", "weight_percent", "expected_performance", "pass_condition",
    "evidence_type", "threshold", "requirement_ids", "source_refs", "document_version_id",
    "chunk_id", "locator", "insufficient_information", "request_path", "topic",
    "requirement_id", "reason_code", "detail",
    # 4.0.0 content-only response
    "plan_title", "plan_summary", "requirements", "module_title", "module_purpose", "objective",
    "task_description", "task_expected_outcome", "task_completion_criteria", "checklist_activity",
    "quiz_question", "quiz_options", "correct_option_index", "quiz_explanation",
    # 4.1.0 content-only response
    "task", "checklist",
})
# Backend-issued requirement keys (R1..Rn) in 4.0.0 content paths are safe to report.
_REQUIREMENT_KEY = re.compile(r"R[0-9]{1,4}")


def _safe_part(part) -> object:
    if isinstance(part, int) and 0 <= part <= 100:
        return part
    if isinstance(part, str) and (part in _SAFE_FIELD_NAMES or _REQUIREMENT_KEY.fullmatch(part)):
        return part
    return "unknown_field"


def safe_validation_diagnostics(error: ValidationError) -> tuple[dict[str, object], ...]:
    """Only schema path/type; never model input, context, message or response text."""
    diagnostics = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:5]:
        path = []
        for part in item.get("loc", ())[:8]:
            path.append(_safe_part(part))
        kind = item.get("type", "unknown")
        diagnostics.append({"loc": tuple(path), "type": kind if isinstance(kind, str)
                            and re.fullmatch(r"[a-z_]{1,64}", kind) else "unknown"})
    return tuple(diagnostics)


# Pydantic renders these messages only from the schema (limits, expected literals) or from
# our own fixed ValueError codes, never from model input. Others (e.g. uuid_parsing, which
# quotes an input character) are logged by type only.
_SAFE_MESSAGE_TYPES = frozenset({
    "missing", "extra_forbidden", "literal_error", "enum", "string_too_short", "string_too_long",
    "string_pattern_mismatch", "too_short", "too_long", "greater_than_equal", "less_than_equal",
    "greater_than", "less_than", "string_type", "int_type", "int_from_float", "bool_type", "tuple_type",
    "list_type", "model_type", "model_attributes_type", "dict_type", "uuid_type", "date_type", "value_error",
})


def _safe_path(parts) -> str:
    """Dotted allowlisted path; unknown names and out-of-range indexes are masked."""
    return ".".join(str(_safe_part(part)) for part in list(parts)[:16])


def validation_records(error: ValidationError) -> list[dict]:
    """Full safe path, type and schema-derived message for each Pydantic error (max 20)."""
    records = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:MAX_DIAGNOSTIC_ERRORS]:
        kind = item.get("type", "unknown")
        kind = kind if isinstance(kind, str) and re.fullmatch(r"[a-z_]{1,64}", kind) else "unknown"
        record = {"loc": _safe_path(item.get("loc", ())), "type": kind}
        if kind in _SAFE_MESSAGE_TYPES and isinstance(item.get("msg"), str):
            record["msg"] = item["msg"][:160]
        records.append(record)
    return records


def _log_schema_invalid(error: ValidationError, request_id: UUID) -> list[dict]:
    """Log-only detail for SCHEMA_INVALID: full path, type and schema-derived message."""
    records = validation_records(error)
    _LOG.warning("generation_schema_invalid run_id=%s errors=%d diagnostics=%s",
                 request_id, error.error_count(), json.dumps(records))
    return records


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["UNVERIFIED", "FAILED", "BLOCKED"]
    error_code: str | None = None
    plan: OnboardingPlan | None = None
    input_hash: str | None = None
    prompt_version: str | None = None
    template_hash: str | None = None
    provider_calls: int = 0


class AttemptTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    attempt_type: Literal["INITIAL", "TRANSPORT_RETRY", "FORMAT_RETRY"]
    provider_outcome: Literal["RESPONSE", "TIMEOUT", "RATE_LIMIT", "UNAVAILABLE", "REJECTED", "ERROR"]
    latency_ms: int
    response_hash: str | None = None
    response_size: int | None = None
    parse_outcome: Literal["SCHEMA_VALID", "SCHEMA_INVALID", "NOT_PARSED"]
    error_code: str | None = None
    # Only the token counts the attempts RPC accepts; empty when the provider reports none.
    usage: dict[str, int] = {}
    # Safe structural diagnostics for a failed parse (failure_detail); empty otherwise.
    diagnostics: dict = {}


def usage_metadata(response) -> dict[str, int]:
    """Provider usage mapped to the RPC's allowlist (prompt/output/total tokens); never text."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    values = {"prompt_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
              "total_tokens": usage.total_tokens}
    return {name: value for name, value in values.items() if isinstance(value, int) and value >= 0}


class StructuralFailure(Exception):
    def __init__(self, code: str, diagnostics: tuple[dict[str, object], ...] = (), detail: dict | None = None):
        super().__init__(code)
        self.code = code
        self.diagnostics = diagnostics
        # Safe, capped, structure-only description persisted with the attempt (never model text).
        self.detail = detail or failure_detail("unspecified", code)


MAX_DIAGNOSTIC_ERRORS = 20
MAX_DIAGNOSTIC_BYTES = 4096


def failure_detail(layer: str, code: str, errors: list[dict] | tuple = (), received: dict | None = None,
                   error_count: int | None = None) -> dict:
    """Bounded, content-free diagnostic: layer, code, error count, safe error records, shape.

    Every string in it is one of our own field names, R# keys, reason/type codes or schema-derived
    messages; it never contains model prose, document text, secrets or employee values.
    """
    records = [dict(item) for item in list(errors)[:MAX_DIAGNOSTIC_ERRORS]]
    detail = {"layer": layer, "code": code, "error_count": len(errors) if error_count is None else error_count,
              "errors": records}
    if received:
        detail["received"] = received
    truncated = len(errors) > MAX_DIAGNOSTIC_ERRORS or (error_count or 0) > len(records)
    while len(json.dumps(detail, sort_keys=True).encode()) > MAX_DIAGNOSTIC_BYTES and detail["errors"]:
        detail["errors"].pop()
        truncated = True
    if len(json.dumps(detail, sort_keys=True).encode()) > MAX_DIAGNOSTIC_BYTES:
        detail.pop("received", None)
        truncated = True
    if truncated:
        detail["truncated"] = True
    return detail


def received_shape(decoded: object, size: int, expected_keys: list[str] | None = None) -> dict:
    """Types, counts and our own key names only; unknown key names are counted, never echoed."""
    shape: dict[str, object] = {"bytes": size, "type": type(decoded).__name__}
    if isinstance(decoded, dict):
        known = [key for key in decoded if isinstance(key, str) and (key in _SAFE_FIELD_NAMES
                                                                     or _REQUIREMENT_KEY.fullmatch(key))]
        shape["top_level_keys"] = sorted(known)[:20]
        shape["unknown_top_level_keys"] = len(decoded) - len(known)
        requirements = decoded.get("requirements")
        if expected_keys is not None:
            shape["requirement_keys_expected"] = len(expected_keys)
            shape["requirements_type"] = type(requirements).__name__
            if isinstance(requirements, dict):
                keys = [key for key in requirements if isinstance(key, str) and _REQUIREMENT_KEY.fullmatch(key)]
                shape["requirement_keys_received"] = len(requirements)
                shape["requirement_keys"] = sorted(keys, key=lambda key: int(key[1:]))[:20]
                shape["non_requirement_keys"] = len(requirements) - len(keys)
                shape["missing_requirement_keys"] = [key for key in expected_keys if key not in requirements][:20]
                shape["entry_field_counts"] = {key: len(value) if isinstance(value, dict) else type(value).__name__
                                               for key, value in list(requirements.items())[:20]
                                               if isinstance(key, str) and _REQUIREMENT_KEY.fullmatch(key)}
            elif isinstance(requirements, list):
                shape["requirement_items_received"] = len(requirements)
    elif isinstance(decoded, list):
        shape["items"] = len(decoded)
    return shape


def retry_feedback(failure: StructuralFailure) -> str:
    """Retry hint built only from our own error code and allowlisted schema path/type."""
    problems = "; ".join(".".join(str(part) for part in item["loc"]) + " " + str(item["type"])
                         for item in failure.diagnostics)
    return "Previous failure: " + failure.code + (". Fix: " + problems if problems else "") + "."


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StructuralFailure("MALFORMED_JSON")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise StructuralFailure("MALFORMED_JSON")


_UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_KEY_TEXT = re.compile(r"S[0-9]{1,6}")


def _safe_key(value: object) -> str:
    """Report an S#-shaped key verbatim; anything else only by type/length, never its text."""
    if isinstance(value, str):
        return value if _KEY_TEXT.fullmatch(value) else f"<non_key string len={len(value)}>"
    return f"<non_key {type(value).__name__}>"


def expand_source_keys(text: str, keys: dict[str, SourceKey], request_id: UUID | None = None) -> str:
    """Replace S# keys with the frozen {document_version_id, chunk_id, locator}, before parse_plan.

    Never repairs: an unknown key, or a key that is not evidence for any of the item's own
    requirement_ids, fails as SCHEMA_INVALID with sanitized path/type diagnostics. Any
    other malformed shape is left untouched for parse_plan to reject as it does today.
    Each rejected key is logged with its path, the item's requirement_ids and the keys
    those requirements allow; no excerpt or other document/model text is logged.
    """
    if not text or not text.strip():
        return text
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        return text
    problems: list[dict[str, object]] = []
    details: list[dict[str, object]] = []

    def safe(path: list) -> tuple:
        return tuple(part if isinstance(part, int) and 0 <= part <= 100
                     else part if isinstance(part, str) and part in _SAFE_FIELD_NAMES
                     else "unknown_field" for part in path[:16])

    def walk(node: object, path: list) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path + [index])
            return
        if not isinstance(node, dict):
            return
        refs = node.get("source_refs")
        if isinstance(refs, list):
            owners = node.get("requirement_ids")
            owners = {str(item).lower() for item in owners if isinstance(item, str)}                 if isinstance(owners, list) else set()
            expanded = []
            for index, ref in enumerate(refs):
                item = keys.get(ref) if isinstance(ref, str) else None
                reason = ("unknown_source_key" if item is None
                          else "source_key_wrong_requirement" if not item.requirement_ids & owners else None)
                if reason is None:
                    expanded.append({"document_version_id": item.document_version_id,
                                     "chunk_id": item.chunk_id, "locator": item.locator})
                    continue
                loc = safe(path + ["source_refs", index])
                problems.append({"loc": loc, "type": reason})
                details.append({
                    "path": _safe_path(loc), "key": _safe_key(ref), "reason": reason,
                    "requirement_ids": sorted(owner if _UUID_TEXT.fullmatch(owner) else "<invalid>"
                                              for owner in owners),
                    "allowed_keys": sorted((key for key, source in keys.items() if source.requirement_ids & owners),
                                           key=lambda key: int(key[1:])),
                })
            node["source_refs"] = expanded
        for name, value in node.items():
            if name != "source_refs":
                walk(value, path + [name])

    walk(decoded, [])
    if problems:
        for detail in details[:10]:
            _LOG.warning("generation_source_key_invalid run_id=%s path=\"%s\" key=\"%s\" reason=\"%s\" "
                         "requirement_ids=%s allowed_keys=%s", request_id, detail["path"], detail["key"],
                         detail["reason"], json.dumps(detail["requirement_ids"]), json.dumps(detail["allowed_keys"]))
        _LOG.warning("generation_source_key_invalid run_id=%s total_invalid=%d logged=%d",
                     request_id, len(details), min(len(details), 10))
        raise StructuralFailure("SCHEMA_INVALID", tuple(problems[:5]), failure_detail(
            "source_keys", "SCHEMA_INVALID", [{"loc": d["path"], "type": d["reason"], "key": d["key"]} for d in details]))
    return json.dumps(decoded, ensure_ascii=False)


_ITEM_FIELDS = ("learning_objectives", "key_concepts", "activities", "checklist_items",
                "tasks", "scenarios", "quizzes", "assessments", "completion_criteria")
_ASSEMBLY_ERRORS = frozenset({"SOURCE_REFS_OUT_OF_BOUNDS", "DEPENDENCY_CYCLE", "RRM_STAGE_NOT_IN_ACTIVE_SET"})


def _loc(path: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in path.split("."))


def _structural(code: str, request_id: UUID, path: str, reason: str, **details) -> StructuralFailure:
    """Log one structured, content-free diagnostic and return the failure to raise.

    Only our own field names, indexes, counts, categories and numeric stage configuration are
    logged: never model text, document text, labels, employee values or raw responses.
    """
    record = {"path": path, "reason": reason, **details}
    _LOG.warning("generation_structural_failure run_id=%s code=%s details=%s",
                 request_id, code, json.dumps(record, sort_keys=True))
    layer = "content_assembly" if code == "ASSEMBLY_INPUT_INVALID" else "plan_structure"
    return StructuralFailure(code, ({"loc": _loc(path), "type": reason},),
                             failure_detail(layer, code, [{"loc": path, "type": reason, **details}]))


def assemble_content(text: str, snapshot: GenerationInputSnapshot, request_id: UUID,
                     version: str = CURRENT_CONTENT_VERSION) -> str:
    """Content-only (4.0.x): validate the model's prose-only response, then build the plan in Python.

    Missing, extra or duplicate requirement entries, blank text, a quiz without exactly three
    distinct options or an index outside 0-2 fail as SCHEMA_INVALID (duplicate JSON keys as
    MALFORMED_JSON); nothing is repaired. The assembled plan then goes through parse_plan.
    """
    size = len(text.encode("utf-8", errors="replace")) if text else 0
    if not text or not text.strip():
        raise StructuralFailure("EMPTY_RESPONSE", detail=failure_detail("content_json", "EMPTY_RESPONSE",
                                                                         received={"bytes": size}))
    if size > 2_000_000:
        raise StructuralFailure("RESPONSE_TOO_LARGE", detail=failure_detail("content_json", "RESPONSE_TOO_LARGE",
                                                                             received={"bytes": size}))
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except StructuralFailure:
        raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
            "content_json", "MALFORMED_JSON", [{"loc": "", "type": "duplicate_key_or_constant"}],
            received={"bytes": size})) from None
    except (ValueError, TypeError, RecursionError) as exc:
        raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
            "content_json", "MALFORMED_JSON", [{"loc": "", "type": "invalid_json" if isinstance(exc, ValueError)
                                                else "nesting_or_type"}], received={"bytes": size})) from None
    expected = list(requirement_keys(snapshot))
    shape = received_shape(decoded, size, expected)
    try:
        content = CONTENT_RESPONSE_MODELS[version].model_validate_json(json.dumps(decoded, ensure_ascii=False))
    except ValidationError as exc:
        records = _log_schema_invalid(exc, request_id)
        raise StructuralFailure("SCHEMA_INVALID", safe_validation_diagnostics(exc), failure_detail(
            "content_model", "SCHEMA_INVALID", records, shape, exc.error_count())) from None
    problems = [{"loc": ("requirements", key), "type": "missing_requirement_content"}
                for key in expected if key not in content.requirements]
    problems += [{"loc": ("requirements", "unknown_field"), "type": "unknown_requirement_key"}
                 for _ in set(content.requirements) - set(expected)]
    if problems:
        _LOG.warning("generation_content_invalid run_id=%s expected_count=%d actual_count=%d diagnostics=%s",
                     request_id, len(expected), len(content.requirements),
                     json.dumps([{"loc": ".".join(map(str, item["loc"])), "type": item["type"]}
                                 for item in problems[:20]]))
        raise StructuralFailure("SCHEMA_INVALID", tuple(problems[:5]), failure_detail(
            "requirement_keys", "SCHEMA_INVALID",
            [{"loc": ".".join(map(str, item["loc"])), "type": item["type"]} for item in problems], shape))
    try:
        plan = assemble_plan(content, snapshot, request_id)
    except ValueError as exc:
        # Deterministic input problems (normally blocked by preflight and the readiness gate).
        reason = str(exc) if str(exc) in _ASSEMBLY_ERRORS else "UNEXPECTED_ASSEMBLY_ERROR"
        raise _structural("ASSEMBLY_INPUT_INVALID", request_id, "assembly", reason.lower()) from None
    return json.dumps(plan, ensure_ascii=False)


def parse_plan(text: str, request_id: UUID, snapshot: GenerationInputSnapshot) -> OnboardingPlan:
    if not text or not text.strip():
        raise StructuralFailure("EMPTY_RESPONSE", detail=failure_detail("plan_json", "EMPTY_RESPONSE"))
    try:
        response_bytes = text.encode("utf-8")
    except UnicodeError:
        raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
            "plan_json", "MALFORMED_JSON", [{"loc": "", "type": "invalid_unicode"}])) from None
    if len(response_bytes) > 2_000_000:
        raise StructuralFailure("RESPONSE_TOO_LARGE", detail=failure_detail(
            "plan_json", "RESPONSE_TOO_LARGE", received={"bytes": len(response_bytes)}))
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        # JSON-mode Pydantic parsing preserves strict primitives while accepting UUID/date JSON strings.
        plan = OnboardingPlan.model_validate_json(json.dumps(decoded, ensure_ascii=False))
    except RecursionError:
        # Pathologically nested JSON exhausts the decoder stack; it is malformed output, not a crash.
        raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
            "plan_json", "MALFORMED_JSON", [{"loc": "", "type": "nesting_too_deep"}])) from None
    except (ValueError, TypeError, ValidationError) as exc:
        if isinstance(exc, StructuralFailure):
            raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
                "plan_json", "MALFORMED_JSON", [{"loc": "", "type": "duplicate_key_or_constant"}])) from None
        if isinstance(exc, ValidationError):
            records = _log_schema_invalid(exc, request_id)
            raise StructuralFailure("SCHEMA_INVALID", safe_validation_diagnostics(exc), failure_detail(
                "onboarding_plan", "SCHEMA_INVALID", records, received={"bytes": len(response_bytes)},
                error_count=exc.error_count())) from None
        raise StructuralFailure("MALFORMED_JSON", detail=failure_detail(
            "plan_json", "MALFORMED_JSON", [{"loc": "", "type": "invalid_json"}])) from None
    if plan.generation_request_id != request_id:
        raise _structural("REQUEST_ID_MISMATCH", request_id, "generation_request_id", "request_id_differs",
                          expected="reserved_run_id", actual="other_uuid")
    context = plan.employee_context
    employee = snapshot.employee
    differing = [name for name, actual, frozen in (
        ("employee_id", context.employee_id, employee.employee_id), ("role_id", context.role_id, employee.role_id),
        ("department_id", context.department_id, employee.department_id),
        ("experience_level", context.experience_level, employee.experience),
        ("location_code", context.location_code, employee.location_code),
        ("joining_date", context.joining_date, employee.joining_date)) if actual != frozen]
    if differing:
        raise _structural("CONTEXT_IDENTITY_MISMATCH", request_id, "employee_context", "identity_fields_differ",
                          fields=differing)
    expected = snapshot.stage_set.items
    expected_ids = [stage.stage_definition_id for stage in expected]
    actual_ids = [stage.stage_id for stage in plan.plan.stages]
    mismatches = []
    for index, (actual, stage) in enumerate(zip(plan.plan.stages, expected)):
        fields = []
        if actual.stage_id != stage.stage_definition_id:
            fields.append("stage_id:" + ("other_frozen_stage" if actual.stage_id in expected_ids else "unknown_stage"))
        if actual.label != stage.label:
            fields.append("label")
        for name, value, frozen in (("sequence", actual.sequence, stage.sequence),
                                    ("target_start_day", actual.target_start_day, stage.start_day),
                                    ("target_end_day", actual.target_end_day, stage.end_day)):
            if value != frozen:
                fields.append(f"{name}:expected={frozen},actual={value}")
        if fields:
            mismatches.append({"index": index, "fields": fields})
    if len(actual_ids) != len(expected_ids) or mismatches:
        raise _structural(
            "STAGE_CONTRACT_MISMATCH", request_id, "plan.stages", "stage_contract",
            expected_count=len(expected_ids), actual_count=len(actual_ids),
            missing_expected_indexes=[i for i, sid in enumerate(expected_ids) if sid not in actual_ids],
            unknown_actual_indexes=[i for i, sid in enumerate(actual_ids) if sid not in expected_ids],
            mismatches=mismatches[:10])
    allowed_requirements = {item.revision_id for item in snapshot.requirements}
    allowed_sources = {(ref.document_version_id, ref.chunk_id): canonical_json(ref.locator)
                       for item in snapshot.requirements for ref in item.evidence}
    stages = {stage.stage_definition_id for stage in expected}
    for si, stage in enumerate(plan.plan.stages):
        for mi, module in enumerate(stage.modules):
            base = f"plan.stages.{si}.modules.{mi}"
            items = [(base, module)]
            for field in _ITEM_FIELDS:
                items.extend((f"{base}.{field}.{k}", item) for k, item in enumerate(getattr(module, field)))
            for ai, assessment in enumerate(module.assessments):
                items.extend((f"{base}.assessments.{ai}.rubric.{k}", row) for k, row in enumerate(assessment.rubric))
            for path, item in items:
                for r, ref in enumerate(item.requirement_ids):
                    if ref not in allowed_requirements:
                        raise _structural("UNKNOWN_REQUIREMENT_REF", request_id, f"{path}.requirement_ids.{r}",
                                          "not_in_frozen_requirements")
                for r, ref in enumerate(item.source_refs):
                    frozen = allowed_sources.get((ref.document_version_id, ref.chunk_id))
                    if frozen != ref.locator:
                        raise _structural("UNKNOWN_SOURCE_REF", request_id, f"{path}.source_refs.{r}",
                                          "unknown_version_or_chunk" if frozen is None else "locator_differs")
            for field in ("checklist_items", "tasks"):
                for k, item in enumerate(getattr(module, field)):
                    if item.due_stage_id not in stages:
                        raise _structural("UNKNOWN_STAGE_REF", request_id, f"{base}.{field}.{k}.due_stage_id",
                                          "not_a_frozen_stage")
    for index, item in enumerate(plan.insufficient_information):
        if item.requirement_id is not None and item.requirement_id not in allowed_requirements:
            raise _structural("UNKNOWN_REQUIREMENT_REF", request_id,
                              f"insufficient_information.{index}.requirement_id", "not_in_frozen_requirements")
    return plan


SAFE_PROVIDER_ERRORS = frozenset({
    "GENERATION_PROJECTION_TOO_LARGE",
    "PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE", "PROVIDER_AUTH_FAILED",
    "PROVIDER_CONFIGURATION_FAILED", "PROVIDER_REQUEST_FAILED", "PROVIDER_RESPONSE_TOO_LARGE",
    "PROVIDER_ACCESS_DENIED", "PROVIDER_PAYMENT_REQUIRED", "PROVIDER_DEADLINE_EXCEEDED",
    "PROVIDER_RESPONSE_REJECTED", "PROVIDER_INVALID_RESPONSE", "PROVIDER_TRUNCATED",
})
STRUCTURAL_PROVIDER_ERRORS = {"PROVIDER_TRUNCATED", "PROVIDER_INVALID_RESPONSE"}
# Transient 5xx/timeout/429: at most 3 attempts, exponential backoff (2s, 4s), honouring
# a longer Retry-After up to the cap. Every attempt is persisted via on_attempt.
MAX_TRANSPORT_RETRIES = 2
# Whole-run budget: a retry is skipped when elapsed time plus one full provider
# deadline would exceed it, so a slow model cannot chain two long calls.
RUN_BUDGET_SECONDS = 295.0  # one full 290 s call fits; a second long call never does


def structural_retry_window(call_deadline: float) -> float:
    """Seconds within which a first call must finish for a format retry to be attempted.

    budget_allows() requires elapsed + call_deadline <= RUN_BUDGET_SECONDS before retrying,
    so a retry happens only if the first attempt ended within RUN_BUDGET_SECONDS -
    call_deadline. With the 290 s NaraRouter deadline that window is 5 s, while observed
    responses take 69-290 s: in practice every structural failure is final. Kept as is on
    purpose until a retry policy is chosen after the first successful 4.0.x generation.
    """
    return max(0.0, RUN_BUDGET_SECONDS - call_deadline)
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 8.0


async def generate_unverified(
    preflight: PreflightResult, request_id: UUID, provider: GenerationProvider,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_attempt: Callable[[AttemptTelemetry], Awaitable[None]] | None = None,
    source_keys: bool | None = None,
    prompt_version: str | None = None,
) -> GenerationResult:
    """The API passes the reserved prompt_version; otherwise source_keys/GENERATION_SOURCE_KEYS decide."""
    if preflight.status != "READY" or preflight.snapshot is None or preflight.input_hash is None:
        return GenerationResult(status="BLOCKED", error_code=preflight.blocker_codes[0]
                                if preflight.blocker_codes else "PREFLIGHT_BLOCKED")
    snapshot = preflight.snapshot
    if input_hash(snapshot) != preflight.input_hash:
        return GenerationResult(status="BLOCKED", error_code="INPUT_HASH_MISMATCH")
    prompt = build_prompt(snapshot, request_id, source_keys, version=prompt_version)
    # Derived from the same frozen snapshot as the prompt's evidence table; never live data.
    keys = source_key_map(snapshot) if prompt.prompt_version in SOURCE_KEY_PROMPT_VERSIONS else None
    if not prompt.within_budget:
        return GenerationResult(status="FAILED", error_code="GENERATION_PROJECTION_TOO_LARGE",
                                input_hash=preflight.input_hash, prompt_version=prompt.prompt_version,
                                template_hash=prompt.template_hash)
    calls = 0
    transport_retries = 0
    attempt_prompt = prompt
    run_started = perf_counter()
    call_deadline = getattr(getattr(provider, "config", None), "timeout_seconds", 0) or 0

    def budget_allows(extra_delay: float = 0.0) -> bool:
        allowed = perf_counter() - run_started + extra_delay + call_deadline <= RUN_BUDGET_SECONDS
        if not allowed:
            _LOG.warning("generation_run_budget_exhausted request_id=%s elapsed_s=%.1f call_deadline_s=%.0f",
                         request_id, perf_counter() - run_started, call_deadline)
        return allowed
    for format_attempt in range(2):
        first_in_format = True
        while True:
            calls += 1
            attempt_type = "INITIAL" if calls == 1 else "FORMAT_RETRY" if first_in_format else "TRANSPORT_RETRY"
            first_in_format = False
            started = perf_counter()
            try:
                response = await provider.generate(attempt_prompt, format_retry=bool(format_attempt))
                if response.finish_reason != "STOP":
                    code = "TRUNCATED_RESPONSE" if response.finish_reason == "MAX_TOKENS" else "PROVIDER_RESPONSE_REJECTED"
                    raise StructuralFailure(code, detail=failure_detail("provider_response", code))
                if prompt.prompt_version in CONTENT_PROMPT_VERSIONS:
                    text = assemble_content(response.text, snapshot, request_id, prompt.prompt_version)
                elif keys is not None:
                    text = expand_source_keys(response.text, keys, request_id)
                else:
                    text = response.text
                plan = parse_plan(text, request_id, snapshot)
            except ProviderFailure as exc:
                code = exc.code if exc.code in SAFE_PROVIDER_ERRORS else "PROVIDER_UNAVAILABLE"
                if on_attempt:
                    await on_attempt(AttemptTelemetry(
                        attempt_type=attempt_type,
                        provider_outcome={"PROVIDER_TIMEOUT": "TIMEOUT", "PROVIDER_DEADLINE_EXCEEDED": "TIMEOUT", "PROVIDER_RATE_LIMIT": "RATE_LIMIT",
                                          "PROVIDER_UNAVAILABLE": "UNAVAILABLE"}.get(code, "REJECTED"),
                        latency_ms=min(int((perf_counter() - started) * 1000), 600000),
                        parse_outcome="NOT_PARSED", error_code=code))
                if exc.retryable and transport_retries < MAX_TRANSPORT_RETRIES:
                    transport_retries += 1
                    delay = min(max(exc.retry_after_seconds or 0.0,
                                    RETRY_BASE_SECONDS * 2 ** (transport_retries - 1)), RETRY_MAX_SECONDS)
                    if not budget_allows(delay):
                        return GenerationResult(status="FAILED", error_code=code, provider_calls=calls)
                    _LOG.warning("generation_provider_retry request_id=%s code=%s retry=%d/%d delay_s=%.1f",
                                 request_id, code, transport_retries, MAX_TRANSPORT_RETRIES, delay)
                    await sleep(delay)
                    continue
                if code in STRUCTURAL_PROVIDER_ERRORS and format_attempt == 0 and budget_allows():
                    break
                return GenerationResult(status="FAILED", error_code=code, provider_calls=calls)
            except StructuralFailure as exc:
                if on_attempt:
                    # Invalid Unicode has no valid UTF-8 fingerprint. Do not repair
                    # the response or lose the failure attempt while hashing it.
                    try:
                        response_bytes = response.text.encode("utf-8")
                    except UnicodeError:
                        response_bytes = None
                    await on_attempt(AttemptTelemetry(
                        attempt_type=attempt_type, provider_outcome="RESPONSE",
                        latency_ms=min(int((perf_counter() - started) * 1000), 600000),
                        response_hash=sha256(response_bytes).hexdigest() if response_bytes is not None else None,
                        response_size=len(response_bytes) if response_bytes is not None else None, parse_outcome="SCHEMA_INVALID",
                        error_code=exc.code, usage=usage_metadata(response), diagnostics=exc.detail))
                if format_attempt == 0 and exc.code in {"EMPTY_RESPONSE", "MALFORMED_JSON", "SCHEMA_INVALID",
                                                       "TRUNCATED_RESPONSE", "RESPONSE_TOO_LARGE"} and budget_allows():
                    attempt_prompt = prompt.model_copy(update={"rules": prompt.rules + "\n" + retry_feedback(exc)})
                    break
                return GenerationResult(status="FAILED", error_code=exc.code, provider_calls=calls)
            except Exception:
                return GenerationResult(status="FAILED", error_code="GENERATION_INTERNAL_ERROR", provider_calls=calls)
            else:
                # Persistence failures must propagate: never report a terminal result
                # after dropping a successfully parsed attempt's provenance.
                if on_attempt:
                    await on_attempt(AttemptTelemetry(
                        attempt_type=attempt_type, provider_outcome="RESPONSE",
                        latency_ms=min(int((perf_counter() - started) * 1000), 600000),
                        response_hash=sha256(response.text.encode("utf-8")).hexdigest(),
                        response_size=len(response.text.encode("utf-8")), parse_outcome="SCHEMA_VALID",
                        usage=usage_metadata(response)))
                return GenerationResult(status="UNVERIFIED", plan=plan, input_hash=preflight.input_hash,
                                        prompt_version=prompt.prompt_version, template_hash=prompt.template_hash,
                                        provider_calls=calls)
    return GenerationResult(status="FAILED", error_code="SCHEMA_INVALID", provider_calls=calls)
