-- Phase 3A.1 ONLY. Prepared for human review; never executed by application startup.
-- Apply once, as a transaction. An accidental second run fails without partial changes.
begin;

create schema rrm_private;
revoke all on schema rrm_private from public, anon, authenticated, service_role;

-- RRM-only UTC policy: never inherit request/session timezone for dates or hashes.
create function rrm_private.utc_timestamp(p_value timestamptz) returns text
language sql immutable strict set search_path = '' as $$
  select to_char(p_value at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
$$;

create function rrm_private.utc_today() returns date
language sql stable set search_path = '' as $$
  select (statement_timestamp() at time zone 'UTC')::date
$$;

create function rrm_private.nonblank_text(p_value text) returns boolean
language sql immutable set search_path = '' as $$
  -- Same explicit whitespace code points as Python REASON_WHITESPACE.
  select coalesce(length(translate(p_value,
    chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(28)||chr(29)||chr(30)||chr(31)||chr(32)||
    chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||
    chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||
    chr(8239)||chr(8287)||chr(12288), '')) > 0, false)
$$;

create function rrm_private.meaningful_reason(p_value text) returns boolean
language sql immutable set search_path = '' as $$
  select coalesce(length(p_value) between 1 and 2000 and rrm_private.nonblank_text(p_value),false)
$$;

create function rrm_private.assert_keys(p_value jsonb, p_allowed text[], p_required text[] default '{}')
returns void language plpgsql set search_path = '' as $$
begin
  if p_value is null or jsonb_typeof(p_value) <> 'object'
     or exists (select 1 from jsonb_object_keys(p_value) k where not (k = any(p_allowed)))
     or not (p_value ?& p_required) then
    raise exception 'RRM_INVALID_STRUCTURE' using errcode = '22023';
  end if;
end $$;

create function rrm_private.canonical_json(p_value jsonb) returns text
language plpgsql immutable strict set search_path = '' as $$
declare v_text text;
begin
  case jsonb_typeof(p_value)
    when 'object' then
      select '{' || coalesce(string_agg(to_jsonb(key)::text || ':' || rrm_private.canonical_json(value), ',' order by key collate "C"), '') || '}'
      into v_text from jsonb_each(p_value);
    when 'array' then
      select '[' || coalesce(string_agg(rrm_private.canonical_json(value), ',' order by ord), '') || ']'
      into v_text from jsonb_array_elements(p_value) with ordinality x(value, ord);
    when 'number' then
      v_text := (p_value #>> '{}')::numeric::text;
      if position('.' in v_text) > 0 then v_text := rtrim(rtrim(v_text, '0'), '.'); end if;
      if v_text::numeric = 0 then v_text := '0'; end if;
    else v_text := p_value::text;
  end case;
  return v_text;
end $$;

create function rrm_private.assert_text_fields(p_value jsonb,p_fields text[]) returns void
language plpgsql set search_path = '' as $$
declare v_field text;
begin
  foreach v_field in array p_fields loop
    if p_value ? v_field and jsonb_typeof(p_value->v_field) not in ('string','null') then
      raise exception 'RRM_INVALID_FIELD_TYPE' using errcode = '22023';
    end if;
  end loop;
end $$;

create function rrm_private.content_hash(p_value jsonb) returns text
language sql immutable strict set search_path = '' as $$
  select encode(sha256(convert_to(rrm_private.canonical_json(p_value), 'UTF8')), 'hex')
$$;

create function rrm_private.immutable_row() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'RRM_IMMUTABLE_HISTORY' using errcode = '42501';
end $$;

create table public.rrm_precedence_configs (
  id uuid primary key default gen_random_uuid(),
  revision integer not null unique check (revision > 0),
  predecessor_id uuid unique references public.rrm_precedence_configs(id) on delete restrict,
  ranks jsonb not null check (jsonb_typeof(ranks) = 'object' and pg_column_size(ranks) <= 8192),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  reason text not null check (rrm_private.meaningful_reason(reason))
);
create table public.rrm_document_authorities (
  config_id uuid not null references public.rrm_precedence_configs(id) on delete restrict,
  document_id uuid not null references public.documents(id) on delete restrict,
  authority_class text not null,
  primary key (config_id, document_id)
);
create index rrm_authority_document_idx on public.rrm_document_authorities(document_id);

create table public.onboarding_stage_definitions (
  id uuid primary key default gen_random_uuid(),
  code text not null check (code ~ '^[A-Z][A-Z0-9_-]{1,63}$'),
  revision integer not null check (revision > 0),
  predecessor_id uuid unique references public.onboarding_stage_definitions(id) on delete restrict,
  label text not null check (length(trim(label)) between 1 and 100),
  sequence integer not null check (sequence >= 0),
  start_day integer not null check (start_day >= 0),
  end_day integer not null check (end_day >= start_day),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (code, revision)
);

create table public.requirements (
  id uuid primary key default gen_random_uuid(),
  requirement_code text not null check (requirement_code ~ '^[A-Z][A-Z0-9_-]{1,63}$'),
  revision integer not null check (revision > 0),
  predecessor_id uuid unique references public.requirements(id) on delete restrict,
  statement text not null check (length(trim(statement)) between 1 and 4000),
  requirement_type text not null check (requirement_type in
    ('MUST_KNOW','MUST_COMPLETE','MUST_DEMONSTRATE','MUST_ACKNOWLEDGE','RECOMMENDED','OPTIONAL','NOT_APPLICABLE')),
  category text not null check (category ~ '^[A-Z][A-Z0-9_-]{1,63}$'),
  mandatory boolean not null,
  competency text check (length(trim(competency)) between 1 and 4000),
  assessment_required boolean not null default false,
  priority text not null default 'MEDIUM' check (priority in ('LOW','MEDIUM','HIGH')),
  timing jsonb not null default '{"state":"NOT_SPECIFIED"}',
  origin text not null check (origin in ('MANUAL','AI_CANDIDATE')),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (requirement_code, revision),
  check ((revision = 1) = (predecessor_id is null)),
  check (mandatory = (requirement_type like 'MUST\_%' escape '\')),
  check (jsonb_typeof(timing) = 'object' and pg_column_size(timing) <= 32768)
);
create index requirements_author_idx on public.requirements(created_by);
create table public.requirement_sources (
  requirement_id uuid not null references public.requirements(id) on delete restrict,
  chunk_id uuid not null references public.document_chunks(id) on delete restrict,
  primary key (requirement_id, chunk_id)
  -- No client-controlled document/version/locator: the chunk defines all three.
);
create index requirement_sources_chunk_idx on public.requirement_sources(chunk_id);
create table public.requirement_applicability (
  requirement_id uuid not null references public.requirements(id) on delete restrict,
  ordinal integer not null check (ordinal between 0 and 31),
  role_id uuid references public.roles(id) on delete restrict,
  department_id uuid references public.departments(id) on delete restrict,
  location_code text check (length(trim(location_code)) between 1 and 80),
  experience public.experience_level,
  primary key (requirement_id, ordinal)
);
create index requirement_scope_role_idx on public.requirement_applicability(role_id, department_id);

create table public.role_requirement_matrices (
  id uuid primary key default gen_random_uuid(),
  role_id uuid not null references public.roles(id) on delete restrict,
  revision integer not null check (revision > 0),
  predecessor_id uuid unique references public.role_requirement_matrices(id) on delete restrict,
  config_id uuid not null references public.rrm_precedence_configs(id) on delete restrict,
  status text not null default 'DRAFT' check (status in ('DRAFT','SUBMITTED','APPROVED','REJECTED','SUPERSEDED')),
  current_edit integer not null default 0 check (current_edit >= 0),
  lock_version integer not null default 0 check (lock_version >= 0),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  submitted_by uuid references public.profiles(id) on delete restrict,
  submitted_at timestamptz,
  decided_by uuid references public.profiles(id) on delete restrict,
  decided_at timestamptz,
  decision_reason text check (decision_reason is null or rrm_private.meaningful_reason(decision_reason)),
  admin_override boolean not null default false,
  submitted_snapshot jsonb,
  snapshot_hash text check (snapshot_hash ~ '^[0-9a-f]{64}$'),
  unique (role_id, revision),
  check ((revision = 1) = (predecessor_id is null)),
  check (not admin_override or rrm_private.meaningful_reason(decision_reason)),
  check (status = 'DRAFT' or (submitted_snapshot is not null and snapshot_hash is not null and submitted_by is not null)),
  check (status in ('DRAFT','SUBMITTED') or (decided_by is not null and decided_at is not null))
);
create unique index rrm_one_approved_role_idx on public.role_requirement_matrices(role_id) where status = 'APPROVED';
create index rrm_status_idx on public.role_requirement_matrices(status, role_id);
create table public.rrm_matrix_edits (
  matrix_id uuid not null references public.role_requirement_matrices(id) on delete restrict,
  edit_no integer not null check (edit_no > 0),
  created_by uuid not null references public.profiles(id) on delete restrict,
  reason text not null check (rrm_private.meaningful_reason(reason)),
  created_at timestamptz not null default now(),
  primary key (matrix_id, edit_no)
);
create table public.role_requirements (
  matrix_id uuid not null,
  edit_no integer not null,
  requirement_id uuid not null references public.requirements(id) on delete restrict,
  sequence integer not null check (sequence between 0 and 100000),
  stage_id uuid references public.onboarding_stage_definitions(id) on delete restrict,
  exception_to uuid,
  downgrade_requested boolean not null default false,
  downgrade_justification text check (downgrade_justification is null or rrm_private.meaningful_reason(downgrade_justification)),
  downgrade_evidence jsonb check (downgrade_evidence is null or
    (jsonb_typeof(downgrade_evidence) = 'object' and pg_column_size(downgrade_evidence) <= 32768)),
  primary key (matrix_id, edit_no, requirement_id),
  foreign key (matrix_id, edit_no) references public.rrm_matrix_edits(matrix_id, edit_no) on delete restrict,
  foreign key (matrix_id, edit_no, exception_to) references public.role_requirements(matrix_id, edit_no, requirement_id) on delete restrict deferrable initially deferred,
  check (exception_to is distinct from requirement_id)
);
create index role_requirements_requirement_idx on public.role_requirements(requirement_id);
create table public.requirement_dependencies (
  matrix_id uuid not null,
  edit_no integer not null,
  dependent_id uuid not null,
  prerequisite_id uuid not null,
  primary key (matrix_id, edit_no, dependent_id, prerequisite_id),
  foreign key (matrix_id, edit_no, dependent_id) references public.role_requirements(matrix_id, edit_no, requirement_id) on delete restrict,
  foreign key (matrix_id, edit_no, prerequisite_id) references public.role_requirements(matrix_id, edit_no, requirement_id) on delete restrict,
  check (dependent_id <> prerequisite_id)
);
create table public.rrm_issues (
  id uuid primary key default gen_random_uuid(),
  matrix_id uuid not null references public.role_requirement_matrices(id) on delete restrict,
  raised_edit integer not null,
  kind text not null check (kind in ('CONFLICT','AMBIGUITY','DUPLICATE','SUSPICIOUS_CONTENT','MISSING_EVIDENCE')),
  detail text not null check (length(trim(detail)) between 1 and 4000),
  requirement_id uuid,
  related_requirement_id uuid,
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (matrix_id, raised_edit) references public.rrm_matrix_edits(matrix_id, edit_no) on delete restrict,
  foreign key (matrix_id, raised_edit, requirement_id) references public.role_requirements(matrix_id, edit_no, requirement_id) on delete restrict,
  foreign key (matrix_id, raised_edit, related_requirement_id) references public.role_requirements(matrix_id, edit_no, requirement_id) on delete restrict,
  unique (id,matrix_id)
);
create index rrm_issues_matrix_idx on public.rrm_issues(matrix_id);
create table public.rrm_issue_resolutions (
  issue_id uuid not null,
  matrix_id uuid not null,
  edit_no integer not null,
  resolved_by uuid not null references public.profiles(id) on delete restrict,
  resolved_at timestamptz not null default now(),
  reason text not null check (rrm_private.meaningful_reason(reason)),
  admin_override boolean not null default false,
  primary key (issue_id,edit_no),
  foreign key (issue_id,matrix_id) references public.rrm_issues(id,matrix_id) on delete restrict,
  foreign key (matrix_id,edit_no) references public.rrm_matrix_edits(matrix_id,edit_no) on delete restrict
);

create function rrm_private.actor(p_author boolean default false, p_reviewer boolean default false) returns uuid
language plpgsql stable security definer set search_path = '' as $$
declare v_actor uuid := public.current_profile_id();
begin
  if v_actor is null or not (public.has_app_role('ADMIN')
     or (p_author and public.has_app_role('TRAINING_MANAGER'))
     or (p_reviewer and public.has_app_role('REVIEWER'))) then
    raise exception 'RRM_FORBIDDEN' using errcode = '42501';
  end if;
  return v_actor;
end $$;

create function rrm_private.audit(p_action text, p_target uuid, p_reason text, p_metadata jsonb)
returns void language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_logs(actor_profile_id, action, target_type, target_id, reason, metadata)
  values(public.current_profile_id(), p_action, 'RRM', p_target, p_reason, p_metadata);
end $$;

create function rrm_private.valid_timing(p_requirement uuid, p_allow_ambiguous boolean default false)
returns void language plpgsql stable set search_path = '' as $$
declare t jsonb; v_field text; v_span jsonb; v_content text; v_quote text; v_expected text;
begin
  select timing into strict t from public.requirements where id = p_requirement;
  perform rrm_private.assert_keys(t, array['state','original_text','trigger','relation','value','unit','calendar_basis','evidence'], array['state']);
  perform rrm_private.assert_text_fields(t,array['state','original_text','trigger','relation','unit','calendar_basis']);
  if t->>'state' not in ('NOT_SPECIFIED','AMBIGUOUS','STRUCTURED') or t->>'state' is null then
    raise exception 'RRM_INVALID_TIMING' using errcode = '22023';
  end if;
  if t->>'state' <> 'STRUCTURED' then
    if exists (select 1 from jsonb_each(t) e where e.key in ('trigger','relation','value','unit','calendar_basis') and e.value <> 'null'::jsonb)
       or coalesce(t->'evidence', '{}'::jsonb) <> '{}'::jsonb
       or ((t->>'state' = 'NOT_SPECIFIED') <> (t->>'original_text' is null)) then
      raise exception 'RRM_INVALID_TIMING' using errcode = '22023';
    end if;
    if t->>'state' = 'AMBIGUOUS' and (not p_allow_ambiguous or length(trim(coalesce(t->>'original_text',''))) = 0) then
      raise exception 'RRM_TIMING_MANUAL_REVIEW' using errcode = '22023';
    end if;
    return;
  end if;
  if not (t ?& array['original_text','trigger','relation','value','unit','calendar_basis','evidence'])
     or t->>'relation' not in ('WITHIN','BEFORE','AFTER','AT') or t->>'unit' not in ('HOUR','DAY','WEEK')
     or t->>'calendar_basis' not in ('CALENDAR','BUSINESS')
     or jsonb_typeof(t->'value') is distinct from 'number' or (t->>'value') !~ '^[0-9]{1,6}$'
     or (t->>'value')::integer > 100000 then
    raise exception 'RRM_INVALID_TIMING' using errcode = '22023';
  end if;
  perform rrm_private.assert_keys(t->'evidence', array['original_text','trigger','relation','value','unit','calendar_basis'],
    array['original_text','trigger','relation','value','unit','calendar_basis']);
  foreach v_field in array array['original_text','trigger','relation','value','unit','calendar_basis'] loop
    v_span := t->'evidence'->v_field;
    perform rrm_private.assert_keys(v_span, array['chunk_id','start','end','quote'], array['chunk_id','start','end','quote']);
    perform rrm_private.assert_text_fields(v_span,array['chunk_id','quote']);
    if jsonb_typeof(v_span->'start') is distinct from 'number' or jsonb_typeof(v_span->'end') is distinct from 'number'
       or (v_span->>'start') !~ '^[0-9]{1,6}$' or (v_span->>'end') !~ '^[0-9]{1,6}$'
       or (v_span->>'end')::integer <= (v_span->>'start')::integer then
      raise exception 'RRM_INVALID_TIMING_SPAN' using errcode = '22023';
    end if;
    select c.content into v_content from public.requirement_sources s join public.document_chunks c on c.id = s.chunk_id
      where s.requirement_id = p_requirement and s.chunk_id = (v_span->>'chunk_id')::uuid;
    v_quote := v_span->>'quote'; v_expected := lower(t->>v_field);
    if v_content is null or v_quote is null or v_expected is null or length(trim(v_expected)) = 0
       or (v_span->>'end')::integer > char_length(v_content)
       or substring(v_content from (v_span->>'start')::integer + 1 for (v_span->>'end')::integer - (v_span->>'start')::integer) <> v_quote
       or not (lower(trim(v_quote)) = v_expected or (v_field = 'unit' and lower(trim(v_quote)) = v_expected || 's')) then
      raise exception 'RRM_TIMING_EVIDENCE_MISMATCH' using errcode = '22023';
    end if;
  end loop;
end $$;

create function public.create_rrm_precedence_config(p_ranks jsonb, p_documents jsonb, p_reason text,
  p_predecessor uuid default null) returns uuid language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(); v_id uuid; v_revision integer; v_key text; v_value jsonb;
begin
  perform pg_advisory_xact_lock(730301);
  if jsonb_typeof(p_ranks) is distinct from 'object' or jsonb_typeof(p_documents) is distinct from 'object'
     or p_ranks = '{}'::jsonb or (select count(*) from jsonb_object_keys(p_ranks)) > 20
     or pg_column_size(p_documents) > 262144 then
    raise exception 'RRM_INVALID_AUTHORITY' using errcode = '22023';
  end if;
  for v_key,v_value in select * from jsonb_each(p_ranks) loop
    if v_key !~ '^[A-Z][A-Z0-9_]{0,63}$' or v_key = 'ROLE_EXCEPTION' or jsonb_typeof(v_value) <> 'number'
       or v_value::text !~ '^[0-9]{1,4}$' or v_value::text::integer > 1000 then
      raise exception 'RRM_INVALID_AUTHORITY' using errcode = '22023';
    end if;
  end loop;
  select coalesce(max(revision),0) + 1 into v_revision from public.rrm_precedence_configs;
  if (v_revision = 1 and p_predecessor is not null) or (v_revision > 1 and not exists
    (select 1 from public.rrm_precedence_configs where id = p_predecessor and revision = v_revision - 1)) then
    raise exception 'RRM_REVISION_CONFLICT' using errcode = '40001';
  end if;
  insert into public.rrm_precedence_configs(revision, predecessor_id, ranks, created_by, reason)
    values(v_revision,p_predecessor,p_ranks,v_actor,p_reason) returning id into v_id;
  for v_key,v_value in select * from jsonb_each(p_documents) loop
    if jsonb_typeof(v_value) <> 'string' or not (p_ranks ? (v_value #>> '{}')) then
      raise exception 'RRM_UNMAPPED_AUTHORITY' using errcode = '22023';
    end if;
    insert into public.rrm_document_authorities values(v_id,v_key::uuid,v_value #>> '{}');
  end loop;
  perform rrm_private.audit('RRM_CONFIG_CREATED',v_id,p_reason,jsonb_build_object('revision',v_revision));
  return v_id;
end $$;
-- Approved initial configuration values (explicit document mappings are supplied by Admin):
-- {"DEPARTMENT_SOP":40,"COMPANY_POLICY":30,"FAQ":20,"INFORMAL_GUIDANCE":10}
-- Approved applicable role exceptions are explicit entry edges, never a filename/category rank.

create function public.create_rrm_stage(p_code text,p_label text,p_sequence integer,p_start integer,p_end integer,
  p_predecessor uuid default null) returns uuid language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(); v_id uuid; v_revision integer := 1; v_old public.onboarding_stage_definitions%rowtype;
begin
  if p_predecessor is not null then
    select * into strict v_old from public.onboarding_stage_definitions where id = p_predecessor for update;
    if v_old.code <> p_code then raise exception 'RRM_PREDECESSOR_MISMATCH' using errcode = '22023'; end if;
    v_revision := v_old.revision + 1;
  end if;
  insert into public.onboarding_stage_definitions(code,revision,predecessor_id,label,sequence,start_day,end_day,created_by)
    values(p_code,v_revision,p_predecessor,p_label,p_sequence,p_start,p_end,v_actor) returning id into v_id;
  perform rrm_private.audit('RRM_STAGE_CREATED',v_id,null,jsonb_build_object('revision',v_revision));
  return v_id;
end $$;

create function public.create_requirement_candidate(p_data jsonb, p_predecessor uuid default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(true,false); v_id uuid; v_revision integer := 1;
  v_old public.requirements%rowtype; v_scope jsonb; v_ordinal integer := 0; v_chunk jsonb;
begin
  perform rrm_private.assert_keys(p_data,array['code','statement','requirement_type','category','mandatory','competency',
    'assessment_required','priority','timing','origin','chunk_ids','scopes'],
    array['code','statement','requirement_type','category','mandatory','origin','chunk_ids','scopes']);
  perform rrm_private.assert_text_fields(p_data,array['code','statement','requirement_type','category','competency','priority','origin']);
  if pg_column_size(p_data) > 262144 or jsonb_typeof(p_data->'mandatory') <> 'boolean'
     or (p_data ? 'assessment_required' and jsonb_typeof(p_data->'assessment_required') <> 'boolean')
     or jsonb_typeof(p_data->'chunk_ids') <> 'array' or jsonb_typeof(p_data->'scopes') <> 'array'
     or jsonb_array_length(p_data->'chunk_ids') not between 1 and 100
     or jsonb_array_length(p_data->'scopes') not between 1 and 32 then
    raise exception 'RRM_INVALID_STRUCTURE' using errcode = '22023';
  end if;
  if p_predecessor is not null then
    select * into strict v_old from public.requirements where id = p_predecessor for update;
    if v_old.requirement_code <> p_data->>'code' then
      raise exception 'RRM_PREDECESSOR_MISMATCH' using errcode = '22023';
    end if;
    v_revision := v_old.revision + 1;
  end if;
  insert into public.requirements(requirement_code,revision,predecessor_id,statement,requirement_type,category,mandatory,
    competency,assessment_required,priority,timing,origin,created_by)
  values(p_data->>'code',v_revision,p_predecessor,p_data->>'statement',p_data->>'requirement_type',p_data->>'category',
    (p_data->>'mandatory')::boolean,p_data->>'competency',coalesce((p_data->>'assessment_required')::boolean,false),
    coalesce(p_data->>'priority','MEDIUM'),coalesce(p_data->'timing','{"state":"NOT_SPECIFIED"}'),p_data->>'origin',v_actor)
  returning id into v_id;
  for v_chunk in select value from jsonb_array_elements(p_data->'chunk_ids') loop
    insert into public.requirement_sources values(v_id,(v_chunk #>> '{}')::uuid);
  end loop;
  for v_scope in select value from jsonb_array_elements(p_data->'scopes') loop
    perform rrm_private.assert_keys(v_scope,array['role_id','department_id','location_code','experience']);
    perform rrm_private.assert_text_fields(v_scope,array['role_id','department_id','location_code','experience']);
    insert into public.requirement_applicability values(v_id,v_ordinal,(v_scope->>'role_id')::uuid,
      (v_scope->>'department_id')::uuid,v_scope->>'location_code',(v_scope->>'experience')::public.experience_level);
    v_ordinal := v_ordinal + 1;
  end loop;
  if exists (select 1 from public.requirement_applicability where requirement_id = v_id
    group by role_id,department_id,location_code,experience having count(*) > 1) then
    raise exception 'RRM_DUPLICATE_SCOPE' using errcode = '22023';
  end if;
  perform rrm_private.valid_timing(v_id,true);
  perform rrm_private.audit('RRM_CANDIDATE_CREATED',v_id,null,jsonb_build_object('revision',v_revision,'creator',v_actor));
  return v_id;
end $$;

create function public.create_rrm_matrix(p_role uuid,p_config uuid,p_predecessor uuid default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(true,false); v_id uuid; v_revision integer := 1; v_old public.role_requirement_matrices%rowtype;
begin
  perform 1 from public.roles where id = p_role and status = 'ACTIVE' for update;
  if not found then raise exception 'RRM_ROLE_INVALID' using errcode = '22023'; end if;
  if p_predecessor is not null then
    select * into strict v_old from public.role_requirement_matrices where id = p_predecessor for update;
    if v_old.role_id <> p_role or v_old.status not in ('APPROVED','REJECTED','SUPERSEDED') then
      raise exception 'RRM_PREDECESSOR_MISMATCH' using errcode = '22023';
    end if;
    v_revision := v_old.revision + 1;
  end if;
  insert into public.role_requirement_matrices(role_id,revision,predecessor_id,config_id,created_by)
    values(p_role,v_revision,p_predecessor,p_config,v_actor) returning id into v_id;
  perform rrm_private.audit('RRM_MATRIX_CREATED',v_id,null,jsonb_build_object('creator',v_actor,'predecessor',p_predecessor));
  return v_id;
end $$;

create function public.edit_rrm_matrix(p_matrix uuid,p_expected_version integer,p_entries jsonb,p_dependencies jsonb,p_reason text)
returns integer language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(true,false); v_matrix public.role_requirement_matrices%rowtype;
  v_entry jsonb; v_edge jsonb; v_edit integer;
begin
  select * into strict v_matrix from public.role_requirement_matrices where id = p_matrix for update;
  if v_matrix.created_by <> v_actor or v_matrix.status <> 'DRAFT' then
    raise exception 'RRM_DRAFT_OWNER_REQUIRED' using errcode = '42501';
  end if;
  if p_expected_version is distinct from v_matrix.lock_version then
    raise exception 'RRM_EDIT_CONFLICT' using errcode = '40001';
  end if;
  if jsonb_typeof(p_entries) is distinct from 'array' or jsonb_typeof(p_dependencies) is distinct from 'array'
     or jsonb_array_length(p_entries) not between 1 and 1000 or jsonb_array_length(p_dependencies) > 5000 then
    raise exception 'RRM_INVALID_STRUCTURE' using errcode = '22023';
  end if;
  v_edit := v_matrix.current_edit + 1;
  insert into public.rrm_matrix_edits values(p_matrix,v_edit,v_actor,p_reason,now());
  for v_entry in select value from jsonb_array_elements(p_entries) loop
    perform rrm_private.assert_keys(v_entry,array['requirement_id','sequence','stage_id','exception_to',
      'downgrade_requested','downgrade_justification','downgrade_evidence'],array['requirement_id','sequence']);
    perform rrm_private.assert_text_fields(v_entry,array['downgrade_justification']);
    if v_entry ? 'downgrade_requested' and jsonb_typeof(v_entry->'downgrade_requested') is distinct from 'boolean' then
      raise exception 'RRM_INVALID_DOWNGRADE_FLAG' using errcode = '22023';
    end if;
    if jsonb_typeof(v_entry->'sequence') <> 'number' or (v_entry->>'sequence') !~ '^[0-9]{1,6}$' then
      raise exception 'RRM_INVALID_SEQUENCE' using errcode = '22023';
    end if;
    insert into public.role_requirements values(p_matrix,v_edit,(v_entry->>'requirement_id')::uuid,
      (v_entry->>'sequence')::integer,(v_entry->>'stage_id')::uuid,(v_entry->>'exception_to')::uuid,
      coalesce((v_entry->>'downgrade_requested')::boolean,false),v_entry->>'downgrade_justification',
      nullif(v_entry->'downgrade_evidence','null'::jsonb));
  end loop;
  for v_edge in select value from jsonb_array_elements(p_dependencies) loop
    perform rrm_private.assert_keys(v_edge,array['dependent_id','prerequisite_id'],array['dependent_id','prerequisite_id']);
    insert into public.requirement_dependencies values(p_matrix,v_edit,(v_edge->>'dependent_id')::uuid,(v_edge->>'prerequisite_id')::uuid);
  end loop;
  update public.role_requirement_matrices set current_edit = v_edit, lock_version = lock_version + 1 where id = p_matrix;
  perform rrm_private.audit('RRM_MATRIX_EDITED',p_matrix,p_reason,jsonb_build_object('edit',v_edit,'creator',v_actor));
  return v_matrix.lock_version + 1;
end $$;

create function rrm_private.contributed(p_matrix uuid,p_actor uuid) returns boolean
language sql stable set search_path = '' as $$
  select exists (select 1 from public.role_requirement_matrices m where m.id = p_matrix
    and (m.created_by = p_actor or m.submitted_by = p_actor))
    or exists (select 1 from public.rrm_matrix_edits e where e.matrix_id = p_matrix and e.created_by = p_actor)
    or exists (select 1 from public.role_requirements e join public.requirements r on r.id = e.requirement_id
      where e.matrix_id = p_matrix and r.created_by = p_actor)
$$;

create function public.raise_rrm_issue(p_matrix uuid,p_expected_version integer,p_kind text,p_detail text,
  p_requirement uuid default null,p_related uuid default null) returns uuid
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(true,true); v_matrix public.role_requirement_matrices%rowtype; v_id uuid;
begin
  select * into strict v_matrix from public.role_requirement_matrices where id = p_matrix for update;
  if v_matrix.status <> 'DRAFT' then raise exception 'RRM_FROZEN_REVISION' using errcode = '22023'; end if;
  if p_expected_version is distinct from v_matrix.lock_version then raise exception 'RRM_EDIT_CONFLICT' using errcode = '40001'; end if;
  insert into public.rrm_issues(matrix_id,raised_edit,kind,detail,requirement_id,related_requirement_id,created_by)
    values(p_matrix,v_matrix.current_edit,p_kind,p_detail,p_requirement,p_related,v_actor) returning id into v_id;
  update public.role_requirement_matrices set lock_version = lock_version + 1 where id = p_matrix;
  perform rrm_private.audit('RRM_ISSUE_RAISED',p_matrix,null,jsonb_build_object('issue_id',v_id,'kind',p_kind));
  return v_id;
end $$;

create function public.resolve_rrm_issue(p_issue uuid,p_expected_version integer,p_reason text,p_admin_override boolean default false)
returns void language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(false,true); v_issue public.rrm_issues%rowtype;
  v_matrix public.role_requirement_matrices%rowtype; v_own boolean;
begin
  select * into strict v_issue from public.rrm_issues where id = p_issue;
  select * into strict v_matrix from public.role_requirement_matrices where id = v_issue.matrix_id for update;
  if v_matrix.status <> 'DRAFT' then raise exception 'RRM_ISSUE_FROZEN' using errcode = '22023'; end if;
  if p_expected_version is distinct from v_matrix.lock_version then raise exception 'RRM_EDIT_CONFLICT' using errcode = '40001'; end if;
  v_own := rrm_private.contributed(v_matrix.id,v_actor);
  if p_admin_override is null or (v_own and not (public.has_app_role('ADMIN') and p_admin_override))
     or (p_admin_override and (not v_own or not public.has_app_role('ADMIN'))) then
    raise exception 'RRM_SELF_REVIEW_FORBIDDEN' using errcode = '42501';
  end if;
  if not rrm_private.meaningful_reason(p_reason) then raise exception 'RRM_REASON_REQUIRED' using errcode = '22023'; end if;
  insert into public.rrm_issue_resolutions(issue_id,matrix_id,edit_no,resolved_by,reason,admin_override)
    values(p_issue,v_matrix.id,v_matrix.current_edit,v_actor,p_reason,p_admin_override);
  update public.role_requirement_matrices set lock_version = lock_version + 1 where id = v_matrix.id;
  perform rrm_private.audit('RRM_ISSUE_RESOLVED',v_matrix.id,p_reason,jsonb_build_object('issue_id',p_issue,'approver',v_actor,'admin_override',p_admin_override));
end $$;

create function rrm_private.valid_downgrade(p_matrix uuid,p_edit integer,p_requirement uuid) returns void
language plpgsql set search_path = '' as $$
declare e public.role_requirements%rowtype; v_downgrade boolean; s jsonb; v_content text;
begin
  select * into strict e from public.role_requirements
    where matrix_id = p_matrix and edit_no = p_edit and requirement_id = p_requirement;
  select coalesce(base.mandatory and not specific.mandatory,false) into v_downgrade
    from public.requirements specific left join public.requirements base on base.id = e.exception_to
    where specific.id = e.requirement_id;
  if not v_downgrade then
    if e.downgrade_requested or e.downgrade_justification is not null or e.downgrade_evidence is not null then
      raise exception 'RRM_UNEXPECTED_DOWNGRADE_DECISION' using errcode = '22023';
    end if;
    return;
  end if;
  if not e.downgrade_requested or not rrm_private.meaningful_reason(e.downgrade_justification)
     or e.downgrade_evidence is null then
    raise exception 'RRM_DOWNGRADE_MANUAL_REVIEW' using errcode = '22023';
  end if;
  s := e.downgrade_evidence;
  perform rrm_private.assert_keys(s,array['chunk_id','start','end','quote'],array['chunk_id','start','end','quote']);
  if jsonb_typeof(s->'chunk_id') is distinct from 'string' or jsonb_typeof(s->'quote') is distinct from 'string'
     or jsonb_typeof(s->'start') is distinct from 'number' or jsonb_typeof(s->'end') is distinct from 'number'
     or (s->>'start') !~ '^[0-9]{1,6}$' or (s->>'end') !~ '^[0-9]{1,6}$' then
    raise exception 'RRM_DOWNGRADE_EVIDENCE_MISMATCH' using errcode = '22023';
  end if;
  select c.content into v_content from public.requirement_sources rs join public.document_chunks c on c.id = rs.chunk_id
    where rs.requirement_id = e.requirement_id and rs.chunk_id = (s->>'chunk_id')::uuid;
  if v_content is null or (s->>'end')::integer <= (s->>'start')::integer
     or (s->>'end')::integer > char_length(v_content) or not rrm_private.nonblank_text(s->>'quote')
     or char_length(s->>'quote') > 4000
     or substring(v_content from (s->>'start')::integer + 1 for (s->>'end')::integer - (s->>'start')::integer) <> s->>'quote' then
    raise exception 'RRM_DOWNGRADE_EVIDENCE_MISMATCH' using errcode = '22023';
  end if;
  -- Eligibility is checked by assert_matrix; an independent matrix approval authorizes
  -- this exact target/justification/span. A draft flag alone never authorizes use.
end $$;

create function rrm_private.assert_matrix(p_matrix uuid) returns void
language plpgsql set search_path = '' as $$
declare m public.role_requirement_matrices%rowtype; v_requirement uuid;
begin
  select * into strict m from public.role_requirement_matrices where id = p_matrix;
  if not exists (select 1 from public.roles where id = m.role_id and status = 'ACTIVE')
     or not exists (select 1 from public.role_requirements where matrix_id = m.id and edit_no = m.current_edit)
     or exists (select 1 from public.rrm_issues i where i.matrix_id = m.id and not exists
       (select 1 from public.rrm_issue_resolutions r where r.issue_id = i.id and r.edit_no = m.current_edit)) then
    raise exception 'RRM_BLOCKING_ISSUE_OR_EMPTY_MATRIX' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements e join public.requirements r on r.id = e.requirement_id
    where e.matrix_id = m.id and e.edit_no = m.current_edit
    group by r.requirement_code having count(*) > 1)
    or exists (select 1 from public.role_requirements e join public.requirements r on r.id = e.requirement_id
      where e.matrix_id = m.id and e.edit_no = m.current_edit
      group by lower(regexp_replace(trim(r.statement), '\s+', ' ', 'g')) having count(*) > 1) then
    raise exception 'RRM_DUPLICATE_REQUIREMENT' using errcode = '22023';
  end if;
  if exists (select 1 from public.requirement_dependencies d
    join public.role_requirements a on (a.matrix_id,a.edit_no,a.requirement_id) = (d.matrix_id,d.edit_no,d.dependent_id)
    join public.role_requirements b on (b.matrix_id,b.edit_no,b.requirement_id) = (d.matrix_id,d.edit_no,d.prerequisite_id)
    where d.matrix_id = m.id and d.edit_no = m.current_edit and b.sequence >= a.sequence) then
    -- Strictly increasing sequence on every edge proves acyclicity, including deep graphs.
    raise exception 'RRM_DEPENDENCY_CYCLE_OR_ORDER' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements e where e.matrix_id = m.id and e.edit_no = m.current_edit
    and (not exists (select 1 from public.requirement_sources where requirement_id = e.requirement_id)
      or not exists (select 1 from public.requirement_applicability where requirement_id = e.requirement_id and (role_id is null or role_id = m.role_id))
      or exists (select 1 from public.requirement_applicability a where a.requirement_id = e.requirement_id and
        ((a.role_id is not null and not exists (select 1 from public.roles x where x.id = a.role_id and x.status = 'ACTIVE'))
          or (a.department_id is not null and not exists (select 1 from public.departments x where x.id = a.department_id and x.status = 'ACTIVE')))))) then
    raise exception 'RRM_INVALID_REQUIREMENT_SCOPE' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements e where e.matrix_id = m.id and e.edit_no = m.current_edit and e.exception_to is not null
    and (exists (select 1 from public.requirement_applicability a where a.requirement_id = e.requirement_id and a.role_id is distinct from m.role_id)
      or not exists (select 1 from public.role_requirements target where target.matrix_id = m.id and target.edit_no = m.current_edit
        and target.requirement_id = e.exception_to and target.exception_to is null))) then
    raise exception 'RRM_INVALID_ROLE_EXCEPTION' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements e join public.requirement_applicability a on a.requirement_id = e.requirement_id
    where e.matrix_id = m.id and e.edit_no = m.current_edit and e.exception_to is not null and not exists
      (select 1 from public.requirement_applicability base where base.requirement_id = e.exception_to and base.role_id is null
       and (base.department_id is null or base.department_id = a.department_id)
       and (base.location_code is null or base.location_code = a.location_code)
       and (base.experience is null or base.experience = a.experience))) then
    raise exception 'RRM_EXCEPTION_SCOPE_NOT_SUBSET' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements a join public.role_requirements b
    on b.matrix_id = a.matrix_id and b.edit_no = a.edit_no and b.exception_to = a.exception_to and b.requirement_id > a.requirement_id
    join public.requirement_applicability sa on sa.requirement_id = a.requirement_id
    join public.requirement_applicability sb on sb.requirement_id = b.requirement_id
    where a.matrix_id = m.id and a.edit_no = m.current_edit and a.exception_to is not null
      and (sa.department_id is null or sb.department_id is null or sa.department_id = sb.department_id)
      and (sa.location_code is null or sb.location_code is null or sa.location_code = sb.location_code)
      and (sa.experience is null or sb.experience is null or sa.experience = sb.experience)) then
    raise exception 'RRM_OVERLAPPING_EXCEPTIONS_MANUAL_REVIEW' using errcode = '22023';
  end if;
  if exists (select 1 from public.role_requirements e
    join public.requirement_sources s on s.requirement_id = e.requirement_id
    join public.document_chunks c on c.id = s.chunk_id
    join public.document_versions v on v.id = c.document_version_id
    join public.documents d on d.id = v.document_id
    where e.matrix_id = m.id and e.edit_no = m.current_edit and
      (d.status <> 'ACTIVE' or v.parse_status <> 'PARSED' or v.review_status <> 'APPROVED'
       or v.effective_date > rrm_private.utc_today() or (v.expiry_date is not null and v.expiry_date < rrm_private.utc_today())
       or c.text_hash <> encode(sha256(convert_to(c.content,'UTF8')),'hex')
       or not exists (select 1 from public.rrm_document_authorities a where a.config_id = m.config_id and a.document_id = d.id))) then
    raise exception 'RRM_INVALID_OR_STALE_SOURCE' using errcode = '22023';
  end if;
  for v_requirement in select requirement_id from public.role_requirements where matrix_id = m.id and edit_no = m.current_edit loop
    perform rrm_private.valid_timing(v_requirement);
    perform rrm_private.valid_downgrade(m.id,m.current_edit,v_requirement);
  end loop;
end $$;

create function rrm_private.lock_sources(p_matrix uuid) returns void
language plpgsql set search_path = '' as $$
begin
  -- Phase 2 supersession must lock the document before updating its approved version.
  -- Lock documents first. Do not lock a submitted version that Phase 2 may be approving.
  perform 1 from public.documents d where d.id in
    (select v.document_id from public.role_requirement_matrices m
     join public.role_requirements e on e.matrix_id = m.id and e.edit_no = m.current_edit
     join public.requirement_sources s on s.requirement_id = e.requirement_id
     join public.document_chunks c on c.id = s.chunk_id join public.document_versions v on v.id = c.document_version_id
     where m.id = p_matrix) order by d.id for share;
  perform rrm_private.assert_matrix(p_matrix);
end $$;

create function rrm_private.matrix_snapshot(p_matrix uuid) returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object('schema_version','rrm-db-1','matrix_id',m.id,'role_id',m.role_id,'revision',m.revision,'edit',m.current_edit,
    'config',jsonb_build_object('id',cfg.id,'ranks',cfg.ranks,'documents',
      (select coalesce(jsonb_agg(to_jsonb(a) order by a.document_id),'[]') from public.rrm_document_authorities a where a.config_id = cfg.id)),
    'entries',(select coalesce(jsonb_agg(jsonb_build_object('entry',to_jsonb(e),'requirement',
      to_jsonb(r) || jsonb_build_object('created_at',rrm_private.utc_timestamp(r.created_at)),
      'scopes',(select jsonb_agg(to_jsonb(a) order by a.ordinal) from public.requirement_applicability a where a.requirement_id = r.id),
      'stage',(select to_jsonb(st) || jsonb_build_object('created_at',rrm_private.utc_timestamp(st.created_at))
        from public.onboarding_stage_definitions st where st.id = e.stage_id),
      'sources',(select jsonb_agg(jsonb_build_object('chunk',
        to_jsonb(c) || jsonb_build_object('created_at',rrm_private.utc_timestamp(c.created_at)),
        'document_id',d.id,'document_status',d.status,
        'version_id',v.id,'sha256',v.sha256,'review_status',v.review_status,'parse_status',v.parse_status,
        'effective_date',v.effective_date,'expiry_date',v.expiry_date,'approved_at',rrm_private.utc_timestamp(v.approved_at)) order by c.id)
        from public.requirement_sources s join public.document_chunks c on c.id = s.chunk_id
        join public.document_versions v on v.id = c.document_version_id join public.documents d on d.id = v.document_id where s.requirement_id = r.id)
      ) order by e.requirement_id),'[]') from public.role_requirements e join public.requirements r on r.id = e.requirement_id
      where e.matrix_id = m.id and e.edit_no = m.current_edit),
    'dependencies',(select coalesce(jsonb_agg(to_jsonb(x) order by x.dependent_id,x.prerequisite_id),'[]') from public.requirement_dependencies x
      where x.matrix_id = m.id and x.edit_no = m.current_edit),
    'issues',(select coalesce(jsonb_agg(jsonb_build_object('issue',
      to_jsonb(i) || jsonb_build_object('created_at',rrm_private.utc_timestamp(i.created_at)),
      'resolution',to_jsonb(r) || jsonb_build_object('resolved_at',rrm_private.utc_timestamp(r.resolved_at))) order by i.id),'[]')
      from public.rrm_issues i join public.rrm_issue_resolutions r on r.issue_id = i.id and r.edit_no = m.current_edit where i.matrix_id = m.id))
  from public.role_requirement_matrices m join public.rrm_precedence_configs cfg on cfg.id = m.config_id where m.id = p_matrix
$$;

create function public.transition_rrm_matrix(p_matrix uuid,p_expected_version integer,p_action text,
  p_reason text default null,p_admin_override boolean default false) returns text
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid; m public.role_requirement_matrices%rowtype; v_role uuid; v_snapshot jsonb; v_hash text; v_own boolean; v_prior uuid;
begin
  -- Role lock serializes approvals for a role; take it before the matrix lock in every transition.
  v_actor := rrm_private.actor(p_action = 'SUBMIT',p_action in ('APPROVE','REJECT'));
  select role_id into strict v_role from public.role_requirement_matrices where id = p_matrix;
  perform 1 from public.roles where id = v_role for update;
  select * into strict m from public.role_requirement_matrices where id = p_matrix for update;
  if p_expected_version is distinct from m.lock_version then raise exception 'RRM_EDIT_CONFLICT' using errcode = '40001'; end if;
  if p_admin_override is null or p_action is null or p_action not in ('SUBMIT','APPROVE','REJECT') then
    raise exception 'RRM_INVALID_ACTION' using errcode = '22023';
  end if;
  if p_reason is not null and not rrm_private.meaningful_reason(p_reason) then
    raise exception 'RRM_REASON_REQUIRED' using errcode = '22023';
  end if;
  if p_action = 'SUBMIT' then
    if m.status <> 'DRAFT' or m.created_by <> v_actor or p_admin_override then raise exception 'RRM_TRANSITION_FORBIDDEN' using errcode = '42501'; end if;
  else
    if m.status <> 'SUBMITTED' then raise exception 'RRM_STATE_CONFLICT' using errcode = '22023'; end if;
    v_own := rrm_private.contributed(p_matrix,v_actor);
    if (v_own and not (public.has_app_role('ADMIN') and p_admin_override))
       or (p_admin_override and (not v_own or not public.has_app_role('ADMIN'))) then
      raise exception 'RRM_SELF_REVIEW_FORBIDDEN' using errcode = '42501';
    end if;
    if (v_own or p_action = 'REJECT') and not rrm_private.meaningful_reason(p_reason) then
      raise exception 'RRM_REASON_REQUIRED' using errcode = '22023';
    end if;
  end if;
  if p_action <> 'REJECT' then
    perform rrm_private.lock_sources(p_matrix);
    v_snapshot := rrm_private.matrix_snapshot(p_matrix); v_hash := rrm_private.content_hash(v_snapshot);
  end if;
  if p_action = 'SUBMIT' then
    update public.role_requirement_matrices set status = 'SUBMITTED',submitted_by = v_actor,submitted_at = now(),
      submitted_snapshot = v_snapshot,snapshot_hash = v_hash,lock_version = lock_version + 1 where id = m.id;
  elsif p_action = 'APPROVE' then
    if v_hash is distinct from m.snapshot_hash then raise exception 'RRM_STALE_SUBMISSION' using errcode = '40001'; end if;
    if exists (select 1 from public.role_requirement_matrices where role_id = m.role_id and status = 'APPROVED' and revision >= m.revision) then
      raise exception 'RRM_STALE_REVISION' using errcode = '40001';
    end if;
    for v_prior in select id from public.role_requirement_matrices where role_id = m.role_id and status = 'APPROVED' loop
      perform rrm_private.audit('RRM_SUPERSEDED',v_prior,p_reason,jsonb_build_object('successor',m.id,'actor',v_actor));
    end loop;
    update public.role_requirement_matrices set status = 'SUPERSEDED',lock_version = lock_version + 1
      where role_id = m.role_id and status = 'APPROVED';
    update public.role_requirement_matrices set status = 'APPROVED',decided_by = v_actor,decided_at = now(),
      decision_reason = p_reason,admin_override = p_admin_override,lock_version = lock_version + 1 where id = m.id;
  else
    update public.role_requirement_matrices set status = 'REJECTED',decided_by = v_actor,decided_at = now(),
      decision_reason = p_reason,admin_override = p_admin_override,lock_version = lock_version + 1 where id = m.id;
  end if;
  perform rrm_private.audit('RRM_' || p_action,m.id,p_reason,jsonb_build_object('creator',m.created_by,'submitter',
    case when p_action = 'SUBMIT' then v_actor else m.submitted_by end,'actor',v_actor,'admin_override',p_admin_override,
    'before_status',m.status,'snapshot_hash',coalesce(v_hash,m.snapshot_hash),
    'downgrade_decisions',(select coalesce(jsonb_agg(jsonb_build_object('requirement_id',e.requirement_id,
      'exception_to',e.exception_to,'justification',e.downgrade_justification,'evidence',e.downgrade_evidence)
      order by e.requirement_id),'[]') from public.role_requirements e
      where e.matrix_id = m.id and e.edit_no = m.current_edit and e.downgrade_requested)));
  return case p_action when 'SUBMIT' then 'SUBMITTED' when 'APPROVE' then 'APPROVED' else 'REJECTED' end;
end $$;

create function public.get_rrm_ground_truth(p_matrix uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_actor uuid := rrm_private.actor(true,true); m public.role_requirement_matrices%rowtype; v_payload jsonb; v_role uuid;
begin
  select role_id into strict v_role from public.role_requirement_matrices where id = p_matrix;
  perform 1 from public.roles where id = v_role for share;
  select * into strict m from public.role_requirement_matrices where id = p_matrix for share;
  if m.status <> 'APPROVED' then raise exception 'RRM_NOT_APPROVED' using errcode = '22023'; end if;
  perform rrm_private.lock_sources(p_matrix);
  v_payload := rrm_private.matrix_snapshot(p_matrix);
  if rrm_private.content_hash(v_payload) is distinct from m.snapshot_hash then
    raise exception 'RRM_STALE_SNAPSHOT' using errcode = '40001';
  end if;
  return jsonb_build_object('matrix_id',m.id,'snapshot_hash',m.snapshot_hash,'snapshot',v_payload);
end $$;

-- All new table access is explicit. No service-role expansion; no existing grants changed.
do $$
declare v_table text; v_function record;
begin
  foreach v_table in array array['rrm_precedence_configs','rrm_document_authorities','onboarding_stage_definitions',
    'requirements','requirement_sources','requirement_applicability','role_requirement_matrices','rrm_matrix_edits',
    'role_requirements','requirement_dependencies','rrm_issues','rrm_issue_resolutions'] loop
    execute format('alter table public.%I enable row level security',v_table);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',v_table);
    execute format('grant select on public.%I to authenticated',v_table);
    execute format('create policy rrm_read on public.%I for select to authenticated using (public.has_app_role(''ADMIN'') or public.has_app_role(''TRAINING_MANAGER'') or public.has_app_role(''REVIEWER''))',v_table);
    if v_table <> 'role_requirement_matrices' then
      execute format('create trigger rrm_immutable before update or delete on public.%I for each row execute function rrm_private.immutable_row()',v_table);
    else
      execute format('create trigger rrm_no_delete before delete on public.%I for each row execute function rrm_private.immutable_row()',v_table);
    end if;
  end loop;
  for v_function in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'rrm_private' or (n.nspname = 'public' and p.proname = any(array[
      'create_rrm_precedence_config','create_rrm_stage','create_requirement_candidate','create_rrm_matrix','edit_rrm_matrix',
      'raise_rrm_issue','resolve_rrm_issue','transition_rrm_matrix','get_rrm_ground_truth'])) loop
    execute format('revoke all on function %s from public,anon,authenticated,service_role',v_function.signature);
  end loop;
end $$;
grant execute on function public.create_rrm_precedence_config(jsonb,jsonb,text,uuid),
  public.create_rrm_stage(text,text,integer,integer,integer,uuid), public.create_requirement_candidate(jsonb,uuid),
  public.create_rrm_matrix(uuid,uuid,uuid),public.edit_rrm_matrix(uuid,integer,jsonb,jsonb,text),
  public.raise_rrm_issue(uuid,integer,text,text,uuid,uuid),public.resolve_rrm_issue(uuid,integer,text,boolean),
  public.transition_rrm_matrix(uuid,integer,text,text,boolean),public.get_rrm_ground_truth(uuid) to authenticated;
commit;
