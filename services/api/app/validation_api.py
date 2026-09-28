"""Phase 5 requests contain identities or human actions, never validator conclusions."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError

from .comparison_report import comparison_rows, to_csv
from .generation_models import GenerationInputSnapshot

from .models import AppRole, Principal
from .security import require_roles
from .validation_models import ReviewRequest
from .validation_repository import ValidationRepository, get_validation_repository
from .validation_service import validate_persisted_plan

router = APIRouter(prefix="/api/v1", tags=["validation"])
AUTHOR = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)
READ = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER)
REVIEW = require_roles(AppRole.ADMIN, AppRole.REVIEWER)


@router.get("/validation-runs")
async def list_validations(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
                          principal: Principal = Depends(READ),
                          repository: ValidationRepository = Depends(get_validation_repository)):
    return await repository.list_runs(principal.token, offset, limit)


@router.post("/generated-plans/{plan_id}/validate")
async def validate(plan_id: UUID, principal: Principal = Depends(AUTHOR),
                   repository: ValidationRepository = Depends(get_validation_repository)):
    return await validate_persisted_plan(principal, plan_id, repository)


@router.get("/validation-runs/{validation_id}")
async def detail(validation_id: UUID, principal: Principal = Depends(READ),
                 repository: ValidationRepository = Depends(get_validation_repository)):
    return await repository.read(principal.token, validation_id=validation_id)


@router.get("/validation-runs/{validation_id}/comparison.csv")
async def comparison_csv(validation_id: UUID, principal: Principal = Depends(READ),
                         repository: ValidationRepository = Depends(get_validation_repository)) -> Response:
    """GenAI vs Python requirement-level comparison, built only from persisted evidence."""
    result = await repository.read(principal.token, validation_id=validation_id)
    plan, run = await repository.load_plan(principal.token, UUID(result["generated_plan_id"]))
    try:
        snapshot = GenerationInputSnapshot.model_validate(run["input_snapshot"])
    except (ValidationError, KeyError, TypeError):
        raise HTTPException(409, "VALIDATION_PROVENANCE_INVALID") from None
    rows = comparison_rows(snapshot, plan["content"], result["findings"], result["decision"]["status"])
    # Leading BOM lets Excel detect UTF-8 (SRS Step 63: Excel-compatible CSV).
    return Response(chr(0xFEFF) + to_csv(rows), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="comparison-{validation_id}.csv"'})


@router.get("/generated-plans/{plan_id}/validation")
async def plan_validation(plan_id: UUID, principal: Principal = Depends(READ),
                          repository: ValidationRepository = Depends(get_validation_repository)):
    return await repository.read(principal.token, plan_id=plan_id)


@router.post("/validation-runs/{validation_id}/review")
async def review(validation_id: UUID, request: ReviewRequest, principal: Principal = Depends(REVIEW),
                 repository: ValidationRepository = Depends(get_validation_repository)):
    if request.action == "OVERRIDE" and AppRole.ADMIN not in principal.profile.roles:
        raise HTTPException(403, "VALIDATION_FORBIDDEN")
    return await repository.review(principal.token, validation_id, request)
