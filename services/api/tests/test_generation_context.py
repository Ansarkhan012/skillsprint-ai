"""Phase 4A preflight fixtures: no Gemini, database, or live stage-set tables."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import pytest

from app.generation_context import (canonical_input, input_hash, preflight, prepare_generation_input,
                                    select_stage_set)
from app.generation_models import (ApprovedMatrixInput, EmployeeGenerationContext, StageSet, StageSetItem)
from app.generation_repository import GenerationRepository
from app.models import AppRole, Principal, Profile
from app.rrm_models import (DEFAULT_AUTHORITY_RANKS, Entry, PrecedenceConfig, Requirement, Scope,
                            Source, Timing)
from app.rrm_rules import RRMError

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
EMP, PROFILE, ROLE, DEPT, CHUNK, VERSION, DOC, REQ, MATRIX, STAGE = (UUID(int=i) for i in range(1, 11))


def employee(**changes):
    data = dict(employee_id=EMP, profile_id=PROFILE, role_id=ROLE, role_code="JUNIOR_DEV",
                department_id=DEPT, department_code="ENG", experience="BEGINNER",
                location_code="KHI", joining_date=date(2026, 9, 23))
    data.update(changes)
    return EmployeeGenerationContext(**data)


def stages(**changes):
    item = StageSetItem(stage_definition_id=STAGE, code="WEEK_1", revision=1,
                        label="Week 1", sequence=1, start_day=1, end_day=7)
    data = dict(id=UUID(int=20), code="DEFAULT", version=1, name="Default", status="ACTIVE", items=(item,))
    data.update(changes)
    return StageSet(**data)


def matrix(**changes):
    content = "Security Awareness Training | All Employees | Within 7 days"
    source = Source(chunk_id=CHUNK, version_id=VERSION, document_id=DOC, content=content,
                    text_hash=sha256(content.encode()).hexdigest(), source_location={"table": 1, "row": 2},
                    document_sha256="a" * 64, document_status="ACTIVE", parse_status="PARSED",
                    review_status="APPROVED", effective_date=date(2026, 9, 1), current_version_id=VERSION)
    req = Requirement(id=REQ, code="SECURITY_TRAINING", revision=2, predecessor_id=UUID(int=30),
                      statement="Security Awareness Training", requirement_type="MUST_COMPLETE",
                      category="POLICY", mandatory=True, timing=Timing(), scopes=(Scope(),),
                      chunk_ids=(CHUNK,), author_id=PROFILE)
    data = dict(id=MATRIX, role_id=ROLE, revision=1, edit=1, lock_version=2,
                status="APPROVED", snapshot_hash="b" * 64, requirements=(req,),
                entries=(Entry(requirement_id=REQ, sequence=1, stage_id=STAGE),),
                dependencies=(), sources={CHUNK: source},
                configuration=PrecedenceConfig(ranks=DEFAULT_AUTHORITY_RANKS,
                                               document_classes={DOC: "COMPANY_POLICY"}))
    data.update(changes)
    return ApprovedMatrixInput(**data)


def ready(m=None, e=None, s=None, at=NOW):
    return prepare_generation_input(e or employee(), m or matrix(), (s or stages(),), at)


def test_ready_preserves_exact_evidence_and_canonical_hash():
    result = ready()
    assert result.status == "READY"
    assert result.snapshot.context_schema_version == "generation-context/1.0.0"
    assert result.snapshot.stage_set.items[0].stage_definition_id == STAGE
    requirement = result.snapshot.requirements[0]
    assert (requirement.revision_id, requirement.code, requirement.mandatory, requirement.obligation_type) == (
        REQ, "SECURITY_TRAINING", True, "MUST_COMPLETE")
    assert requirement.evidence[0].document_id == DOC
    assert requirement.evidence[0].document_version_id == VERSION
    assert requirement.evidence[0].chunk_id == CHUNK
    assert requirement.evidence[0].locator == {"table": 1, "row": 2}
    assert requirement.evidence[0].text_hash == matrix().sources[CHUNK].text_hash
    assert result.input_hash == sha256(canonical_input(result.snapshot).encode()).hexdigest()
    assert ready(at=NOW + timedelta(hours=2)).input_hash == result.input_hash
    assert result.snapshot.as_of.isoformat() == "2026-09-24T00:00:00+00:00"
    assert "previous_experience_summary" not in canonical_input(result.snapshot)


@pytest.mark.parametrize("scope,context,expected", [
    (Scope(), employee(), "READY"),
    (Scope(role_id=ROLE), employee(), "READY"),
    (Scope(department_id=DEPT), employee(), "READY"),
    (Scope(location_code="KHI"), employee(), "READY"),
    (Scope(experience="BEGINNER"), employee(), "READY"),
    (Scope(role_id=ROLE, department_id=DEPT, location_code="KHI", experience="BEGINNER"), employee(), "READY"),
    (Scope(role_id=UUID(int=31)), employee(), "NO_APPLICABLE_REQUIREMENTS"),
    (Scope(location_code="KHI"), employee(location_code=None), "MISSING_EMPLOYEE_CONTEXT"),
])
def test_scope_resolution(scope, context, expected):
    base = matrix()
    req = base.requirements[0].model_copy(update={"scopes": (scope,)})
    result = ready(base.model_copy(update={"requirements": (req,)}), context)
    assert result.status == ("READY" if expected == "READY" else "BLOCKED")
    if expected != "READY":
        assert result.blocker_codes == (expected,)


@pytest.mark.parametrize("sets,code", [
    ((), "NO_ACTIVE_STAGE_SET"),
    ((stages(), stages(id=UUID(int=21))), "MULTIPLE_ACTIVE_STAGE_SETS"),
    ((stages(items=()),), "INVALID_STAGE_CONFIGURATION"),
    ((stages(items=(stages().items[0], stages().items[0])),), "INVALID_STAGE_CONFIGURATION"),
    ((stages(items=(stages().items[0].model_copy(update={"sequence": 2}),)),), "INVALID_STAGE_CONFIGURATION"),
])
def test_stage_selection_rejections(sets, code):
    with pytest.raises(RRMError, match=code):
        select_stage_set(sets)


def test_stage_version_changes_hash_and_unpinned_stage_fails():
    baseline = ready()
    changed = ready(s=stages(version=2))
    assert changed.input_hash != baseline.input_hash
    revised_item = stages().items[0].model_copy(update={"stage_definition_id": UUID(int=33), "revision": 2})
    assert ready(s=stages(items=(revised_item,))).blocker_codes == ("RRM_STAGE_NOT_IN_ACTIVE_SET",)
    assert ready(m=matrix(entries=(Entry(requirement_id=REQ, sequence=1, stage_id=UUID(int=33)),))).blocker_codes == (
        "RRM_STAGE_NOT_IN_ACTIVE_SET",)


def test_stage_duplicates_and_order_fail_closed():
    first = stages().items[0]
    same_code = first.model_copy(update={"stage_definition_id": UUID(int=35), "sequence": 2})
    with pytest.raises(RRMError, match="INVALID_STAGE_CONFIGURATION"):
        select_stage_set((stages(items=(first, same_code)),))
    second = first.model_copy(update={"stage_definition_id": UUID(int=36), "code": "DAY_30",
                                      "sequence": 2, "start_day": 0})
    with pytest.raises(RRMError, match="INVALID_STAGE_CONFIGURATION"):
        select_stage_set((stages(items=(first, second)),))


def test_timing_priority_dependencies_and_stage_order_preserved():
    base = matrix()
    req = base.requirements[0].model_copy(update={"priority": "HIGH"})
    following = req.model_copy(update={"id": UUID(int=37), "code": "FOLLOWUP", "revision": 1,
                                       "predecessor_id": None, "statement": "Follow up."})
    changed = base.model_copy(update={"requirements": (req, following),
                                      "entries": (base.entries[0], Entry(requirement_id=following.id,
                                                                           sequence=2, stage_id=STAGE)),
                                      "dependencies": ((following.id, REQ),)})
    result = ready(m=changed)
    assert result.status == "READY"
    assert result.snapshot.dependencies == ((following.id, REQ),)
    assert next(item for item in result.snapshot.requirements if item.revision_id == following.id).dependencies == (REQ,)
    assert next(item for item in result.snapshot.requirements if item.revision_id == REQ).priority == "HIGH"
    assert result.snapshot.stage_set.items[0].sequence == 1


def test_draft_ambiguous_known_case_never_generates():
    ambiguous = Timing(state="AMBIGUOUS", original_text="Within 7 days")
    base = matrix()
    req = base.requirements[0].model_copy(update={"timing": ambiguous})
    assert ready(m=base.model_copy(update={"status": "DRAFT", "requirements": (req,)})).blocker_codes == (
        "NO_APPROVED_MATRIX",)
    assert ready(m=base.model_copy(update={"requirements": (req,)})).blocker_codes == ("AMBIGUOUS_TIMING",)


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED", "SUPERSEDED", "REJECTED"])
def test_only_approved_matrix(status):
    assert ready(m=matrix(status=status)).blocker_codes == ("NO_APPROVED_MATRIX",)


def test_source_and_dependency_fail_closed():
    base = matrix()
    old = base.sources[CHUNK].model_copy(update={"current_version_id": UUID(int=70)})
    assert ready(m=base.model_copy(update={"sources": {CHUNK: old}})).blocker_codes == ("STALE_SOURCE",)
    unapproved = old.model_copy(update={"current_version_id": VERSION, "review_status": "SUBMITTED"})
    assert ready(m=base.model_copy(update={"sources": {CHUNK: unapproved}})).blocker_codes == ("STALE_SOURCE",)
    assert ready(m=base.model_copy(update={"dependencies": ((REQ, UUID(int=50)),)})).blocker_codes == (
        "INVALID_DEPENDENCY",)
    assert ready(m=base.model_copy(update={"blocking_issues": ("CONFLICT",)})).blocker_codes == (
        "UNRESOLVED_CONFLICT",)


def test_optional_and_exception_preserved():
    base = matrix()
    original = base.requirements[0]
    optional = original.model_copy(update={
        "id": UUID(int=40), "code": "RECOMMENDED_READING", "revision": 1, "predecessor_id": None,
        "requirement_type": "OPTIONAL", "mandatory": False, "statement": "Read the guidance.",
        "scopes": (Scope(role_id=ROLE),),
    })
    optional_entry = Entry(requirement_id=optional.id, sequence=2, stage_id=STAGE)
    changed = base.model_copy(update={"requirements": (original, optional),
                                      "entries": (base.entries[0], optional_entry)})
    result = ready(m=changed)
    assert result.status == "READY"
    assert len(result.snapshot.requirements) == 2
    assert next(req for req in result.snapshot.requirements if req.code == "RECOMMENDED_READING").mandatory is False
    mandatory_exception = optional.model_copy(update={"requirement_type": "MUST_COMPLETE", "mandatory": True})
    exception_entry = optional_entry.model_copy(update={"exception_to": REQ})
    result = ready(m=base.model_copy(update={"requirements": (original, mandatory_exception),
                                             "entries": (base.entries[0], exception_entry)}))
    assert result.status == "READY"
    assert len(result.snapshot.requirements) == 1
    assert result.snapshot.requirements[0].exception_to == REQ


class StubRepository:
    def __init__(self):
        self.tokens = []

    async def employee(self, token, employee_id):
        self.tokens.append(token)
        return employee() if employee_id == EMP else None

    async def approved_matrix(self, token, role_id):
        self.tokens.append(token)
        return matrix() if role_id == ROLE else None

    async def stage_sets(self, token):
        self.tokens.append(token)
        return (stages(),)


def principal(role=AppRole.TRAINING_MANAGER, status="ACTIVE"):
    profile = Profile(id=PROFILE, auth_user_id=UUID(int=60), display_name="Test", status=status,
                      roles=frozenset({role}))
    return Principal(user_id=profile.auth_user_id, token="test-user-jwt", profile=profile)


def test_service_uses_caller_jwt_and_blocks_unauthorized():
    repo = StubRepository()
    assert asyncio.run(preflight(principal(), EMP, repo, NOW)).status == "READY"
    assert repo.tokens == ["test-user-jwt"] * 3
    repo.tokens.clear()
    assert asyncio.run(preflight(principal(AppRole.EMPLOYEE), EMP, repo, NOW)).blocker_codes == ("FORBIDDEN_ROLE",)
    assert asyncio.run(preflight(principal(status="INACTIVE"), EMP, repo, NOW)).blocker_codes == ("FORBIDDEN_ROLE",)
    assert repo.tokens == []


class RowRepository:
    def __init__(self):
        self.calls = []

    async def rows(self, token, table, params):
        self.calls.append((token, table, params))
        if table == "employees":
            return [{"id": str(EMP), "profile_id": str(PROFILE), "role_id": str(ROLE),
                     "department_id": str(DEPT), "experience_level": "BEGINNER",
                     "location_code": "KHI", "joining_date": "2026-09-23"}]
        if table == "roles":
            return [{"id": str(ROLE), "code": "JUNIOR_DEV", "department_id": str(DEPT), "status": "ACTIVE"}]
        if table == "departments":
            return [{"id": str(DEPT), "code": "ENG", "status": "ACTIVE"}]
        if table == "onboarding_stage_sets":
            return [{"id": str(UUID(int=20)), "code": "DEFAULT", "version": 1,
                     "name": "Default", "status": "ACTIVE"}]
        if table == "onboarding_stage_set_items":
            return [{"stage_definition_id": str(STAGE), "sequence": 1}]
        if table == "onboarding_stage_definitions":
            return [{"id": str(STAGE), "code": "WEEK_1", "revision": 1, "label": "Week 1",
                     "sequence": 1, "start_day": 1, "end_day": 7}]
        return []


def test_repository_scoped_employee_projection_and_stage_set_boundary():
    underlying = RowRepository()
    repo = GenerationRepository(underlying)
    found = asyncio.run(repo.employee("caller-jwt", EMP))
    selected = asyncio.run(repo.stage_sets("caller-jwt"))
    assert found == employee()
    assert selected[0].items[0].stage_definition_id == STAGE
    assert all(token == "caller-jwt" for token, _, _ in underlying.calls)
    assert underlying.calls[0][2]["select"] == (
        "id,profile_id,role_id,department_id,experience_level,location_code,joining_date")
    assert all("name" not in call[2].get("select", "") for call in underlying.calls if call[1] == "employees")


def test_repository_approved_truth_uses_user_jwt_and_pinned_lineage(monkeypatch):
    base = matrix()
    req = base.requirements[0]
    src = base.sources[CHUNK]
    raw = {
        "matrix_id": str(MATRIX), "role_id": str(ROLE), "revision": 1, "edit": 1,
        "config": {"ranks": DEFAULT_AUTHORITY_RANKS,
                   "documents": [{"document_id": str(DOC), "authority_class": "COMPANY_POLICY"}]},
        "entries": [{
            "entry": base.entries[0].model_dump(mode="json"),
            "requirement": {"id": str(REQ), "requirement_code": req.code, "revision": 2,
                            "predecessor_id": str(req.predecessor_id), "statement": req.statement,
                            "requirement_type": req.requirement_type, "category": req.category,
                            "mandatory": True, "competency": None, "assessment_required": False,
                            "priority": "MEDIUM", "timing": req.timing.model_dump(mode="json"),
                            "origin": "MANUAL", "created_by": str(PROFILE)},
            "scopes": [{"role_id": None, "department_id": None, "location_code": None,
                        "experience": None}],
            "sources": [{"chunk": {"id": str(CHUNK), "text_hash": src.text_hash},
                         "version_id": str(VERSION), "document_id": str(DOC)}],
        }], "dependencies": [], "issues": [],
    }

    class GroundTruthRows:
        def __init__(self):
            self.tokens = []

        async def rows(self, token, table, params):
            self.tokens.append(token)
            assert table == "role_requirement_matrices"
            assert params["status"] == "eq.APPROVED"
            return [{"id": str(MATRIX), "role_id": str(ROLE), "revision": 1, "current_edit": 1,
                     "lock_version": 2, "status": "APPROVED", "snapshot_hash": "b" * 64}]

        async def rpc(self, token, name, payload):
            self.tokens.append(token)
            assert name == "get_rrm_ground_truth"
            assert payload == {"p_matrix": str(MATRIX)}
            return {"matrix_id": str(MATRIX), "snapshot_hash": "b" * 64, "snapshot": raw}

    async def resolved(repo, token, ids):
        repo.tokens.append(token)
        assert ids == [str(CHUNK)]
        return {str(CHUNK): {
            "chunk": {"id": str(CHUNK), "content": src.content, "text_hash": src.text_hash,
                      "source_location": src.source_location},
            "version": {"id": str(VERSION), "sha256": "a" * 64, "parse_status": "PARSED",
                        "review_status": "APPROVED", "effective_date": "2026-09-01", "expiry_date": None},
            "document": {"id": str(DOC), "status": "ACTIVE"},
        }}

    monkeypatch.setattr("app.generation_repository.eligible_sources", resolved)
    underlying = GroundTruthRows()
    found = asyncio.run(GenerationRepository(underlying).approved_matrix("user-jwt", ROLE))
    assert found.requirements[0].id == REQ
    assert found.sources[CHUNK].version_id == VERSION
    assert underlying.tokens == ["user-jwt"] * 3
