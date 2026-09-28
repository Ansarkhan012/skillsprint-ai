-- Read-only: run this FIRST in the currently linked project's Supabase SQL Editor.
-- No migration or generation is performed. Compare the installed V2 function body
-- with the local 202609270001 body, ignoring whitespace only.
begin read only;
select p.oid::regprocedure as function_signature,
       md5(regexp_replace(p.prosrc, '\s+', '', 'g')) = '7da77a4384888ad0fc6a8683c5401568' as matches_local_v2_body,
       position('phase4d-compact-context/2.0.0' in p.prosrc) > 0 as v2_prompt_pin,
       position('11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc' in p.prosrc) > 0 as v2_template_pin,
       position('onboarding-plan/1.0.0' in p.prosrc) > 0 as schema_pin,
       position('projection_hash' in p.prosrc) > 0 as projection_hash_guard,
       position('nararouter' in p.prosrc) > 0 as nararouter_already_present
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname = 'reserve_generation_run_bounded';
select conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.generation_runs'::regclass
  and conname in ('generation_runs_provider_check', 'generation_runs_compact_v2_projection_check');
rollback;
-- Expected before applying 202609270002: one function row, matches_local_v2_body=true,
-- all four pin/guard flags=true, nararouter_already_present=false.
-- A mismatch requires inspecting pg_get_functiondef; do NOT apply blindly.
