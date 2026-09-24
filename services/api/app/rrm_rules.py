"""Pure ground-truth preparation rules; not the Phase 5 plan validator/JEV."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import re
from uuid import UUID

from .rrm_models import EmployeeContext, Entry, MatrixStatus, PrecedenceConfig, Requirement, Scope, Source, Timing, meaningful_reason


class RRMError(ValueError):
    pass


def utc_timestamp(value: datetime) -> str:
    """Canonical SQL-compatible UTC timestamp, exactly six fractional digits."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise RRMError("NAIVE_TIMESTAMP")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def utc_date(value: datetime) -> date:
    # Caller supplies a trusted backend clock instant, never an HTTP date preference.
    utc_timestamp(value)  # Reject naive instants rather than assuming local timezone.
    return value.astimezone(timezone.utc).date()


def validate_downgrade(entry: Entry, requirements: dict[UUID, Requirement], sources: dict[UUID, Source]) -> None:
    req = requirements[entry.requirement_id]
    base = requirements.get(entry.exception_to)
    downgrade = base is not None and base.mandatory and not req.mandatory
    if not downgrade:
        if entry.downgrade_requested or entry.downgrade_justification is not None or entry.downgrade_evidence is not None:
            raise RRMError("UNEXPECTED_DOWNGRADE_DECISION")
        return
    span = entry.downgrade_evidence
    if not entry.downgrade_requested or not meaningful_reason(entry.downgrade_justification) or span is None:
        raise RRMError("DOWNGRADE_MANUAL_REVIEW")
    source = sources.get(span.chunk_id)
    if (source is None or span.chunk_id not in req.chunk_ids or span.end > len(source.content)
            or source.content[span.start:span.end] != span.quote):
        raise RRMError("DOWNGRADE_EVIDENCE_MISMATCH")
    # Presence is not entailment. Only independent matrix approval authorizes use.


def applicability(scopes: tuple[Scope, ...], context: EmployeeContext) -> str:
    if not scopes:
        return "MANUAL_REVIEW"
    unknown = False
    for scope in scopes:
        uncertain, mismatch = False, False
        for key in ("role_id", "department_id", "location_code", "experience"):
            expected, actual = getattr(scope, key), getattr(context, key)
            if expected is not None:
                if actual is None or actual == "":
                    uncertain = True
                elif actual != expected:
                    mismatch = True
        if not mismatch and not uncertain:
            return "APPLICABLE"
        unknown |= uncertain and not mismatch
    return "MANUAL_REVIEW" if unknown else "NOT_APPLICABLE"


def normalized_statement(text: str) -> str:
    # Preserve punctuation/numbers/negation; no semantic similarity claim.
    return re.sub(r"\s+", " ", text).strip().lower()


def duplicate_groups(requirements: tuple[Requirement, ...]) -> tuple[tuple[UUID, ...], ...]:
    groups = defaultdict(list)
    for req in requirements:
        groups[normalized_statement(req.statement)].append(req.id)
    return tuple(tuple(sorted(ids, key=str)) for _, ids in sorted(groups.items()) if len(ids) > 1)


def validate_dependencies(entries: tuple[Entry, ...], edges: tuple[tuple[UUID, UUID], ...]) -> None:
    """Edges are (dependent, prerequisite); prerequisites must precede dependents."""
    order = {entry.requirement_id: entry.sequence for entry in entries}
    if len(order) != len(entries) or len(set(edges)) != len(edges):
        raise RRMError("DUPLICATE_ENTRY_OR_DEPENDENCY")
    adjacency = {key: [] for key in order}
    for dependent, prerequisite in edges:
        if dependent not in order or prerequisite not in order:
            raise RRMError("DEPENDENCY_OUTSIDE_MATRIX")
        adjacency[dependent].append(prerequisite)
    # Iterative Kahn traversal also handles deep evaluator-provided graphs.
    pending = {key: len(values) for key, values in adjacency.items()}
    reverse = defaultdict(list)
    for dependent, prerequisite in edges:
        reverse[prerequisite].append(dependent)
    queue = [key for key, value in pending.items() if value == 0]
    visited = 0
    while queue:
        key = queue.pop()
        visited += 1
        for dependent in reverse[key]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                queue.append(dependent)
    if visited != len(order):
        raise RRMError("DEPENDENCY_CYCLE")
    if any(order[prerequisite] >= order[dependent] for dependent, prerequisite in edges):
        raise RRMError("DEPENDENCY_ORDER")


def source_eligible(source: Source, on_date: date) -> bool:
    return (source.document_status == "ACTIVE" and source.parse_status == "PARSED"
            and source.review_status == "APPROVED" and source.current_version_id == source.version_id
            and source.effective_date <= on_date
            and (source.expiry_date is None or on_date <= source.expiry_date)
            and bool(source.content.strip())
            and sha256(source.content.encode("utf-8")).hexdigest() == source.text_hash)


def validate_timing(timing: Timing, sources: dict[UUID, Source], linked_chunks: tuple[UUID, ...]) -> None:
    if timing.state == "AMBIGUOUS":
        raise RRMError("TIMING_MANUAL_REVIEW")
    if timing.state != "STRUCTURED":
        return
    for field, span in timing.evidence.items():
        source = sources.get(span.chunk_id)
        if (source is None or span.chunk_id not in linked_chunks
                or span.end > len(source.content) or source.content[span.start:span.end] != span.quote):
            raise RRMError("TIMING_EVIDENCE_MISMATCH")
        actual = span.quote.strip().lower()
        expected = str(getattr(timing, field)).lower()
        accepted = {expected}
        if field == "unit":
            accepted.add(expected + "s")
        if actual not in accepted:
            raise RRMError("TIMING_VALUE_NOT_EVIDENCED")
    # Exact anchors do not prove prose entailment: matrix approval is still human.


def precedence(left: UUID, right: UUID, config: PrecedenceConfig, *,
               approved_exception: bool = False, exception_target: UUID | None = None,
               applicable_role_exception: bool = False) -> str:
    """Input document IDs, not categories/filenames. Returns LEFT/RIGHT/MANUAL_REVIEW."""
    if approved_exception and applicable_role_exception and exception_target == right and left != right:
        return "LEFT"
    left_class, right_class = config.document_classes.get(left), config.document_classes.get(right)
    if left_class is None or right_class is None:
        return "MANUAL_REVIEW"
    l_rank, r_rank = config.ranks[left_class], config.ranks[right_class]
    if l_rank == r_rank:
        return "MANUAL_REVIEW"
    return "LEFT" if l_rank > r_rank else "RIGHT"


def canonical_json(value) -> str:
    """Version 1: sorted UTF-8 keys, compact arrays, finite decimal numbers, no timestamps inferred."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            raise RRMError("NON_FINITE_NUMBER")
        number = Decimal(str(value))
        if not number.is_finite():
            raise RRMError("NON_FINITE_NUMBER")
        result = format(number, "f")
        return (result.rstrip("0").rstrip(".") if "." in result else result) if number else "0"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(x) for x in value) + "]"
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return "{" + ",".join(canonical_json(k) + ":" + canonical_json(value[k]) for k in sorted(value)) + "}"
    raise RRMError("NON_JSON_SNAPSHOT")


def snapshot_hash(payload: dict) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def complete_snapshot(requirements: tuple[Requirement, ...], entries: tuple[Entry, ...],
                      sources: dict[UUID, Source], context: EmployeeContext, on_date: date,
                      dependencies: tuple[tuple[UUID, UUID], ...] = (), *,
                      status: MatrixStatus,
                      blocking_issues: tuple[str, ...] = (), configuration: PrecedenceConfig | None = None) -> dict:
    """Fail the whole snapshot instead of dropping stale/unknown mandatory entries."""
    if status != MatrixStatus.APPROVED or not entries or blocking_issues:
        raise RRMError("MATRIX_NOT_ELIGIBLE")
    if configuration is None or context.role_id is None:
        raise RRMError("MISSING_CONFIGURATION_OR_ROLE")
    required = {r.id: r for r in requirements}
    if len(required) != len(requirements) or {e.requirement_id for e in entries} != set(required):
        raise RRMError("INCOMPLETE_REQUIREMENT_SET")
    if len({r.code for r in requirements}) != len(requirements) or duplicate_groups(requirements):
        raise RRMError("DUPLICATE_REQUIREMENT")
    validate_dependencies(entries, dependencies)
    applicable = set()
    for req in requirements:
        for chunk_id in req.chunk_ids:
            source = sources.get(chunk_id)
            if source is None or source.chunk_id != chunk_id or not source_eligible(source, on_date):
                raise RRMError("INVALID_OR_STALE_SOURCE")
            if source.document_id not in configuration.document_classes:
                raise RRMError("UNMAPPED_AUTHORITY")
        validate_timing(req.timing, sources, req.chunk_ids)
        result = applicability(req.scopes, context)
        if result == "MANUAL_REVIEW":
            raise RRMError("APPLICABILITY_MANUAL_REVIEW")
        if result == "APPLICABLE":
            applicable.add(req.id)
    effective = set(applicable)
    exceptions: dict[UUID, UUID] = {}
    for entry in entries:
        validate_downgrade(entry, required, sources)
        if entry.exception_to is not None:
            if entry.exception_to == entry.requirement_id or entry.exception_to not in required:
                raise RRMError("INVALID_EXCEPTION_TARGET")
            if not all(s.role_id == context.role_id and s.role_id is not None for s in required[entry.requirement_id].scopes):
                raise RRMError("EXCEPTION_NOT_ROLE_SPECIFIC")
            if any(e.requirement_id == entry.exception_to and e.exception_to is not None for e in entries):
                raise RRMError("EXCEPTION_CHAIN")
            for scope in required[entry.requirement_id].scopes:
                if not any(base.role_id is None and all(getattr(base, key) is None or
                           getattr(base, key) == getattr(scope, key)
                           for key in ("department_id", "location_code", "experience"))
                           for base in required[entry.exception_to].scopes):
                    raise RRMError("EXCEPTION_SCOPE_NOT_SUBSET")
            if entry.requirement_id in applicable:
                if entry.exception_to in exceptions:
                    raise RRMError("OVERLAPPING_EXCEPTIONS_MANUAL_REVIEW")
                exceptions[entry.exception_to] = entry.requirement_id
                effective.discard(entry.exception_to)
    if any(d in effective and p not in effective for d, p in dependencies):
        raise RRMError("PREREQUISITE_NOT_APPLICABLE")
    return {"schema_version": "rrm-1", "on_date": on_date.isoformat(),
            "context": context.model_dump(mode="json"), "configuration": configuration.model_dump(mode="json"),
            "requirements": [r.model_dump(mode="json") for r in sorted(requirements, key=lambda r: str(r.id))],
            "entries": [e.model_dump(mode="json") for e in sorted(entries, key=lambda e: str(e.requirement_id))],
            "dependencies": [[str(d), str(p)] for d, p in sorted(dependencies, key=lambda e: (str(e[0]), str(e[1])))],
            "applicable_ids": sorted(map(str, applicable)),
            "effective_ids": sorted(map(str, effective)),
            "exception_resolutions": {str(k): str(v) for k, v in sorted(exceptions.items(), key=lambda pair: str(pair[0]))},
            "sources": [sources[c].model_dump(mode="json") for c in sorted({c for r in requirements for c in r.chunk_ids}, key=str)]}


def authorize_transition(status: MatrixStatus, action: str, actor: UUID, roles: frozenset[str],
                         contributors: frozenset[UUID], expected_version: int, current_version: int,
                         *, active: bool = True, admin_override: bool = False,
                         reason: str | None = None, integrity_valid: bool = True,
                         creator_id: UUID | None = None) -> MatrixStatus:
    if not active or not roles:
        raise RRMError("RRM_FORBIDDEN")
    if reason is not None and not meaningful_reason(reason):
        raise RRMError("RRM_REASON_REQUIRED")
    if expected_version != current_version:
        raise RRMError("RRM_EDIT_CONFLICT")
    if action == "SUBMIT":
        if (status != MatrixStatus.DRAFT or not roles.intersection({"ADMIN", "TRAINING_MANAGER"})
                or actor != creator_id or admin_override):
            raise RRMError("RRM_TRANSITION_FORBIDDEN")
        target = MatrixStatus.SUBMITTED
    elif action in {"APPROVE", "REJECT"}:
        if status != MatrixStatus.SUBMITTED or not roles.intersection({"ADMIN", "REVIEWER"}):
            raise RRMError("RRM_TRANSITION_FORBIDDEN")
        own = actor in contributors
        if own and not ("ADMIN" in roles and admin_override and meaningful_reason(reason)):
            raise RRMError("RRM_SELF_REVIEW_FORBIDDEN")
        if admin_override and ("ADMIN" not in roles or not own or not meaningful_reason(reason)):
            raise RRMError("RRM_INVALID_OVERRIDE")
        if action == "REJECT" and not meaningful_reason(reason):
            raise RRMError("RRM_REASON_REQUIRED")
        target = MatrixStatus.APPROVED if action == "APPROVE" else MatrixStatus.REJECTED
    else:
        raise RRMError("RRM_INVALID_ACTION")
    if action != "REJECT" and not integrity_valid:
        raise RRMError("RRM_INTEGRITY_FAILURE")
    return target
