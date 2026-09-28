-- Complete NaraRouter reservation acceptance after 202609270002.
-- The earlier migration updated the provider check and function, but left this
-- table-level model check limited to Gemini and Groq. No rows are changed.
begin;

do $$
declare v_model_check text;
begin
  select pg_get_constraintdef(c.oid) into v_model_check
    from pg_constraint c
   where c.conrelid = 'public.generation_runs'::regclass
     and c.conname = 'generation_runs_model_check'
     and c.contype = 'c'
     and c.convalidated;
  if v_model_check is null
     or position('gemini' in v_model_check) = 0
     or position('openai/gpt-oss-20b' in v_model_check) = 0
     or position('nararouter' in v_model_check) > 0
     or not exists (
       select 1 from pg_constraint c
        where c.conrelid = 'public.generation_runs'::regclass
          and c.conname = 'generation_runs_provider_check'
          and c.convalidated
          and position('nararouter' in pg_get_constraintdef(c.oid)) > 0
     )
     or not exists (
       select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'reserve_generation_run_bounded'
          and p.oid = to_regprocedure(
            'public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)')
          and position('gemini-3.8-flash-high' in p.prosrc) > 0
     ) then
    raise exception 'NARAROUTER_MODEL_CONTRACT_PRECHECK_FAILED';
  end if;
end $$;

alter table public.generation_runs drop constraint generation_runs_model_check;
alter table public.generation_runs add constraint generation_runs_model_check
  check ((provider = 'gemini' and model ~ '^[A-Za-z0-9_.-]{1,100}$')
      or (provider = 'groq' and model = 'openai/gpt-oss-20b')
      or (provider = 'nararouter' and model = 'gemini-3.8-flash-high'));

commit;
