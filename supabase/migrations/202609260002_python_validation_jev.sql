-- Phase 5 additive backend foundation. Review before one manual transactional application.
begin;
create schema val5_private;
revoke all on schema val5_private from public,anon,authenticated,service_role;

create table public.validation_runs (
  id uuid primary key default gen_random_uuid(),
  generated_plan_id uuid not null references public.generated_plans(id) on delete restrict,
  validator_version text not null check (validator_version = 'python-validator/1.0.0'),
  input_hash text not null check (input_hash ~ '^[0-9a-f]{64}$'),
  projection_hash text not null check (projection_hash ~ '^[0-9a-f]{64}$'),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  result_hash text not null check (result_hash ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references public.profiles(id) on delete restrict,
  started_at timestamptz not null,
  completed_at timestamptz not null check (completed_at >= started_at),
  summary jsonb not null check (jsonb_typeof(summary) = 'object' and pg_column_size(summary) <= 4096),
  unique(generated_plan_id,validator_version,input_hash,projection_hash,content_hash)
);
create index validation_plan_time on public.validation_runs(generated_plan_id,completed_at desc,id desc);

create table public.validation_findings (
  id uuid primary key default gen_random_uuid(),
  validation_run_id uuid not null references public.validation_runs(id) on delete restrict,
  ordinal integer not null check (ordinal between 0 and 1999),
  code text not null check (code in ('MISSING_MANDATORY_REQUIREMENT','UNSUPPORTED_REQUIREMENT',
    'SOURCE_SUPPORT_MISSING','SOURCE_REFERENCE_INVALID','ROLE_APPLICABILITY_MISMATCH',
    'TIMING_MISMATCH','TIMING_UNRESOLVED','DEPENDENCY_MISSING','DEPENDENCY_INVALID',
    'DEPENDENCY_ORDER_VIOLATION','DEPENDENCY_CYCLE','DUPLICATE_REQUIREMENT',
    'CONTRADICTION_DETECTED','OUTDATED_SOURCE','STALE_INPUT','STRUCTURAL_REFERENCE_INVALID')),
  severity text not null check (severity in ('WARNING','ERROR','REVIEW')),
  -- Unknown generated requirement UUIDs must remain recordable as invalid references.
  requirement_id uuid,
  location text not null check (length(location) <= 240),
  explanation text not null check (length(explanation) between 1 and 300),
  evidence jsonb not null check (jsonb_typeof(evidence) = 'array' and jsonb_array_length(evidence) <= 100),
  unique(validation_run_id,ordinal)
);
create table public.jev_decisions (
  validation_run_id uuid primary key references public.validation_runs(id) on delete restrict,
  version text not null check (version = 'jev/1.0.0'),
  status text not null check (status in ('VERIFIED','VERIFIED_WITH_WARNING','INCOMPLETE',
    'UNSUPPORTED','CONTRADICTORY','MANUAL_REVIEW')),
  rule text not null check (rule ~ '^JEV-00[1-7]$'),
  reason_codes jsonb not null check (jsonb_typeof(reason_codes) = 'array' and jsonb_array_length(reason_codes) <= 16)
);
create table public.plan_review_actions (
  id uuid primary key default gen_random_uuid(),
  validation_run_id uuid not null references public.validation_runs(id) on delete restrict,
  actor_profile_id uuid not null references public.profiles(id) on delete restrict,
  action text not null check (action in ('APPROVE','REJECT','REGENERATE','OVERRIDE')),
  reason text not null check (rrm_private.meaningful_reason(reason)),
  created_at timestamptz not null default now()
);
create index review_validation_time on public.plan_review_actions(validation_run_id,created_at desc,id desc);

create function val5_private.can_read(p_plan uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select public.current_profile_id() is not null and exists (
    select 1 from public.generated_plans p join public.generation_runs r on r.id=p.run_id
    where p.id=p_plan and (public.has_app_role('ADMIN') or public.has_app_role('REVIEWER')
      or (public.has_app_role('TRAINING_MANAGER') and r.created_by=public.current_profile_id())))
$$;

-- Recheck approval-critical current state under shared locks at persistence/review.
-- Original snapshot and historical validation evidence are never rewritten.
create function val5_private.assert_current(p_run uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare r public.generation_runs%rowtype; e public.employees%rowtype;
  m public.role_requirement_matrices%rowtype; s public.onboarding_stage_sets%rowtype;
  items jsonb; ref jsonb; req jsonb; eligible integer;
begin
  select * into strict r from public.generation_runs where id=p_run for share;
  select * into strict e from public.employees where id=r.employee_id for share;
  perform 1 from public.roles where id=e.role_id for share;
  perform 1 from public.departments where id=e.department_id for share;
  select * into strict m from public.role_requirement_matrices where id=r.matrix_id for share;
  select * into strict s from public.onboarding_stage_sets where id=r.stage_set_id for share;
  if r.status <> 'UNVERIFIED' or m.status <> 'APPROVED' or s.status <> 'ACTIVE'
     or m.revision <> r.matrix_revision or m.current_edit <> r.matrix_edit
     or m.lock_version <> r.matrix_lock_version or m.snapshot_hash is distinct from r.matrix_snapshot_hash
     or s.version <> r.stage_set_version or m.role_id <> e.role_id
     or e.role_id::text is distinct from r.input_snapshot->'employee'->>'role_id'
     or e.department_id::text is distinct from r.input_snapshot->'employee'->>'department_id'
     or e.profile_id::text is distinct from r.input_snapshot->'employee'->>'profile_id'
     or e.experience_level::text is distinct from r.input_snapshot->'employee'->>'experience'
     or e.location_code is distinct from r.input_snapshot->'employee'->>'location_code'
     or e.joining_date::text is distinct from r.input_snapshot->'employee'->>'joining_date'
     or not exists(select 1 from public.roles where id=e.role_id and status='ACTIVE'
       and code=r.input_snapshot->'employee'->>'role_code' and (department_id is null or department_id=e.department_id))
     or not exists(select 1 from public.departments where id=e.department_id and status='ACTIVE'
       and code=r.input_snapshot->'employee'->>'department_code') then
    raise exception 'VAL5_STALE_INPUT' using errcode='40001';
  end if;
  select jsonb_agg(jsonb_build_object('stage_definition_id',d.id,'code',d.code,'revision',d.revision,
      'label',d.label,'sequence',i.sequence,'start_day',d.start_day,'end_day',d.end_day) order by i.sequence)
    into items from public.onboarding_stage_set_items i
    join public.onboarding_stage_definitions d on d.id=i.stage_definition_id where i.stage_set_id=s.id;
  if items is distinct from r.input_snapshot->'stage_set'->'items'
     or s.name is distinct from r.input_snapshot->'stage_set'->>'name'
     or s.code is distinct from r.stage_set_code then
    raise exception 'VAL5_STALE_INPUT' using errcode='40001';
  end if;
  if exists(select 1 from public.rrm_issues i where i.matrix_id=m.id and not exists(
      select 1 from public.rrm_issue_resolutions resolved where resolved.issue_id=i.id
        and resolved.edit_no=m.current_edit)) then
    raise exception 'VAL5_STALE_INPUT' using errcode='40001';
  end if;
  perform gen4_private.assert_effective_input(r.employee_id,r.matrix_id,r.input_snapshot);
  for req in select value from jsonb_array_elements(r.input_snapshot->'requirements') loop
    for ref in select value from jsonb_array_elements(req->'evidence') loop
      perform 1 from public.documents where id=(ref->>'document_id')::uuid for share;
      perform 1 from public.document_versions where id=(ref->>'document_version_id')::uuid for share;
      select count(*) into eligible from public.current_effective_document_version(
        (ref->>'document_id')::uuid,(now() at time zone 'UTC')::date);
      if eligible <> 1 or not exists(select 1 from public.current_effective_document_version(
          (ref->>'document_id')::uuid,(now() at time zone 'UTC')::date)
          where id=(ref->>'document_version_id')::uuid) then
        raise exception 'VAL5_STALE_INPUT' using errcode='40001';
      end if;
    end loop;
  end loop;
end $$;

-- Only the trusted Python backend may submit computed evidence. No user JWT can execute this RPC.
create function public.record_python_validation(p_actor uuid,p_plan uuid,p_result jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare p public.generated_plans%rowtype; r public.generation_runs%rowtype;
  existing public.validation_runs%rowtype; vid uuid; f jsonb; ordinal integer := 0; digest text;
begin
  if auth.role() is distinct from 'service_role' then
    raise exception 'VAL5_FORBIDDEN' using errcode='42501';
  end if;
  select * into strict p from public.generated_plans where id=p_plan for share;
  select * into strict r from public.generation_runs where id=p.run_id for share;
  if not exists(select 1 from public.profiles pr join public.profile_roles ar on ar.profile_id=pr.id
      where pr.id=p_actor and pr.status='ACTIVE' and (ar.role='ADMIN'
        or (ar.role='TRAINING_MANAGER' and r.created_by=p_actor))) then
    raise exception 'VAL5_FORBIDDEN' using errcode='42501';
  end if;
  perform rrm_private.assert_keys(p_result,array['validator_version','input_hash','projection_hash','content_hash',
    'started_at','completed_at','evidence','decision'],array['validator_version','input_hash','projection_hash',
    'content_hash','started_at','completed_at','evidence','decision']);
  if p.status <> 'UNVERIFIED' or r.status <> 'UNVERIFIED' or r.completed_at is null
     or p_result->>'validator_version' is distinct from 'python-validator/1.0.0'
     or p_result->>'input_hash' is distinct from r.input_hash
     or p_result->>'projection_hash' is distinct from r.projection_hash or r.projection_hash is null
     or p_result->>'content_hash' is distinct from p.content_hash
     or rrm_private.content_hash(r.input_snapshot) <> r.input_hash
     or rrm_private.content_hash(p.content) <> p.content_hash
     or pg_column_size(p_result) > 4194304
     or jsonb_typeof(p_result->'evidence'->'findings') is distinct from 'array'
     or jsonb_array_length(p_result->'evidence'->'findings') > 2000
     or p_result->'evidence'->>'validator_version' is distinct from 'python-validator/1.0.0'
     or p_result->'decision'->>'version' is distinct from 'jev/1.0.0' then
    raise exception 'VAL5_INVALID_INPUT' using errcode='22023';
  end if;
  if p_result->'decision'->>'status' in ('VERIFIED','VERIFIED_WITH_WARNING') then
    if p_result->'evidence'->>'structurally_valid' is distinct from 'true'
       or p_result->'evidence'->>'current_input' is distinct from 'true'
       or jsonb_typeof(p_result->'evidence'->'mandatory_total') is distinct from 'number'
       or jsonb_typeof(p_result->'evidence'->'mandatory_covered') is distinct from 'number'
       or (p_result->'evidence'->>'mandatory_total')::integer <= 0
       or (p_result->'evidence'->>'mandatory_total')::integer is distinct from
          (p_result->'evidence'->>'mandatory_covered')::integer
       or exists(select 1 from jsonb_array_elements(p_result->'evidence'->'findings') x
                 where x->>'severity' is distinct from 'WARNING'
                    or x->>'code' is distinct from 'DUPLICATE_REQUIREMENT') then
      raise exception 'VAL5_INVALID_INPUT' using errcode='22023';
    end if;
    perform val5_private.assert_current(r.id);
  end if;
  digest := rrm_private.content_hash(p_result - 'started_at' - 'completed_at');
  -- Serialize concurrent requests for this immutable plan; no partially visible evidence.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_plan::text,5));
  select * into existing from public.validation_runs where generated_plan_id=p_plan
    and validator_version=p_result->>'validator_version' and input_hash=r.input_hash
    and projection_hash=r.projection_hash and content_hash=p.content_hash;
  if found then
    if existing.result_hash <> digest then
      raise exception 'VAL5_IDEMPOTENCY_CONFLICT' using errcode='40001';
    end if;
    return jsonb_build_object('validation_run_id',existing.id,'idempotent_replay',true,
      'decision',(select status from public.jev_decisions where validation_run_id=existing.id));
  end if;
  insert into public.validation_runs(generated_plan_id,validator_version,input_hash,projection_hash,content_hash,
    result_hash,created_by,started_at,completed_at,summary)
    values(p_plan,p_result->>'validator_version',r.input_hash,r.projection_hash,p.content_hash,digest,p_actor,
      (p_result->>'started_at')::timestamptz,(p_result->>'completed_at')::timestamptz,
      (p_result->'evidence' - 'findings') || jsonb_build_object(
        'finding_count',jsonb_array_length(p_result->'evidence'->'findings'))) returning id into vid;
  for f in select value from jsonb_array_elements(p_result->'evidence'->'findings') loop
    insert into public.validation_findings(validation_run_id,ordinal,code,severity,requirement_id,location,explanation,evidence)
      values(vid,ordinal,f->>'code',f->>'severity',(f->>'requirement_id')::uuid,f->>'location',f->>'explanation',f->'evidence');
    ordinal := ordinal+1;
  end loop;
  insert into public.jev_decisions(validation_run_id,version,status,rule,reason_codes)
    values(vid,p_result->'decision'->>'version',p_result->'decision'->>'status',
      p_result->'decision'->>'rule',p_result->'decision'->'reason_codes');
  insert into public.audit_logs(actor_profile_id,action,target_type,target_id,metadata)
    values(p_actor,'PYTHON_VALIDATION_COMPLETED','VALIDATION',vid,
      jsonb_build_object('generated_plan_id',p_plan,'result_hash',digest,'decision',p_result->'decision'->>'status'));
  return jsonb_build_object('validation_run_id',vid,'idempotent_replay',false,'decision',p_result->'decision'->>'status');
end $$;

create function public.review_validated_plan(p_validation uuid,p_action text,p_reason text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare actor uuid := public.current_profile_id(); v public.validation_runs%rowtype;
  r public.generation_runs%rowtype; result text; action_id uuid;
begin
  if actor is null or not (public.has_app_role('ADMIN') or public.has_app_role('REVIEWER'))
     or (p_action='OVERRIDE' and not public.has_app_role('ADMIN')) then
    raise exception 'VAL5_FORBIDDEN' using errcode='42501';
  end if;
  if p_action is null or p_action not in ('APPROVE','REJECT','REGENERATE','OVERRIDE')
     or not rrm_private.meaningful_reason(p_reason) then
    raise exception 'VAL5_INVALID_REVIEW' using errcode='22023';
  end if;
  select * into strict v from public.validation_runs where id=p_validation for share;
  select gr.* into strict r from public.generated_plans p join public.generation_runs gr on gr.id=p.run_id
    where p.id=v.generated_plan_id;
  if actor=r.created_by or actor=r.employee_profile_id then
    raise exception 'VAL5_SELF_REVIEW' using errcode='42501';
  end if;
  select status into strict result from public.jev_decisions where validation_run_id=v.id;
  if p_action='APPROVE' then
    if result not in ('VERIFIED','VERIFIED_WITH_WARNING') then
      raise exception 'VAL5_REQUIRES_REVIEW' using errcode='22023';
    end if;
    perform val5_private.assert_current(r.id);
  end if;
  -- Override is a disposition only, never verification or publication. Stale input
  -- cannot be promoted to ordinary approval by this action.
  insert into public.plan_review_actions(validation_run_id,actor_profile_id,action,reason)
    values(v.id,actor,p_action,p_reason) returning id into action_id;
  insert into public.audit_logs(actor_profile_id,action,target_type,target_id,reason,metadata)
    values(actor,'PLAN_REVIEW_'||p_action,'VALIDATION',v.id,p_reason,jsonb_build_object(
      'review_action_id',action_id,'generated_plan_id',v.generated_plan_id,'original_jev_status',result));
  return jsonb_build_object('review_action_id',action_id,'action',p_action,'jev_status',result);
end $$;

-- Immutable evidence/actions, explicit SELECT-only privileges, no recursive policies.
do $$
declare t text;
begin
  foreach t in array array['validation_runs','validation_findings','jev_decisions','plan_review_actions'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('create trigger %I before update or delete on public.%I for each row execute function gen4_private.immutable_row()',t||'_immutable',t);
  end loop;
end $$;
create policy validation_runs_read on public.validation_runs for select to authenticated
  using (val5_private.can_read(generated_plan_id));
create policy validation_findings_read on public.validation_findings for select to authenticated
  using (exists(select 1 from public.validation_runs v where v.id=validation_run_id));
create policy jev_decisions_read on public.jev_decisions for select to authenticated
  using (exists(select 1 from public.validation_runs v where v.id=validation_run_id));
create policy plan_review_actions_read on public.plan_review_actions for select to authenticated
  using (exists(select 1 from public.validation_runs v where v.id=validation_run_id));
revoke all on function val5_private.can_read(uuid),val5_private.assert_current(uuid),
  public.record_python_validation(uuid,uuid,jsonb),public.review_validated_plan(uuid,text,text)
  from public,anon,authenticated,service_role;
grant usage on schema val5_private to authenticated;
grant execute on function val5_private.can_read(uuid),public.review_validated_plan(uuid,text,text) to authenticated;
grant execute on function public.record_python_validation(uuid,uuid,jsonb) to service_role;
commit;
