# AI Usage Declaration

## Phase 3 closure candidate — 2026-09-24

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Final repository consistency audit and documentation of the owner's accepted Phase 3 closure decisions |
| Scope | Documentation only: Phase 3 implementation/QA notes, Phase Plan, SRS traceability status and this declaration. No application code, migrations, live rows, Phase 4, commit, push or deployment. |
| Accepted decisions | SECURITY_TRAINING r2 stays AMBIGUOUS and blocks submission without an invented trigger. Final competition dataset inventory and expanded adversarial/live database attack checks are Phase 7 gates. Intermittent data-service incident remains non-reproducible with safe diagnostics available. |
| Status | COMPLETE / LOCKED CANDIDATE, pending final gate results and a separate Git commit. No new live security test result claimed. |


## Phase 3 intermittent data-service 503 investigation

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Diagnose reported live 503 responses and Requirements page render failure |
| Finding | Historic `DATA_SERVICE_UNAVAILABLE` mapping discarded the underlying exception/status. Current signed-in browser reads recovered; the prior upstream cause could not be reconstructed from old logs. Server rendering lacked a route retry state. |
| Changes | Add safe gateway diagnostics (table, exception class, upstream status, response receipt, client closed state), controlled regression tests, and a Requirements route error/retry component. No token/header/body/raw exception logging, auth changes, retry of writes, or timeout increase. |
| Tests | Focused backend 61 passed, full backend 291 passed with one existing warning and normal exit 0; focused frontend 19 passed, all frontend 28 passed; TypeScript, ESLint, production build, diff check and scoped secret scan passed. |
| Live status | API health 200; Requirements page, matrix/config list and Candidates rendered in a signed-in browser. Direct authenticated FastAPI status/underlying historic exception remains unverified. No RRM row created or changed. |


## Phase 3 Manual Review issue action visibility correction

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Diagnose a live reported missing issue action for a Training Manager |
| Finding | The action was rendered only for the matrix creator although the existing authenticated issue API and SQL RPC allow a Training Manager to raise an issue on any DRAFT matrix. |
| Change | Show the existing ambiguity issue action to authorized Admin/Training Manager on DRAFT matrices; retain creator-only edit/submit, authenticated API, duplicate check and version check. Add non-owner regression coverage. |
| Tests | Focused RRM frontend 18 passed; all frontend 27 passed; TypeScript, ESLint, production build and git diff --check passed. Production build retried with approved access after sandbox trace-file EPERM. Backend and migration unchanged. |
| Live status | No live issue or row was created; the corrected action still needs live acceptance. |


## Phase 3 final QA — 2026-09-24

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Final static, automated and safely available live Phase 3 QA |
| Changes | Bounded complete matrix relation pagination prevents silent dependency/issue truncation; Unicode code-point timing spans match Python/SQL; regression tests and Phase 3 audit documentation |
| Files | rrm_service.py, test_rrm_bulk.py, frontend lib/rrm.ts and rrm-workflow.test.mjs, PHASE3_RRM_IMPLEMENTATION.md, PHASE3_FINAL_QA.md, this declaration |
| Results | Focused backend 213 passed; full backend 287 passed, one existing warning, exit 0 and normal termination; focused frontend 17 passed, all frontend 26 passed; TypeScript, ESLint and production build passed. Build required approved retry after sandbox trace-file EPERM. Diff and scoped secret checks passed. |
| Live evidence | Available browser redirected to login. No authenticated workflow test or live row mutation performed; no credentials requested. User-reported ambiguity rejection is not represented as newly executed evidence. |
| Human review | Not locked. Live Manual Review/security acceptance and minimum dataset inventory/scope decision remain outstanding. No migration, Phase 4, commit, push or deployment. |

## Phase 0 entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Architecture assistance: analyze the SRS; draft system, database, API, GenAI, validation, JEV, security, traceability, and phased-delivery designs |
| Prompt / assistance type | User-directed Lead Software Architect task constrained to Phase 0 documentation |
| Artifacts affected | `ARCHITECTURE.md`, `SRS_MATRIX.md`, `DATABASE_DESIGN.md`, `API_CONTRACTS.md`, `GENAI_CONTRACT.md`, `VALIDATION_DESIGN.md`, `JEV_DESIGN.md`, `PHASE_PLAN.md`, `.env.example`, `.gitignore`, `AI_USAGE.md` |
| Modification performed | Created planning documents and safe configuration placeholders; updated ignore rules. No application code, migrations, deployment, or production data created. |
| Verification/testing status | Automated document-presence/content checks and consistency checks are planned/performed as recorded in the Phase 0 handoff. No application tests exist because implementation is explicitly out of scope. |
| Human review status | **Phase 0 architecture approved and locked by the user before Phase 1 began.** |
| Verifying team member | Pending assignment |

## Phase 0 correction entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Apply architecture corrections requested during human Phase 0 review |
| Prompt / assistance type | Targeted correction of MVP tenancy scope, approval separation, locked defaults, and cross-document consistency |
| Artifacts affected | `ARCHITECTURE.md`, `SRS_MATRIX.md`, `DATABASE_DESIGN.md`, `API_CONTRACTS.md`, `VALIDATION_DESIGN.md`, `PHASE_PLAN.md`, `AI_USAGE.md` |
| Modification performed | Removed MVP multi-tenancy; enforced Training Manager draft/submit versus Reviewer/Admin approval; recorded accepted OCR, retrieval, export, upload, stage, precedence, and deployment decisions; audited stale references |
| Verification/testing status | Documentation consistency searches performed. No application tests apply because application implementation remains out of scope. |
| Human review status | **Phase 0 corrections approved and locked by the user before Phase 1 began.** |
| Verifying team member | Pending assignment |

Future AI-assisted work must add entries identifying prompts/assistance type, exact files/modules, modifications, tests performed, and the team member who verified the output. Do not replace this history.

## Phase 1 foundation entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Implement the approved Phase 1 application foundation |
| Prompt / assistance type | User-provided Phase 1 implementation brief and locked Phase 0 architecture |
| Files/features affected | `apps/web/` Next.js shell, login, reusable UI and API client; `services/api/` FastAPI, auth/RBAC, directory APIs and tests; `supabase/migrations/202609230001_foundation.sql`; `README.md`; `.env.example`; this declaration |
| Modification performed | Created frontend and backend foundations, single-organization schema/RLS, audit triggers, typed boundary, and reviewable setup instructions |
| Tests performed | Backend pytest, frontend ESLint, TypeScript, Next.js production build, dependency audit, and static security/diff review; exact final results are reported in the Phase 1 handoff |
| Human review status | **Phase 1 implementation pending human review.** No Phase 1 approval is claimed. |
| Verifying team member | Pending assignment |

## Phase 1 SQL security hardening entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Apply a human-requested Phase 1 migration security correction |
| Prompt / assistance type | Focused review and explicit `anon` table-privilege revocation |
| Files/features affected | `supabase/migrations/202609230001_foundation.sql`, this declaration |
| Modification performed | Explicitly revoked all table privileges from `anon` and `PUBLIC` on the six Phase 1 foundation tables before authenticated application grants; explicitly revoked direct `anon`/`PUBLIC` function execution; retained Admin-only audit-log read access |
| Tests performed | Focused SQL security review and existing affected checks; results reported in the handoff |
| Human review status | **Pending human review.** Migration was not executed or applied to a live project. |
| Verifying team member | Pending assignment |

## Phase 1 RBAC/RLS verification preparation entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Prepare controlled verification of the four remaining Phase 1 application roles after the user-reported live Admin login success |
| Prompt / assistance type | User-directed route/RLS inspection, manual-only test-user bootstrap template, verification matrix, and automated test expansion |
| Files/features affected | `supabase/testing/bootstrap_existing_auth_user_role.sql`, `docs/PHASE1_RBAC_RLS_VERIFICATION.md`, `services/api/tests/test_foundation.py`, this declaration |
| Modification performed | Added a fail-closed SQL Editor template for an already-created Auth user, documented actual protected API/RLS expectations and live checks, and expanded route-level RBAC tests; no live Supabase changes or application feature changes |
| Tests performed | Backend pytest, frontend lint/typecheck/production build, and static security/diff review; exact results reported in the handoff. Live non-Admin/RLS checks remain manual and unverified. |
| Human review status | **Pending human review.** User reported Admin live login verified; remaining role/RLS checks have not been claimed as passed. |
| Verifying team member | Pending assignment |

## Phase 1 closure-readiness entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Perform user-requested Phase 1 closure checks without starting Phase 2 |
| Prompt / assistance type | Final automated validation, documentation/secret-safety review, and git-status audit |
| Files/features affected | `README.md`, `.gitignore`, this declaration; existing Phase 1 frontend, backend, migration, and verification documents reviewed |
| Modification performed | Clarified Supabase as the chosen implementation rather than an explicit SRS requirement, recorded the user-reported five-role login verification, clarified server-side RBAC versus navigation, and ignored generated TypeScript build information |
| Tests performed | Backend pytest: 41 passed, one upstream TestClient deprecation warning. Frontend lint, typecheck, and production build passed. Git ignore/tracked-file and pending-source secret-safety checks performed. |
| Human review status | **Phase 1 approved and locked by the project owner.** Successful login/dashboard verification for all five roles was reported. Detailed live row-level RLS checks remain separately documented and are not claimed as completed. |
| Verifying team member | Project owner (final review and lock decision) |

## Phase 2 document intelligence entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Implement the reviewed Phase 2 document-intelligence scope while preserving locked Phase 0/1 behavior |
| Prompt / assistance type | User-provided Phase 2 brief and interruption-recovery brief; code, migration, test, and UI implementation |
| Files/features affected | New Phase 2 migration, Python document parser/repository/API/tests, Next.js Documents workspace/proxy/types/loading/error states, `.env.example`, parser dependencies, `README.md`, `API_CONTRACTS.md`, and Phase 2 implementation notes |
| Modification performed | Added private document data/storage design, Python PDF/DOCX validation/parsing/chunking, user-scoped processing/review APIs, enterprise Documents UI, and recovery/security documentation; no RRM/GenAI/OCR/embedding/Phase 3 functionality |
| Tests performed | Full backend pytest: 63 passed, one upstream TestClient deprecation warning. Frontend lint, TypeScript typecheck, and production build passed. `git diff --check` passed. Migration security and hidden-evaluation coupling reviewed statically; no live migration or RLS result is claimed. |
| Human review status | **Phase 2 pending human review.** New migration has not been applied; no Phase 2 approval, commit, push, or deployment is claimed. |
| Verifying team member | Pending assignment |

## Phase 2 adversarial-audit correction entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Correct the Phase 2 implementation after the read-only adversarial audit returned `FIXES_REQUIRED_BEFORE_MIGRATION` |
| Prompt / assistance type | Human-directed security, state-machine, parser, pagination, recovery, and test corrections; no Phase 3 scope |
| Files/features affected | Phase 2 migration, FastAPI document repository/API/parser/request limiter/tests, Next.js document gateway/workspace, `.env.example`, `README.md`, `API_CONTRACTS.md`, Phase 2 review notes, this declaration |
| Modification performed | Restricted parse finalization to a backend-only service credential; blocked dual-role self-review except explicit audited Admin override; bounded upload requests; preserved heading source content; added paginated review, current-effective query, and checksum-verified retry semantics. No live database action. |
| Tests performed | Backend pytest: 74 passed, one upstream TestClient deprecation warning (`-p no:cacheprovider` because pytest cache creation hangs in this sandbox). Frontend lint, typecheck, production build passed. `git diff --check` passed with line-ending warnings. Static SQL/security review performed; live Supabase RLS/Storage tests remain pending. |
| Human review status | **Pending human review.** Phase 2 migration remains unapplied; no commit, push, or deployment is claimed. |
| Verifying team member | Pending assignment |

## Phase 2 final closeout entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Complete the project-owner-authorized Phase 2 closeout after manual migration and workflow testing |
| Prompt / assistance type | Final architecture/security review, automated quality gates, evidence-based documentation, secret/diff inspection, commit and push |
| Files/features affected | Phase 2 implementation and migration reviewed; `docs/PHASE2_DOCUMENT_INTELLIGENCE.md`, `README.md`, and this declaration updated |
| Modification performed | Recorded the applied migration, user-reported PDF/DOCX and role-workflow evidence, Phase 2 lock decision, and still-pending direct RLS/Storage attack checks; no Phase 3 feature or deployment |
| Tests performed | Backend pytest: 74 passed, one upstream TestClient deprecation warning; frontend lint, TypeScript check, and production build passed. Static security and staged secret/diff checks performed separately before commit. |
| Human review status | Project owner authorized Phase 2 final closeout after reporting live workflow verification. Detailed direct RPC/table/Storage attack checks are not claimed as executed. |
| Verifying team member | Project owner (manual live evidence and closeout decision) |

## Phase 3A.1 domain/data foundation entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Implement only the approved deterministic/manual RRM foundation checkpoint |
| Prompt / assistance type | Human-approved Phase 3 design and bounded 3A.1 brief; domain modeling, pure rules, additive SQL, adversarial tests and pre-migration static review |
| Files/features affected | `services/api/app/rrm_models.py`, `rrm_rules.py`, `services/api/tests/test_rrm.py`, `test_rrm_sql_contract.py`, `supabase/migrations/202609230003_rrm_foundation.sql`, `docs/PHASE3_RRM_IMPLEMENTATION.md`, this declaration |
| Modification performed | Added immutable requirement revisions and draft-edit history, evidence/applicability, matrix lifecycle/security, explicit authority/stage configuration, timing evidence, deterministic eligibility/hash rules and append-only issue resolutions. No existing application route or locked migration changed. |
| Tests performed | Backend pytest: **214 passed** (74 existing regression cases plus 140 new cases: 110 domain/rule and 30 static SQL contract cases); one existing upstream TestClient deprecation warning. Frontend lint, typecheck and production build passed; build required filesystem escalation after a sandbox trace-file EPERM. Git diff/whitespace and seven-file secret-pattern checks passed. No PostgreSQL migration, runtime/RLS/concurrency test or live Supabase test was executed. |
| Human review status | **Checkpoint pending migration review. Phase 3 is not complete.** Migration not applied; no commit, push or deployment. |
| Verifying team member | Pending human review |

## Phase 4D bounded generation projection correction

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Reduce the provider request that reached HTTP 413 without changing authoritative frozen input or deterministic verification boundaries |
| Files/features affected | Phase 4 prompt/service/API/persistence code, focused generation and SQL-contract tests, new additive bounded-projection migration, Phase 4C/4D implementation notes, this declaration |
| Modification performed | Added a deterministic bounded projection, separate projection hash and new prompt version; retained full input snapshot/hash and strict UNVERIFIED-only output. Oversized projection fails before provider invocation. Historical migrations/runs were not changed. |
| Tests performed | Phase 4 focused and full backend results are reported in the task handoff. No live SQL application or provider call was performed. |
| Human review status | Pending review; new migration not applied. No commit, push, or deployment. |
| Verifying team member | Pending human review |

## Phase 4D Groq provider integration

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Add Groq as the active backend-only Phase 4 provider after a successful standalone provider probe |
| Files/features affected | Generation provider selection/adapter, backend-only configuration example, additive Groq SQL migration, focused tests, Phase 4 implementation notes and this declaration |
| Modification performed | Preserved Gemini and the existing frozen-context, retry, strict validation and UNVERIFIED-only workflow; added a Groq chat-completion adapter and the minimum SQL provider/model acceptance change. No automatic fallback, Phase 5/JEV, live data change, commit, push or deployment. |
| Live status | No Groq SkillSprint generation request has been made by Codex. The additive migration requires separate human review/application, followed by backend configuration and live preflight. Historical Gemini FAILED runs are untouched. |
| Human review status | Pending. |

## Phase 4C final automated and live-evidence audit

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Audit the applied Phase 4C foundation for lock readiness without new live data or Gemini calls |
| Files/features affected | `docs/PHASE4C_GENERATION_IMPLEMENTATION.md`, `GENAI_CONTRACT.md`, this declaration; the reviewed Phase 4C migration was staged for later commit without changing its contents |
| Modification performed | Updated documentation to distinguish human-reported bootstrap and five-role live authorization evidence from unexecuted valid-run lifecycle tests. No application code, schema or live records changed in this audit. |
| Tests performed | Focused Phase 4A/4B/4C backend: **83 passed**. Full backend: **374 passed**, one existing TestClient deprecation warning, exit 0. Frontend auth/RRM tests: **23 passed**; lint, typecheck and production build passed. Whitespace and scoped high-confidence secret checks passed. |
| Human review status | **PHASE_4C_READY_TO_LOCK**, not committed or pushed. No real Gemini call; controlled-data lifecycle and cross-record live checks remain unexecuted. |
| Verifying team member | Pending human lock review |

## Phase 3A.2 ambiguous-timing manual-review UX correction

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Complete bounded RRM readiness, issue-routing and immutable timing-revision UX following live human review |
| Files/features affected | `services/api/app/rrm_service.py`, `services/api/tests/test_rrm_api.py`, `apps/web/src/lib/rrm.ts`, `apps/web/src/components/requirements/requirements-workspace.tsx`, `apps/web/tests/rrm-workflow.test.mjs`, `docs/PHASE3_RRM_IMPLEMENTATION.md`, this declaration |
| Modification performed | Ambiguous active timing now blocks advisory readiness and the submit control; authors can raise an explicit ambiguity issue; structured timing revision requires exact linked chunk spans for every field and retains original text; an issue resolution alone does not clear timing. Existing SQL transition remains authoritative and unchanged. |
| Tests performed | Frontend focused/full available tests: 20 passed; frontend lint, typecheck and production build passed. The backend shutdown gate subsequently identified an inaccessible pytest cache under restricted runs; after the test-runner correction, full backend pytest exited normally with **285 passed, 1 existing deprecation warning**. Scoped secret-pattern and diff whitespace checks returned no finding. |
| Human review status | Pending human workflow review. No live requirement/matrix changes, migration, commit, push or deployment. |
| Verifying team member | Pending human review |

## Backend pytest shutdown gate

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Diagnose and correct the post-test pytest shutdown hang before Phase 3A.2 review |
| Files/features affected | `services/api/pytest.ini`, `services/api/tests/test_rrm_bulk.py`, this declaration |
| Root cause / correction | Even one static SQL test hung after its progress reached 100% under the restricted workspace, while it exited normally outside that restriction. The legacy `services/api/.pytest_cache` was inaccessible and pytest's optional cacheprovider stalled on session completion. Disabling only cacheprovider for this backend suite restored normal exit; fixture teardown, FastAPI lifespan and shared `httpx.AsyncClient` closure remain active. No application or database behavior changed. |
| Tests performed | Focused client/lifecycle: **3 passed**; focused RRM API: **22 passed**; full backend pytest: **285 passed, 1 existing Starlette/TestClient deprecation warning**, final summary printed, exit code 0, normal process termination. Repeated app lifecycles close distinct pools, and user Authorization remains per request. |
| Human review status | Shutdown gate complete; Phase 3A.2 still pending human workflow review. No live data change, migration, commit, push or deployment. |
| Verifying team member | Pending human review |

## Phase 3A.2 human RRM workflow implementation

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Implement the human source-backed requirement and role-matrix workflow on the already-applied Phase 3A.1 contract |
| Files/features affected | `services/api/app/rrm.py`, `rrm_service.py`, `rrm_repository.py`, `main.py`, new RRM API tests; Next.js requirements page/workspace, typed RRM client and narrow gateway extension, frontend tests; Phase 3 implementation notes and this declaration |
| Modification performed | Added user-JWT FastAPI list/read/create/edit/transition/issue/ground-truth routes; current-effective source prechecks, safe error mapping, role-aware evidence-first candidate and matrix UI, explicit Admin override controls. No migration, Gemini, plan generation, service-role workflow expansion, deployment, commit or push. |
| Tests performed | New backend RRM API tests: 15 passed. New frontend RRM tests: 6 passed. Full-suite and production gate results are recorded in the final task handoff; no live database attack result is inferred. |
| Human review status | Phase 3A.2 pending manual workflow review. Phase 3A.1 direct SQL/RLS/RPC/security checks remain pending. Phase 3 is not complete or locked. |
| Verifying team member | Pending human review |

## Phase 3A.1 pre-migration audit correction entry

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Fix only audit findings F1, F2 and F3 before migration |
| Prompt / assistance type | Human-directed bounded security/correctness fixes and focused read-only re-audit |
| Files/features affected | `rrm_models.py`, `rrm_rules.py`, both Phase 3 test modules, `202609230003_rrm_foundation.sql`, `docs/PHASE3_RRM_IMPLEMENTATION.md`, this declaration |
| Modification performed | Explicit UTC canonical timestamps/date eligibility; mandatory downgrade request, reason and exact source evidence enforced within existing matrix review; common deterministic nonblank reason validation. No Phase 1/2 migration, route, parser, grant expansion or service-role change. |
| Tests performed | Complete backend: **249 passed**, one existing TestClient deprecation warning. Focused Phase 3: **175 passed**; **35 added regression cases**. Frontend lint/typecheck/build passed; build retried with filesystem permission after `.next/trace` EPERM. Diff/whitespace and secret-pattern checks performed. |
| Re-audit / limitations | No remaining known Blocker/High in scoped static re-audit. Database execution, timezone RPC behavior, RLS/concurrency and SQL/Python hash parity remain REQUIRED LIVE TEST; no live Supabase results claimed. Evidence presence still requires human semantic review. |
| Human review status | **Fixes ready for review, not locked.** Migration remains unapplied. No commit, push, deployment or Phase 3A.2 implementation. |
| Verifying team member | Pending human review |

## Phase 5 independent validator and JEV foundation

Codex implemented deterministic Python validation, versioned findings/JEV, authenticated APIs, immutable evidence/review persistence and an additive unapplied migration. The Phase 4 output model and generation code were not changed. Source timing without a comparable generated timing tuple requires MANUAL_REVIEW; factual prose entailment is not claimed. Tests: 53 focused Phase 5 checks; 474 full backend tests passed, one existing deprecation warning, normal exit 0. Diff and scoped credential-pattern checks passed. No provider request, live validation, database mutation, migration application, frontend build, commit, push or deployment. Human review and live migration/RLS verification remain pending.

## Phase 4D compact exact-output request recovery

Codex inspected the outbound Groq construction and factored repeated output-schema constraints without changing strict output validation or the frozen snapshot/projection. Added a final serialized-body guard, corrected employee mapping prose, created a new prompt pin/additive migration, and added round-trip/size/security contract tests. Offline synthetic 6/8/5 body decreased from 23,392 to 16,644 bytes; exact historical live request size/provider threshold remain unproven. Focused tests: 130 passed; full backend: 421 passed, one existing warning, exit 0. No provider/database calls, migration application, configuration changes, commit or deployment. Pending human review; see `docs/PHASE4D_COMPACT_REQUEST_AUDIT.md`.

## Login form security correction after interrupted Phase 3A.1 live verification

| Field | Value |
|---|---|
| Tool | OpenAI Codex |
| Purpose | Prevent native login form fallback from placing credentials in a URL when client JavaScript is unavailable |
| Files/features affected | `apps/web/src/app/login/page.tsx`, `apps/web/tests/login-form-security.test.mjs`, `apps/web/package.json`, this declaration |
| Modification performed | Added explicit POST fallback, removed native form names from credential inputs, and disabled submission in server HTML until hydration. Supabase client authentication, session handling, RBAC, and backend authorization were not changed. |
| Tests performed | Four focused executable auth tests passed; frontend lint, TypeScript check, and production build passed; backend regression 249 passed with one existing TestClient deprecation warning. Secret-pattern and diff checks performed separately. |
| Human review status | Login security fix pending review. No real browser login result is claimed; Phase 3A.1 live verification remains paused. No migration edits, commit, push, or deployment. |
| Verifying team member | Pending human review |
