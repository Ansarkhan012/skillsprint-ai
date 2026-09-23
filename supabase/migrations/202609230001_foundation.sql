-- Phase 1 only. Single fictional organization; no tenant discriminator.
create extension if not exists pgcrypto;

create type public.app_role as enum ('ADMIN', 'TRAINING_MANAGER', 'REVIEWER', 'MANAGER', 'EMPLOYEE');
create type public.profile_status as enum ('ACTIVE', 'INACTIVE');
create type public.record_status as enum ('ACTIVE', 'ARCHIVED');
create type public.experience_level as enum ('BEGINNER', 'INTERMEDIATE', 'ADVANCED');

create table public.profiles (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique references auth.users(id) on delete restrict,
  display_name text not null check (length(trim(display_name)) between 1 and 160),
  status public.profile_status not null default 'ACTIVE',
  last_login_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.profile_roles (
  profile_id uuid not null references public.profiles(id) on delete cascade,
  role public.app_role not null,
  created_at timestamptz not null default now(),
  primary key (profile_id, role)
);
create index profile_roles_role_idx on public.profile_roles(role);

create table public.departments (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code ~ '^[A-Z0-9_-]{2,32}$'),
  name text not null check (length(trim(name)) between 1 and 160),
  parent_id uuid references public.departments(id) on delete restrict,
  status public.record_status not null default 'ACTIVE',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (parent_id is distinct from id)
);
create index departments_parent_idx on public.departments(parent_id);

create table public.roles (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code ~ '^[A-Z0-9_-]{2,32}$'),
  name text not null check (length(trim(name)) between 1 and 160),
  description text,
  department_id uuid references public.departments(id) on delete restrict,
  status public.record_status not null default 'ACTIVE',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index roles_department_idx on public.roles(department_id);

create table public.employees (
  id uuid primary key default gen_random_uuid(),
  employee_code text not null unique check (length(trim(employee_code)) between 1 and 40),
  profile_id uuid unique references public.profiles(id) on delete set null,
  role_id uuid not null references public.roles(id) on delete restrict,
  department_id uuid not null references public.departments(id) on delete restrict,
  experience_level public.experience_level not null default 'BEGINNER',
  location_code text,
  joining_date date not null,
  manager_employee_id uuid references public.employees(id) on delete set null,
  required_competencies jsonb not null default '[]'::jsonb,
  previous_experience_summary text,
  training_status text not null default 'NOT_STARTED',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (manager_employee_id is distinct from id)
);
create index employees_role_idx on public.employees(role_id);
create index employees_department_idx on public.employees(department_id);
create index employees_manager_idx on public.employees(manager_employee_id);

create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_profile_id uuid references public.profiles(id) on delete set null,
  service_actor text,
  action text not null,
  target_type text not null,
  target_id uuid,
  correlation_id uuid,
  reason text,
  before_hash text,
  after_hash text,
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);
create index audit_logs_occurred_idx on public.audit_logs(occurred_at desc);
create index audit_logs_target_idx on public.audit_logs(target_type, target_id);
create index audit_logs_actor_idx on public.audit_logs(actor_profile_id, occurred_at desc);

create function public.current_profile_id() returns uuid
language sql stable security definer set search_path = '' as $$
  select id from public.profiles where auth_user_id = (select auth.uid()) and status = 'ACTIVE' limit 1
$$;

create function public.current_employee_id() returns uuid
language sql stable security definer set search_path = '' as $$
  select id from public.employees where profile_id = public.current_profile_id() limit 1
$$;

create function public.has_app_role(required_role public.app_role) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.profile_roles pr
    join public.profiles p on p.id = pr.profile_id
    where p.auth_user_id = (select auth.uid()) and p.status = 'ACTIVE' and pr.role = required_role
  )
$$;

revoke all on function public.current_profile_id() from public, anon;
revoke all on function public.current_employee_id() from public, anon;
revoke all on function public.has_app_role(public.app_role) from public, anon;
grant execute on function public.current_profile_id() to authenticated;
grant execute on function public.current_employee_id() to authenticated;
grant execute on function public.has_app_role(public.app_role) to authenticated;

create function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

create function public.audit_foundation_change() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  target uuid;
  audit_meta jsonb;
begin
  if tg_table_name = 'profile_roles' then
    target := case when tg_op = 'DELETE' then old.profile_id else new.profile_id end;
    if tg_op = 'DELETE' then
      audit_meta := jsonb_build_object('operation', tg_op, 'role', old.role);
    else
      audit_meta := jsonb_build_object('operation', tg_op, 'role', new.role);
    end if;
  else
    target := case when tg_op = 'DELETE' then old.id else new.id end;
    audit_meta := jsonb_build_object('operation', tg_op);
  end if;
  insert into public.audit_logs(actor_profile_id, service_actor, action, target_type, target_id, metadata)
  values (
    public.current_profile_id(),
    case when (select auth.uid()) is null then 'migration_or_service' else null end,
    tg_op, tg_table_name, target,
    audit_meta
  );
  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end $$;
revoke all on function public.audit_foundation_change() from public, anon;
revoke all on function public.touch_updated_at() from public, anon;

create trigger profiles_touch before update on public.profiles for each row execute function public.touch_updated_at();
create trigger departments_touch before update on public.departments for each row execute function public.touch_updated_at();
create trigger roles_touch before update on public.roles for each row execute function public.touch_updated_at();
create trigger employees_touch before update on public.employees for each row execute function public.touch_updated_at();
create trigger profiles_audit after insert or update or delete on public.profiles for each row execute function public.audit_foundation_change();
create trigger profile_roles_audit after insert or update or delete on public.profile_roles for each row execute function public.audit_foundation_change();
create trigger departments_audit after insert or update or delete on public.departments for each row execute function public.audit_foundation_change();
create trigger roles_audit after insert or update or delete on public.roles for each row execute function public.audit_foundation_change();
create trigger employees_audit after insert or update or delete on public.employees for each row execute function public.audit_foundation_change();

alter table public.profiles enable row level security;
alter table public.profile_roles enable row level security;
alter table public.departments enable row level security;
alter table public.roles enable row level security;
alter table public.employees enable row level security;
alter table public.audit_logs enable row level security;

create policy profiles_read on public.profiles for select to authenticated
using (id = public.current_profile_id() or public.has_app_role('ADMIN'));
create policy profiles_admin_write on public.profiles for all to authenticated
using (public.has_app_role('ADMIN')) with check (public.has_app_role('ADMIN'));

create policy profile_roles_read on public.profile_roles for select to authenticated
using (profile_id = public.current_profile_id() or public.has_app_role('ADMIN'));
create policy profile_roles_admin_write on public.profile_roles for all to authenticated
using (public.has_app_role('ADMIN')) with check (public.has_app_role('ADMIN'));

create policy departments_read on public.departments for select to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER') or public.has_app_role('MANAGER'));
create policy departments_write on public.departments for all to authenticated
using (public.has_app_role('ADMIN')) with check (public.has_app_role('ADMIN'));

create policy roles_read on public.roles for select to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER') or public.has_app_role('MANAGER'));
create policy roles_write on public.roles for all to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER'))
with check (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER'));

create policy employees_read on public.employees for select to authenticated
using (
  public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER') or public.has_app_role('REVIEWER')
  or profile_id = public.current_profile_id()
  or (public.has_app_role('MANAGER') and manager_employee_id = public.current_employee_id())
);
create policy employees_write on public.employees for all to authenticated
using (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER'))
with check (public.has_app_role('ADMIN') or public.has_app_role('TRAINING_MANAGER'));

create policy audit_logs_admin_read on public.audit_logs for select to authenticated
using (public.has_app_role('ADMIN'));

revoke all on public.profiles, public.profile_roles, public.departments, public.roles, public.employees, public.audit_logs from anon, public;
revoke all on public.audit_logs from authenticated;
grant select on public.audit_logs to authenticated;
grant select on public.profiles, public.profile_roles, public.departments, public.roles, public.employees to authenticated;
grant insert, update, delete on public.profiles, public.profile_roles, public.departments, public.roles, public.employees to authenticated;

-- Bootstrap the first Admin using the Supabase SQL editor after creating an Auth user.
-- No default users, credentials, or fictional audit history are inserted here.
