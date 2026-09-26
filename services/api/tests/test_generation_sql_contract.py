"""Static Phase 4C migration checks; these do not claim live PostgreSQL execution."""

from pathlib import Path
import re

from app.generation_prompt import PROMPT_VERSION, SCHEMA_VERSION, template_hash


SQL = (Path(__file__).resolve().parents[3] / "supabase" / "migrations" /
       "202609250001_generation_foundation.sql").read_text(encoding="utf-8")
GROQ_SQL = (Path(__file__).resolve().parents[3] / "supabase" / "migrations" /
            "202609250002_groq_generation_provider.sql").read_text(encoding="utf-8")
BOUNDED_SQL = (Path(__file__).resolve().parents[3] / "supabase" / "migrations" /
               "202609250003_bounded_generation_projection.sql").read_text(encoding="utf-8")
EXACT_SQL = (Path(__file__).resolve().parents[3] / "supabase" / "migrations" /
             "202609250004_exact_generation_output_contract.sql").read_text(encoding="utf-8")
COMPACT_SQL = (Path(__file__).resolve().parents[3] / "supabase" / "migrations" /
               "202609260001_compact_generation_output_contract.sql").read_text(encoding="utf-8")


def test_groq_additive_migration_keeps_existing_generation_guards():
    assert "\nbegin;" in GROQ_SQL and GROQ_SQL.rstrip().endswith("commit;")
    assert GROQ_SQL.count("end $$;") == 1
    assert "provider in ('gemini','groq')" in GROQ_SQL
    assert "p_provider not in ('gemini','groq')" in GROQ_SQL
    assert "create or replace function public.reserve_generation_run" in GROQ_SQL
    assert "security definer set search_path = ''" in GROQ_SQL
    for guard in ("gen4_private.actor()", "rrm_private.content_hash(p_input)",
                  "gen4_private.assert_effective_input", "GEN4_IDEMPOTENCY_CONFLICT",
                  "on conflict (created_by,employee_id,idempotency_key_hash) do nothing"):
        assert guard in GROQ_SQL
    for forbidden in ("drop table", "truncate ", "delete from public.generation_runs",
                      "update public.generation_runs", "disable row level security"):
        assert forbidden not in GROQ_SQL.lower()
    assert not re.search(r"(?im)^\s*(grant|revoke|create policy|alter policy|drop policy)\b", GROQ_SQL)
    assert "alter table public.generated_plans" not in GROQ_SQL.lower()
    assert "status = 'UNVERIFIED'" in SQL
    old = SQL[SQL.index("create function public.reserve_generation_run("):]
    old = old[:old.index("end $$;") + len("end $$;")]
    new = GROQ_SQL[GROQ_SQL.index("create or replace function public.reserve_generation_run("):]
    new = new[:new.index("end $$;") + len("end $$;")]
    # Only provider/model validation may differ from the already-reviewed RPC.
    new = new.replace("create or replace function", "create function", 1)
    old_start = old.index("or p_provider is distinct from 'gemini'")
    new_start = new.index("or p_provider is null")
    old_end = old.index("or p_prompt_version is distinct from")
    new_end = new.index("or p_prompt_version is distinct from")
    assert new[:new_start] == old[:old_start]
    assert new[new_end:] == old[old_end:]


def test_groq_provider_model_provenance_is_exact_and_gemini_remains_compatible():
    assert "check (provider in ('gemini','groq'))" in GROQ_SQL
    table_gemini = re.search(r"provider = 'gemini' and model ~ '([^']+)'", GROQ_SQL)
    rpc_gemini = re.search(r"p_provider = 'gemini' and p_model !~ '([^']+)'", GROQ_SQL)
    assert table_gemini and rpc_gemini
    old_gemini = re.search(r"provider = 'gemini'\).*?model ~ '([^']+)'", SQL, re.S)
    assert old_gemini and table_gemini.group(1) == rpc_gemini.group(1) == old_gemini.group(1)
    gemini_pattern = re.compile(table_gemini.group(1))
    for model in ("gemini-3.8-flash", "gemini_2.5", "gemini.flash"):
        assert gemini_pattern.fullmatch(model)
    assert not gemini_pattern.fullmatch("openai/gpt-oss-20b")
    assert "provider = 'groq' and model = 'openai/gpt-oss-20b'" in GROQ_SQL
    assert "p_provider = 'groq' and p_model is distinct from 'openai/gpt-oss-20b'" in GROQ_SQL
    assert "provider in ('gemini','groq')" in GROQ_SQL
    assert "p_provider is null or p_provider not in ('gemini','groq')" in GROQ_SQL
    # No alternative Groq model predicate or generic slash-bearing model check.
    assert GROQ_SQL.count("provider = 'groq' and model = 'openai/gpt-oss-20b'") == 1
    assert "[A-Za-z0-9_./-]" not in GROQ_SQL


def test_additive_transaction_and_exact_bootstrap_defaults():
    assert SQL.lstrip().startswith("-- Phase 4C additive foundation")
    assert "\nbegin;" in SQL and SQL.rstrip().endswith("commit;")
    for forbidden in ("drop table", "truncate ", "delete from public.", "update public.onboarding_stage_definitions"):
        assert forbidden not in SQL.lower()
    for code in ("ORIENTATION", "POLICIES_COMPLIANCE", "ROLE_TRAINING",
                 "PRACTICAL_APPLICATION", "ASSESSMENT_COMPLETION"):
        assert code in SQL
    assert "v_starts integer[] := array[0,1,2,4,7]" in SQL
    assert "v_ends integer[] := array[1,3,5,7,7]" in SQL
    assert "values(v_codes[v_index],1,null,v_labels[v_index],v_index - 1,v_starts[v_index],v_ends[v_index],v_actor)" in SQL
    assert "gen4_private.actor(true)" in SQL
    assert "GEN4_BOOTSTRAP_PARTIAL_CONFIGURATION" in SQL
    assert "GEN4_BOOTSTRAP_CONFLICT" in SQL
    assert "and name = 'Standard Employee Onboarding' and status = 'ACTIVE'" in SQL
    assert "or exists (select 1 from public.onboarding_stage_sets)" in SQL
    assert "pg_catalog.pg_advisory_xact_lock(4004,1)" in SQL
    assert "lock table public.onboarding_stage_definitions in share row exclusive mode" in SQL


def test_stage_set_uniqueness_immutability_and_versioning():
    assert "create unique index onboarding_one_active_set" in SQL
    assert "unique(code,version)" in SQL
    assert "unique(stage_set_id,stage_definition_id)" in SQL
    assert "stage_set_items_immutable" in SQL
    assert "stage_set_update_guard" in SQL
    assert "gen4_private.assert_stage_set" in SQL
    assert "group by s.code having count(*) > 1" in SQL


def test_generation_lifecycle_idempotency_and_stale_guards():
    for name in ("generation_runs", "generation_attempts", "generated_plans"):
        assert f"create table public.{name}" in SQL
    assert "status in ('QUEUED','RUNNING','UNVERIFIED','FAILED','STALE_INPUT')" in SQL
    assert "status = 'UNVERIFIED'" in SQL
    assert "unique(created_by,employee_id,idempotency_key_hash)" in SQL
    assert "create unique index generation_one_active_input" in SQL
    assert "on conflict (created_by,employee_id,idempotency_key_hash) do nothing" in SQL
    assert "v_existing.provider_config is distinct from p_provider_config" in SQL
    assert "for update" in SQL
    assert "generation_attempts_immutable" in SQL and "generated_plans_immutable" in SQL
    assert "v_run.status <> 'RUNNING'" in SQL
    assert "p_postflight_hash is distinct from v_run.input_hash" in SQL
    assert "(v_run.input_snapshot->>'as_of')::timestamptz is distinct from" in SQL
    assert "GENERATION_STALE_INPUT" in SQL
    assert "get_rrm_ground_truth" in SQL
    assert "v_employee.profile_id::text is distinct from v_run.input_snapshot->'employee'->>'profile_id'" in SQL
    assert "r.status = 'ACTIVE' and (r.department_id is null or r.department_id = v_employee.department_id)" in SQL
    assert "r.code = v_run.input_snapshot->'employee'->>'role_code'" in SQL
    assert "d.status = 'ACTIVE' and d.code = v_run.input_snapshot->'employee'->>'department_code'" in SQL
    assert "v_matrix.revision is distinct from v_run.matrix_revision" in SQL
    for name in ("reserve_generation_run", "finish_generation_run"):
        section = SQL[SQL.index(f"create function public.{name}"):]
        assert section.index("perform 1 from public.roles where id = v_employee.role_id for share") < section.index(
            "from public.role_requirement_matrices")
    assert "is distinct from v_set.name" in SQL
    assert "is distinct from v_chunk.text_hash" in SQL
    assert "p_plan->>'schema_version' is distinct from v_run.schema_version" in SQL
    assert "p_plan->>'generation_request_id' is distinct from p_run::text" in SQL
    assert "p_response_hash is null or p_response_size is null" in SQL


def test_grants_rls_actor_and_fixed_search_paths():
    assert "revoke all on schema gen4_private from public, anon, authenticated, service_role" in SQL
    assert "revoke all on public.%I from public,anon,authenticated,service_role" in SQL
    assert "grant select on public.%I to authenticated" in SQL
    assert "enable row level security" in SQL
    assert "revoke all on function %s from public,anon,authenticated,service_role" in SQL
    assert "to authenticated;" in SQL
    assert SQL.count("security definer set search_path = ''") == 12
    assert "public.current_profile_id()" in SQL and "public.has_app_role('ADMIN')" in SQL
    assert "public.has_app_role('TRAINING_MANAGER')" in SQL
    assert "public.has_app_role('REVIEWER')" in SQL
    assert "created_by = public.current_profile_id()" in SQL
    assert "service_role" not in SQL[SQL.index("create function public.reserve_generation_run"):SQL.index("-- Explicit grants")]


def test_abandoned_run_recovery_is_admin_only_bounded_and_audited():
    section = SQL[SQL.index("create function public.recover_abandoned_generation_run"):
                  SQL.index("-- Explicit grants")]
    assert "gen4_private.actor(true)" in section
    assert "where id = p_run for update" in section
    assert "v_run.status <> 'RUNNING'" in section
    assert "interval '15 minutes'" in section
    assert "GEN4_RECOVERY_TOO_EARLY" in section
    assert "status = 'FAILED',error_code = 'ABANDONED_RUN'" in section
    assert "GENERATION_ABANDONED" in section
    assert "insert into public.generated_plans" not in section


def test_prompt_versions_are_locked_to_reviewed_phase4b_contract():
    assert "phase4b-generation/1.0.0" in SQL
    assert SCHEMA_VERSION in SQL
    assert "c37953b0647c2133fb49c149d3a5cfbe0e5efa1a512a137bfabb76a551ee0827" in SQL
    assert "phase4d-bounded-generation/1.0.0" in BOUNDED_SQL
    assert "a0275be4cc8b88bb4ff2b0cf19485abcd482482cca662dffb0e37fa130e8e2a6" in BOUNDED_SQL
    assert PROMPT_VERSION in COMPACT_SQL and template_hash() in COMPACT_SQL


def test_exact_output_contract_migration_preserves_reservation_security():
    assert EXACT_SQL.lstrip().startswith("-- Phase 4D")
    assert "\nbegin;" in EXACT_SQL and EXACT_SQL.rstrip().endswith("commit;")
    assert EXACT_SQL.count("end $$;") == 1
    assert "security definer set search_path = ''" in EXACT_SQL
    assert "add constraint generation_runs_exact_output_projection_check" in EXACT_SQL
    assert "prompt_version <> 'phase4d-exact-output/1.0.0' or projection_hash is not null" in EXACT_SQL
    assert "gen4_private.actor()" in EXACT_SQL
    assert "gen4_private.assert_effective_input" in EXACT_SQL
    assert "rrm_private.content_hash(p_input) <> p_input_hash" in EXACT_SQL
    assert "p_provider not in ('gemini','groq')" in EXACT_SQL
    assert "p_model is distinct from 'openai/gpt-oss-20b'" in EXACT_SQL
    assert "v_existing.projection_hash <> p_provider_config->>'projection_hash'" in EXACT_SQL
    assert "insert into public.generated_plans" not in EXACT_SQL
    assert EXACT_SQL.lower().count("alter table") == 1
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", EXACT_SQL)
    old_function = BOUNDED_SQL.split("create or replace function public.reserve_generation_run_bounded(", 1)[1].split("end $$;", 1)[0]
    new_function = EXACT_SQL.split("create or replace function public.reserve_generation_run_bounded(", 1)[1].split("end $$;", 1)[0]
    assert new_function.replace("phase4d-exact-output/1.0.0", "phase4d-bounded-generation/1.0.0").replace(
        "f8ce3cc932b45cec0c0fe132b18707f35eb0809d54e5af1dd2707aa960998401", "a0275be4cc8b88bb4ff2b0cf19485abcd482482cca662dffb0e37fa130e8e2a6") == old_function


def test_compact_migration_changes_only_new_contract_pin_and_constraint():
    normalized = COMPACT_SQL.replace("compact exact output prompt", "exact output prompt").replace(
        "generation_runs_compact_output_projection_check", "generation_runs_exact_output_projection_check").replace(
        PROMPT_VERSION, "phase4d-exact-output/1.0.0").replace(
        template_hash(), "f8ce3cc932b45cec0c0fe132b18707f35eb0809d54e5af1dd2707aa960998401")
    assert normalized.strip() == EXACT_SQL.strip()
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop|grant|revoke)\b", COMPACT_SQL)


def test_bounded_projection_migration_is_additive_and_pins_new_hash():
    assert BOUNDED_SQL.lstrip().startswith("-- Phase 4D")
    assert "\nbegin;" in BOUNDED_SQL and BOUNDED_SQL.rstrip().endswith("commit;")
    assert BOUNDED_SQL.count("end $$;") == 1
    assert "add column projection_hash text" in BOUNDED_SQL
    assert "projection_hash is null or projection_hash ~ '^[0-9a-f]{64}$'" in BOUNDED_SQL
    assert "p_provider_config->>'projection_hash' is null" in BOUNDED_SQL
    assert "create or replace function public.reserve_generation_run_bounded" in BOUNDED_SQL
    assert "create or replace function public.reserve_generation_run(" not in BOUNDED_SQL
    assert "security definer set search_path = ''" in BOUNDED_SQL
    assert "gen4_private.actor()" in BOUNDED_SQL
    assert "gen4_private.assert_effective_input" in BOUNDED_SQL
    assert "rrm_private.content_hash(p_input) <> p_input_hash" in BOUNDED_SQL
    assert "or v_existing.projection_hash <> p_provider_config->>'projection_hash'" in BOUNDED_SQL
    assert "revoke all on function public.reserve_generation_run_bounded" in BOUNDED_SQL
    assert "to authenticated;" in BOUNDED_SQL
    assert not re.search(r"(?im)^\s*(update|delete|truncate|drop table|grant (insert|update|delete))\b", BOUNDED_SQL)
    assert "status = 'UNVERIFIED'" in SQL
