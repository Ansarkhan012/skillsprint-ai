-- Phase 4D bounded prompt provenance. Historical rows and RPC remain unchanged.
begin;

alter table public.generation_runs add column projection_hash text
  check (projection_hash is null or projection_hash ~ '^[0-9a-f]{64}$');
alter table public.generation_runs add constraint generation_runs_bounded_projection_check
  check (prompt_version <> 'phase4d-bounded-generation/1.0.0' or projection_hash is not null);

create or replace function public.reserve_generation_run_bounded(
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
     or p_provider is null or p_provider not in ('gemini','groq')
     or p_model is null
     or (p_provider = 'gemini' and p_model !~ '^[A-Za-z0-9_.-]{1,100}$')
     or (p_provider = 'groq' and p_model is distinct from 'openai/gpt-oss-20b')
     or p_prompt_version is distinct from 'phase4d-bounded-generation/1.0.0'
     or p_template_hash is distinct from 'a0275be4cc8b88bb4ff2b0cf19485abcd482482cca662dffb0e37fa130e8e2a6'
     or p_schema_version is distinct from 'onboarding-plan/1.0.0'
     or p_provider_config is null or jsonb_typeof(p_provider_config) <> 'object'
     or pg_column_size(p_provider_config) > 8192
     or (select count(*) from jsonb_object_keys(p_provider_config)) <> 4
     or exists (select 1 from jsonb_object_keys(p_provider_config) k
                where k not in ('temperature','max_output_tokens','timeout_seconds','projection_hash'))
     or p_provider_config->>'projection_hash' is null
     or p_provider_config->>'projection_hash' !~ '^[0-9a-f]{64}$'
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
    template_hash,schema_version,projection_hash,idempotency_key_hash)
  values(p_employee,v_employee.profile_id,v_actor,v_matrix.id,v_matrix.revision,v_matrix.current_edit,
    v_matrix.lock_version,v_matrix.snapshot_hash,p_input,p_input_hash,v_set.id,v_set.code,v_set.version,
    p_provider,p_model,p_provider_config,p_prompt_version,p_template_hash,p_schema_version,
    p_provider_config->>'projection_hash',p_idempotency_key_hash)
  on conflict (created_by,employee_id,idempotency_key_hash) do nothing returning id into v_id;
  if v_id is null then
    select * into strict v_existing from public.generation_runs
      where created_by = v_actor and employee_id = p_employee and idempotency_key_hash = p_idempotency_key_hash;
    if v_existing.input_hash <> p_input_hash or v_existing.prompt_version <> p_prompt_version
       or v_existing.schema_version <> p_schema_version or v_existing.provider <> p_provider
       or v_existing.model <> p_model or v_existing.provider_config is distinct from p_provider_config
       or v_existing.template_hash <> p_template_hash
       or v_existing.projection_hash <> p_provider_config->>'projection_hash' then
      raise exception 'GEN4_IDEMPOTENCY_CONFLICT' using errcode = '40001';
    end if;
    return jsonb_build_object('id',v_existing.id,'status',v_existing.status,'created',false);
  end if;
  perform gen4_private.audit('GENERATION_REQUESTED','GENERATION',v_id,
    jsonb_build_object('employee_id',p_employee,'input_hash',p_input_hash,'prompt_version',p_prompt_version));
  return jsonb_build_object('id',v_id,'status','QUEUED','created',true);
end $$;

-- Default function EXECUTE privileges are revoked before the narrow application grant.
revoke all on function public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)
  from public,anon,authenticated,service_role;
grant execute on function public.reserve_generation_run_bounded(uuid,jsonb,text,text,text,text,jsonb,text,text,text)
  to authenticated;

commit;
