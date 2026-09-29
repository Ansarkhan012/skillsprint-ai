-- Read-only. Run in the Supabase SQL editor; save the single JSON cell to a file and pass it
-- to --db-verification. Verifies the live reservation function accepts this exact contract.
with f as (
  select pg_get_functiondef('public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)'::regprocedure) as d
)
select json_build_object(
  'checked_prompt_version', 'phase4d-content-only/4.1.2',
  'checked_template_hash', 'c0402bdf188c55d1f467dcb01b94891d75955a442152af80f60e84a929d46180',
  'checked_provider', 'deepseek',
  'checked_model', 'deepseek-flash',
  'provider_accepted', position('''deepseek''' in d) > 0 and exists (
    select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass
    and conname = 'generation_runs_provider_check'
    and position('''deepseek''' in pg_get_constraintdef(oid)) > 0),
  'pair_accepted', d ~ 'p_prompt_version = ''phase4d-content-only/4.1.2''\s+and p_template_hash = ''c0402bdf188c55d1f467dcb01b94891d75955a442152af80f60e84a929d46180''',
  'model_accepted', (position('''deepseek-flash''' in d) > 0 or 'deepseek' = 'gemini') and exists (
    select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass
    and conname = 'generation_runs_model_check'
    and (position('''deepseek-flash''' in pg_get_constraintdef(oid)) > 0 or 'deepseek' = 'gemini')),
  'max_timeout_seconds', (regexp_match(d, 'timeout_seconds''\)::numeric not between 1 and (\d+)'))[1]::int,
  'max_output_tokens_upper', (regexp_match(d, 'max_output_tokens''\)::numeric not between 256 and (\d+)'))[1]::int,
  'projection_constraint_present', exists (select 1 from pg_constraint where conrelid = 'public.generation_runs'::regclass and conname = 'generation_runs_content_v412_projection_check'),
  'diagnostics_table_present', to_regclass('public.generation_attempt_diagnostics') is not null,
  'diagnostics_rpc_present', exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                                     where n.nspname = 'public' and p.proname = 'record_generation_attempt_diagnostics'),
  'diagnostics_rpc_executable', coalesce((select has_function_privilege('authenticated', p.oid, 'execute')
                                          from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                                          where n.nspname = 'public'
                                            and p.proname = 'record_generation_attempt_diagnostics'), false),
  'postgrest_schema_reload_trigger_present', exists (select 1 from pg_event_trigger where evtname ilike 'pgrst%')
) as readiness
from f;
