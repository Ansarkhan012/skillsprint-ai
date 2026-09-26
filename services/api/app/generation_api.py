"""Phase 4C synchronous generation API. Never assigns or verifies a plan."""

from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .generation_context import preflight
from .generation_persistence import GenerationStore, get_generation_store
from .generation_prompt import PROMPT_VERSION, SCHEMA_VERSION, build_prompt, template_hash
from .generation_provider import (GeminiEnvironment, GeminiProvider, GroqEnvironment, GroqProvider,
                                  GenerationProvider, ProviderConfig, ProviderFailure)
from .generation_service import generate_unverified
from .models import AppRole, Principal
from .rrm_rules import snapshot_hash
from .security import require_roles


router = APIRouter(prefix="/api/v1", tags=["generation"])
AUTHOR = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)
READ = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER)
ADMIN = require_roles(AppRole.ADMIN)


class GenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: UUID


class GenerationPreflightResponse(BaseModel):
    readiness: Literal["READY", "BLOCKED"]
    employee_id: UUID
    blocker_codes: list[str]
    matrix_id: UUID | None = None
    matrix_revision: int | None = None
    stage_set_id: UUID | None = None
    stage_set_version: int | None = None
    requirement_count: int | None = None
    dependency_count: int | None = None
    input_hash: str | None = None


def get_provider_bundle(request: Request) -> tuple[GenerationProvider, ProviderConfig]:
    try:
        selection = GeminiEnvironment().ai_provider
        if selection == "gemini":
            config = GeminiEnvironment().adapter_config()
            return GeminiProvider(request.app.state.supabase_http, config), config
        if selection == "groq":
            config = GroqEnvironment().adapter_config()
            return GroqProvider(request.app.state.supabase_http, config), config
        raise ProviderFailure("PROVIDER_CONFIGURATION_FAILED")
    except ProviderFailure:
        raise HTTPException(503, "GENERATION_PROVIDER_NOT_CONFIGURED") from None


@router.post("/onboarding-stage-sets/bootstrap", status_code=201)
async def bootstrap_stage_set(principal: Principal = Depends(ADMIN),
                              store: GenerationStore = Depends(get_generation_store)) -> dict:
    result = await store.rpc(principal.token, "bootstrap_standard_onboarding_stages", {})
    return {"stage_set_id": result, "configuration_not_policy": True}


@router.get("/generation-runs/preflight/{employee_id}", response_model=GenerationPreflightResponse)
async def generation_preflight(
    employee_id: UUID,
    principal: Principal = Depends(AUTHOR),
    store: GenerationStore = Depends(get_generation_store),
) -> GenerationPreflightResponse:
    result = await preflight(principal, employee_id, store, datetime.now(timezone.utc))
    if result.status == "BLOCKED":
        return GenerationPreflightResponse(readiness="BLOCKED", employee_id=employee_id,
                                           blocker_codes=list(result.blocker_codes))
    if result.snapshot is None or result.input_hash is None:
        raise HTTPException(503, "PREFLIGHT_UNAVAILABLE")
    snapshot = result.snapshot
    return GenerationPreflightResponse(
        readiness="READY", employee_id=employee_id, blocker_codes=[],
        matrix_id=snapshot.matrix_id, matrix_revision=snapshot.matrix_revision,
        stage_set_id=snapshot.stage_set.id, stage_set_version=snapshot.stage_set.version,
        requirement_count=len(snapshot.requirements), dependency_count=len(snapshot.dependencies),
        input_hash=result.input_hash,
    )


@router.post("/generation-runs", status_code=202)
async def create_generation(
    data: GenerationCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(AUTHOR),
    store: GenerationStore = Depends(get_generation_store),
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
        raise HTTPException(422, "INVALID_IDEMPOTENCY_KEY")
    first = await preflight(principal, data.employee_id, store, datetime.now(timezone.utc))
    if first.status != "READY" or first.snapshot is None:
        raise HTTPException(409, first.blocker_codes[0] if first.blocker_codes else "PREFLIGHT_BLOCKED")
    prompt = build_prompt(first.snapshot)
    provider, config = get_provider_bundle(request)
    reserved = await store.reserve(principal.token, {
        "p_employee": str(data.employee_id), "p_input": first.snapshot.model_dump(mode="json"),
        "p_input_hash": first.input_hash,
        "p_idempotency_key_hash": sha256(idempotency_key.encode("utf-8")).hexdigest(),
        "p_provider": config.provider, "p_model": config.model,
        "p_provider_config": {"temperature": config.temperature,
                              "max_output_tokens": config.max_output_tokens,
                              "timeout_seconds": config.timeout_seconds,
                              "projection_hash": prompt.projection_hash},
        "p_prompt_version": PROMPT_VERSION, "p_template_hash": template_hash(),
        "p_schema_version": SCHEMA_VERSION,
    })
    run_id = UUID(reserved["id"])
    if reserved["status"] != "QUEUED" or not await store.claim(principal.token, run_id):
        return {"id": str(run_id), "status": reserved["status"], "idempotent_replay": True}

    async def record(item):
        await store.record_attempt(principal.token, run_id, item)

    result = await generate_unverified(first, run_id, provider, on_attempt=record)
    if result.status != "UNVERIFIED" or result.plan is None:
        status = await store.finish(principal.token, run_id, None, None, None,
                                    result.error_code or "GENERATION_INTERNAL_ERROR")
        return {"id": str(run_id), "status": status, "error_code": result.error_code}
    second = await preflight(principal, data.employee_id, store, datetime.now(timezone.utc))
    if second.status != "READY":
        if second.blocker_codes and second.blocker_codes[0] in {
            "NO_APPROVED_MATRIX", "STALE_MATRIX", "STALE_SOURCE", "NO_ACTIVE_STAGE_SET",
            "RRM_STAGE_NOT_IN_ACTIVE_SET", "MISSING_EMPLOYEE_CONTEXT", "INVALID_DEPENDENCY",
            "UNRESOLVED_CONFLICT", "UNRESOLVED_REVIEW_ISSUE", "AMBIGUOUS_TIMING",
        }:
            post_hash = None
        else:
            status = await store.finish(principal.token, run_id, None, None, None, "POSTFLIGHT_UNAVAILABLE")
            return {"id": str(run_id), "status": status, "error_code": "POSTFLIGHT_UNAVAILABLE"}
    else:
        post_hash = second.input_hash
    content = result.plan.model_dump(mode="json")
    status = await store.finish(principal.token, run_id, post_hash, content, snapshot_hash(content), None)
    return {"id": str(run_id), "status": status, "idempotent_replay": False}


@router.get("/generation-runs")
async def list_generations(offset: int = 0, limit: int = 30,
                           employee_id: UUID | None = None,
                           principal: Principal = Depends(READ),
                           store: GenerationStore = Depends(get_generation_store)) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "INVALID_PAGE")
    if employee_id is not None:
        return await store.list_runs(principal.token, offset, limit, employee_id=employee_id)
    return await store.list_runs(principal.token, offset, limit)


@router.get("/generation-runs/{run_id}")
async def generation_detail(run_id: UUID, principal: Principal = Depends(READ),
                            store: GenerationStore = Depends(get_generation_store)) -> dict:
    return await store.detail(principal.token, run_id)
