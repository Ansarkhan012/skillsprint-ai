"""Network-free comparison of structured plan attributes with frozen approved RRM.

No semantic similarity, text entailment, provider calls, or output repair. The v1
output has no module timing tuple: any source timing therefore requires review.
"""
import json
from collections import defaultdict

from pydantic import ValidationError

from .generation_models import GenerationInputSnapshot
from .generation_output import OnboardingPlan
from .rrm_models import EmployeeContext
from .rrm_rules import applicability, canonical_json
from .validation_models import Evidence, Finding, ValidationEvidence

EXPLANATIONS = {
    "MISSING_MANDATORY_REQUIREMENT": "An applicable mandatory requirement has no grounded module.",
    "UNSUPPORTED_REQUIREMENT": "A requirement reference is outside the approved frozen input.",
    "SOURCE_SUPPORT_MISSING": "A mapped requirement lacks its approved source support.",
    "SOURCE_REFERENCE_INVALID": "A source/version/chunk/locator does not support the mapped requirements.",
    "ROLE_APPLICABILITY_MISMATCH": "Employee identity or applicability differs from the frozen ground truth.",
    "TIMING_MISMATCH": "Generated stage timing differs from the fixed approved stage window.",
    "TIMING_UNRESOLVED": "The output contract cannot independently express and compare this requirement's timing.",
    "DEPENDENCY_MISSING": "An approved prerequisite module is missing from the dependent module.",
    "DEPENDENCY_INVALID": "A prerequisite reference is unknown, self-referential, or unsupported by the RRM.",
    "DEPENDENCY_ORDER_VIOLATION": "A prerequisite follows its dependent in generated stage/module order.",
    "DEPENDENCY_CYCLE": "The dependency graph contains a cycle.",
    "DUPLICATE_REQUIREMENT": "A requirement is repeated across modules; consistent repetition is a warning.",
    "CONTRADICTION_DETECTED": "Generated mandatory/priority or repeated structured attributes conflict with ground truth.",
    "OUTDATED_SOURCE": "Current source eligibility could not confirm the frozen approved evidence.",
    "STALE_INPUT": "Current authoritative context differs from the pinned generation input.",
    "STRUCTURAL_REFERENCE_INVALID": "The plan or its reference structure fails the pinned structural contract.",
}
CHILDREN = ("learning_objectives", "key_concepts", "activities", "checklist_items", "tasks",
            "scenarios", "quizzes", "assessments", "completion_criteria")


def has_cycle(graph: dict) -> bool:
    # Iterative topological walk avoids recursion limits on bounded but long plans.
    degree = {node: 0 for node in graph}
    reverse = defaultdict(list)
    for node, prerequisites in graph.items():
        for prerequisite in set(prerequisites):
            if prerequisite in degree:
                degree[node] += 1
                reverse[prerequisite].append(node)
    queue = [node for node, count in degree.items() if count == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for other in reverse[node]:
            degree[other] -= 1
            if degree[other] == 0:
                queue.append(other)
    return visited != len(graph)


def validate_plan(content: dict, snapshot: GenerationInputSnapshot, run_id,
                  *, current_input: bool, stale_source: bool = False) -> ValidationEvidence:
    requirements = {req.revision_id: req for req in snapshot.requirements}
    mandatory = {key for key, req in requirements.items() if req.mandatory}
    findings = []

    def add(code, location, req=None, severity="ERROR"):
        if len(findings) >= 1999:
            raise ValueError("VALIDATION_LIMIT_EXCEEDED")
        refs = () if req not in requirements else tuple(Evidence(
            document_id=ref.document_id, document_version_id=ref.document_version_id,
            chunk_id=ref.chunk_id, locator=canonical_json(ref.locator))
            for ref in requirements[req].evidence)
        findings.append(Finding(code=code, severity=severity, requirement_id=req,
            location=location, explanation=EXPLANATIONS[code], evidence=refs))

    def result(valid, covered):
        return ValidationEvidence(mandatory_total=len(mandatory), mandatory_covered=len(covered & mandatory),
            structurally_valid=valid, current_input=current_input, findings=tuple(findings))

    if not current_input:
        add("OUTDATED_SOURCE" if stale_source else "STALE_INPUT", "input", severity="REVIEW")
    try:
        plan = OnboardingPlan.model_validate_json(json.dumps(content, ensure_ascii=False))
    except (ValidationError, ValueError, TypeError) as exc:
        code = "STRUCTURAL_REFERENCE_INVALID"
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            if any("source_refs" in item["loc"] for item in errors):
                code = "SOURCE_SUPPORT_MISSING"
        add(code, "plan")
        return result(False, set())

    employee = snapshot.employee
    actual = plan.employee_context
    if (actual.employee_id, actual.role_id, actual.department_id, actual.experience_level,
        actual.location_code, actual.joining_date) != (employee.employee_id, employee.role_id,
        employee.department_id, employee.experience, employee.location_code, employee.joining_date):
        add("ROLE_APPLICABILITY_MISMATCH", "employee_context")
    if plan.generation_request_id != run_id:
        add("STRUCTURAL_REFERENCE_INVALID", "generation_request_id")
    context = EmployeeContext(role_id=employee.role_id, department_id=employee.department_id,
                              location_code=employee.location_code, experience=employee.experience)
    for req in snapshot.requirements:
        if applicability(req.applicability, context) != "APPLICABLE":
            add("ROLE_APPLICABILITY_MISMATCH", "input.applicability", req.revision_id)
        if req.timing.state != "NOT_SPECIFIED":
            add("TIMING_UNRESOLVED", "input.timing", req.revision_id, "REVIEW")
    if not requirements or len(requirements) != len(snapshot.requirements):
        add("STRUCTURAL_REFERENCE_INVALID", "input.requirements")
    expected_stages = snapshot.stage_set.items
    if [s.stage_id for s in plan.plan.stages] != [s.stage_definition_id for s in expected_stages]:
        add("STRUCTURAL_REFERENCE_INVALID", "plan.stages")
    stage_map = {s.stage_definition_id: s for s in expected_stages}
    modules, positions, coverage, represented = {}, {}, defaultdict(list), defaultdict(list)
    for si, stage in enumerate(plan.plan.stages):
        path = f"plan.stages[{si}]"
        expected = stage_map.get(stage.stage_id)
        if expected and (stage.target_start_day, stage.target_end_day) != (expected.start_day, expected.end_day):
            add("TIMING_MISMATCH", path)
        if expected and (stage.label, stage.sequence) != (expected.label, expected.sequence):
            add("STRUCTURAL_REFERENCE_INVALID", path)
        for mi, module in enumerate(stage.modules):
            if len(modules) >= 1000:
                raise ValueError("VALIDATION_LIMIT_EXCEEDED")
            path = f"plan.stages[{si}].modules[{mi}]"
            modules[module.module_id] = module
            positions[module.module_id] = (si, mi)
            nodes = [(path, module)]
            for field in CHILDREN:
                for ni, node in enumerate(getattr(module, field)):
                    nodes.append((f"{path}.{field}[{ni}]", node))
                    if field == "assessments":
                        nodes.extend((f"{path}.{field}[{ni}].rubric[{ri}]", row)
                                     for ri, row in enumerate(node.rubric))
            grounded_module = True
            for node_path, node in nodes:
                ids = set(node.requirement_ids)
                if len(ids) != len(node.requirement_ids):
                    add("DUPLICATE_REQUIREMENT", node_path)
                    grounded_module = False
                allowed = set()
                for rid in sorted(ids, key=str):
                    if rid not in requirements:
                        add("UNSUPPORTED_REQUIREMENT", node_path, rid)
                        grounded_module = False
                        continue
                    refs = {(r.document_version_id, r.chunk_id, canonical_json(r.locator))
                            for r in requirements[rid].evidence}
                    supplied = {(r.document_version_id, r.chunk_id, r.locator) for r in node.source_refs}
                    allowed |= refs
                    if not refs or not refs.issubset(supplied):
                        add("SOURCE_SUPPORT_MISSING", node_path, rid)
                        grounded_module = False
                if any((r.document_version_id, r.chunk_id, r.locator) not in allowed for r in node.source_refs):
                    add("SOURCE_REFERENCE_INVALID", node_path)
                    grounded_module = False
                if hasattr(node, "due_stage_id") and node.due_stage_id not in stage_map:
                    add("STRUCTURAL_REFERENCE_INVALID", node_path)
                elif hasattr(node, "due_stage_id"):
                    for rid in ids & requirements.keys():
                        expected_due = requirements[rid].stage_definition_id
                        if expected_due is not None and node.due_stage_id != expected_due:
                            add("TIMING_MISMATCH", node_path, rid)
            for rid in set(module.requirement_ids) & requirements.keys():
                represented[rid].append(module.module_id)
                req = requirements[rid]
                if (module.mandatory, module.priority) != (req.mandatory, req.priority):
                    add("CONTRADICTION_DETECTED", path, rid)
                if req.stage_definition_id is not None and stage.stage_id != req.stage_definition_id:
                    add("STRUCTURAL_REFERENCE_INVALID", path, rid)
                if grounded_module:
                    coverage[rid].append(module.module_id)
    for rid in sorted(mandatory - coverage.keys(), key=str):
        add("MISSING_MANDATORY_REQUIREMENT", "plan", rid)
    for rid, mids in sorted(coverage.items(), key=lambda pair: str(pair[0])):
        if len(mids) > 1:
            signatures = {(modules[mid].mandatory, modules[mid].priority) for mid in mids}
            add("CONTRADICTION_DETECTED" if len(signatures) > 1 else "DUPLICATE_REQUIREMENT",
                "plan.modules", rid, "ERROR" if len(signatures) > 1 else "WARNING")
    approved_edges = set(snapshot.dependencies)
    for mid, module in modules.items():
        for prerequisite in module.prerequisite_module_ids:
            if prerequisite not in modules or prerequisite == mid:
                add("DEPENDENCY_INVALID", "plan.prerequisites")
            elif not any((d, p) in approved_edges for d in module.requirement_ids
                         for p in modules[prerequisite].requirement_ids):
                add("DEPENDENCY_INVALID", "plan.prerequisites")
            elif positions[prerequisite] >= positions[mid]:
                add("DEPENDENCY_ORDER_VIOLATION", "plan.prerequisites")
    for dependent, prerequisite in sorted(approved_edges, key=lambda pair: tuple(map(str, pair))):
        if dependent not in requirements or prerequisite not in requirements:
            add("DEPENDENCY_INVALID", "input.dependencies")
        for mid in represented.get(dependent, []):
            if not set(represented.get(prerequisite, [])) & set(modules[mid].prerequisite_module_ids):
                add("DEPENDENCY_MISSING", "plan.prerequisites", dependent)
    if has_cycle({mid: module.prerequisite_module_ids for mid, module in modules.items()}) or has_cycle({
            rid: [p for d, p in approved_edges if d == rid] for rid in requirements}):
        add("DEPENDENCY_CYCLE", "dependencies")
    if plan.insufficient_information:
        add("STRUCTURAL_REFERENCE_INVALID", "insufficient_information", severity="REVIEW")
    return result(True, set(coverage))
