"""Static migration contract tests ONLY. These never connect to or execute PostgreSQL.

They catch privilege/guard regressions, not PostgreSQL runtime or live RLS failures.
"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]
SQL = (ROOT / "supabase/migrations/202609230003_rrm_foundation.sql").read_text(encoding="utf-8")


def body(name):
    match = re.search(r"create function " + re.escape(name) + r"\(.*?\$\$(.*?)\$\$;", SQL, re.S)
    assert match, name
    return match.group(1)


def test_migration_is_atomic_and_additive():
    sql = re.sub(r"--[^\n]*", "", SQL).strip()
    assert sql.startswith("begin;") and sql.endswith("commit;")
    assert not re.search(r"\b(drop|truncate|delete\s+from)\b", sql, re.I)
    assert not re.search(r"alter\s+table\s+public\.(profiles|profile_roles|documents|document_versions|document_chunks)\b", sql, re.I)
    assert "create or replace" not in sql


def test_all_new_tables_are_in_security_loop_with_explicit_read_only_grants():
    tables = set(re.findall(r"create table public\.(\w+)", SQL))
    loop = re.search(r"foreach v_table in array array\[(.*?)\] loop", SQL, re.S).group(1)
    assert tables == set(re.findall(r"'([^']+)'", loop))
    assert len(tables) == 12
    assert "alter table public.%I enable row level security" in SQL
    assert "revoke all on public.%I from public,anon,authenticated,service_role" in SQL
    assert "grant select on public.%I to authenticated" in SQL
    assert not re.search(r"grant\s+(insert|update|delete|all)\b", SQL, re.I)
    policy = re.search(r"create policy rrm_read.*", SQL).group()
    for role in ("ADMIN", "TRAINING_MANAGER", "REVIEWER"):
        assert role in policy
    assert "'MANAGER'" not in policy and "'EMPLOYEE'" not in policy


def test_functions_have_fixed_search_path_and_explicit_acl():
    headers = re.findall(r"create function (.*?)as \$\$", SQL, re.S)
    assert len(headers) >= 15
    assert all("set search_path = ''" in header for header in headers)
    public_names = set(re.findall(r"create function public\.(\w+)\(", SQL))
    acl_names = set(re.findall(r"'(\w+)'", re.search(r"p.proname = any\(array\[(.*?)\]\)", SQL, re.S).group(1)))
    assert public_names == acl_names
    assert "revoke all on schema rrm_private from public, anon, authenticated, service_role" in SQL
    assert "revoke all on function %s from public,anon,authenticated,service_role" in SQL
    assert "to service_role" not in SQL
    for name in public_names:
        assert "rrm_private.actor(" in body("public." + name)


def test_no_client_supplied_source_lineage_or_approval_identity():
    candidate = body("public.create_requirement_candidate")
    assert "insert into public.requirement_sources values(v_id,(v_chunk #>> '{}')::uuid)" in candidate
    assert "p_data->>'created_by'" not in candidate
    assert "p_data->>'document_version_id'" not in candidate
    assert "p_data->>'source_location'" not in candidate
    assert "rrm_private.assert_keys" in candidate
    assert "public.document_chunks(id) on delete restrict" in SQL
    assert "join public.document_versions v on v.id = c.document_version_id" in SQL


@pytest.mark.parametrize("guard", ["d.status <> 'ACTIVE'", "v.parse_status <> 'PARSED'", "v.review_status <> 'APPROVED'",
    "v.effective_date > rrm_private.utc_today()", "v.expiry_date < rrm_private.utc_today()", "c.text_hash <>", "rrm_document_authorities",
    "RRM_DUPLICATE_REQUIREMENT", "RRM_DEPENDENCY_CYCLE_OR_ORDER", "RRM_INVALID_REQUIREMENT_SCOPE",
    "RRM_OVERLAPPING_EXCEPTIONS_MANUAL_REVIEW", "RRM_EXCEPTION_SCOPE_NOT_SUBSET", "rrm_private.valid_timing"])
def test_approval_integrity_guards(guard):
    assert guard in body("rrm_private.assert_matrix")


def test_approval_cannot_skip_source_checks_with_admin_override():
    transition = body("public.transition_rrm_matrix")
    assert "if p_action <> 'REJECT' then" in transition
    assert "perform rrm_private.lock_sources(p_matrix)" in transition
    assert "if v_hash is distinct from m.snapshot_hash" in transition
    assert "p_admin_override" not in transition.split("if p_action <> 'REJECT' then",1)[1].split("end if;",1)[0]
    assert "public.has_app_role('ADMIN') and p_admin_override" in transition
    assert "RRM_REASON_REQUIRED" in transition
    assert "rrm_private.contributed(p_matrix,v_actor)" in transition


def test_all_contributors_including_old_edits_are_checked():
    contributors = body("rrm_private.contributed")
    assert "m.created_by = p_actor or m.submitted_by = p_actor" in contributors
    assert "e.created_by = p_actor" in contributors and "r.created_by = p_actor" in contributors
    assert "current_edit" not in contributors


@pytest.mark.parametrize("name", ["edit_rrm_matrix", "raise_rrm_issue", "resolve_rrm_issue", "transition_rrm_matrix"])
def test_mutations_use_expected_versions_and_row_locks(name):
    code = body("public." + name)
    assert "for update" in code
    assert "p_expected_version is distinct from" in code
    assert "RRM_EDIT_CONFLICT" in code
    assert "lock_version = lock_version + 1" in code


def test_no_history_deletion_or_submitted_editing():
    edit = body("public.edit_rrm_matrix")
    assert "v_matrix.created_by <> v_actor or v_matrix.status <> 'DRAFT'" in edit
    assert "insert into public.rrm_matrix_edits" in edit
    assert "delete" not in edit.lower()
    assert "RRM_IMMUTABLE_HISTORY" in body("rrm_private.immutable_row")
    assert "before update or delete" in SQL and "before delete" in SQL


def test_issue_resolution_is_append_only_and_rechecked_after_edits():
    resolve = body("public.resolve_rrm_issue")
    assert "insert into public.rrm_issue_resolutions" in resolve
    assert "update public.rrm_issues" not in resolve
    assert "r.edit_no = m.current_edit" in body("rrm_private.assert_matrix")


def test_stale_ground_truth_revalidated_and_no_filtered_partial_result():
    code = body("public.get_rrm_ground_truth")
    assert "m.status <> 'APPROVED'" in code
    assert "for share" in code
    assert "rrm_private.lock_sources(p_matrix)" in code
    assert "is distinct from m.snapshot_hash" in code
    assert "exception when" not in code.lower()
    assert "order by d.id for share" in body("rrm_private.lock_sources")


def test_roles_serialized_and_old_revision_cannot_supersede_newer():
    code = body("public.transition_rrm_matrix")
    assert code.index("from public.roles") < code.index("select * into strict m")
    assert "revision >= m.revision" in code
    assert "RRM_SUPERSEDED" in code
    assert "rrm_one_approved_role_idx" in SQL


def test_timing_requires_exact_source_anchors_and_rejects_null_offsets():
    code = body("rrm_private.valid_timing")
    assert "jsonb_typeof(v_span->'start') is distinct from 'number'" in code
    assert "jsonb_typeof(v_span->'end') is distinct from 'number'" in code
    assert "substring(v_content" in code
    assert "(v_span->>'end')::integer > char_length(v_content)" in code
    assert "RRM_TIMING_MANUAL_REVIEW" in code
    assert "RRM_TIMING_EVIDENCE_MISMATCH" in code


def test_canonical_order_and_hash_algorithm_are_explicit():
    code = body("rrm_private.canonical_json")
    assert 'order by key collate "C"' in code
    assert "order by ord" in code
    assert "sha256(convert_to" in body("rrm_private.content_hash")
    snapshot = body("rrm_private.matrix_snapshot")
    assert "order by e.requirement_id" in snapshot and "order by c.id" in snapshot


def test_no_provider_or_service_secret_in_new_migration():
    assert "SUPABASE_SERVICE_ROLE_KEY" not in SQL
    assert not re.search(r"eyJ[\w-]{20,}\.[\w-]{20,}\.[\w-]{20,}", SQL)
    assert "http" not in SQL.lower()


def test_utc_policy_does_not_inherit_session_timezone():
    assert "statement_timestamp() at time zone 'UTC'" in body('rrm_private.utc_today')
    timestamp = body('rrm_private.utc_timestamp')
    assert "p_value at time zone 'UTC'" in timestamp
    assert 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"' in timestamp
    assert 'current_date' not in SQL.lower()
    snapshot = body('rrm_private.matrix_snapshot')
    for expression in ('r.created_at', 'st.created_at', 'c.created_at', 'v.approved_at', 'i.created_at', 'r.resolved_at'):
        assert f'rrm_private.utc_timestamp({expression})' in snapshot
    for fn in ('public.transition_rrm_matrix', 'public.get_rrm_ground_truth'):
        assert 'rrm_private.matrix_snapshot(p_matrix)' in body(fn)
        assert 'rrm_private.content_hash(' in body(fn)
        assert 'rrm_private.lock_sources(p_matrix)' in body(fn)


def test_downgrade_cannot_bypass_evidence_or_review():
    guard = body('rrm_private.valid_downgrade')
    for text in ('base.mandatory and not specific.mandatory', 'not e.downgrade_requested',
                 'rrm_private.meaningful_reason(e.downgrade_justification)', 'e.downgrade_evidence is null',
                 'rs.requirement_id = e.requirement_id', "rs.chunk_id = (s->>'chunk_id')::uuid",
                 'substring(v_content', 'RRM_DOWNGRADE_MANUAL_REVIEW', 'RRM_DOWNGRADE_EVIDENCE_MISMATCH'):
        assert text in guard
    assert 'rrm_private.valid_downgrade(m.id,m.current_edit,v_requirement)' in body('rrm_private.assert_matrix')
    assert 'p_admin_override' not in guard
    assert 'p_admin_override' not in body('rrm_private.assert_matrix')
    assert "'downgrade_decisions'" in body('public.transition_rrm_matrix')
    assert "'entry',to_jsonb(e)" in body('rrm_private.matrix_snapshot')
    assert "jsonb_typeof(v_entry->'downgrade_requested') is distinct from 'boolean'" in body('public.edit_rrm_matrix')


def test_reason_whitespace_set_and_security_fields_match_python():
    from app.rrm_models import REASON_WHITESPACE
    chars = {int(x) for x in re.findall(r'chr\((\d+)\)', body('rrm_private.nonblank_text'))}
    assert chars == set(map(ord, REASON_WHITESPACE))
    assert 'translate(p_value,' in body('rrm_private.nonblank_text')
    assert 'between 1 and 2000' in body('rrm_private.meaningful_reason')
    assert SQL.count('reason text not null check (rrm_private.meaningful_reason(reason))') == 3
    for field in ('decision_reason', 'downgrade_justification'):
        assert f'rrm_private.meaningful_reason({field})' in SQL
    for fn in ('public.transition_rrm_matrix', 'public.resolve_rrm_issue'):
        assert 'rrm_private.meaningful_reason(p_reason)' in body(fn)
