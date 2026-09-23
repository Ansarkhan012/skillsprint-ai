-- Phase 2 only. Review before manual application; never run from application startup.
create type public.document_parse_status as enum ('UPLOADED', 'PROCESSING', 'PARSED', 'NEEDS_REVIEW', 'FAILED');
create type public.document_review_status as enum ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'SUPERSEDED');

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  document_code text not null unique check (document_code ~ '^[A-Z0-9_-]{2,64}$'),
  title text not null check (length(trim(title)) between 1 and 240),
  category text not null check (length(trim(category)) between 1 and 100),
  department_id uuid references public.departments(id) on delete restrict,
  status public.record_status not null default 'ACTIVE',
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index documents_department_idx on public.documents(department_id);
create index documents_category_idx on public.documents(category);

create table public.document_versions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete restrict,
  version_label text not null check (length(trim(version_label)) between 1 and 64),
  effective_date date not null,
  expiry_date date,
  original_filename text not null check (length(original_filename) between 1 and 240
    and original_filename !~ '[[:cntrl:]/]' and position(chr(92) in original_filename) = 0),
  mime_type text not null check (mime_type in ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
  size_bytes integer not null check (size_bytes > 0 and size_bytes <= 15728640),
  storage_path text not null unique,
  sha256 text not null unique check (sha256 ~ '^[0-9a-f]{64}$'),
  parse_status public.document_parse_status not null default 'UPLOADED',
  parse_error_code text,
  review_status public.document_review_status not null default 'DRAFT',
  parser_version text,
  uploaded_by uuid not null references public.profiles(id) on delete restrict,
  submitted_by uuid references public.profiles(id) on delete restrict,
  submitted_at timestamptz,
  approved_by uuid references public.profiles(id) on delete restrict,
  approved_at timestamptz,
  rejected_by uuid references public.profiles(id) on delete restrict,
  rejected_at timestamptz,
  decision_reason text,
  admin_override boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (document_id, version_label),
  check (expiry_date is null or expiry_date >= effective_date),
  check (parse_status = 'PARSED' or review_status <> 'APPROVED'),
  check (not admin_override or length(trim(coalesce(decision_reason, ''))) > 0),
  check (storage_path = document_id::text || '/' || id::text || case when mime_type = 'application/pdf' then '.pdf' else '.docx' end)
);
create unique index document_versions_one_approved_idx on public.document_versions(document_id) where review_status = 'APPROVED';
create index document_versions_document_idx on public.document_versions(document_id, created_at desc);
create index document_versions_review_idx on public.document_versions(review_status, parse_status);

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_version_id uuid not null references public.document_versions(id) on delete restrict,
  chunk_key text not null check (chunk_key ~ '^[0-9a-f]{64}$'),
  sequence integer not null check (sequence >= 0),
  content text not null check (length(trim(content)) > 0 and length(content) <= 10000),
  text_hash text not null check (text_hash ~ '^[0-9a-f]{64}$'),
  heading text check (length(heading) <= 240),
  section_path text check (length(section_path) <= 1000),
  source_location jsonb not null check (jsonb_typeof(source_location) = 'object'
    and pg_column_size(source_location) <= 8192),
  page_number integer check (page_number > 0),
  paragraph_start integer check (paragraph_start > 0),
  paragraph_end integer check (paragraph_end >= paragraph_start),
  char_start integer check (char_start >= 0),
  char_end integer check (char_end >= char_start),
  parser_version text not null,
  created_at timestamptz not null default now(),
  unique (document_version_id, chunk_key),
  unique (document_version_id, sequence)
);
create index document_chunks_version_idx on public.document_chunks(document_version_id, sequence);
create index document_chunks_search_idx on public.document_chunks using gin (to_tsvector('english', content));

create trigger documents_touch before update on public.documents for each row execute function public.touch_updated_at();
create trigger document_versions_touch before update on public.document_versions for each row execute function public.touch_updated_at();
create trigger documents_audit after insert or update on public.documents for each row execute function public.audit_foundation_change();

create function public.audit_document_version_change() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.audit_logs(actor_profile_id, service_actor, action, target_type, target_id, reason, metadata)
  values (public.current_profile_id(),
    case when (select auth.uid()) is null then 'migration_or_service' else null end,
    tg_op, 'document_versions', new.id, new.decision_reason,
    jsonb_build_object('review_status', new.review_status, 'parse_status', new.parse_status,
      'creator_profile_id', new.uploaded_by, 'approver_profile_id', new.approved_by,
      'admin_override', new.admin_override));
  return new;
end $$;
revoke all on function public.audit_document_version_change() from public, anon, authenticated;
create trigger document_versions_audit after insert or update on public.document_versions
for each row execute function public.audit_document_version_change();

alter table public.documents enable row level security;
alter table public.document_versions enable row level security;
alter table public.document_chunks enable row level security;
create policy documents_read on public.documents for select to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'));
create policy document_versions_read on public.document_versions for select to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'));
create policy document_chunks_read on public.document_chunks for select to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'));
revoke all on public.documents, public.document_versions, public.document_chunks from public, anon, authenticated;
grant select on public.documents, public.document_versions, public.document_chunks to authenticated;

-- One reusable current-effective rule; callers still see rows through invoker RLS.
create function public.current_effective_document_version(p_document_id uuid, p_on_date date default current_date)
returns setof public.document_versions language sql stable security invoker set search_path = '' as $$
  select v.* from public.document_versions v
  join public.documents d on d.id = v.document_id
  where v.document_id = p_document_id and d.status = 'ACTIVE'
    and v.review_status = 'APPROVED' and v.parse_status = 'PARSED'
    and v.effective_date <= p_on_date
    and (v.expiry_date is null or v.expiry_date >= p_on_date)
$$;
revoke all on function public.current_effective_document_version(uuid,date) from public, anon;
grant execute on function public.current_effective_document_version(uuid,date) to authenticated;

-- Authoring and review use the user's JWT; only trusted Python processing may finalize via service_role.
create function public.begin_document_upload(
  p_document_id uuid, p_document_code text, p_title text, p_category text, p_department_id uuid,
  p_version_id uuid, p_version_label text, p_effective_date date, p_expiry_date date,
  p_original_filename text, p_mime_type text, p_size_bytes integer, p_sha256 text
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_actor uuid := public.current_profile_id();
  v_document_id uuid := coalesce(p_document_id, gen_random_uuid());
  v_path text;
begin
  if v_actor is null or not (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER')) then
    raise exception 'DOCUMENT_FORBIDDEN' using errcode = '42501';
  end if;
  if p_version_id is null or p_document_code !~ '^[A-Z0-9_-]{2,64}$'
     or length(trim(coalesce(p_title, ''))) not between 1 and 240
     or length(trim(coalesce(p_category, ''))) not between 1 and 100
     or length(trim(coalesce(p_version_label, ''))) not between 1 and 64
     or p_effective_date is null or (p_expiry_date is not null and p_expiry_date < p_effective_date)
     or p_mime_type not in ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
     or p_size_bytes not between 1 and 15728640 or p_sha256 !~ '^[0-9a-f]{64}$'
     or length(coalesce(p_original_filename, '')) not between 1 and 240 then
    raise exception 'DOCUMENT_INVALID' using errcode = '22023';
  end if;
  if p_document_id is null then
    insert into public.documents(id, document_code, title, category, department_id, created_by)
    values (v_document_id, p_document_code, trim(p_title), trim(p_category), p_department_id, v_actor);
  elsif not exists (select 1 from public.documents d where d.id = p_document_id and d.status = 'ACTIVE'
    and d.document_code = p_document_code and d.title = trim(p_title)
    and d.category = trim(p_category) and d.department_id is not distinct from p_department_id) then
    raise exception 'DOCUMENT_METADATA_MISMATCH' using errcode = '22023';
  end if;
  v_path := v_document_id::text || '/' || p_version_id::text || case when p_mime_type = 'application/pdf' then '.pdf' else '.docx' end;
  insert into public.document_versions(id, document_id, version_label, effective_date, expiry_date,
    original_filename, mime_type, size_bytes, storage_path, sha256, uploaded_by)
  values (p_version_id, v_document_id, trim(p_version_label), p_effective_date, p_expiry_date,
    p_original_filename, p_mime_type, p_size_bytes, v_path, p_sha256, v_actor);
  return jsonb_build_object('document_id', v_document_id, 'version_id', p_version_id, 'storage_path', v_path);
end $$;

create function public.mark_document_processing(p_version_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare v_version public.document_versions%rowtype;
begin
  if not (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER')) then
    raise exception 'DOCUMENT_FORBIDDEN' using errcode = '42501';
  end if;
  select * into v_version from public.document_versions where id = p_version_id for update;
  if not found or v_version.uploaded_by <> public.current_profile_id()
    or v_version.parse_status <> 'UPLOADED' or v_version.review_status <> 'DRAFT'
    or not exists (select 1 from storage.objects o
      where o.bucket_id = 'company-documents' and o.name = v_version.storage_path) then
    raise exception 'DOCUMENT_STATE_CONFLICT' using errcode = '22023';
  end if;
  update public.document_versions set parse_status = 'PROCESSING' where id = p_version_id;
end $$;

create function public.finish_document_processing(p_version_id uuid, p_status public.document_parse_status,
  p_error_code text, p_chunks jsonb, p_parser_version text)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_version public.document_versions%rowtype;
  v_chunk jsonb;
begin
  if (select auth.role()) is distinct from 'service_role' then
    raise exception 'DOCUMENT_FORBIDDEN' using errcode = '42501';
  end if;
  select * into v_version from public.document_versions where id = p_version_id for update;
  if not found or v_version.review_status <> 'DRAFT'
     or (p_status = 'FAILED' and v_version.parse_status not in ('UPLOADED', 'PROCESSING'))
     or (p_status <> 'FAILED' and v_version.parse_status <> 'PROCESSING') then
    raise exception 'DOCUMENT_STATE_CONFLICT' using errcode = '22023';
  end if;
  if p_status <> 'FAILED' and not exists (select 1 from storage.objects o
    where o.bucket_id = 'company-documents' and o.name = v_version.storage_path) then
    raise exception 'DOCUMENT_STORAGE_MISSING' using errcode = '22023';
  end if;
  if p_status is null or p_chunks is null
     or p_status not in ('PARSED', 'NEEDS_REVIEW', 'FAILED') or jsonb_typeof(p_chunks) <> 'array'
     or jsonb_array_length(p_chunks) > 5000 or length(coalesce(p_parser_version, '')) not between 1 and 80
     or (p_status = 'PARSED' and jsonb_array_length(p_chunks) = 0)
     or (p_status <> 'PARSED' and length(trim(coalesce(p_error_code, ''))) = 0)
     or length(coalesce(p_error_code, '')) > 80 then
    raise exception 'DOCUMENT_INVALID' using errcode = '22023';
  end if;
  for v_chunk in select value from jsonb_array_elements(p_chunks) loop
    insert into public.document_chunks(document_version_id, chunk_key, sequence, content, text_hash,
      heading, section_path, source_location, page_number, paragraph_start, paragraph_end,
      char_start, char_end, parser_version)
    values (p_version_id, v_chunk->>'chunk_key', (v_chunk->>'sequence')::integer,
      v_chunk->>'content', v_chunk->>'text_hash', v_chunk->>'heading', v_chunk->>'section_path',
      coalesce(v_chunk->'source_location', '{}'::jsonb), (v_chunk->>'page_number')::integer,
      (v_chunk->>'paragraph_start')::integer, (v_chunk->>'paragraph_end')::integer,
      (v_chunk->>'char_start')::integer, (v_chunk->>'char_end')::integer, p_parser_version);
  end loop;
  update public.document_versions set parse_status = p_status, parse_error_code = p_error_code,
    parser_version = p_parser_version where id = p_version_id;
end $$;

create function public.submit_document_version(p_version_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare v_version public.document_versions%rowtype;
begin
  if not (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER')) then
    raise exception 'DOCUMENT_FORBIDDEN' using errcode = '42501';
  end if;
  select * into v_version from public.document_versions where id = p_version_id for update;
  if not found or v_version.review_status <> 'DRAFT' or v_version.parse_status <> 'PARSED'
    or (v_version.uploaded_by <> public.current_profile_id() and not public.has_app_role('ADMIN'))
    or not exists (select 1 from public.document_chunks where document_version_id = p_version_id) then
    raise exception 'DOCUMENT_STATE_CONFLICT' using errcode = '22023';
  end if;
  update public.document_versions set review_status = 'SUBMITTED', submitted_by = public.current_profile_id(),
    submitted_at = now() where id = p_version_id;
end $$;

create function public.decide_document_version(p_version_id uuid, p_approve boolean, p_reason text,
  p_admin_override boolean default false)
returns void language plpgsql security definer set search_path = '' as $$
declare
  v_version public.document_versions%rowtype;
  v_actor uuid := public.current_profile_id();
  v_override boolean;
begin
  if v_actor is null or not (public.has_app_role('ADMIN') or public.has_app_role('REVIEWER')) then
    raise exception 'DOCUMENT_FORBIDDEN' using errcode = '42501';
  end if;
  select * into v_version from public.document_versions where id = p_version_id for update;
  if not found or v_version.review_status <> 'SUBMITTED' then
    raise exception 'DOCUMENT_STATE_CONFLICT' using errcode = '22023';
  end if;
  if p_approve is null then
    raise exception 'DOCUMENT_INVALID_DECISION' using errcode = '22023';
  end if;
  v_override := v_version.uploaded_by = v_actor or v_version.submitted_by = v_actor;
  if v_override and (not public.has_app_role('ADMIN') or not p_admin_override) then
    raise exception 'DOCUMENT_SELF_REVIEW_FORBIDDEN' using errcode = '42501';
  end if;
  if p_admin_override and (not v_override or not public.has_app_role('ADMIN')) then
    raise exception 'DOCUMENT_INVALID_OVERRIDE' using errcode = '42501';
  end if;
  if (not p_approve or v_override) and length(trim(coalesce(p_reason, ''))) = 0 then
    raise exception 'DOCUMENT_REASON_REQUIRED' using errcode = '22023';
  end if;
  if p_approve then
    if v_version.parse_status <> 'PARSED' or v_version.effective_date > current_date
       or (v_version.expiry_date is not null and v_version.expiry_date < current_date) then
      raise exception 'DOCUMENT_NOT_EFFECTIVE' using errcode = '22023';
    end if;
    perform 1 from public.documents where id = v_version.document_id for update;
    update public.document_versions set review_status = 'SUPERSEDED'
      where document_id = v_version.document_id and review_status = 'APPROVED';
    update public.document_versions set review_status = 'APPROVED', approved_by = v_actor,
      approved_at = now(), decision_reason = nullif(trim(p_reason), ''), admin_override = v_override
      where id = p_version_id;
  else
    update public.document_versions set review_status = 'REJECTED', rejected_by = v_actor,
      rejected_at = now(), decision_reason = trim(p_reason), admin_override = v_override where id = p_version_id;
  end if;
end $$;

revoke all on function public.begin_document_upload(uuid,text,text,text,uuid,uuid,text,date,date,text,text,integer,text) from public, anon;
revoke all on function public.mark_document_processing(uuid) from public, anon;
revoke all on function public.finish_document_processing(uuid,public.document_parse_status,text,jsonb,text) from public, anon, authenticated;
revoke all on function public.submit_document_version(uuid) from public, anon;
revoke all on function public.decide_document_version(uuid,boolean,text,boolean) from public, anon;
grant execute on function public.begin_document_upload(uuid,text,text,text,uuid,uuid,text,date,date,text,text,integer,text) to authenticated;
grant execute on function public.mark_document_processing(uuid) to authenticated;
grant execute on function public.finish_document_processing(uuid,public.document_parse_status,text,jsonb,text) to service_role;
grant execute on function public.submit_document_version(uuid) to authenticated;
grant execute on function public.decide_document_version(uuid,boolean,text,boolean) to authenticated;

-- Storage paths are server-generated from immutable UUIDs, never from the submitted filename.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('company-documents', 'company-documents', false, 15728640,
  array['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']);

create function public.can_upload_document_object(p_path text) returns boolean
language sql stable security definer set search_path = '' as $$
  select (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER'))
    and exists (select 1 from public.document_versions v where v.storage_path = p_path
      and v.uploaded_by = public.current_profile_id() and v.parse_status = 'UPLOADED'
      and v.review_status = 'DRAFT')
$$;
revoke all on function public.can_upload_document_object(text) from public, anon;
grant execute on function public.can_upload_document_object(text) to authenticated;

create policy company_documents_insert on storage.objects for insert to authenticated
with check (bucket_id = 'company-documents' and public.can_upload_document_object(name));
create policy company_documents_read on storage.objects for select to authenticated
using (bucket_id = 'company-documents'
  and (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER'))
  and exists (select 1 from public.document_versions v where v.storage_path = name));
-- No update/delete policy: originals are immutable through user-scoped clients.
