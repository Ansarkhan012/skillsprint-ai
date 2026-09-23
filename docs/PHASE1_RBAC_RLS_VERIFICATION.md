# Phase 1 RBAC and RLS verification

This is a controlled **manual live test plan**, not evidence that the live checks have passed. The Admin login, `/api/v1/me`, and dashboard were reported as verified by the project owner. No live test below is claimed as completed by this document.

## Test-user bootstrap

1. Create each non-Admin test user manually in Supabase Auth. Do not place passwords, tokens, or keys in this repository or in chat. A usable password-login account must be confirmed/enabled as required by the project's Auth settings.
2. Review `supabase/testing/bootstrap_existing_auth_user_role.sql`. In a private SQL Editor copy, replace all three `NULL` assignments with the existing Auth user UUID, a non-sensitive display name, and exactly one of `TRAINING_MANAGER`, `REVIEWER`, `MANAGER`, or `EMPLOYEE` cast to `public.app_role`.
3. Execute the reviewed copy **once per distinct Auth user**, manually in the trusted SQL Editor. It aborts on missing input, a nonexistent Auth user, an existing profile, or an out-of-scope role. It inserts one ACTIVE profile and one membership in a transaction. It does not create an Auth user or an employee row.
4. Inspect `profiles` and `profile_roles` in the SQL Editor after bootstrap. The SQL Editor is privileged and bypasses normal user RLS: never treat its results as RLS evidence. Do not rerun the template for an existing profile.

## Current protected API matrix

`200` means an authorized read/check; `201` means an authorized create with a valid, unique payload and required references. `403` means the route's role check denies access. Every row also requires an ACTIVE profile with at least one role; otherwise it fails closed. `GET /api/v1/health` is public and is not in this protected-endpoint matrix.

| Method and route | ADMIN | TRAINING_MANAGER | REVIEWER | MANAGER | EMPLOYEE |
|---|---:|---:|---:|---:|---:|
| `GET /api/v1/me` | 200 | 200 | 200 | 200 | 200 |
| `GET /api/v1/admin/check` | 200 | 403 | 403 | 403 | 403 |
| `GET /api/v1/departments` | 200 | 200 | 200 | 200 | 403 |
| `GET /api/v1/roles` | 200 | 200 | 200 | 200 | 403 |
| `GET /api/v1/employees` | 200 | 200 | 200 | 200 | 403 |
| `POST /api/v1/departments` | 201 | 403 | 403 | 403 | 403 |
| `POST /api/v1/roles` | 201 | 201 | 403 | 403 | 403 |
| `POST /api/v1/employees` | 201 | 201 | 403 | 403 | 403 |

For authenticated directory reads, `200` does **not** imply all rows are visible: RLS filters the result. For authorized creates, an invalid payload/reference can produce `422`, a duplicate `409`, or another data-service error; use disposable, valid test data only when verifying `201`. No Phase 1 update/delete API route exists. For every protected route, a missing token should give `401`; an authenticated user with missing/inactive/roleless profile should give `403` before the route runs.

## Current table-level RLS expectations

Test with each user's normal Supabase session (public client key plus that user's access token), **not** the SQL Editor, service role, or a privileged client. Authenticated has explicit table grants, but the following RLS policies restrict actual rows and writes. An RLS-denied `SELECT` may return an empty result rather than `403`.

| Table | ADMIN | TRAINING_MANAGER | REVIEWER | MANAGER | EMPLOYEE |
|---|---|---|---|---|---|
| `profiles` | Read/write all | Read own only | Read own only | Read own only | Read own only |
| `profile_roles` | Read/write all | Read own only | Read own only | Read own only | Read own only |
| `departments` | Read/write all | Read all; no write | Read all; no write | Read all; no write | No rows; no write |
| `roles` | Read/write all | Read/write all | Read all; no write | Read all; no write | No rows; no write |
| `employees` | Read/write all | Read/write all | Read all; no write | Read own linked row and direct reports; no write | Read own linked row only; no write |
| `audit_logs` | Read all; no direct write | No rows; no direct write | No rows; no direct write | No rows; no direct write | No rows; no direct write |

The Admin-only `audit_logs` read policy does not grant direct insert/update/delete to anyone using an authenticated client. Foundation-table triggers create audit events through the trusted function. No Phase 1 API endpoint exposes audit-log reads yet.

## Manual live checklist — record pass/fail separately

- [ ] Prepare distinct non-sensitive department/role and employee fixtures with Admin-authorized means. For Manager scope, link the Manager's own `employees.profile_id` to their profile, set one other row's `manager_employee_id` to that manager employee ID, and leave a third row unrelated. For Employee scope, link one employee row to the Employee profile and keep an unrelated row. A profile alone does not create an employee row. Record fixture IDs privately; a zero-row result without an unrelated fixture proves nothing.
- [ ] For each of the four test accounts, sign in and confirm `/api/v1/me` returns `200` with only the intended role. Verify Admin-only `/api/v1/admin/check` returns `403` for all four, especially Training Manager.
- [ ] Exercise each protected API route against the matrix. Use valid disposable payloads for allowed POSTs, and inspect resulting audit events as Admin. Do not run writes against production business records. A denied POST must leave no row or audit event.
- [ ] As Employee, query `employees` with own and unrelated IDs: own linked row may be visible; arbitrary other employee rows must not be visible. The Employee API directory endpoint itself returns `403`.
- [ ] As Manager, query own employee row, direct-report row, and unrelated row through a user-scoped Supabase client: only own and direct-report rows may be visible. `GET /api/v1/employees` should contain that same subset, not arbitrary employees.
- [ ] As Reviewer, verify directory reads (`departments`, `roles`, and all `employees`) and denied writes. Reviewer has no approval endpoint in Phase 1 and must not gain mutation access by calling Supabase directly.
- [ ] As Training Manager, verify allowed role/employee creates, denied department create, denied Admin check, denied other users' `profiles`/`profile_roles` reads or writes, and no ability to insert an ADMIN membership for self.
- [ ] As each non-Admin, verify `audit_logs` returns no rows and direct insert/update/delete is denied; verify only Admin can read audit events.
- [ ] Try a direct authenticated `profile_roles` insert/update for self-promotion as each non-Admin; it must be denied by RLS. Verify no ADMIN membership was created. Admin bootstrap in the SQL Editor is not a client-side permission test.
- [ ] With a separate disposable account lacking a profile, and then one with an INACTIVE profile, verify protected API calls fail closed (`403`) and the protected application does not open the dashboard. Do not deactivate the working Admin account. A roleless ACTIVE profile should also fail closed.
- [ ] Check an unauthorized deep link and a direct API call, not just a hidden sidebar item. Navigation visibility is presentation only; backend role checks and RLS are the authorization boundaries.

Do not publish access tokens or credentials in test reports. Record only the role, route/table, expected result, observed status/row visibility, and pass/fail. Clean up disposable fixtures through a reviewed, separately authorized manual process after testing; this document does not run cleanup.

## Repeated `/api/v1/me` during development

The protected layout calls `/api/v1/me` once per render. A `[section]` page calls it again after the layout to enforce section access, so visiting a section can cause a genuine duplicate application call. The dashboard page itself calls only `/api/v1/health`; it does **not** make a second `/me` call. Repeated `/me` entries while opening the dashboard are therefore consistent with additional Next.js development renders, prefetches, or navigations, not a duplicate in the dashboard component. No optimization was made because the reported dashboard repetition alone does not establish an implementation bug. For a section route, the two-call path is known and could be revisited separately if it becomes material.
