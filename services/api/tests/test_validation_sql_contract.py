"""Static SQL security contracts; no claim of live PostgreSQL execution."""
from pathlib import Path
import re

SQL=(Path(__file__).parents[3]/"supabase/migrations/202609260002_python_validation_jev.sql").read_text()


def test_additive_transaction_and_no_phase4_mutation():
    assert SQL.count("\nbegin;")==1 and SQL.rstrip().endswith("commit;")
    assert SQL.count("$$")%2==0
    assert not re.search(r"(?im)^\s*(update|delete|drop|truncate)\b",SQL)
    assert "alter table public.generation_runs" not in SQL
    assert "alter table public.generated_plans" not in SQL
    for table in ("validation_runs","validation_findings","jev_decisions","plan_review_actions"):
        assert f"create table public.{table}" in SQL


def test_computed_evidence_is_backend_only_not_forgeable_by_user_jwt():
    assert "auth.role() is distinct from 'service_role'" in SQL
    assert "grant execute on function public.record_python_validation(uuid,uuid,jsonb) to service_role" in SQL
    assert "from public,anon,authenticated,service_role" in SQL
    assert "revoke all on public.%I from public,anon,authenticated,service_role" in SQL
    assert "grant select on public.%I to authenticated" in SQL
    assert not re.search(r"grant (insert|update|delete|all)",SQL,re.I)
    assert "enable row level security" in SQL
    assert SQL.count("security definer set search_path = ''")==4


def test_idempotency_and_hashes_are_bound():
    assert "unique(generated_plan_id,validator_version,input_hash,projection_hash,content_hash)" in SQL
    assert "pg_advisory_xact_lock" in SQL
    assert "existing.result_hash <> digest" in SQL
    assert "VAL5_IDEMPOTENCY_CONFLICT" in SQL
    for guard in ("p_result->>'input_hash' is distinct from r.input_hash",
        "p_result->>'projection_hash' is distinct from r.projection_hash",
        "p_result->>'content_hash' is distinct from p.content_hash",
        "rrm_private.content_hash(r.input_snapshot) <> r.input_hash",
        "rrm_private.content_hash(p.content) <> p.content_hash"):
        assert guard in SQL


def test_review_authority_independence_and_audit():
    assert "public.has_app_role('ADMIN') or public.has_app_role('REVIEWER')" in SQL
    assert "p_action='OVERRIDE' and not public.has_app_role('ADMIN')" in SQL
    assert "not rrm_private.meaningful_reason(p_reason)" in SQL
    assert "actor=r.created_by or actor=r.employee_profile_id" in SQL
    assert "insert into public.plan_review_actions" in SQL
    assert "original_jev_status" in SQL and "PLAN_REVIEW_" in SQL
    assert "gen4_private.immutable_row()" in SQL
    assert "result not in ('VERIFIED','VERIFIED_WITH_WARNING')" in SQL
    assert "perform val5_private.assert_current(r.id)" in SQL


def test_staleness_guard_and_read_policies():
    for text in ("m.status <> 'APPROVED'", "s.status <> 'ACTIVE'", "m.lock_version <> r.matrix_lock_version",
        "current_effective_document_version", "now() at time zone 'UTC'", "gen4_private.assert_effective_input",
        "r.created_by=public.current_profile_id()", "public.has_app_role('REVIEWER')"):
        assert text in SQL
    assert "public.has_app_role('MANAGER')" not in SQL
    assert "public.has_app_role('EMPLOYEE')" not in SQL


def test_repository_rpc_argument_names_match_sql():
    import ast
    source=(Path(__file__).parents[1]/"app/validation_repository.py").read_text()
    tree=ast.parse(source)
    for name in ("record_python_validation","review_validated_plan"):
        signature=re.search(rf"create function public\.{name}\((.*?)\) returns",SQL,re.S).group(1)
        expected={argument.strip().split()[0] for argument in signature.split(',')}
        call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call)
            and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value==name)
        actual={key.value for key in call.args[1].keys}
        assert actual==expected
