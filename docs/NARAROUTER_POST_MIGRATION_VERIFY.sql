-- Run AFTER manually executing 202609270002 once. Catalog reads only.
-- No reservation function call, data writes, or provider invocation.
-- Expect one row with every boolean true. A false flag requires investigation.
begin read only;
with target as (
  select to_regprocedure('public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)') as id
), fn as (
  select p.oid, p.prosecdef, p.proconfig,
         regexp_replace(p.prosrc, '\s+', '', 'g') as body
  from target t left join pg_proc p on p.oid = t.id
), checks as (
  select *,
    exists (select 1 from pg_constraint c
      where c.conrelid = 'public.generation_runs'::regclass
        and c.conname = 'generation_runs_provider_check' and c.convalidated
        and position('''nararouter''' in pg_get_constraintdef(c.oid)) > 0) as table_accepts_nararouter,
    exists (select 1 from pg_constraint c
      where c.conrelid = 'public.generation_runs'::regclass
        and c.conname = 'generation_runs_compact_v2_projection_check' and c.convalidated
        and position('phase4d-compact-context/2.0.0' in pg_get_constraintdef(c.oid)) > 0
        and position('projection_hash IS NOT NULL' in pg_get_constraintdef(c.oid)) > 0) as table_projection_guard
  from fn
)
select oid is not null as function_exists,
  coalesce(md5(body) = '7322060893ad8019ff185f605ea427a4', false) as complete_body_matches_reviewed_migration,
  table_accepts_nararouter,
  coalesce(position($q$p_providernotin('gemini','groq','nararouter')$q$ in body) > 0, false) as function_accepts_nararouter,
  coalesce(position($q$(p_provider='nararouter'andp_modelisdistinctfrom'gemini-3.8-flash-high')$q$ in body) > 0, false) as exact_nararouter_model_pin,
  coalesce(position($q$(p_provider='groq'andp_modelisdistinctfrom'openai/gpt-oss-20b')$q$ in body) > 0, false) as exact_groq_model_pin,
  coalesce(position($q$(p_provider='gemini'andp_model!~'^[A-Za-z0-9_.-]{1,100}$')$q$ in body) > 0, false) as gemini_validation_preserved,
  coalesce(position($q$p_prompt_versionisdistinctfrom'phase4d-compact-context/2.0.0'$q$ in body) > 0, false) as v2_prompt_pin,
  coalesce(position($q$p_template_hashisdistinctfrom'11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc'$q$ in body) > 0, false) as v2_template_pin,
  coalesce(position($q$p_schema_versionisdistinctfrom'onboarding-plan/1.0.0'$q$ in body) > 0, false) as output_schema_pin,
  coalesce(position($q$p_provider_config->>'projection_hash'isnull$q$ in body) > 0
    and position($q$p_provider_config->>'projection_hash'!~'^[0-9a-f]{64}$'$q$ in body) > 0
    and position($q$template_hash,schema_version,projection_hash,idempotency_key_hash)$q$ in body) > 0
    and position($q$p_provider_config->>'projection_hash',p_idempotency_key_hash)$q$ in body) > 0, false) as projection_validation_and_persistence,
  table_projection_guard,
  coalesce(prosecdef, false) as security_definer,
  coalesce('search_path=""' = any(proconfig), false) as empty_search_path
from checks;
rollback;
