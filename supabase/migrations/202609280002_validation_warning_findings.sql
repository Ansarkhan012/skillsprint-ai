-- Align record_python_validation with jev/1.0.0: any WARNING-severity finding is
-- non-blocking for VERIFIED_WITH_WARNING. Previously only a duplicate-requirement
-- warning was accepted, so staged structured timing (TIMING_UNRESOLVED WARNING)
-- could not be persisted. Only that predicate changes; privileges are preserved by
-- CREATE OR REPLACE. Apply manually after 202609260002. No rows are changed.
begin;

create or replace function public.record_python_validation(p_actor uuid,p_plan uuid,p_result jsonb) returns jsonb
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
                 where x->>'severity' is distinct from 'WARNING') then
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

commit;
