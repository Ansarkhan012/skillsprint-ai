-- Safe structural diagnostics for failed generation attempts.
-- Stores only what the backend's failure_detail() produces: validation layer, code, error count,
-- field paths, error types, schema-derived messages and response shape (types, counts, our own key
-- names). Never the raw provider response, generated prose, document excerpts, secrets or PII.
-- Additive: a new append-only table and one writer; generation_attempts, existing RPCs and
-- historical rows are unchanged. The backend writes diagnostics best-effort after the attempt,
-- so generation keeps working if this migration is not applied. Apply manually after 202609280009.
begin;

create table public.generation_attempt_diagnostics (
  run_id uuid not null,
  attempt_no integer not null check (attempt_no between 1 and 4),
  diagnostics jsonb not null check (jsonb_typeof(diagnostics) = 'object' and pg_column_size(diagnostics) <= 8192),
  created_at timestamptz not null default now(),
  primary key (run_id, attempt_no),
  foreign key (run_id, attempt_no) references public.generation_attempts(run_id, attempt_no) on delete restrict
);

create trigger generation_attempt_diagnostics_immutable before update or delete on public.generation_attempt_diagnostics
  for each row execute function gen4_private.immutable_row();

alter table public.generation_attempt_diagnostics enable row level security;
revoke all on public.generation_attempt_diagnostics from public, anon, authenticated, service_role;
grant select on public.generation_attempt_diagnostics to authenticated;
-- Same visibility as generation_attempts: readable exactly when the run is readable.
create policy generation_attempt_diagnostics_read on public.generation_attempt_diagnostics
  for select to authenticated using (exists (select 1 from public.generation_runs r where r.id = run_id));

create function public.record_generation_attempt_diagnostics(p_run uuid, p_attempt integer, p_diagnostics jsonb)
returns void language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(); v_run public.generation_runs%rowtype;
begin
  if p_run is null or p_attempt is null or p_diagnostics is null
     or jsonb_typeof(p_diagnostics) <> 'object' or pg_column_size(p_diagnostics) > 8192
     or exists (select 1 from jsonb_object_keys(p_diagnostics) k
                where k not in ('layer','code','error_count','errors','received','truncated'))
     or jsonb_typeof(p_diagnostics->'layer') is distinct from 'string'
     or jsonb_typeof(p_diagnostics->'code') is distinct from 'string'
     or p_diagnostics->>'code' !~ '^[A-Z][A-Z0-9_]{1,79}$'
     or jsonb_typeof(p_diagnostics->'errors') is distinct from 'array'
     or jsonb_array_length(p_diagnostics->'errors') > 20 then
    raise exception 'GEN4_INVALID_DIAGNOSTICS' using errcode = '22023';
  end if;
  select * into strict v_run from public.generation_runs where id = p_run for update;
  -- Only the run's creator, only while the run is executing.
  if v_run.created_by <> v_actor or v_run.status <> 'RUNNING' then
    raise exception 'GEN4_FORBIDDEN_OR_STATE' using errcode = '42501';
  end if;
  -- Only for an attempt that exists and failed parsing.
  if not exists (select 1 from public.generation_attempts
                 where run_id = p_run and attempt_no = p_attempt and parse_outcome = 'SCHEMA_INVALID') then
    raise exception 'GEN4_INVALID_DIAGNOSTICS' using errcode = '22023';
  end if;
  insert into public.generation_attempt_diagnostics(run_id, attempt_no, diagnostics)
  values (p_run, p_attempt, p_diagnostics);
end $$;

revoke all on function public.record_generation_attempt_diagnostics(uuid,integer,jsonb)
  from public, anon, authenticated, service_role;
grant execute on function public.record_generation_attempt_diagnostics(uuid,integer,jsonb) to authenticated;

commit;
