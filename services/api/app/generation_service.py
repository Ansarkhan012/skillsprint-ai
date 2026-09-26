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

from .generation_context import input_hash
from .generation_models import GenerationInputSnapshot, PreflightResult
from .generation_output import OnboardingPlan
from .generation_prompt import build_prompt
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
})


def safe_validation_diagnostics(error: ValidationError) -> tuple[dict[str, object], ...]:
    """Only schema path/type; never model input, context, message or response text."""
    diagnostics = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:5]:
        path = []
        for part in item.get("loc", ())[:8]:
            path.append(part if isinstance(part, int) and 0 <= part <= 100
                        else part if isinstance(part, str) and part in _SAFE_FIELD_NAMES
                        else "unknown_field")
        kind = item.get("type", "unknown")
        diagnostics.append({"loc": tuple(path), "type": kind if isinstance(kind, str)
                            and re.fullmatch(r"[a-z_]{1,64}", kind) else "unknown"})
    return tuple(diagnostics)


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


class StructuralFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StructuralFailure("MALFORMED_JSON")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise StructuralFailure("MALFORMED_JSON")


def parse_plan(text: str, request_id: UUID, snapshot: GenerationInputSnapshot) -> OnboardingPlan:
    if not text or not text.strip():
        raise StructuralFailure("EMPTY_RESPONSE")
    if len(text.encode("utf-8")) > 2_000_000:
        raise StructuralFailure("RESPONSE_TOO_LARGE")
    try:
        decoded = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        # JSON-mode Pydantic parsing preserves strict primitives while accepting UUID/date JSON strings.
        plan = OnboardingPlan.model_validate_json(json.dumps(decoded, ensure_ascii=False))
    except (ValueError, TypeError, ValidationError) as exc:
        if isinstance(exc, StructuralFailure):
            raise
        if isinstance(exc, ValidationError):
            _LOG.warning("generation_schema_invalid request_id=%s diagnostics=%s",
                         request_id, safe_validation_diagnostics(exc))
        raise StructuralFailure("SCHEMA_INVALID" if isinstance(exc, ValidationError) else "MALFORMED_JSON") from None
    if plan.generation_request_id != request_id:
        raise StructuralFailure("REQUEST_ID_MISMATCH")
    context = plan.employee_context
    employee = snapshot.employee
    if (context.employee_id != employee.employee_id or context.role_id != employee.role_id
            or context.department_id != employee.department_id or context.experience_level != employee.experience
            or context.location_code != employee.location_code or context.joining_date != employee.joining_date):
        raise StructuralFailure("CONTEXT_IDENTITY_MISMATCH")
    expected = snapshot.stage_set.items
    if len(plan.plan.stages) != len(expected) or any(
            (actual.stage_id, actual.label, actual.sequence, actual.target_start_day, actual.target_end_day)
            != (stage.stage_definition_id, stage.label, stage.sequence, stage.start_day, stage.end_day)
            for actual, stage in zip(plan.plan.stages, expected)):
        raise StructuralFailure("STAGE_CONTRACT_MISMATCH")
    allowed_requirements = {item.revision_id for item in snapshot.requirements}
    allowed_sources = {(ref.document_version_id, ref.chunk_id): canonical_json(ref.locator)
                       for item in snapshot.requirements for ref in item.evidence}
    stages = {stage.stage_definition_id for stage in expected}
    for stage in plan.plan.stages:
        for module in stage.modules:
            items = [module]
            for field in ("learning_objectives", "key_concepts", "activities", "checklist_items",
                          "tasks", "scenarios", "quizzes", "assessments", "completion_criteria"):
                items.extend(getattr(module, field))
            for assessment in module.assessments:
                items.extend(assessment.rubric)
            for item in items:
                if any(ref not in allowed_requirements for ref in item.requirement_ids):
                    raise StructuralFailure("UNKNOWN_REQUIREMENT_REF")
                if any(allowed_sources.get((ref.document_version_id, ref.chunk_id)) != ref.locator
                       for ref in item.source_refs):
                    raise StructuralFailure("UNKNOWN_SOURCE_REF")
            for item in (*module.checklist_items, *module.tasks):
                if item.due_stage_id not in stages:
                    raise StructuralFailure("UNKNOWN_STAGE_REF")
    for item in plan.insufficient_information:
        if item.requirement_id is not None and item.requirement_id not in allowed_requirements:
            raise StructuralFailure("UNKNOWN_REQUIREMENT_REF")
    return plan


SAFE_PROVIDER_ERRORS = frozenset({
    "GENERATION_PROJECTION_TOO_LARGE",
    "PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE", "PROVIDER_AUTH_FAILED",
    "PROVIDER_CONFIGURATION_FAILED", "PROVIDER_REQUEST_FAILED", "PROVIDER_RESPONSE_TOO_LARGE",
    "PROVIDER_RESPONSE_REJECTED", "PROVIDER_INVALID_RESPONSE", "PROVIDER_TRUNCATED",
})
STRUCTURAL_PROVIDER_ERRORS = {"PROVIDER_TRUNCATED", "PROVIDER_INVALID_RESPONSE"}


async def generate_unverified(
    preflight: PreflightResult, request_id: UUID, provider: GenerationProvider,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_attempt: Callable[[AttemptTelemetry], Awaitable[None]] | None = None,
) -> GenerationResult:
    if preflight.status != "READY" or preflight.snapshot is None or preflight.input_hash is None:
        return GenerationResult(status="BLOCKED", error_code=preflight.blocker_codes[0]
                                if preflight.blocker_codes else "PREFLIGHT_BLOCKED")
    snapshot = preflight.snapshot
    if input_hash(snapshot) != preflight.input_hash:
        return GenerationResult(status="BLOCKED", error_code="INPUT_HASH_MISMATCH")
    prompt = build_prompt(snapshot, request_id)
    if not prompt.within_budget:
        return GenerationResult(status="FAILED", error_code="GENERATION_PROJECTION_TOO_LARGE",
                                input_hash=preflight.input_hash, prompt_version=prompt.prompt_version,
                                template_hash=prompt.template_hash)
    calls = 0
    transport_retries = 0
    rate_limit_retries = 0
    for format_attempt in range(2):
        first_in_format = True
        while True:
            calls += 1
            attempt_type = "INITIAL" if calls == 1 else "FORMAT_RETRY" if first_in_format else "TRANSPORT_RETRY"
            first_in_format = False
            started = perf_counter()
            try:
                response = await provider.generate(prompt, format_retry=bool(format_attempt))
                if response.finish_reason != "STOP":
                    raise StructuralFailure("TRUNCATED_RESPONSE" if response.finish_reason == "MAX_TOKENS"
                                            else "PROVIDER_RESPONSE_REJECTED")
                plan = parse_plan(response.text, request_id, snapshot)
            except ProviderFailure as exc:
                code = exc.code if exc.code in SAFE_PROVIDER_ERRORS else "PROVIDER_UNAVAILABLE"
                if on_attempt:
                    await on_attempt(AttemptTelemetry(
                        attempt_type=attempt_type,
                        provider_outcome={"PROVIDER_TIMEOUT": "TIMEOUT", "PROVIDER_RATE_LIMIT": "RATE_LIMIT",
                                          "PROVIDER_UNAVAILABLE": "UNAVAILABLE"}.get(code, "REJECTED"),
                        latency_ms=min(int((perf_counter() - started) * 1000), 600000),
                        parse_outcome="NOT_PARSED", error_code=code))
                if (code == "PROVIDER_RATE_LIMIT" and exc.retryable
                        and exc.retry_after_seconds is not None
                        and 0.5 <= exc.retry_after_seconds <= 2.0
                        and rate_limit_retries == 0 and transport_retries < 2):
                    rate_limit_retries += 1
                    transport_retries += 1
                    await sleep(exc.retry_after_seconds)
                    continue
                if code != "PROVIDER_RATE_LIMIT" and exc.retryable and transport_retries < 2:
                    transport_retries += 1
                    await sleep(0.25 * (2 ** (transport_retries - 1)))
                    continue
                if code in STRUCTURAL_PROVIDER_ERRORS and format_attempt == 0:
                    break
                return GenerationResult(status="FAILED", error_code=code, provider_calls=calls)
            except StructuralFailure as exc:
                if on_attempt:
                    await on_attempt(AttemptTelemetry(
                        attempt_type=attempt_type, provider_outcome="RESPONSE",
                        latency_ms=min(int((perf_counter() - started) * 1000), 600000),
                        response_hash=sha256(response.text.encode("utf-8")).hexdigest(),
                        response_size=len(response.text.encode("utf-8")), parse_outcome="SCHEMA_INVALID",
                        error_code=exc.code))
                if format_attempt == 0 and exc.code in {"EMPTY_RESPONSE", "MALFORMED_JSON", "SCHEMA_INVALID",
                                                       "TRUNCATED_RESPONSE", "RESPONSE_TOO_LARGE"}:
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
                        response_size=len(response.text.encode("utf-8")), parse_outcome="SCHEMA_VALID"))
                return GenerationResult(status="UNVERIFIED", plan=plan, input_hash=preflight.input_hash,
                                        prompt_version=prompt.prompt_version, template_hash=prompt.template_hash,
                                        provider_calls=calls)
    return GenerationResult(status="FAILED", error_code="SCHEMA_INVALID", provider_calls=calls)
