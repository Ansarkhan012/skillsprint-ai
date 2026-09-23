# AI Usage Declaration

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
