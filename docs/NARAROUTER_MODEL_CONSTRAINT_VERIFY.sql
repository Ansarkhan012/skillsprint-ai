-- Read-only post-correction check. Expect all booleans true.
begin read only;
with constraints as (
  select conname, pg_get_constraintdef(oid) as definition
    from pg_constraint
   where conrelid = 'public.generation_runs'::regclass
     and conname in ('generation_runs_provider_check', 'generation_runs_model_check')
)
select
  exists (select 1 from constraints where conname = 'generation_runs_provider_check'
          and position('nararouter' in definition) > 0) as provider_accepts_nararouter,
  exists (select 1 from constraints where conname = 'generation_runs_model_check'
          and position('gemini' in definition) > 0
          and position('openai/gpt-oss-20b' in definition) > 0
          and position('gemini-3.8-flash-high' in definition) > 0
          and position('nararouter' in definition) > 0) as model_check_accepts_exact_nararouter_alias;
rollback;
