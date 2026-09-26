# Phase 6 product experience

## Initial inventory (before implementation)

Authenticated routes: dashboard, documents, requirements, phase4d-test, and the
dynamic section routes plans, employees, departments, reports, audit, users,
settings. Eight surfaces (dashboard plus seven dynamic sections) contained
deferred workflow copy. The users route had no management API. The internal
phase4d-test route appeared in normal navigation.

Documents already supports upload, processing retry, version review, original
download, current-effective checks and paginated chunks. Requirements supports
candidates/revisions, evidence selection, draft edits, dependencies, review issues,
authority configuration, submission and independent approval. These are retained.
Authentication uses Supabase SSR sessions, FastAPI role checks and database RLS.
Existing forms use Input/Button/Badge and the mobile sidebar uses Radix Dialog.
Documents and Requirements have error boundaries; only Documents had loading UI.
Settings/account had sign-out only. No employee/department editing API exists.

## Integration boundaries

Product reads and writes use the authenticated same-origin gateway. Navigation
visibility never replaces API authorization. Generation and validation remain
separate explicit actions. Failed runs are history, never generated plans.
Human review adds a disposition without rewriting the JEV decision.
Internal Phase 4D tools and browser locks are retained outside normal navigation.

Small backend reads expose existing employee context, paginated validation
summaries and Admin audit events. No schema, provider, validator or JEV changes.
Directory lists remain bounded and report their page scope; reports do not infer
global totals from partial responses. Employee identity may be an employee code
when a readable linked profile is absent. No Auth user is created by these forms.

## Final route inventory

| Route | Implemented experience |
|---|---|
| `/app` | Redirect to dashboard |
| `/app/dashboard` | Actual authorized page counts, workflow, recent documents and JEV decisions; unavailable counts never become zero |
| `/app/documents` | Existing upload/version/review/download/processing workflow; confirmations, author guard, source expansion and timestamps |
| `/app/requirements` | Existing candidate, revision, matrix, configuration, issue and ground-truth workflows; readable timing/evidence, role deep-link |
| `/app/employees` | Paged searchable employee directory and authenticated creation form |
| `/app/employees/{id}` | Employee context, department/role, profile linkage and filtered generation history link |
| `/app/departments` | Department/job-role directories, page search, existing authorized creation actions |
| `/app/plans` | Paged generation history, employee filter, explicit preflight and confirmed one-shot generation |
| `/app/plans/{run_id}` | Failed/running history or accepted plan content; stages/modules, citations, attempts/provenance and separate validation action |
| `/app/reviews` | Paged persisted validation results |
| `/app/reviews/{validation_id}` | Findings, evidence, JEV decision and independently authorized human disposition/history |
| `/app/reports` | Real page-scoped operational and JEV distribution tables; no invented global totals |
| `/app/audit` | Admin-only paginated safe audit-event fields |
| `/app/settings` | Real identity/roles, session sign-out, read-only workspace/generation/validation responsibilities |
| `/app/phase4d-test` | Existing restricted internal tool retained, excluded from normal navigation |
| `/app/users` or unknown section/detail | Not found; unsupported user-management link removed |
| `/login`, `/access-denied`, not-found/error boundaries | Secure existing login, safe recovery/navigation, no raw errors |

## Authorization and safety

Admin/TM author controls use existing APIs. Department creation and audit reads
are Admin-only. Reviewer sees evidence and independent review, not generation
creation. Manager gets permitted employee/organization/report reads. Employee
gets account/dashboard and an honest plan-access explanation. Manager/Employee
never fetch generation drafts through the Plans surface. Navigation is not an
authorization boundary: FastAPI and caller-JWT RLS remain authoritative.

Review actions require confirmation/reason, deny self-review in the UI and retain
the backend checks. Admin override is a separate human disposition, never a JEV
rewrite. Regeneration review records an action only; it does not call a provider.
Generation requires explicit successful preflight and confirmation; a browser
marker is stored before sending, preventing repeat submission after uncertainty.
Historical internal test locks are not cleared. Validation is a distinct action.

## Small read-only backend additions

- Bounded offset/limit for existing department/role/employee lists; existing array
  response contract retained, caller JWT unchanged.
- Employee list adds existing context fields and an RLS-protected profile label;
  `GET /employees/{id}` exposes the same fields for an authorized detail view.
- `GET /validation-runs` lists existing summaries/JEV decisions under caller RLS.
- Validation detail adds safe plan author/employee context for independent-review
  action visibility and a link to the run; no trusted-key read introduced.
- `GET /audit-events` is Admin-only and excludes raw audit metadata.
- Generation history accepts an optional employee UUID filter before pagination.
  No generation or validation mutation semantics were changed.

## Forms, responsive and accessibility work

Shared cards, status badges, labeled fields, scrollable business tables, bounded
Radix dialogs, loading/empty/error states and safe retry controls. Existing mobile
drawer retained; nested route highlighting, breadcrumb, settings/user menu,
skip-to-content link, wrapping actions, responsive grids and reduced-motion
skeletons added. Source prose is expandable, not a default raw payload dump.
Unsupported profile/directory editing and runtime AI settings have no fake controls.

## Verification (2026-09-26)

- Frontend Node tests: **53 passed, 0 failed**. Includes authenticated gateway,
  five-role navigation, create-control permissions, failed-run presentation,
  human override/JEV separation, self-review, safe errors, persisted one-shot
  submission, login and existing RRM regressions.
- Focused backend reads/foundation/generation API/validation API/SQL-contract
  tests: **99 passed**, one existing Starlette deprecation warning.
- Full backend: **483 passed**, one existing warning, normal exit 0.
- TypeScript, ESLint, production build: PASS. Build required filesystem approval
  for Next.js generated artifacts; no deployment performed.
- Diff/whitespace check: PASS. Scoped changed/new-file credential-pattern scan:
  no matches; no environment files or migrations in the change set.
- Static unfinished-page search: no deferred/coming-soon/TODO/FIXME route copy.
  Legitimate input placeholders and test fixtures are retained.

User-facing placeholder routes remaining: **0**.
Dead navigation items remaining (static route inventory): **0**.
Fake/mock production metrics remaining: **0**.

## Limitations and review status

**Ready for code/product review, not a claim of live visual acceptance.** Browser
automation failed to initialize (missing kernel assets). Consequently authenticated
walkthroughs, live sign-out and screenshots at 375/768/1024/1440px were NOT executed.
Responsive behavior is implemented but requires that human visual pass.

No live data, provider, migration or generation operation was performed. No real
successful plan/validation result is fabricated: accepted-plan/review display is
tested with fixtures. Current production generation limitations remain unchanged.
Manager/Employee published-plan delivery has no current API and is explicitly
unavailable, rather than exposing Unverified plans. Directory labels/choices load
up to 100 records; search is page-local; reports disclose loaded-page scope.
Directory edit/delete and user management are omitted because no contract exists.
Broader dataset, production live RLS tests and future publishing remain separate.

## Changed files

- App routes: access-denied/page.tsx; api/document-gateway/[...path]/route.ts;
  app/page.tsx; app/[section]/page.tsx; app/[section]/[id]/page.tsx;
  app/dashboard/page.tsx; app/documents/page.tsx; app/requirements/page.tsx;
  app/requirements/loading.tsx; app/loading.tsx; app/error.tsx; error.tsx;
  not-found.tsx; globals.css (all under `apps/web/src/app`).
- Components: documents/documents-workspace.tsx;
  requirements/requirements-workspace.tsx; layout/app-shell.tsx;
  layout/navigation.ts; layout/sidebar.tsx; layout/user-menu.tsx; ui/dialog.tsx;
  product/common.tsx; product/directory.tsx; product/overview.tsx;
  product/plans.tsx; product/reviews.tsx; product/settings.tsx;
  product/traceability.tsx; product/workspace.tsx (under `apps/web/src/components`).
- Client libraries: `apps/web/src/lib/product.ts`, documents.ts, rrm.ts.
- Frontend tests: foundation-gateway.test.mjs, rrm-workflow.test.mjs,
  product-experience.test.mjs (under `apps/web/tests`).
- Backend: `services/api/app/main.py`, generation_api.py,
  generation_persistence.py, validation_api.py, validation_repository.py;
  `services/api/tests/test_product_reads.py`.
- Documentation: this report and `AI_USAGE.md`.

## Final route inventory

| Route | Implemented experience |
|---|---|
| `/app` | Redirect to dashboard |
| `/app/dashboard` | Actual authorized page counts, workflow, recent documents and JEV decisions; unavailable counts never become zero |
| `/app/documents` | Existing upload/version/review/download/processing workflow; confirmations, author guard, source expansion and timestamps |
| `/app/requirements` | Existing candidate, revision, matrix, configuration, issue and ground-truth workflows; readable timing/evidence, role deep-link |
| `/app/employees` | Paged searchable employee directory and authenticated creation form |
| `/app/employees/{id}` | Employee context, department/role, profile linkage and filtered generation history link |
| `/app/departments` | Department/job-role directories, page search, existing authorized creation actions |
| `/app/plans` | Paged generation history, employee filter, explicit preflight and confirmed one-shot generation |
| `/app/plans/{run_id}` | Failed/running history or accepted plan content; stages/modules, citations, attempts/provenance and separate validation action |
| `/app/reviews` | Paged persisted validation results |
| `/app/reviews/{validation_id}` | Findings, evidence, JEV decision and independently authorized human disposition/history |
| `/app/reports` | Real page-scoped operational and JEV distribution tables; no invented global totals |
| `/app/audit` | Admin-only paginated safe audit-event fields |
| `/app/settings` | Real identity/roles, session sign-out, read-only workspace/generation/validation responsibilities |
| `/app/phase4d-test` | Existing restricted internal tool retained, excluded from normal navigation |
| `/app/users` or unknown section/detail | Not found; unsupported user-management link removed |
| `/login`, `/access-denied`, not-found/error boundaries | Secure existing login, safe recovery/navigation, no raw errors |

## Authorization and safety

Admin/TM author controls use existing APIs. Department creation and audit reads
are Admin-only. Reviewer sees evidence and independent review, not generation
creation. Manager gets permitted employee/organization/report reads. Employee
gets account/dashboard and an honest plan-access explanation. Manager/Employee
never fetch generation drafts through the Plans surface. Navigation is not an
authorization boundary: FastAPI and caller-JWT RLS remain authoritative.

Review actions require confirmation/reason, deny self-review in the UI and retain
the backend checks. Admin override is a separate human disposition, never a JEV
rewrite. Regeneration review records an action only; it does not call a provider.
Generation requires explicit successful preflight and confirmation; a browser
marker is stored before sending, preventing repeat submission after uncertainty.
Historical internal test locks are not cleared. Validation is a distinct action.

## Small read-only backend additions

- Bounded offset/limit for existing department/role/employee lists; existing array
  response contract retained, caller JWT unchanged.
- Employee list adds existing context fields and an RLS-protected profile label;
  `GET /employees/{id}` exposes the same fields for an authorized detail view.
- `GET /validation-runs` lists existing summaries/JEV decisions under caller RLS.
- Validation detail adds safe plan author/employee context for independent-review
  action visibility and a link to the run; no trusted-key read introduced.
- `GET /audit-events` is Admin-only and excludes raw audit metadata.
- Generation history accepts an optional employee UUID filter before pagination.
  No generation or validation mutation semantics were changed.

## Forms, responsive and accessibility work

Shared cards, status badges, labeled fields, scrollable business tables, bounded
Radix dialogs, loading/empty/error states and safe retry controls. Existing mobile
drawer retained; nested route highlighting, breadcrumb, settings/user menu,
skip-to-content link, wrapping actions, responsive grids and reduced-motion
skeletons added. Source prose is expandable, not a default raw payload dump.
Unsupported profile/directory editing and runtime AI settings have no fake controls.

## Verification (2026-09-26)

- Frontend Node tests: **53 passed, 0 failed**. Includes authenticated gateway,
  five-role navigation, create-control permissions, failed-run presentation,
  human override/JEV separation, self-review, safe errors, persisted one-shot
  submission, login and existing RRM regressions.
- Focused backend reads/foundation/generation API/validation API/SQL-contract
  tests: **99 passed**, one existing Starlette deprecation warning.
- Full backend: **483 passed**, one existing warning, normal exit 0.
- TypeScript, ESLint, production build: PASS. Build required filesystem approval
  for Next.js generated artifacts; no deployment performed.
- Diff/whitespace check: PASS. Scoped changed/new-file credential-pattern scan:
  no matches; no environment files or migrations in the change set.
- Static unfinished-page search: no deferred/coming-soon/TODO/FIXME route copy.
  Legitimate input placeholders and test fixtures are retained.

User-facing placeholder routes remaining: **0**.
Dead navigation items remaining (static route inventory): **0**.
Fake/mock production metrics remaining: **0**.

## Limitations and review status

**Ready for code/product review, not a claim of live visual acceptance.** Browser
automation failed to initialize (missing kernel assets). Consequently authenticated
walkthroughs, live sign-out and screenshots at 375/768/1024/1440px were NOT executed.
Responsive behavior is implemented but requires that human visual pass.

No live data, provider, migration or generation operation was performed. No real
successful plan/validation result is fabricated: accepted-plan/review display is
tested with fixtures. Current production generation limitations remain unchanged.
Manager/Employee published-plan delivery has no current API and is explicitly
unavailable, rather than exposing Unverified plans. Directory labels/choices load
up to 100 records; search is page-local; reports disclose loaded-page scope.
Directory edit/delete and user management are omitted because no contract exists.
Broader dataset, production live RLS tests and future publishing remain separate.

## Changed files

- App routes: access-denied/page.tsx; api/document-gateway/[...path]/route.ts;
  app/page.tsx; app/[section]/page.tsx; app/[section]/[id]/page.tsx;
  app/dashboard/page.tsx; app/documents/page.tsx; app/requirements/page.tsx;
  app/requirements/loading.tsx; app/loading.tsx; app/error.tsx; error.tsx;
  not-found.tsx; globals.css (all under `apps/web/src/app`).
- Components: documents/documents-workspace.tsx;
  requirements/requirements-workspace.tsx; layout/app-shell.tsx;
  layout/navigation.ts; layout/sidebar.tsx; layout/user-menu.tsx; ui/dialog.tsx;
  product/common.tsx; product/directory.tsx; product/overview.tsx;
  product/plans.tsx; product/reviews.tsx; product/settings.tsx;
  product/traceability.tsx; product/workspace.tsx (under `apps/web/src/components`).
- Client libraries: `apps/web/src/lib/product.ts`, documents.ts, rrm.ts.
- Frontend tests: foundation-gateway.test.mjs, rrm-workflow.test.mjs,
  product-experience.test.mjs (under `apps/web/tests`).
- Backend: `services/api/app/main.py`, generation_api.py,
  generation_persistence.py, validation_api.py, validation_repository.py;
  `services/api/tests/test_product_reads.py`.
- Documentation: this report and `AI_USAGE.md`.
