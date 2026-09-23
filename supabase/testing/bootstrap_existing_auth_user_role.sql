-- MANUAL TEST SETUP ONLY. Review and run in the Supabase SQL Editor.
-- Do not run as a migration or from the application. No Auth user is created here.
-- Replace the three NULL values below before running. The Auth user must already exist.
-- Use a distinct test Auth user for each role. This script refuses an existing profile.

begin;

do $$
declare
  v_auth_user_id uuid := null; -- Replace with 'EXISTING_AUTH_USER_UUID'::uuid.
  v_display_name text := null; -- Replace with a quoted, non-sensitive test display name.
  v_role public.app_role := null; -- Replace with one of the four roles listed below.
  v_profile_id uuid;
begin
  if v_auth_user_id is null or v_display_name is null or v_role is null then
    raise exception 'Set auth user UUID, display name, and test role explicitly';
  end if;
  if length(trim(v_display_name)) not between 1 and 160 then
    raise exception 'Display name must be 1 to 160 characters';
  end if;
  if v_role not in ('TRAINING_MANAGER', 'REVIEWER', 'MANAGER', 'EMPLOYEE') then
    raise exception 'Only non-Admin Phase 1 test roles are allowed';
  end if;
  if not exists (select 1 from auth.users where id = v_auth_user_id) then
    raise exception 'Auth user does not exist';
  end if;
  if exists (select 1 from public.profiles where auth_user_id = v_auth_user_id) then
    raise exception 'Auth user already has a profile; no roles were changed';
  end if;

  insert into public.profiles (auth_user_id, display_name, status)
  values (v_auth_user_id, trim(v_display_name), 'ACTIVE')
  returning id into v_profile_id;

  insert into public.profile_roles (profile_id, role)
  values (v_profile_id, v_role);

  if (select count(*) from public.profile_roles where profile_id = v_profile_id) <> 1 then
    raise exception 'Expected exactly one assigned application role';
  end if;
end $$;

commit;
