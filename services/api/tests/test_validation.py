"""Phase 5 deterministic fixtures; no provider, database, or live generation."""
from copy import deepcopy
from uuid import UUID
import json

import pytest

from app.jev import decide, PRECEDENCE
from app.plan_validator import validate_plan
from app.rrm_models import Timing, EvidenceSpan, Scope
from app.validation_models import ValidationEvidence, ReviewRequest
from test_generation_context import ready

RUN = UUID(int=500)
PLAN = UUID(int=501)


def fixture():
    frozen = ready().snapshot
    windows = ((0,1),(1,3),(2,5),(4,7),(7,7))
    stages = tuple(frozen.stage_set.items[0].model_copy(update={
        "stage_definition_id": UUID(int=300+i), "sequence": i+1,
        "code": f"STAGE_{i}", "label": f"Stage {i+1}", "start_day": start, "end_day": end})
        for i,(start,end) in enumerate(windows))
    assignments = (1,0,1,2,3,4)
    edges = ((3,0),(3,2),(4,3),(5,0),(5,1),(5,2),(5,3),(5,4))
    requirements = tuple(frozen.requirements[0].model_copy(update={
        "revision_id": UUID(int=200+i), "code": f"P4D_{i}", "sequence": i,
        "stage_definition_id": stages[assignments[i]].stage_definition_id,
        "dependencies": tuple(UUID(int=200+p) for d,p in edges if d==i),
        "evidence": (frozen.requirements[0].evidence[0].model_copy(update={
            "chunk_id": UUID(int=400+i), "locator": {"paragraph": 15+2*i}}),)}) for i in range(6))
    frozen = frozen.model_copy(update={"requirements": requirements,
        "dependencies": tuple((UUID(int=200+d),UUID(int=200+p)) for d,p in edges),
        "stage_set": frozen.stage_set.model_copy(update={"items": stages})})
    output_stages = [{"stage_id": str(s.stage_definition_id), "label":s.label,"sequence":s.sequence,
        "target_start_day":s.start_day,"target_end_day":s.end_day,"modules":[]} for s in stages]
    for i,req in enumerate(requirements):
        output_stages[assignments[i]]["modules"].append({
            "module_id":str(UUID(int=600+i)), "title":f"Training {i}","purpose":"Complete the approved activity",
            "category":"POLICY","mandatory":True,"priority":req.priority,"difficulty":"BEGINNER",
            "estimated_minutes":30,"requirement_ids":[str(req.revision_id)],
            "source_refs":[{"document_version_id":str(req.evidence[0].document_version_id),
                "chunk_id":str(req.evidence[0].chunk_id),"locator":json.dumps(req.evidence[0].locator,separators=(',',':'))}],
            "prerequisite_module_ids":[str(UUID(int=600+p)) for d,p in edges if d==i]})
    employee=frozen.employee
    plan={"schema_version":"onboarding-plan/1.0.0","generation_request_id":str(RUN),
        "employee_context":{"employee_id":str(employee.employee_id),"role_id":str(employee.role_id),
            "department_id":str(employee.department_id),"experience_level":employee.experience,
            "location_code":employee.location_code,"joining_date":employee.joining_date.isoformat()},
        "plan":{"title":"Engineering onboarding","summary":"Approved requirements","stages":output_stages}}
    return frozen,plan


def module(plan, i):
    return next(m for s in plan["plan"]["stages"] for m in s["modules"] if m["module_id"]==str(UUID(int=600+i)))


def check(plan, frozen, **kwargs):
    evidence=validate_plan(plan,frozen,RUN,current_input=kwargs.pop("current_input",True),**kwargs)
    return evidence,decide(evidence)


def test_correct_structurally_comparable_six_eight_five_plan_verified():
    frozen,plan=fixture()
    assert (len(frozen.requirements),len(frozen.dependencies),len(frozen.stage_set.items))==(6,8,5)
    evidence,decision=check(plan,frozen)
    assert decision.status=="VERIFIED" and evidence.mandatory_covered==6 and not evidence.findings
    assert check(plan,frozen)==(evidence,decision)


def test_consistent_repeated_activity_warning_not_rejected():
    frozen,plan=fixture()
    extra=deepcopy(module(plan,1)); extra["module_id"]=str(UUID(int=999))
    plan["plan"]["stages"][0]["modules"].append(extra)
    assert check(plan,frozen)[1].status=="VERIFIED_WITH_WARNING"


def test_missing_mandatory_requirement_incomplete():
    frozen,plan=fixture()
    plan["plan"]["stages"][-1]["modules"]=[]
    evidence,decision=check(plan,frozen)
    assert decision.status=="INCOMPLETE"
    assert evidence.mandatory_covered==5


@pytest.mark.parametrize("mutation,code,status",[
    (lambda p: module(p,0)["requirement_ids"].append(str(UUID(int=888))),"UNSUPPORTED_REQUIREMENT","UNSUPPORTED"),
    (lambda p: module(p,0).update(source_refs=[]),"SOURCE_SUPPORT_MISSING","UNSUPPORTED"),
    (lambda p: module(p,0)["source_refs"][0].update(locator="invented"),"SOURCE_REFERENCE_INVALID","UNSUPPORTED"),
    (lambda p: p["plan"]["stages"][1].update(target_end_day=5),"TIMING_MISMATCH","CONTRADICTORY"),
    (lambda p: module(p,3).update(prerequisite_module_ids=[]),"DEPENDENCY_MISSING","CONTRADICTORY"),
    (lambda p: module(p,3)["prerequisite_module_ids"].append(str(UUID(int=888))),"DEPENDENCY_INVALID","CONTRADICTORY"),
    (lambda p: module(p,0).update(mandatory=False),"CONTRADICTION_DETECTED","CONTRADICTORY"),
    (lambda p: p["plan"]["stages"][0].update(stage_id=str(UUID(int=888))),"STRUCTURAL_REFERENCE_INVALID","MANUAL_REVIEW"),
    (lambda p: p["employee_context"].update(role_id=str(UUID(int=888))),"ROLE_APPLICABILITY_MISMATCH","MANUAL_REVIEW"),
    (lambda p: p.update(unexpected="never accepted"),"STRUCTURAL_REFERENCE_INVALID","MANUAL_REVIEW"),
])
def test_mutations_fail_closed(mutation,code,status):
    frozen,plan=fixture(); mutation(plan)
    evidence,decision=check(plan,frozen)
    assert code in {f.code for f in evidence.findings}
    assert decision.status==status


def test_wrong_requirement_source_pair_is_not_accepted_even_if_source_exists_elsewhere():
    frozen,plan=fixture()
    module(plan,0)["source_refs"]=deepcopy(module(plan,1)["source_refs"])
    assert check(plan,frozen)[1].status=="UNSUPPORTED"


@pytest.mark.parametrize("state",["AMBIGUOUS","STRUCTURED"])
def test_timing_without_output_timing_tuple_requires_review(state):
    frozen,plan=fixture()
    timing=Timing(state="AMBIGUOUS",original_text="Within 2 days")
    if state=="STRUCTURED":
        span=EvidenceSpan(chunk_id=frozen.requirements[0].evidence[0].chunk_id,start=0,end=1,quote="x")
        timing=Timing(state="STRUCTURED",original_text="Within 2 calendar days after joining date",
            trigger="joining date",relation="WITHIN",value=2,unit="DAY",calendar_basis="CALENDAR",
            evidence={key:span for key in ("original_text","trigger","relation","value","unit","calendar_basis")})
    frozen=frozen.model_copy(update={"requirements":(frozen.requirements[0].model_copy(update={"timing":timing}),*frozen.requirements[1:])})
    assert check(plan,frozen)[1].status=="MANUAL_REVIEW"


@pytest.mark.parametrize("stale_source",[False,True])
def test_stale_context_never_verifies(stale_source):
    frozen,plan=fixture()
    assert check(plan,frozen,current_input=False,stale_source=stale_source)[1].status=="MANUAL_REVIEW"


def test_cycle_and_order_are_detected():
    frozen,plan=fixture()
    module(plan,0)["prerequisite_module_ids"]=[str(UUID(int=603))]
    evidence,decision=check(plan,frozen)
    assert "DEPENDENCY_CYCLE" in {f.code for f in evidence.findings}
    assert decision.status=="CONTRADICTORY"
    # A valid edge placed in reverse order must be independently detected.
    frozen,plan=fixture()
    plan["plan"]["stages"].reverse()
    assert "DEPENDENCY_ORDER_VIOLATION" in {f.code for f in check(plan,frozen)[0].findings}


def test_applicability_is_rechecked_from_frozen_predicates():
    frozen,plan=fixture()
    changed=frozen.requirements[0].model_copy(update={"applicability":(Scope(department_id=UUID(int=999)),)})
    frozen=frozen.model_copy(update={"requirements":(changed,*frozen.requirements[1:])})
    assert check(plan,frozen)[1].status=="MANUAL_REVIEW"


def test_conflicting_duplicate_is_contradictory():
    frozen,plan=fixture(); duplicate=deepcopy(module(plan,1))
    duplicate.update(module_id=str(UUID(int=999)),mandatory=False)
    plan["plan"]["stages"][0]["modules"].append(duplicate)
    assert check(plan,frozen)[1].status=="CONTRADICTORY"


def test_positive_invariants_and_precedence():
    assert decide(ValidationEvidence(mandatory_total=0,mandatory_covered=0,structurally_valid=True,
        current_input=True,findings=())).status=="MANUAL_REVIEW"
    assert [row[0] for row in PRECEDENCE]==["CONTRADICTORY","UNSUPPORTED","MANUAL_REVIEW","INCOMPLETE"]
    frozen,plan=fixture(); module(plan,0).update(mandatory=False)
    module(plan,1)["source_refs"]=[]
    # Invalid schema cannot supply trusted contradiction evidence; structural failure wins safely.
    assert check(plan,frozen)[1].status=="UNSUPPORTED"


def test_grounded_child_due_stage_cannot_change_requirement_stage():
    frozen,plan=fixture(); m=module(plan,0)
    m["checklist_items"]=[{"checklist_item_id":str(UUID(int=800)),"activity":"Complete activity",
        "required":True,"due_stage_id":str(frozen.stage_set.items[-1].stage_definition_id),
        "responsible_role":"Employee","requirement_ids":m["requirement_ids"],"source_refs":m["source_refs"]}]
    assert check(plan,frozen)[1].status=="CONTRADICTORY"


@pytest.mark.parametrize("reason",[""," ","\u2003\n"])
def test_empty_override_reason_invalid(reason):
    with pytest.raises(ValueError): ReviewRequest(action="OVERRIDE",reason=reason)


def test_validator_imports_have_no_provider_or_network_dependency():
    import ast
    from pathlib import Path
    for name in ("plan_validator.py","jev.py","validation_models.py"):
        tree=ast.parse((Path(__file__).parents[1]/"app"/name).read_text())
        modules=[node.module or "" for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(any(x in name for x in ("provider","httpx","generation_service")) for name in modules)
