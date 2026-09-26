-- Phase 4C additive foundation. Apply once, transactionally, only after human review.
-- No stage rows are inserted at migration time; authenticated Admin bootstrap is explicit.
begin;

create schema gen4_private;
revoke all on schema gen4_private from public, anon, authenticated, service_role;

create table public.onboarding_stage_sets (
  id uuid primary key default gen_random_uuid(),
  code text not null check (code ~ '^[A-Z][A-Z0-9_]{1,63}$'),
  version integer not null check (version > 0),
  name text not null check (length(trim(name)) between 1 and 160),
  status text not null default 'INACTIVE' check (status in ('INACTIVE','ACTIVE')),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  unique(code,version),
  check (status <> 'ACTIVE' or activated_at is not null)
);
create unique index onboarding_one_active_set on public.onboarding_stage_sets ((true)) where status = 'ACTIVE';

create table public.onboarding_stage_set_items (
  stage_set_id uuid not null references public.onboarding_stage_sets(id) on delete restrict,
  stage_definition_id uuid not null references public.onboarding_stage_definitions(id) on delete restrict,
  sequence integer not null check (sequence between 1 and 100),
  primary key(stage_set_id,sequence),
  unique(stage_set_id,stage_definition_id)
);

create table public.generation_runs (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references public.employees(id) on delete restrict,
  employee_profile_id uuid references public.profiles(id) on delete restrict,
  created_by uuid not null references public.profiles(id) on delete restrict,
  matrix_id uuid not null references public.role_requirement_matrices(id) on delete restrict,
  matrix_revision integer not null check (matrix_revision > 0),
  matrix_edit integer not null check (matrix_edit >= 0),
  matrix_lock_version integer not null check (matrix_lock_version >= 0),
  matrix_snapshot_hash text not null check (matrix_snapshot_hash ~ '^[0-9a-f]{64}$'),
  input_snapshot jsonb not null check (jsonb_typeof(input_snapshot) = 'object' and pg_column_size(input_snapshot) <= 4194304),
  input_hash text not null check (input_hash ~ '^[0-9a-f]{64}$'),
  stage_set_id uuid not null references public.onboarding_stage_sets(id) on delete restrict,
  stage_set_code text not null,
  stage_set_version integer not null check (stage_set_version > 0),
  provider text not null check (provider = 'gemini'),
  model text not null check (model ~ '^[A-Za-z0-9_.-]{1,100}$'),
  provider_config jsonb not null check (jsonb_typeof(provider_config) = 'object' and pg_column_size(provider_config) <= 8192),
  prompt_version text not null check (length(prompt_version) between 1 and 120),
  template_hash text not null check (template_hash ~ '^[0-9a-f]{64}$'),
  schema_version text not null check (schema_version = 'onboarding-plan/1.0.0'),
  idempotency_key_hash text not null check (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'QUEUED' check (status in ('QUEUED','RUNNING','UNVERIFIED','FAILED','STALE_INPUT')),
  error_code text check (error_code is null or error_code ~ '^[A-Z][A-Z0-9_]{1,79}$'),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  unique(created_by,employee_id,idempotency_key_hash),
  check ((status in ('UNVERIFIED','FAILED','STALE_INPUT')) = (completed_at is not null))
);
create unique index generation_one_active_input on public.generation_runs
  (created_by,employee_id,input_hash,prompt_version,schema_version)
  where status in ('QUEUED','RUNNING');
create index generation_runs_actor_time on public.generation_runs(created_by,created_at desc,id desc);
create index generation_runs_employee_time on public.generation_runs(employee_id,created_at desc);

create table public.generation_attempts (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.generation_runs(id) on delete restrict,
  attempt_no integer not null check (attempt_no between 1 and 4),
  attempt_type text not null check (attempt_type in ('INITIAL','TRANSPORT_RETRY','FORMAT_RETRY')),
  provider_outcome text not null check (provider_outcome in ('RESPONSE','TIMEOUT','RATE_LIMIT','UNAVAILABLE','REJECTED','ERROR')),
  latency_ms integer not null check (latency_ms between 0 and 600000),
  usage_metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(usage_metadata) = 'object' and pg_column_size(usage_metadata) <= 4096),
  response_hash text check (response_hash ~ '^[0-9a-f]{64}$'),
  response_size integer check (response_size between 0 and 100000000),
  parse_outcome text not null check (parse_outcome in ('SCHEMA_VALID','SCHEMA_INVALID','NOT_PARSED')),
  error_code text check (error_code is null or error_code ~ '^[A-Z][A-Z0-9_]{1,79}$'),
  created_at timestamptz not null default now(),
  unique(run_id,attempt_no)
);
create index generation_attempts_run_idx on public.generation_attempts(run_id,attempt_no);

create table public.generated_plans (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null unique references public.generation_runs(id) on delete restrict,
  schema_version text not null check (schema_version = 'onboarding-plan/1.0.0'),
  content jsonb not null check (jsonb_typeof(content) = 'object' and pg_column_size(content) <= 4194304),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'UNVERIFIED' check (status = 'UNVERIFIED'),
  created_at timestamptz not null default now()
);

create function gen4_private.immutable_row() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'GEN4_IMMUTABLE' using errcode = '42501';
end $$;
create trigger generation_attempts_immutable before update or delete on public.generation_attempts
  for each row execute function gen4_private.immutable_row();
create trigger generated_plans_immutable before update or delete on public.generated_plans
  for each row execute function gen4_private.immutable_row();
create trigger stage_set_items_immutable before update or delete on public.onboarding_stage_set_items
  for each row execute function gen4_private.immutable_row();

create function gen4_private.stage_set_update_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(new) - 'status' - 'activated_at') <> (to_jsonb(old) - 'status' - 'activated_at')
     or new.status = old.status
     or not ((old.status = 'INACTIVE' and new.status = 'ACTIVE')
          or (old.status = 'ACTIVE' and new.status = 'INACTIVE')) then
    raise exception 'GEN4_INVALID_STAGE_TRANSITION' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger stage_set_update_guard before update on public.onboarding_stage_sets
  for each row execute function gen4_private.stage_set_update_guard();
create trigger stage_set_delete_guard before delete on public.onboarding_stage_sets
  for each row execute function gen4_private.immutable_row();

create function gen4_private.run_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (to_jsonb(new) - 'status' - 'started_at' - 'completed_at' - 'error_code') <>
     (to_jsonb(old) - 'status' - 'started_at' - 'completed_at' - 'error_code')
     or not ((old.status = 'QUEUED' and new.status = 'RUNNING')
          or (old.status = 'RUNNING' and new.status in ('UNVERIFIED','FAILED','STALE_INPUT'))) then
    raise exception 'GEN4_INVALID_TRANSITION' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger generation_run_guard before update on public.generation_runs
  for each row execute function gen4_private.run_guard();
create trigger generation_run_delete_guard before delete on public.generation_runs
  for each row execute function gen4_private.immutable_row();

create function gen4_private.actor(p_admin boolean default false) returns uuid
language plpgsql stable security definer set search_path = '' as $$
declare v_actor uuid := public.current_profile_id();
begin
  if v_actor is null or not (public.has_app_role('ADMIN') or
      (not p_admin and public.has_app_role('TRAINING_MANAGER'))) then
    raise exception 'GEN4_FORBIDDEN' using errcode = '42501';
  end if;
  return v_actor;
end $$;

create function gen4_private.audit(p_action text,p_type text,p_target uuid,p_meta jsonb)
returns void language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_logs(actor_profile_id,action,target_type,target_id,metadata)
  values(public.current_profile_id(),p_action,p_type,p_target,coalesce(p_meta,'{}'::jsonb));
end $$;

create function gen4_private.assert_stage_set(p_id uuid) returns void
language plpgsql stable security definer set search_path = '' as $$
declare v_count integer;
begin
  select count(*) into v_count from public.onboarding_stage_set_items where stage_set_id = p_id;
  if v_count < 1 or v_count > 100 or exists (
      select 1 from public.onboarding_stage_set_items i
      where i.stage_set_id = p_id and i.sequence not between 1 and v_count
    ) or exists (
      select 1 from public.onboarding_stage_set_items i
      join public.onboarding_stage_definitions s on s.id = i.stage_definition_id
      where i.stage_set_id = p_id
      group by s.code having count(*) > 1
    ) or exists (
      select 1 from public.onboarding_stage_set_items a
      join public.onboarding_stage_definitions sa on sa.id = a.stage_definition_id
      join public.onboarding_stage_set_items b on b.stage_set_id = a.stage_set_id and b.sequence = a.sequence + 1
      join public.onboarding_stage_definitions sb on sb.id = b.stage_definition_id
      where a.stage_set_id = p_id and sb.start_day < sa.start_day
    ) then
    raise exception 'GEN4_INVALID_STAGE_CONFIGURATION' using errcode = '22023';
  end if;
end $$;

create function public.create_onboarding_stage_set(p_code text,p_version integer,p_name text,p_stage_ids uuid[])
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(true); v_id uuid; v_count integer;
begin
  if p_code is null or p_code !~ '^[A-Z][A-Z0-9_]{1,63}$' or p_version is null or p_version < 1
     or p_name is null or length(trim(p_name)) not between 1 and 160
     or p_stage_ids is null or cardinality(p_stage_ids) not between 1 and 100 then
    raise exception 'GEN4_INVALID_STAGE_CONFIGURATION' using errcode = '22023';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(4004,1);
  select count(*) into v_count from public.onboarding_stage_definitions where id = any(p_stage_ids);
  if v_count <> cardinality(p_stage_ids) or exists (select 1 from unnest(p_stage_ids) x where x is null)
     or (select count(distinct code) from public.onboarding_stage_definitions where id = any(p_stage_ids)) <> v_count then
    raise exception 'GEN4_INVALID_STAGE_CONFIGURATION' using errcode = '22023';
  end if;
  insert into public.onboarding_stage_sets(code,version,name,created_by)
  values(p_code,p_version,p_name,v_actor) returning id into v_id;
  insert into public.onboarding_stage_set_items(stage_set_id,stage_definition_id,sequence)
    select v_id,x.id,x.ordinality::integer from unnest(p_stage_ids) with ordinality as x(id,ordinality);
  perform gen4_private.assert_stage_set(v_id);
  perform gen4_private.audit('STAGE_SET_CREATED','STAGE_SET',v_id,
    jsonb_build_object('code',p_code,'version',p_version,'stage_count',v_count));
  return v_id;
end $$;

create function public.activate_onboarding_stage_set(p_id uuid) returns uuid
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(true); v_set public.onboarding_stage_sets%rowtype;
begin
  perform pg_catalog.pg_advisory_xact_lock(4004,1);
  select * into strict v_set from public.onboarding_stage_sets where id = p_id for update;
  perform gen4_private.assert_stage_set(p_id);
  if v_set.status = 'ACTIVE' then return p_id; end if;
  update public.onboarding_stage_sets set status = 'INACTIVE' where status = 'ACTIVE';
  update public.onboarding_stage_sets set status = 'ACTIVE',activated_at = now() where id = p_id;
  perform gen4_private.audit('STAGE_SET_ACTIVATED','STAGE_SET',p_id,
    jsonb_build_object('code',v_set.code,'version',v_set.version,'actor',v_actor));
  return p_id;
end $$;

-- Explicit Admin operation after migration, never a migration-time fake creator.
-- Day windows organize a demo plan; they do not define requirement-level policy timing.
create function public.bootstrap_standard_onboarding_stages() returns uuid
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(true); v_set uuid; v_ids uuid[] := '{}';
  v_codes text[] := array['ORIENTATION','POLICIES_COMPLIANCE','ROLE_TRAINING',
                          'PRACTICAL_APPLICATION','ASSESSMENT_COMPLETION'];
  v_labels text[] := array['Orientation','Policies & Compliance','Role-Specific Training',
                           'Practical Application','Assessment & Completion'];
  v_starts integer[] := array[0,1,2,4,7];
  v_ends integer[] := array[1,3,5,7,7];
  v_id uuid; v_index integer; v_matches integer;
begin
  perform pg_catalog.pg_advisory_xact_lock(4004,1);
  -- Phase 3 stage-revision RPC does not take this advisory lock. Serialize
  -- its INSERTs too, so the empty-catalog check is not a concurrent phantom.
  lock table public.onboarding_stage_definitions in share row exclusive mode;
  select id into v_set from public.onboarding_stage_sets
    where code = 'STANDARD_EMPLOYEE_ONBOARDING' and version = 1;
  if v_set is not null then
    select count(*) into v_matches from public.onboarding_stage_set_items i
      join public.onboarding_stage_definitions s on s.id = i.stage_definition_id
      where i.stage_set_id = v_set and i.sequence between 1 and 5
        and s.code = v_codes[i.sequence] and s.label = v_labels[i.sequence]
        and s.sequence = i.sequence - 1 and s.start_day = v_starts[i.sequence]
        and s.end_day = v_ends[i.sequence] and s.revision = 1 and s.predecessor_id is null;
    if v_matches <> 5 or (select count(*) from public.onboarding_stage_set_items where stage_set_id = v_set) <> 5
       or not exists (select 1 from public.onboarding_stage_sets where id = v_set
         and name = 'Standard Employee Onboarding' and status = 'ACTIVE') then
      raise exception 'GEN4_BOOTSTRAP_CONFLICT' using errcode = '22023';
    end if;
    return v_set;
  end if;
  if exists (select 1 from public.onboarding_stage_definitions)
     or exists (select 1 from public.onboarding_stage_sets) then
    raise exception 'GEN4_BOOTSTRAP_PARTIAL_CONFIGURATION' using errcode = '22023';
  end if;
  for v_index in 1..5 loop
    insert into public.onboarding_stage_definitions
      (code,revision,predecessor_id,label,sequence,start_day,end_day,created_by)
    values(v_codes[v_index],1,null,v_labels[v_index],v_index - 1,v_starts[v_index],v_ends[v_index],v_actor)
    returning id into v_id;
    v_ids := array_append(v_ids,v_id);
  end loop;
  v_set := public.create_onboarding_stage_set('STANDARD_EMPLOYEE_ONBOARDING',1,
    'Standard Employee Onboarding',v_ids);
  perform public.activate_onboarding_stage_set(v_set);
  perform gen4_private.audit('STAGE_SET_BOOTSTRAPPED','STAGE_SET',v_set,
    jsonb_build_object('stage_codes',v_codes,'actor',v_actor,'configuration_not_policy',true));
  return v_set;
end $$;

-- A direct authenticated RPC caller cannot substitute a different requirement set
-- for the approved matrix. Phase 5 still judges the generated content itself.
create function gen4_private.assert_effective_input(p_employee uuid,p_matrix uuid,p_input jsonb) returns void
language plpgsql stable security definer set search_path = '' as $$
declare v_employee public.employees%rowtype; v_edit integer; v_expected uuid[]; v_actual uuid[];
  v_item jsonb; v_req public.requirements%rowtype; v_entry public.role_requirements%rowtype;
  v_source jsonb; v_source_count integer; v_distinct_sources integer; v_chunk record; v_scope jsonb; v_deps jsonb;
begin
  select * into strict v_employee from public.employees where id = p_employee;
  select current_edit into strict v_edit from public.role_requirement_matrices where id = p_matrix;
  if exists (
    select 1 from public.role_requirements e
    where e.matrix_id = p_matrix and e.edit_no = v_edit
      and not exists (
        select 1 from public.requirement_applicability a where a.requirement_id = e.requirement_id
          and (a.role_id is null or a.role_id = v_employee.role_id)
          and (a.department_id is null or a.department_id = v_employee.department_id)
          and (a.experience is null or a.experience = v_employee.experience_level)
          and (a.location_code is null or a.location_code = v_employee.location_code)
      ) and exists (
        select 1 from public.requirement_applicability a where a.requirement_id = e.requirement_id
          and (a.role_id is null or a.role_id = v_employee.role_id)
          and (a.department_id is null or a.department_id = v_employee.department_id)
          and (a.experience is null or a.experience = v_employee.experience_level)
          and a.location_code is not null and v_employee.location_code is null
      )
  ) then raise exception 'GEN4_MISSING_EMPLOYEE_CONTEXT' using errcode = '22023'; end if;
  with applicable as (
    select e.requirement_id,e.exception_to from public.role_requirements e
    where e.matrix_id = p_matrix and e.edit_no = v_edit and exists (
      select 1 from public.requirement_applicability a where a.requirement_id = e.requirement_id
        and (a.role_id is null or a.role_id = v_employee.role_id)
        and (a.department_id is null or a.department_id = v_employee.department_id)
        and (a.experience is null or a.experience = v_employee.experience_level)
        and (a.location_code is null or a.location_code = v_employee.location_code))
  ) select coalesce(array_agg(requirement_id order by requirement_id),'{}'::uuid[]) into v_expected
    from applicable a where not exists (select 1 from applicable x where x.exception_to = a.requirement_id);
  select coalesce(array_agg((x->>'revision_id')::uuid order by (x->>'revision_id')::uuid),'{}'::uuid[])
    into v_actual from jsonb_array_elements(p_input->'requirements') x;
  if cardinality(v_expected) = 0 or v_actual is distinct from v_expected then
    raise exception 'GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH' using errcode = '22023';
  end if;
  for v_item in select value from jsonb_array_elements(p_input->'requirements') loop
    select * into strict v_req from public.requirements where id = (v_item->>'revision_id')::uuid;
    select * into strict v_entry from public.role_requirements
      where matrix_id = p_matrix and edit_no = v_edit and requirement_id = v_req.id;
    if v_item->>'code' is distinct from v_req.requirement_code
       or (v_item->>'revision')::integer is distinct from v_req.revision
       or v_item->>'statement' is distinct from v_req.statement
       or v_item->>'obligation_type' is distinct from v_req.requirement_type
       or (v_item->>'mandatory')::boolean is distinct from v_req.mandatory
       or v_item->>'priority' is distinct from v_req.priority
       or v_item->'timing'->>'state' is distinct from v_req.timing->>'state'
       or v_item->'timing'->>'original_text' is distinct from v_req.timing->>'original_text'
       or v_item->'timing'->>'trigger' is distinct from v_req.timing->>'trigger'
       or v_item->'timing'->>'relation' is distinct from v_req.timing->>'relation'
       or v_item->'timing'->>'value' is distinct from v_req.timing->>'value'
       or v_item->'timing'->>'unit' is distinct from v_req.timing->>'unit'
       or v_item->'timing'->>'calendar_basis' is distinct from v_req.timing->>'calendar_basis'
       or coalesce(v_item->'timing'->'evidence','{}'::jsonb) is distinct from
          coalesce(v_req.timing->'evidence','{}'::jsonb)
       or (v_item->>'stage_definition_id')::uuid is distinct from v_entry.stage_id
       or (v_item->>'sequence')::integer is distinct from v_entry.sequence
       or (v_item->>'exception_to')::uuid is distinct from v_entry.exception_to
       or (v_item->>'downgrade_requested')::boolean is distinct from v_entry.downgrade_requested
       or v_item->>'downgrade_justification' is distinct from v_entry.downgrade_justification
       or nullif(v_item->'downgrade_evidence','null'::jsonb) is distinct from v_entry.downgrade_evidence then
      raise exception 'GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH' using errcode = '22023';
    end if;
    select coalesce(jsonb_agg(jsonb_build_object('role_id',a.role_id,'department_id',a.department_id,
        'location_code',a.location_code,'experience',a.experience) order by a.ordinal),'[]'::jsonb)
      into v_scope from public.requirement_applicability a where a.requirement_id = v_req.id;
    if v_item->'applicability' is distinct from v_scope then
      raise exception 'GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH' using errcode = '22023';
    end if;
    select coalesce(jsonb_agg(d.prerequisite_id order by d.prerequisite_id),'[]'::jsonb)
      into v_deps from public.requirement_dependencies d
      where d.matrix_id = p_matrix and d.edit_no = v_edit and d.dependent_id = v_req.id;
    if v_item->'dependencies' is distinct from v_deps then
      raise exception 'GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH' using errcode = '22023';
    end if;
    select count(*) into v_source_count from public.requirement_sources where requirement_id = v_req.id;
    if jsonb_typeof(v_item->'evidence') is distinct from 'array'
       or jsonb_array_length(v_item->'evidence') is distinct from v_source_count then
      raise exception 'GEN4_SOURCE_MISMATCH' using errcode = '22023';
    end if;
    select count(distinct x->>'chunk_id') into v_distinct_sources
      from jsonb_array_elements(v_item->'evidence') x;
    if v_distinct_sources <> v_source_count then
      raise exception 'GEN4_SOURCE_MISMATCH' using errcode = '22023';
    end if;
    for v_source in select value from jsonb_array_elements(v_item->'evidence') loop
      select c.id as chunk_id,c.content,c.text_hash,c.source_location,v.id as version_id,d.id as document_id
        into v_chunk from public.requirement_sources s
        join public.document_chunks c on c.id = s.chunk_id
        join public.document_versions v on v.id = c.document_version_id
        join public.documents d on d.id = v.document_id
        where s.requirement_id = v_req.id and c.id = (v_source->>'chunk_id')::uuid;
      if not found or v_source->>'document_id' is distinct from v_chunk.document_id::text
         or v_source->>'document_version_id' is distinct from v_chunk.version_id::text
         or v_source->>'text_hash' is distinct from v_chunk.text_hash
         or v_source->'locator' is distinct from v_chunk.source_location
         or v_source->>'excerpt' is distinct from left(v_chunk.content,1200) then
        raise exception 'GEN4_SOURCE_MISMATCH' using errcode = '22023';
      end if;
    end loop;
  end loop;
  select coalesce(jsonb_agg(jsonb_build_array(d.dependent_id,d.prerequisite_id)
    order by d.dependent_id,d.prerequisite_id),'[]'::jsonb) into v_deps
    from public.requirement_dependencies d where d.matrix_id = p_matrix and d.edit_no = v_edit
      and d.dependent_id = any(v_expected);
  if p_input->'dependencies' is distinct from v_deps then
    raise exception 'GEN4_EFFECTIVE_REQUIREMENTS_MISMATCH' using errcode = '22023';
  end if;
end $$;

create function public.reserve_generation_run(
  p_employee uuid,p_input jsonb,p_input_hash text,p_idempotency_key_hash text,
  p_provider text,p_model text,p_provider_config jsonb,p_prompt_version text,
  p_template_hash text,p_schema_version text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(); v_employee public.employees%rowtype;
  v_matrix public.role_requirement_matrices%rowtype; v_set public.onboarding_stage_sets%rowtype;
  v_id uuid; v_existing public.generation_runs%rowtype; v_stage record; v_item jsonb; v_truth jsonb;
begin
  if p_employee is null or p_input is null or jsonb_typeof(p_input) <> 'object'
     or pg_column_size(p_input) > 4194304 or p_input->>'context_schema_version' is distinct from 'generation-context/1.0.0'
     or jsonb_typeof(p_input->'requirements') is distinct from 'array'
     or jsonb_array_length(p_input->'requirements') < 1
     or p_input_hash is null or p_input_hash !~ '^[0-9a-f]{64}$'
     or rrm_private.content_hash(p_input) <> p_input_hash
     or (p_input->>'as_of')::timestamptz is distinct from
        (((now() at time zone 'UTC')::date)::timestamp at time zone 'UTC')
     or p_idempotency_key_hash is null or p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
     or p_provider is distinct from 'gemini' or p_model is null or p_model !~ '^[A-Za-z0-9_.-]{1,100}$'
     or p_prompt_version is distinct from 'phase4b-generation/1.0.0'
     or p_template_hash is distinct from 'c37953b0647c2133fb49c149d3a5cfbe0e5efa1a512a137bfabb76a551ee0827'
     or p_schema_version is distinct from 'onboarding-plan/1.0.0'
     or p_provider_config is null or jsonb_typeof(p_provider_config) <> 'object'
     or pg_column_size(p_provider_config) > 8192
     or (select count(*) from jsonb_object_keys(p_provider_config)) <> 3
     or exists (select 1 from jsonb_object_keys(p_provider_config) k
                where k not in ('temperature','max_output_tokens','timeout_seconds'))
     or jsonb_typeof(p_provider_config->'temperature') is distinct from 'number'
     or jsonb_typeof(p_provider_config->'max_output_tokens') is distinct from 'number'
     or jsonb_typeof(p_provider_config->'timeout_seconds') is distinct from 'number'
     or (p_provider_config->>'temperature')::numeric not between 0 and 1
     or (p_provider_config->>'max_output_tokens')::numeric not between 256 and 65536
     or (p_provider_config->>'timeout_seconds')::numeric not between 1 and 60 then
    raise exception 'GEN4_INVALID_INPUT' using errcode = '22023';
  end if;
  select * into strict v_employee from public.employees where id = p_employee for share;
  -- Phase 3 transitions lock role before matrix. Preserve that order.
  perform 1 from public.roles where id = v_employee.role_id for share;
  perform 1 from public.departments where id = v_employee.department_id for share;
  if p_input->'employee'->>'employee_id' is distinct from p_employee::text
     or p_input->'employee'->>'profile_id' is distinct from v_employee.profile_id::text
     or p_input->'employee'->>'role_id' is distinct from v_employee.role_id::text
     or p_input->'employee'->>'department_id' is distinct from v_employee.department_id::text
     or p_input->'employee'->>'experience' is distinct from v_employee.experience_level::text
     or p_input->'employee'->>'location_code' is distinct from v_employee.location_code
     or p_input->'employee'->>'joining_date' is distinct from v_employee.joining_date::text then
    raise exception 'GEN4_EMPLOYEE_CONTEXT_STALE' using errcode = '40001';
  end if;
  if not exists (select 1 from public.roles where id = v_employee.role_id and status = 'ACTIVE'
                   and (department_id is null or department_id = v_employee.department_id))
     or not exists (select 1 from public.departments where id = v_employee.department_id and status = 'ACTIVE') then
    raise exception 'GEN4_EMPLOYEE_CONTEXT_STALE' using errcode = '40001';
  end if;
  if p_input->'employee'->>'role_code' is distinct from
       (select code from public.roles where id = v_employee.role_id)
     or p_input->'employee'->>'department_code' is distinct from
       (select code from public.departments where id = v_employee.department_id) then
    raise exception 'GEN4_EMPLOYEE_CONTEXT_STALE' using errcode = '40001';
  end if;
  select * into strict v_set from public.onboarding_stage_sets
    where id = (p_input->'stage_set'->>'id')::uuid and status = 'ACTIVE' for share;
  perform gen4_private.assert_stage_set(v_set.id);
  if p_input->'stage_set'->>'code' is distinct from v_set.code
     or p_input->'stage_set'->>'name' is distinct from v_set.name
     or p_input->'stage_set'->>'status' is distinct from v_set.status
     or (p_input->'stage_set'->>'version')::integer is distinct from v_set.version
     or jsonb_typeof(p_input->'stage_set'->'items') is distinct from 'array'
     or jsonb_array_length(p_input->'stage_set'->'items') is distinct from
        (select count(*) from public.onboarding_stage_set_items where stage_set_id = v_set.id) then
    raise exception 'GEN4_STAGE_SET_STALE' using errcode = '40001';
  end if;
  for v_stage in select i.sequence,i.stage_definition_id,s.code,s.revision,s.label,s.start_day,s.end_day
    from public.onboarding_stage_set_items i join public.onboarding_stage_definitions s on s.id = i.stage_definition_id
    where i.stage_set_id = v_set.id order by i.sequence loop
    v_item := p_input->'stage_set'->'items'->(v_stage.sequence - 1);
    if v_item->>'stage_definition_id' is distinct from v_stage.stage_definition_id::text
       or v_item->>'code' is distinct from v_stage.code
       or (v_item->>'revision')::integer is distinct from v_stage.revision
       or v_item->>'label' is distinct from v_stage.label
       or (v_item->>'sequence')::integer is distinct from v_stage.sequence
       or (v_item->>'start_day')::integer is distinct from v_stage.start_day
       or (v_item->>'end_day')::integer is distinct from v_stage.end_day then
      raise exception 'GEN4_STAGE_SET_STALE' using errcode = '40001';
    end if;
  end loop;
  select * into strict v_matrix from public.role_requirement_matrices
    where id = (p_input->>'matrix_id')::uuid for share;
  if v_matrix.status is distinct from 'APPROVED' or v_matrix.role_id is distinct from v_employee.role_id
     or (p_input->>'matrix_revision')::integer is distinct from v_matrix.revision
     or (p_input->>'matrix_edit')::integer is distinct from v_matrix.current_edit
     or (p_input->>'matrix_lock_version')::integer is distinct from v_matrix.lock_version
     or p_input->>'matrix_snapshot_hash' is distinct from v_matrix.snapshot_hash then
    raise exception 'GEN4_MATRIX_STALE' using errcode = '40001';
  end if;
  v_truth := public.get_rrm_ground_truth(v_matrix.id);
  if v_truth->>'snapshot_hash' is distinct from v_matrix.snapshot_hash then
    raise exception 'GEN4_MATRIX_STALE' using errcode = '40001';
  end if;
  perform gen4_private.assert_effective_input(p_employee,v_matrix.id,p_input);
  insert into public.generation_runs(employee_id,employee_profile_id,created_by,matrix_id,
    matrix_revision,matrix_edit,matrix_lock_version,matrix_snapshot_hash,input_snapshot,input_hash,
    stage_set_id,stage_set_code,stage_set_version,provider,model,provider_config,prompt_version,
    template_hash,schema_version,idempotency_key_hash)
  values(p_employee,v_employee.profile_id,v_actor,v_matrix.id,v_matrix.revision,v_matrix.current_edit,
    v_matrix.lock_version,v_matrix.snapshot_hash,p_input,p_input_hash,v_set.id,v_set.code,v_set.version,
    p_provider,p_model,p_provider_config,p_prompt_version,p_template_hash,p_schema_version,p_idempotency_key_hash)
  on conflict (created_by,employee_id,idempotency_key_hash) do nothing returning id into v_id;
  if v_id is null then
    select * into strict v_existing from public.generation_runs
      where created_by = v_actor and employee_id = p_employee and idempotency_key_hash = p_idempotency_key_hash;
    if v_existing.input_hash <> p_input_hash or v_existing.prompt_version <> p_prompt_version
       or v_existing.schema_version <> p_schema_version or v_existing.provider <> p_provider
       or v_existing.model <> p_model or v_existing.provider_config is distinct from p_provider_config
       or v_existing.template_hash <> p_template_hash then
      raise exception 'GEN4_IDEMPOTENCY_CONFLICT' using errcode = '40001';
    end if;
    return jsonb_build_object('id',v_existing.id,'status',v_existing.status,'created',false);
  end if;
  perform gen4_private.audit('GENERATION_REQUESTED','GENERATION',v_id,
    jsonb_build_object('employee_id',p_employee,'input_hash',p_input_hash,'prompt_version',p_prompt_version));
  return jsonb_build_object('id',v_id,'status','QUEUED','created',true);
end $$;

create function public.claim_generation_run(p_run uuid) returns boolean
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(); v_run public.generation_runs%rowtype;
begin
  select * into strict v_run from public.generation_runs where id = p_run for update;
  if v_run.created_by <> v_actor then raise exception 'GEN4_FORBIDDEN' using errcode = '42501'; end if;
  if v_run.status <> 'QUEUED' then return false; end if;
  update public.generation_runs set status = 'RUNNING',started_at = now() where id = p_run;
  perform gen4_private.audit('GENERATION_STARTED','GENERATION',p_run,'{}'::jsonb);
  return true;
end $$;

create function public.record_generation_attempt(p_run uuid,p_type text,p_outcome text,p_latency integer,
  p_usage jsonb,p_response_hash text,p_response_size integer,p_parse text,p_error text) returns integer
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(); v_run public.generation_runs%rowtype; v_number integer;
begin
  select * into strict v_run from public.generation_runs where id = p_run for update;
  if v_run.created_by <> v_actor or v_run.status <> 'RUNNING' then
    raise exception 'GEN4_FORBIDDEN_OR_STATE' using errcode = '42501';
  end if;
  select coalesce(max(attempt_no),0) + 1 into v_number from public.generation_attempts where run_id = p_run;
  if v_number > 4 or p_type not in ('INITIAL','TRANSPORT_RETRY','FORMAT_RETRY')
     or p_outcome not in ('RESPONSE','TIMEOUT','RATE_LIMIT','UNAVAILABLE','REJECTED','ERROR')
     or p_parse not in ('SCHEMA_VALID','SCHEMA_INVALID','NOT_PARSED')
     or p_latency is null or p_latency not between 0 and 600000
     or p_usage is null or jsonb_typeof(p_usage) <> 'object' or pg_column_size(p_usage) > 4096
     or exists (select 1 from jsonb_object_keys(p_usage) k
                where k not in ('prompt_tokens','output_tokens','total_tokens'))
     or (p_response_hash is not null and p_response_hash !~ '^[0-9a-f]{64}$')
     or (p_response_size is not null and p_response_size not between 0 and 100000000)
     or (p_parse = 'SCHEMA_VALID' and (p_outcome is distinct from 'RESPONSE'
                                      or p_response_hash is null or p_response_size is null))
     or (p_error is not null and p_error !~ '^[A-Z][A-Z0-9_]{1,79}$') then
    raise exception 'GEN4_INVALID_ATTEMPT' using errcode = '22023';
  end if;
  insert into public.generation_attempts(run_id,attempt_no,attempt_type,provider_outcome,latency_ms,
    usage_metadata,response_hash,response_size,parse_outcome,error_code)
  values(p_run,v_number,p_type,p_outcome,p_latency,p_usage,p_response_hash,p_response_size,p_parse,p_error);
  perform gen4_private.audit('GENERATION_ATTEMPT','GENERATION',p_run,
    jsonb_build_object('attempt',v_number,'outcome',p_outcome,'parse',p_parse,'error',p_error));
  return v_number;
end $$;

create function public.finish_generation_run(p_run uuid,p_postflight_hash text,p_plan jsonb,
  p_content_hash text,p_error text) returns text
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(); v_run public.generation_runs%rowtype;
  v_set public.onboarding_stage_sets%rowtype; v_employee public.employees%rowtype; v_matrix public.role_requirement_matrices%rowtype;
  v_stale boolean := false; v_truth jsonb;
begin
  select * into strict v_run from public.generation_runs where id = p_run for update;
  if v_run.created_by <> v_actor or v_run.status <> 'RUNNING' then
    raise exception 'GEN4_FORBIDDEN_OR_STATE' using errcode = '42501';
  end if;
  if p_plan is null then
    if p_error is null or p_error !~ '^[A-Z][A-Z0-9_]{1,79}$' or p_content_hash is not null then
      raise exception 'GEN4_INVALID_FINISH' using errcode = '22023';
    end if;
    update public.generation_runs set status = 'FAILED',error_code = p_error,completed_at = now() where id = p_run;
    perform gen4_private.audit('GENERATION_FAILED','GENERATION',p_run,jsonb_build_object('error',p_error));
    return 'FAILED';
  end if;
  if p_error is not null or p_content_hash is null or p_content_hash !~ '^[0-9a-f]{64}$'
     or jsonb_typeof(p_plan) <> 'object' or pg_column_size(p_plan) > 4194304
     or p_plan->>'schema_version' is distinct from v_run.schema_version
     or p_plan->>'generation_request_id' is distinct from p_run::text
     or rrm_private.content_hash(p_plan) <> p_content_hash then
    raise exception 'GEN4_INVALID_FINISH' using errcode = '22023';
  end if;
  if not exists (select 1 from public.generation_attempts
                 where run_id = p_run and parse_outcome = 'SCHEMA_VALID') then
    raise exception 'GEN4_INVALID_FINISH' using errcode = '22023';
  end if;
  if p_postflight_hash is distinct from v_run.input_hash then v_stale := true; end if;
  if (v_run.input_snapshot->>'as_of')::timestamptz is distinct from
     (((now() at time zone 'UTC')::date)::timestamp at time zone 'UTC') then
    v_stale := true;
  end if;
  select * into v_set from public.onboarding_stage_sets where id = v_run.stage_set_id for share;
  select * into v_employee from public.employees where id = v_run.employee_id for share;
  -- Keep the Phase 3 role -> matrix order, and stabilize coded employee context.
  perform 1 from public.roles where id = v_employee.role_id for share;
  perform 1 from public.departments where id = v_employee.department_id for share;
  select * into v_matrix from public.role_requirement_matrices where id = v_run.matrix_id for share;
  if v_set.status is distinct from 'ACTIVE' or v_set.version is distinct from v_run.stage_set_version
     or v_set.name is distinct from v_run.input_snapshot->'stage_set'->>'name'
     or v_set.code is distinct from v_run.stage_set_code
     or v_employee.profile_id::text is distinct from v_run.input_snapshot->'employee'->>'profile_id'
     or v_employee.role_id is distinct from (v_run.input_snapshot->'employee'->>'role_id')::uuid
     or v_employee.department_id is distinct from (v_run.input_snapshot->'employee'->>'department_id')::uuid
     or v_employee.experience_level::text is distinct from v_run.input_snapshot->'employee'->>'experience'
     or v_employee.location_code is distinct from v_run.input_snapshot->'employee'->>'location_code'
     or v_employee.joining_date::text is distinct from v_run.input_snapshot->'employee'->>'joining_date'
     or not exists (select 1 from public.roles r where r.id = v_employee.role_id
                    and r.status = 'ACTIVE' and (r.department_id is null or r.department_id = v_employee.department_id)
                    and r.code = v_run.input_snapshot->'employee'->>'role_code')
     or not exists (select 1 from public.departments d where d.id = v_employee.department_id
                    and d.status = 'ACTIVE' and d.code = v_run.input_snapshot->'employee'->>'department_code')
     or v_matrix.status is distinct from 'APPROVED'
     or v_matrix.role_id is distinct from v_employee.role_id
     or v_matrix.revision is distinct from v_run.matrix_revision
     or v_matrix.snapshot_hash is distinct from v_run.matrix_snapshot_hash
     or v_matrix.current_edit is distinct from v_run.matrix_edit
     or v_matrix.lock_version is distinct from v_run.matrix_lock_version then
    v_stale := true;
  end if;
  if not v_stale then
    begin
      v_truth := public.get_rrm_ground_truth(v_run.matrix_id);
      if v_truth->>'snapshot_hash' is distinct from v_run.matrix_snapshot_hash then v_stale := true; end if;
    exception when sqlstate '40001' or sqlstate '22023' then v_stale := true;
    end;
  end if;
  if v_stale then
    update public.generation_runs set status = 'STALE_INPUT',error_code = 'STALE_INPUT',completed_at = now()
      where id = p_run;
    perform gen4_private.audit('GENERATION_STALE_INPUT','GENERATION',p_run,
      jsonb_build_object('input_hash',v_run.input_hash));
    return 'STALE_INPUT';
  end if;
  insert into public.generated_plans(run_id,schema_version,content,content_hash)
    values(p_run,v_run.schema_version,p_plan,p_content_hash);
  update public.generation_runs set status = 'UNVERIFIED',completed_at = now() where id = p_run;
  perform gen4_private.audit('GENERATION_UNVERIFIED','GENERATION',p_run,
    jsonb_build_object('content_hash',p_content_hash,'input_hash',v_run.input_hash));
  return 'UNVERIFIED';
end $$;

-- Explicit Admin-only terminal recovery after a run has been quiet for at
-- least 15 minutes. It never retries a provider or creates a plan.
create function public.recover_abandoned_generation_run(p_run uuid) returns boolean
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := gen4_private.actor(true); v_run public.generation_runs%rowtype;
  v_last_attempt timestamptz;
begin
  select * into strict v_run from public.generation_runs where id = p_run for update;
  if v_run.status <> 'RUNNING' then return false; end if;
  select max(created_at) into v_last_attempt from public.generation_attempts where run_id = p_run;
  if greatest(v_run.started_at,coalesce(v_last_attempt,v_run.started_at)) > now() - interval '15 minutes' then
    raise exception 'GEN4_RECOVERY_TOO_EARLY' using errcode = '40001';
  end if;
  update public.generation_runs set status = 'FAILED',error_code = 'ABANDONED_RUN',completed_at = now()
    where id = p_run;
  perform gen4_private.audit('GENERATION_ABANDONED','GENERATION',p_run,
    jsonb_build_object('original_creator',v_run.created_by,'recovered_by',v_actor,
      'started_at',v_run.started_at,'last_attempt_at',v_last_attempt));
  return true;
end $$;

-- Explicit grants: no direct authenticated writes, no anon/PUBLIC access.
do $$
declare v_table text; v_function record;
begin
  foreach v_table in array array['onboarding_stage_sets','onboarding_stage_set_items',
      'generation_runs','generation_attempts','generated_plans'] loop
    execute format('alter table public.%I enable row level security',v_table);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',v_table);
    execute format('grant select on public.%I to authenticated',v_table);
  end loop;
  for v_function in select p.oid::regprocedure as signature from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'gen4_private' or (n.nspname = 'public' and p.proname = any(array[
      'create_onboarding_stage_set','activate_onboarding_stage_set','bootstrap_standard_onboarding_stages',
      'reserve_generation_run','claim_generation_run','record_generation_attempt','finish_generation_run',
      'recover_abandoned_generation_run'])) loop
    execute format('revoke all on function %s from public,anon,authenticated,service_role',v_function.signature);
  end loop;
end $$;

create policy stage_sets_read on public.onboarding_stage_sets for select to authenticated using (
  public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'));
create policy stage_set_items_read on public.onboarding_stage_set_items for select to authenticated using (
  public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'));
create policy generation_runs_read on public.generation_runs for select to authenticated using (
  public.has_app_role('ADMIN') or public.has_app_role('REVIEWER')
  or (public.has_app_role('TRAINING_MANAGER') and created_by = public.current_profile_id()));
create policy generation_attempts_read on public.generation_attempts for select to authenticated using (
  exists (select 1 from public.generation_runs r where r.id = run_id));
create policy generated_plans_read on public.generated_plans for select to authenticated using (
  exists (select 1 from public.generation_runs r where r.id = run_id));

grant execute on function public.create_onboarding_stage_set(text,integer,text,uuid[]),
  public.activate_onboarding_stage_set(uuid),public.bootstrap_standard_onboarding_stages(),
  public.reserve_generation_run(uuid,jsonb,text,text,text,text,jsonb,text,text,text),
  public.claim_generation_run(uuid),
  public.record_generation_attempt(uuid,text,text,integer,jsonb,text,integer,text,text),
  public.finish_generation_run(uuid,text,jsonb,text,text),
  public.recover_abandoned_generation_run(uuid) to authenticated;

commit;
