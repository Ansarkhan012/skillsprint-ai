"""Pure deterministic decision table. Human disposition never changes this evidence."""
from .validation_models import JEVDecision, ValidationEvidence

# First matching row wins. Warnings are excluded from blocking predicates.
PRECEDENCE = (
    ("CONTRADICTORY", frozenset({"TIMING_MISMATCH", "CONTRADICTION_DETECTED",
        "DEPENDENCY_MISSING", "DEPENDENCY_INVALID", "DEPENDENCY_ORDER_VIOLATION", "DEPENDENCY_CYCLE"})),
    ("UNSUPPORTED", frozenset({"UNSUPPORTED_REQUIREMENT", "SOURCE_SUPPORT_MISSING", "SOURCE_REFERENCE_INVALID"})),
    ("MANUAL_REVIEW", frozenset({"TIMING_UNRESOLVED", "OUTDATED_SOURCE", "STALE_INPUT",
        "ROLE_APPLICABILITY_MISMATCH", "STRUCTURAL_REFERENCE_INVALID", "DUPLICATE_REQUIREMENT"})),
    ("INCOMPLETE", frozenset({"MISSING_MANDATORY_REQUIREMENT"})),
)


def decide(evidence: ValidationEvidence) -> JEVDecision:
    blockers = {item.code for item in evidence.findings
                if item.severity != "WARNING" or item.code != "DUPLICATE_REQUIREMENT"}
    reasons = tuple(sorted({item.code for item in evidence.findings}))
    for index, (status, codes) in enumerate(PRECEDENCE, 1):
        if blockers & codes:
            return JEVDecision(status=status, rule=f"JEV-{index:03}", reason_codes=reasons)
    # Positive invariants are mandatory even if a caller constructs empty findings.
    if (blockers or not evidence.structurally_valid or not evidence.current_input
            or evidence.mandatory_total == 0 or evidence.mandatory_covered != evidence.mandatory_total):
        return JEVDecision(status="MANUAL_REVIEW", rule="JEV-005", reason_codes=reasons)
    return JEVDecision(status="VERIFIED_WITH_WARNING" if evidence.findings else "VERIFIED",
                       rule="JEV-006" if evidence.findings else "JEV-007", reason_codes=reasons)
