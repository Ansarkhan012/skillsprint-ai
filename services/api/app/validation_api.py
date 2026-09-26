"""Phase 5 requests contain identities or human actions, never validator conclusions."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException

from .models import AppRole, Principal
from .security import require_roles
from .validation_models import ReviewRequest
from .validation_repository import ValidationRepository, get_validation_repository
from .validation_service import validate_persisted_plan

router = APIRouter(prefix="/api/v1", tags=["validation"])
AUTHOR = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)
READ = require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER)
REVIEW = require_roles(AppRole.ADMIN, AppRole.REVIEWER)


@router.post("/generated-plans/{plan_id}/validate")
async def validate(plan_id: UUID, principal: Principal = Depends(AUTHOR),
                   repository: ValidationRepository = Depends(get_validation_repository)):
    return await validate_persisted_plan(principal, plan_id, repository)


@router.get("/validation-runs/{validation_id}")
async def detail(validation_id: UUID, principal: Principal = Depends(READ),
                 repository: ValidationRepository = Depends(get_validation_repository)):
    return await repository.read(principal.token, validation_id=validation_id)


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
