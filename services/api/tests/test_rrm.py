"""Executable domain tests. SQL grant/transaction contracts are tested separately."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.rrm_models import (DEFAULT_AUTHORITY_RANKS, EmployeeContext, Entry, EvidenceSpan,
                            MatrixRevision, MatrixStatus, PrecedenceConfig, Requirement, Scope, Source, StageDefinition, Timing)
from app.rrm_rules import (RRMError, applicability, authorize_transition, canonical_json,
                           complete_snapshot, duplicate_groups, precedence, snapshot_hash,
                           source_eligible, validate_dependencies, validate_timing)

TODAY = date(2026, 9, 23)
ROLE, DEPT, AUTHOR, REVIEWER = (UUID(int=i) for i in range(1, 5))


def requirement(**changes):
    values = dict(id=uuid4(), code="REQ-01", revision=1, statement="Complete security training.",
                  requirement_type="MUST_COMPLETE", category="COMPLIANCE", mandatory=True,
                  scopes=(Scope(),), chunk_ids=(uuid4(),), author_id=AUTHOR)
    values.update(changes)
    return Requirement(**values)


def source(chunk_id=None, **changes):
    version = uuid4()
    text = "Complete security training."
    values = dict(chunk_id=chunk_id or uuid4(), version_id=version, document_id=uuid4(),
                  content=text, text_hash=sha256(text.encode()).hexdigest(), source_location={"table": 1, "row": 2, "cell": 1},
                  document_sha256="a" * 64, document_status="ACTIVE", parse_status="PARSED", review_status="APPROVED",
                  effective_date=TODAY, current_version_id=version)
    values.update(changes)
    return Source(**values)


def config(*sources):
    return PrecedenceConfig(ranks=DEFAULT_AUTHORITY_RANKS,
                            document_classes={s.document_id: "COMPANY_POLICY" for s in sources})


def build_snapshot(req=None, src=None, **changes):
    req = req or requirement()
    src = src or source(req.chunk_ids[0])
    values = dict(requirements=(req,), entries=(Entry(requirement_id=req.id, sequence=1),),
                  sources={src.chunk_id: src}, context=EmployeeContext(role_id=ROLE), on_date=TODAY,
                  configuration=config(src), status=MatrixStatus.APPROVED)
    values.update(changes)
    return complete_snapshot(**values)


@pytest.mark.parametrize("scope,context,expected", [
    (Scope(), EmployeeContext(), "APPLICABLE"),
    (Scope(role_id=ROLE), EmployeeContext(role_id=ROLE), "APPLICABLE"),
    (Scope(role_id=ROLE), EmployeeContext(role_id=uuid4()), "NOT_APPLICABLE"),
    (Scope(role_id=ROLE), EmployeeContext(), "MANUAL_REVIEW"),
    (Scope(department_id=DEPT), EmployeeContext(role_id=ROLE), "MANUAL_REVIEW"),
    (Scope(location_code="KHI"), EmployeeContext(location_code=""), "MANUAL_REVIEW"),
    (Scope(experience="BEGINNER"), EmployeeContext(experience="ADVANCED"), "NOT_APPLICABLE"),
    (Scope(department_id=DEPT, location_code="KHI"), EmployeeContext(department_id=DEPT, location_code="KHI"), "APPLICABLE"),
    (Scope(role_id=ROLE, location_code="KHI"), EmployeeContext(role_id=uuid4()), "NOT_APPLICABLE"),
])
def test_typed_scope(scope, context, expected):
    assert applicability((scope,), context) == expected


def test_scope_disjunction_true_beats_unknown_and_empty_fails_closed():
    context = EmployeeContext(role_id=ROLE)
    assert applicability((Scope(location_code="KHI"), Scope(role_id=ROLE)), context) == "APPLICABLE"
    assert applicability((), context) == "MANUAL_REVIEW"


@pytest.mark.parametrize("payload", [{"expression": "true"}, {"role_id": "ADMIN"}, {"experience": "EXPERT"}])
def test_no_executable_or_application_role_scope(payload):
    with pytest.raises(ValidationError):
        Scope(**payload)


@pytest.mark.parametrize("changes", [
    {"mandatory": False}, {"mandatory": "true"}, {"requirement_type": "OPTIONAL"},
    {"revision": 2}, {"revision": 1, "predecessor_id": uuid4()}, {"scopes": ()},
    {"statement": "  "}, {"origin": "AI_APPROVED"}, {"category": ""},
])
def test_requirement_contract_rejects_malformed(changes):
    with pytest.raises(ValidationError):
        requirement(**changes)


def test_requirement_is_immutable_and_successor_retains_identity():
    original = requirement()
    with pytest.raises(ValidationError):
        original.statement = "replace history"
    successor = requirement(code=original.code, revision=2, predecessor_id=original.id, origin="AI_CANDIDATE")
    assert successor.id != original.id and successor.code == original.code


@pytest.mark.parametrize("status", ["SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"])
def test_matrix_lifecycle_requires_review_metadata(status):
    with pytest.raises(ValidationError):
        MatrixRevision(id=uuid4(), role_id=ROLE, revision=1, config_id=uuid4(), created_by=AUTHOR, status=status)


def test_stages_use_data_instead_of_fixed_labels():
    stage = StageDefinition(id=uuid4(), code="STAGE-X", label="Safety induction", sequence=7, start_day=3, end_day=9)
    assert stage.label == "Safety induction"
    with pytest.raises(ValidationError):
        StageDefinition(**{**stage.model_dump(), "end_day": 1})


def test_matrix_override_metadata_requires_reason():
    with pytest.raises(ValidationError, match="OVERRIDE_REASON_REQUIRED"):
        MatrixRevision(id=uuid4(), role_id=ROLE, revision=1, config_id=uuid4(), created_by=AUTHOR, admin_override=True)


def test_duplicate_source_and_scope_denied():
    chunk = uuid4()
    for values in ({"chunk_ids": (chunk, chunk)}, {"scopes": (Scope(), Scope())}):
        with pytest.raises(ValidationError):
            requirement(**values)


def test_normalized_duplicate_candidate_keeps_negation_and_numbers_distinct():
    a = requirement(statement="Complete   Training  within 7 days.")
    b = requirement(code="REQ-02", statement="complete training within 7 days.")
    c = requirement(code="REQ-03", statement="Do not complete training within 7 days.")
    d = requirement(code="REQ-04", statement="Complete training within 3 days.")
    assert duplicate_groups((a, b, c, d)) == (tuple(sorted((a.id, b.id), key=str)),)


def test_dependency_graph_accepts_multiple_prerequisites():
    ids = [uuid4() for _ in range(3)]
    entries = tuple(Entry(requirement_id=i, sequence=n) for n, i in enumerate(ids))
    validate_dependencies(entries, ((ids[2], ids[0]), (ids[2], ids[1])))


@pytest.mark.parametrize("kind", ["self", "cycle", "outside", "order", "duplicate"])
def test_dependency_graph_rejects_bad_edges(kind):
    a, b = uuid4(), uuid4()
    entries = (Entry(requirement_id=a, sequence=1), Entry(requirement_id=b, sequence=2))
    edges = {"self": ((a, a),), "cycle": ((a, b), (b, a)), "outside": ((b, uuid4()),),
             "order": ((a, b),), "duplicate": ((b, a), (b, a))}[kind]
    with pytest.raises(RRMError):
        validate_dependencies(entries, edges)


def test_deep_dag_does_not_depend_on_recursion_limit():
    ids = [UUID(int=100 + i) for i in range(2000)]
    entries = tuple(Entry(requirement_id=i, sequence=n) for n, i in enumerate(ids))
    validate_dependencies(entries, tuple(zip(ids[1:], ids[:-1])))


@pytest.mark.parametrize("changes", [
    {"review_status": "DRAFT"}, {"review_status": "SUBMITTED"}, {"review_status": "REJECTED"},
    {"review_status": "SUPERSEDED"}, {"parse_status": "NEEDS_REVIEW"}, {"parse_status": "FAILED"},
    {"parse_status": "PROCESSING"}, {"document_status": "ARCHIVED"},
    {"effective_date": date(2027, 1, 1)}, {"expiry_date": date(2026, 9, 22)},
    {"current_version_id": None}, {"current_version_id": uuid4()}, {"text_hash": "0" * 64},
])
def test_ineligible_source_states(changes):
    assert not source_eligible(source(**changes), TODAY)


def test_source_date_boundaries_inclusive():
    assert source_eligible(source(effective_date=TODAY, expiry_date=TODAY), TODAY)


def structured_timing():
    text = "Within 7 calendar days after joining"
    src = source(content=text, text_hash=sha256(text.encode()).hexdigest())
    tokens = {"original_text": text, "trigger": "joining", "relation": "Within", "value": "7", "unit": "days", "calendar_basis": "calendar"}
    evidence = {key: EvidenceSpan(chunk_id=src.chunk_id, start=text.index(value), end=text.index(value)+len(value), quote=value)
                for key, value in tokens.items()}
    return Timing(state="STRUCTURED", original_text=text, trigger="joining", relation="WITHIN", value=7,
                  unit="DAY", calendar_basis="CALENDAR", evidence=evidence), src


def test_timing_exact_support_and_no_guessing():
    timing, src = structured_timing()
    validate_timing(timing, {src.chunk_id: src}, (src.chunk_id,))
    validate_timing(Timing(), {}, ())
    with pytest.raises(RRMError, match="MANUAL_REVIEW"):
        validate_timing(Timing(state="AMBIGUOUS", original_text="Within 7 days"), {}, ())


@pytest.mark.parametrize("field,value", [("value", 3), ("trigger", "discovery"), ("calendar_basis", "BUSINESS"), ("relation", "AFTER")])
def test_timing_values_cannot_disagree_with_quotes(field, value):
    timing, src = structured_timing()
    timing = Timing(**{**timing.model_dump(), field: value})
    with pytest.raises(RRMError, match="NOT_EVIDENCED"):
        validate_timing(timing, {src.chunk_id: src}, (src.chunk_id,))


def test_timing_cross_chunk_and_offsets_forgery():
    timing, src = structured_timing()
    with pytest.raises(RRMError):
        validate_timing(timing, {src.chunk_id: src}, (uuid4(),))
    bad = timing.model_dump()
    bad["evidence"]["value"]["start"] = 0
    with pytest.raises(RRMError):
        validate_timing(Timing(**bad), {src.chunk_id: src}, (src.chunk_id,))
    bad = timing.model_dump()
    bad["evidence"]["original_text"]["end"] = len(src.content) + 100
    with pytest.raises(RRMError, match="EVIDENCE_MISMATCH"):
        validate_timing(Timing(**bad), {src.chunk_id: src}, (src.chunk_id,))


@pytest.mark.parametrize("payload", [
    {"state": "NOT_SPECIFIED", "original_text": "Within 7 days"},
    {"state": "AMBIGUOUS"}, {"state": "STRUCTURED", "original_text": "Within 7 days"},
    {"state": "AMBIGUOUS", "original_text": "soon", "value": 7},
])
def test_timing_malformed_structure(payload):
    with pytest.raises(ValidationError):
        Timing(**payload)


def test_configured_precedence_and_explicit_exception():
    sop, policy, faq, missing = (uuid4() for _ in range(4))
    cfg = PrecedenceConfig(ranks=DEFAULT_AUTHORITY_RANKS,
                            document_classes={sop: "DEPARTMENT_SOP", policy: "COMPANY_POLICY", faq: "FAQ"})
    assert precedence(sop, policy, cfg) == "LEFT"
    assert precedence(faq, policy, cfg) == "RIGHT"
    assert precedence(policy, policy, cfg) == "MANUAL_REVIEW"
    assert precedence(missing, policy, cfg) == "MANUAL_REVIEW"
    assert precedence(policy, sop, cfg, approved_exception=True, exception_target=sop, applicable_role_exception=True) == "LEFT"
    assert precedence(policy, sop, cfg, approved_exception=False, exception_target=sop, applicable_role_exception=True) == "RIGHT"
    assert precedence(policy, sop, cfg, approved_exception=True, exception_target=sop, applicable_role_exception=False) == "RIGHT"
    # Rank data, not code, controls ordinary precedence.
    changed = PrecedenceConfig(ranks={**DEFAULT_AUTHORITY_RANKS, "COMPANY_POLICY": 50}, document_classes=cfg.document_classes)
    assert precedence(sop, policy, changed) == "RIGHT"


def test_equal_rank_requires_manual_review():
    a, b = uuid4(), uuid4()
    cfg = PrecedenceConfig(ranks={"A": 1, "B": 1}, document_classes={a: "A", b: "B"})
    assert precedence(a, b, cfg) == "MANUAL_REVIEW"


@pytest.mark.parametrize("ranks,mapping", [({"ROLE_EXCEPTION": 100}, {}), ({"POLICY": -1}, {}),
    ({"POLICY": True}, {}), ({"POLICY": 1}, {uuid4(): "unmapped"})])
def test_config_rejects_malformed_authority(ranks, mapping):
    with pytest.raises(ValidationError):
        PrecedenceConfig(ranks=ranks, document_classes=mapping)


def test_snapshot_complete_and_reproducible():
    req = requirement()
    src = source(req.chunk_ids[0])
    a = build_snapshot(req, src)
    b = build_snapshot(req, src)
    assert a == b and snapshot_hash(a) == snapshot_hash(b)
    assert a["sources"][0]["source_location"]["row"] == 2


@pytest.mark.parametrize("changes", [{"status": MatrixStatus.SUBMITTED}, {"blocking_issues": ("CONFLICT",)},
                                    {"entries": ()}, {"requirements": ()}, {"configuration": None}])
def test_snapshot_fail_closed(changes):
    with pytest.raises(RRMError):
        build_snapshot(**changes)


def test_snapshot_rejects_mismatched_dictionary_chunk_identity():
    req = requirement()
    wrong = source()
    with pytest.raises(RRMError, match="INVALID_OR_STALE_SOURCE"):
        build_snapshot(req, wrong, sources={req.chunk_ids[0]: wrong})


def test_one_stale_source_blocks_whole_multi_source_requirement():
    a, b = source(), source(review_status="SUPERSEDED")
    req = requirement(chunk_ids=(a.chunk_id, b.chunk_id))
    with pytest.raises(RRMError, match="STALE_SOURCE"):
        build_snapshot(req, a, sources={a.chunk_id: a, b.chunk_id: b}, configuration=config(a, b))


def test_unknown_context_is_not_silently_filtered():
    with pytest.raises(RRMError, match="APPLICABILITY_MANUAL_REVIEW"):
        build_snapshot(requirement(scopes=(Scope(department_id=DEPT),)))


def test_unmapped_source_authority_blocks_snapshot():
    with pytest.raises(RRMError, match="UNMAPPED_AUTHORITY"):
        build_snapshot(configuration=PrecedenceConfig(ranks=DEFAULT_AUTHORITY_RANKS, document_classes={}))


def test_prerequisite_must_be_applicable_to_same_employee():
    a = requirement(scopes=(Scope(location_code="OTHER"),))
    b = requirement(code="REQ-02", statement="Second duty")
    sa, sb = source(a.chunk_ids[0]), source(b.chunk_ids[0])
    with pytest.raises(RRMError, match="PREREQUISITE_NOT_APPLICABLE"):
        complete_snapshot((a, b), (Entry(requirement_id=a.id, sequence=0), Entry(requirement_id=b.id, sequence=1)),
                          {sa.chunk_id: sa, sb.chunk_id: sb}, EmployeeContext(role_id=ROLE, location_code="KHI"), TODAY,
                          ((b.id, a.id),), configuration=config(sa, sb), status=MatrixStatus.APPROVED)


def test_explicit_role_exception_keeps_general_and_specific_evidence():
    base = requirement()
    special = requirement(code="REQ-02", statement="Complete advanced security training.", scopes=(Scope(role_id=ROLE),))
    sa, sb = source(base.chunk_ids[0]), source(special.chunk_ids[0])
    entries = (Entry(requirement_id=base.id, sequence=0), Entry(requirement_id=special.id, sequence=1, exception_to=base.id))
    args = ((base, special), entries, {sa.chunk_id: sa, sb.chunk_id: sb}, EmployeeContext(role_id=ROLE), TODAY)
    result = complete_snapshot(*args, configuration=config(sa, sb), status=MatrixStatus.APPROVED)
    assert len(result["requirements"]) == 2
    assert result["effective_ids"] == [str(special.id)]
    assert result["exception_resolutions"] == {str(base.id): str(special.id)}
    wrong_scope = requirement(code="REQ-02", id=special.id, statement=special.statement, chunk_ids=special.chunk_ids)
    with pytest.raises(RRMError, match="EXCEPTION_NOT_ROLE_SPECIFIC"):
        complete_snapshot((base, wrong_scope), *args[1:], configuration=config(sa, sb), status=MatrixStatus.APPROVED)


def test_snapshot_never_assumes_candidate_approval():
    req = requirement(origin="AI_CANDIDATE")
    src = source(req.chunk_ids[0])
    with pytest.raises(TypeError, match="status"):
        complete_snapshot((req,), (Entry(requirement_id=req.id, sequence=0),),
                          {src.chunk_id: src}, EmployeeContext(role_id=ROLE), TODAY, configuration=config(src))
    with pytest.raises(RRMError, match="MATRIX_NOT_ELIGIBLE"):
        build_snapshot(req, src, status=MatrixStatus.DRAFT)


@pytest.mark.parametrize("roles,own,override,reason,accepted", [
    ({"TRAINING_MANAGER"}, True, False, None, False),
    ({"TRAINING_MANAGER"}, False, False, None, False),
    ({"TRAINING_MANAGER", "REVIEWER"}, True, False, None, False),
    ({"TRAINING_MANAGER", "REVIEWER"}, True, True, "urgent", False),
    ({"REVIEWER"}, False, False, None, True),
    ({"ADMIN"}, True, False, "urgent", False),
    ({"ADMIN"}, True, True, None, False),
    ({"ADMIN"}, True, True, " ", False),
    ({"ADMIN"}, True, True, "Emergency approved by owner", True),
    ({"ADMIN"}, False, True, "override", False),
    ({"ADMIN"}, False, False, None, True),
    ({"MANAGER"}, False, False, None, False),
    ({"EMPLOYEE"}, False, False, None, False),
])
def test_approval_rbac_and_identity(roles, own, override, reason, accepted):
    args = (MatrixStatus.SUBMITTED, "APPROVE", AUTHOR if own else REVIEWER, frozenset(roles), frozenset({AUTHOR}), 2, 2)
    if accepted:
        assert authorize_transition(*args, admin_override=override, reason=reason) == MatrixStatus.APPROVED
    else:
        with pytest.raises(RRMError):
            authorize_transition(*args, admin_override=override, reason=reason)


@pytest.mark.parametrize("role", ["ADMIN", "TRAINING_MANAGER"])
def test_owner_can_submit(role):
    assert authorize_transition(MatrixStatus.DRAFT,"SUBMIT",AUTHOR,frozenset({role}),frozenset({AUTHOR}),0,0,
                                creator_id=AUTHOR) == MatrixStatus.SUBMITTED


@pytest.mark.parametrize("active,expected,integrity,status", [
    (False, 2, True, MatrixStatus.SUBMITTED), (True, 1, True, MatrixStatus.SUBMITTED),
    (True, 2, False, MatrixStatus.SUBMITTED), (True, 2, True, MatrixStatus.APPROVED),
    (True, 2, True, MatrixStatus.REJECTED), (True, 2, True, MatrixStatus.DRAFT),
])
def test_admin_cannot_override_integrity_staleness_or_lifecycle(active, expected, integrity, status):
    with pytest.raises(RRMError):
        authorize_transition(status,"APPROVE",AUTHOR,frozenset({"ADMIN"}),frozenset({AUTHOR}),expected,2,
                             active=active,integrity_valid=integrity,admin_override=True,reason="Emergency")


def test_reviewer_cannot_submit_and_rejection_requires_reason():
    with pytest.raises(RRMError):
        authorize_transition(MatrixStatus.DRAFT,"SUBMIT",REVIEWER,frozenset({"REVIEWER"}),frozenset({REVIEWER}),0,0,creator_id=REVIEWER)
    with pytest.raises(RRMError):
        authorize_transition(MatrixStatus.SUBMITTED,"REJECT",REVIEWER,frozenset({"REVIEWER"}),frozenset({AUTHOR}),1,1)
    assert authorize_transition(MatrixStatus.SUBMITTED,"REJECT",REVIEWER,frozenset({"REVIEWER"}),frozenset({AUTHOR}),1,1,
                                reason="Fix evidence",integrity_valid=False) == MatrixStatus.REJECTED


def test_canonical_hash_handles_order_unicode_numbers_and_changes():
    a = {"z": [1.0, Decimal("1.2500"), -0.0], "é": "source\ntext", "a": True}
    b = {"a": True, "é": "source\ntext", "z": [1, 1.25, 0]}
    assert canonical_json(a) == '{"a":true,"z":[1,1.25,0],"é":"source\\ntext"}'
    assert snapshot_hash(a) == snapshot_hash(b)
    assert snapshot_hash(a) != snapshot_hash({**b,"a":False})
    assert snapshot_hash({"sources":[1,2]}) != snapshot_hash({"sources":[2,1]})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), {1: "key"}, uuid4(), {1,2}])
def test_canonical_hash_rejects_non_json(value):
    with pytest.raises(RRMError):
        canonical_json(value)


@pytest.mark.parametrize('offset', [-12, -7, 0, 5, 14])
@pytest.mark.parametrize('instant', ['2026-09-23T00:00:00.000001+00:00', '2026-09-23T23:59:59.999999+00:00'])
def test_utc_instants_preserve_eligibility_payload_hash_and_stale_comparisons(offset, instant):
    from app.rrm_rules import utc_date, utc_timestamp
    utc = datetime.fromisoformat(instant)
    local = utc.astimezone(timezone(timedelta(hours=offset)))
    req = requirement()
    src = source(req.chunk_ids[0], effective_date=utc.date(), expiry_date=utc.date())
    assert source_eligible(src, utc_date(local)) == source_eligible(src, utc_date(utc)) is True
    snapshots = [build_snapshot(req, src, on_date=utc_date(t)) for t in (utc, local)]
    for payload, instant_value in zip(snapshots, (utc, local)):
        payload['canonical_timestamp_fixture'] = utc_timestamp(instant_value)
    assert snapshots[0] == snapshots[1]
    submitted_hash = snapshot_hash(snapshots[0])
    assert snapshot_hash(snapshots[1]) == submitted_hash  # approval stale comparison
    assert snapshot_hash(snapshots[1]) == submitted_hash  # retrieval stale comparison
    assert utc_timestamp(local) == instant.replace('+00:00', 'Z')
    expired = src.model_copy(update={'expiry_date': utc.date() - timedelta(days=1)})
    future = src.model_copy(update={'effective_date': utc.date() + timedelta(days=1)})
    assert not source_eligible(expired, utc_date(local))
    assert not source_eligible(future, utc_date(local))


def test_utc_helpers_reject_naive_instants():
    from app.rrm_rules import utc_date, utc_timestamp
    for fn in (utc_date, utc_timestamp):
        with pytest.raises(RRMError, match='NAIVE_TIMESTAMP'):
            fn(datetime(2026, 9, 23))


@pytest.mark.parametrize('text', ['', ' ', '\t', '\r\n', '\v\f', '\u0085', '\u00a0', '\u2003', '\u2028\u2029', '\u3000', ' \t\n'])
def test_security_reasons_reject_whitespace_consistently(text):
    from app.rrm_models import meaningful_reason, validate_reason
    assert not meaningful_reason(text)
    with pytest.raises(ValueError, match='MEANINGFUL_REASON_REQUIRED'):
        validate_reason(text)
    with pytest.raises(RRMError):
        authorize_transition(MatrixStatus.SUBMITTED, 'APPROVE', AUTHOR, frozenset({'ADMIN'}),
                             frozenset({AUTHOR}), 1, 1, admin_override=True, reason=text)
    with pytest.raises(ValidationError):
        Entry(requirement_id=uuid4(), sequence=0, downgrade_justification=text)


def downgrade_fixture(**changes):
    base = requirement()
    optional = requirement(code='REQ-02', statement='Training is optional for this role.',
                           requirement_type='OPTIONAL', mandatory=False, scopes=(Scope(role_id=ROLE),))
    sa = source(base.chunk_ids[0])
    text = optional.statement
    sb = source(optional.chunk_ids[0], content=text, text_hash=sha256(text.encode()).hexdigest())
    entry_data = dict(requirement_id=optional.id, sequence=1, exception_to=base.id, downgrade_requested=True,
                      downgrade_justification='Explicit role exemption supported by the linked policy.',
                      downgrade_evidence=EvidenceSpan(chunk_id=sb.chunk_id, start=0, end=len(text), quote=text))
    entry_data.update(changes)
    entries = (Entry(requirement_id=base.id, sequence=0), Entry(**entry_data))
    args = ((base, optional), entries, {sa.chunk_id: sa, sb.chunk_id: sb}, EmployeeContext(role_id=ROLE), TODAY)
    return args, dict(configuration=config(sa, sb), status=MatrixStatus.APPROVED)


def test_explicit_downgrade_requires_approved_matrix_and_retains_auditable_evidence():
    args, kwargs = downgrade_fixture()
    result = complete_snapshot(*args, **kwargs)
    base, optional = args[0]
    assert result['effective_ids'] == [str(optional.id)]
    assert len(result['requirements']) == 2
    record = next(x for x in result['entries'] if x['requirement_id'] == str(optional.id))
    assert record['exception_to'] == str(base.id) and record['downgrade_evidence'] and record['downgrade_justification']
    with pytest.raises(RRMError, match='MATRIX_NOT_ELIGIBLE'):
        complete_snapshot(*args, **{**kwargs, 'status': MatrixStatus.SUBMITTED})


@pytest.mark.parametrize('changes', [
    {'downgrade_requested': False, 'downgrade_justification': None, 'downgrade_evidence': None},
    {'downgrade_evidence': None}, {'downgrade_justification': None},
    {'downgrade_requested': False},
])
def test_downgrade_missing_decision_evidence_or_reason_blocks_even_admin_integrity_override(changes):
    args, kwargs = downgrade_fixture(**changes)
    with pytest.raises(RRMError, match='DOWNGRADE_MANUAL_REVIEW'):
        complete_snapshot(*args, **kwargs)
    with pytest.raises(RRMError, match='RRM_INTEGRITY_FAILURE'):
        authorize_transition(MatrixStatus.SUBMITTED, 'APPROVE', AUTHOR, frozenset({'ADMIN'}),
                             frozenset({AUTHOR}), 1, 1, admin_override=True, reason='Emergency', integrity_valid=False)


@pytest.mark.parametrize('attack', ['wrong_chunk', 'wrong_quote', 'wrong_role', 'stale_evidence', 'unrelated_target'])
def test_downgrade_rejects_invalid_or_unrelated_evidence_and_scope(attack):
    args, kwargs = downgrade_fixture()
    requirements, entries, sources, context, on_date = args
    base, optional = requirements
    entry = entries[1]
    if attack == 'wrong_chunk':
        entry = entry.model_copy(update={'downgrade_evidence': entry.downgrade_evidence.model_copy(update={'chunk_id': base.chunk_ids[0]})})
    elif attack == 'wrong_quote':
        entry = entry.model_copy(update={'downgrade_evidence': entry.downgrade_evidence.model_copy(update={'quote': 'forged'})})
    elif attack == 'wrong_role':
        optional = optional.model_copy(update={'scopes': (Scope(role_id=uuid4()),)})
    elif attack == 'stale_evidence':
        sources[optional.chunk_ids[0]] = sources[optional.chunk_ids[0]].model_copy(update={'review_status': 'SUPERSEDED'})
    else:
        entry = entry.model_copy(update={'exception_to': None})
    with pytest.raises(RRMError):
        complete_snapshot((base, optional), (entries[0], entry), sources, context, on_date, **kwargs)
