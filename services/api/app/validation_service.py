"""Independent validation orchestration; no generation/provider imports."""
from datetime import datetime, timezone
import re
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

from .generation_context import input_hash, preflight
from .generation_models import GenerationInputSnapshot
from .jev import decide
from .models import AppRole
from .plan_validator import validate_plan
from .rrm_rules import snapshot_hash


async def validate_persisted_plan(principal, plan_id, repository):
    if principal.profile.status != "ACTIVE" or not principal.profile.roles & {AppRole.ADMIN, AppRole.TRAINING_MANAGER}:
        raise HTTPException(403, "FORBIDDEN_ROLE")
    plan, run = await repository.load_plan(principal.token, plan_id)
    if (plan["status"] != "UNVERIFIED" or run["status"] != "UNVERIFIED" or not run.get("completed_at")
            or plan["schema_version"] != "onboarding-plan/1.0.0" or plan["run_id"] != run["id"]):
        raise HTTPException(409, "VALIDATION_REQUIRES_UNVERIFIED_PLAN")
    if AppRole.ADMIN not in principal.profile.roles and str(principal.profile.id) != run["created_by"]:
        raise HTTPException(403, "VALIDATION_FORBIDDEN")
    try:
        frozen = GenerationInputSnapshot.model_validate(run["input_snapshot"])
        if (input_hash(frozen) != run["input_hash"] or snapshot_hash(plan["content"]) != plan["content_hash"]
                or str(frozen.employee.employee_id) != run["employee_id"]
                or run["schema_version"] != plan["schema_version"]
                or not all(isinstance(run.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", run[key])
                           for key in ("input_hash", "projection_hash", "template_hash"))
                or not all(run.get(key) for key in ("prompt_version", "provider", "model"))):
            raise ValueError("INVALID_PROVENANCE")
    except (ValidationError, ValueError, KeyError, TypeError):
        raise HTTPException(409, "VALIDATION_PROVENANCE_INVALID") from None
    started = datetime.now(timezone.utc)
    current = await preflight(principal, frozen.employee.employee_id, repository, started)
    if current.status == "BLOCKED" and any(code in {"GROUND_TRUTH_UNAVAILABLE", "GROUND_TRUTH_ACCESS_DENIED"}
                                          for code in current.blocker_codes):
        raise HTTPException(503, "VALIDATION_GROUND_TRUTH_UNAVAILABLE")
    # Compare substantive frozen data; advancing the calendar alone is not a mutation.
    # Current preflight has already rechecked date-sensitive source eligibility.
    current_matches = (current.status == "READY" and current.snapshot is not None
        and input_hash(current.snapshot.model_copy(update={"as_of": frozen.as_of})) == run["input_hash"])
    try:
        evidence = validate_plan(plan["content"], frozen, UUID(run["id"]), current_input=current_matches,
                                 stale_source="STALE_SOURCE" in current.blocker_codes)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "VALIDATION_CANNOT_COMPLETE") from None
    decision = decide(evidence)
    return await repository.persist(principal.profile.id, plan_id, {
        "validator_version": evidence.validator_version, "input_hash": run["input_hash"],
        "projection_hash": run["projection_hash"], "content_hash": plan["content_hash"],
        "started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence.model_dump(mode="json"), "decision": decision.model_dump(mode="json"),
    })
