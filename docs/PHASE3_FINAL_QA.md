# Phase 3 final QA — 2026-09-24

STATUS: **COMPLETE / LOCKED CANDIDATE**. Phase 3 closure is accepted by the
project owner, subject to the final gates below. The earlier QA observations in
this file remain historical evidence. No Phase 4 work, migration edit/application,
live row mutation, commit, push or deployment occurred in this closeout pass.

## Accepted closure decisions

`SECURITY_TRAINING` r2 remains `AMBIGUOUS` with `original_text = "Within 7 days"`.
Its approved source does not identify the event starting the seven-day period.
The DRAFT Junior Software Developer matrix therefore correctly shows readiness
No / Manual Review Required and cannot submit. No trigger is inferred and no r3
is required. This is successful fail-closed validation, not a defect.

The minimum competition dataset inventory is deferred to Phase 7 Hidden
Evaluation / Dataset Hardening. Final SRS targets remain >=20 documents,
>=10 job roles, >=150 requirements, >=50 mandatory and >=30 role-specific
requirements, plus conflicts/ambiguities, policy version changes and adversarial
cases. Expanded live database/RPC/RLS attack checks and broader adversarial
testing are also deferred to Phase 7. Existing automated security/RBAC/RLS
coverage remains Phase 3 evidence; deferred live checks are not claimed as done.

The historical `DATA_SERVICE_UNAVAILABLE` incident is not currently reproducible.
Safe diagnostics and Requirements retry UI exist; no speculative infrastructure
change is warranted. Advanced authoring UI polish remains non-blocking.

This closeout pass changes documentation only. The Phase 3 migration remains
untracked and was not edited or applied in this pass. It cannot be compared to
an approved Git revision until committed. Phase 4 has not been implemented.

Final closeout gates: full backend pytest **291 passed**, one existing warning,
normal exit 0; full frontend tests **28 passed**; TypeScript, ESLint, production
build, `git diff --check` and scoped secret scan **PASS**. No tracked real env
file or secret-pattern candidate was found among changed/untracked source files.
The Phase 1/2 migrations have no diff against HEAD. No Blocker/High Phase 3
TODO/FIXME/debug artifact or broken import surfaced in the audit and gates.

## Subsequent live acceptance UI correction

The project owner reported that a signed-in Test Training Manager could see the
ambiguous timing blocker but no issue action. Inspection found that the action
was inside the Role Matrices readiness block, gated by matrix creator identity.
The existing issue API and SQL RPC authorize Training Manager issue creation on
any DRAFT matrix; edit and submit still require the creator. The UI now shows
the issue context and action to Admin/Training Manager on a DRAFT even when they
did not create it. It still checks for an open duplicate, fetches a fresh lock
version and calls the authenticated issue endpoint. Backend/SQL rules are unchanged.
This is code/test evidence only; live issue creation and persistence still need
retesting. The earlier automated counts below describe the preceding QA run.
After this correction: focused RRM frontend **18 passed**, all frontend **27
passed**, TypeScript/ESLint/production build passed, and `git diff --check`
passed. The build required an approved retry for sandbox EPERM on `.next/trace`.

## Static audit

These are code/test findings, not executed live PostgreSQL security tests.

| Areas | Evidence and result |
|---|---|
| Requirement lifecycle/revisions; immutable history | Same-code successor/predecessor constraints and append-only triggers; API/UI create new revisions, never mutate old requirements. Static/test pass. |
| Exact evidence; approved/current sources | Chunk FKs establish lineage; SHA-256, parsed/approved/effective checks, current-version RPC in bulk resolver; SQL revalidates at transition/retrieval. Static/test pass. |
| Applicability | Typed OR clauses of role/department/location/experience; pure rules fail closed on insufficient context; SQL checks active scope references. Static/test pass. |
| Mandatory/optional; exceptions | Explicit target, scope subset, meaningful downgrade reason and exact evidence; independent approval/audit retained. Static/test pass. |
| Structured/ambiguous timing | Exact spans for all structured fields; AMBIGUOUS blocks SQL submission and readiness; issue resolution never changes timing. Static/test pass. |
| Dependencies | Same-edit FKs, no self-edge, prerequisite sequence proves acyclicity; replacement fails closed on dependent relationships. Static/test pass. |
| Precedence/conflicts | Pinned ranks/document authorities; pure rules route equal/missing precedence to review; explicit issues block transitions. Static/test pass; semantic conflict identification still requires humans. |
| Manual review/issues | Refreshed UI duplicate-open check, independent reasoned per-edit resolution; edits invalidate prior resolutions. Static/test pass; live acceptance outstanding. |
| Role matrices/lifecycle | Owned DRAFT complete edits, SUBMITTED snapshot, APPROVED/REJECTED decision, SUPERSEDED history; current usability rechecked. Static/test pass. |
| Independent/self-review | Trusted SQL actor checks historical contributors; dual roles do not bypass; actual Admin override needs reason/audit, not integrity bypass. Static/test pass. |
| Concurrency/audit | Expected-version checks; matrix/source/role locks; immutable edits; actor, creator, submitter, reviewer and override metadata. Static/test pass; live concurrent transactions outstanding. |
| RLS/RBAC | All 12 tables RLS-enabled, authenticated SELECT only; guarded RPCs, fixed search_path, private helpers revoked; Manager/Employee denied by backend and SQL. Static/test pass; live attacks outstanding. |
| No ordinary service role; no AI autoapproval | RRM forwards caller JWT; no default pool Authorization; manual origin and independent approval; no provider introduced. Static/test pass. |
| Performance | Lifespan-owned pooled client, bulk evidence/requirements, one current RPC per unique document, bounded concurrency, lazy tabs. Request-count/lifecycle tests pass; no new warm live latency claimed. |

SQL submission/approval remains authoritative. Readiness is advisory, not a
replacement for all SQL validation. Stage labels remain configurable data.

## Two corrections

1. Matrix detail previously requested 5,000 dependency rows in one PostgREST call
   subject to server limits, and only 100 issues/resolutions. A complete edit
   could lose omitted edges; readiness could miss issues. Ordered 100-row pages
   now fetch entries/dependencies/issues/resolutions completely or fail closed
   at 1,000/5,000/10,000/10,000 respectively. Small matrix call counts are unchanged.
   Tests cover 1,101 edges, 102 issues, 101 resolutions and over-limit rejection.
2. JavaScript UTF-16 offsets differed from Python/SQL code-point offsets. Timing
   spans now use code points, tested with non-BMP characters before/inside quotes.
   No evidence or timing semantics were inferred or relaxed.

## Executed gates

| Gate | Result |
|---|---|
| Focused backend RRM (four test modules) | 213 passed, exit 0 |
| Full backend pytest | 287 passed, 1 existing Starlette TestClient deprecation warning; final summary printed, exit 0, normal termination |
| Focused frontend RRM | 17 passed |
| All frontend tests: node --test tests/*.test.mjs | 26 passed, including 5 gateway and 4 auth tests |
| TypeScript / ESLint | Passed, exit 0 |
| Production build | Passed, exit 0 after approved retry for sandbox EPERM on existing .next/trace-build |
| git diff --check | Passed |
| Scoped changed/untracked source secret-pattern scan | No secret candidates; no tracked real env files; not an exhaustive history/secret-format guarantee |
| Locked Phase 1/2 migrations vs HEAD | No diff |

Pytest cacheprovider remains disabled for legacy cache permissions; tests and
resource teardown are not disabled. Pool tests cover JWT isolation, repeated
app lifecycles, closure and idempotent cleanup.

## Historical live evidence and earlier acceptance plan

User-reported context, not independently reverified: Junior Software Developer
revision 1 is DRAFT with SECURITY_TRAINING r2; timing is AMBIGUOUS, original text
"Within 7 days"; SQL rejected submission with RRM_TIMING_MANUAL_REVIEW. This is
expected and is not a defect to bypass.

Executed browser observation: /app/requirements redirected to
/login?next=%2Fapp%2Frequirements. No authenticated persona was available. No
credentials were requested; no issue/resolution/r3/matrix mutation was performed.

MANUAL REQUIRED:

1. As the author, verify readiness No, r2 and original phrase visible, manual-review
   blocker and Submit disabled. Automated markup tests are not this live result.
2. Create an AMBIGUITY issue: "The approved source states 'Within 7 days' but does
   not identify the event from which the seven-day period begins. Manual review
   is required; no timing trigger should be inferred." Refresh for persistence;
   repeat action must show/retain the existing open issue.
3. Independently sign in as Reviewer/Admin and record a reasoned resolution.
   Verify timing remains AMBIGUOUS and submission blocked. Do not create r3 until
   approved sources explicitly support all structured timing fields.
4. Execute documented live ACL/RLS/RPC, self-review, stale-source, downgrade,
   integrity and concurrency checks. SQL/Python hash parity and alternate-timezone
   RPC behavior remain required LIVE tests, not static claims.

Database issue uniqueness is not enforced: UI duplicate detection and stale-write
checks protect the normal flow; direct callers can create additional issues with
fresh versions. Each remains independently blocking. No database uniqueness claim.

## Historical closure scope and limitations, superseded by accepted decisions above

`PHASE_PLAN.md` Phase 3 includes a minimum fictional dataset and inventory tests.
`SRS_MATRIX.md` requires >=20 documents, >=10 job roles, >=150 requirements,
>=50 mandatory and >=30 role-specific requirements. Implementation notes say no
fictional dataset was implemented; no completion inventory was available. The
earlier instruction deferred the 10-role dataset. Full closure needs completion
evidence or an explicit human decision to move this gate to a later milestone.
This audit does not fabricate records/counts or silently waive the plan.

Non-blocking limitations: dedicated advanced exception/downgrade/stage UI remains
limited; structured/multiple-scope candidate revision uses guarded API contracts
rather than a general UI editor; semantic entailment needs independent humans;
broad filters and detail size limits fail closed; catalogs may need refresh after
external changes. Relation paging assumes PostgREST row cap >=100; existing bulk
source batches assume the standard 1,000-row cap. Optional Gemini extraction is
not implemented and is not required for the manual workflow. New live warm
performance was not measured.

No known remaining Blocker/High implementation defect was identified after the
two fixes. Closure is withheld for outstanding live acceptance/security evidence
and unresolved dataset acceptance scope, not the intentionally ambiguous matrix.

## Files changed in this audit only

- services/api/app/rrm_service.py
- services/api/tests/test_rrm_bulk.py
- apps/web/src/lib/rrm.ts
- apps/web/tests/rrm-workflow.test.mjs
- docs/PHASE3_RRM_IMPLEMENTATION.md
- docs/PHASE3_FINAL_QA.md (new)
- AI_USAGE.md

Other pre-existing working-tree edits are preserved.

## Intermittent data-service 503 investigation

User-observed before this pass: `/api/v1/me` and `/api/v1/requirements?limit=50`
returned 503; the frontend gateway returned 503 and the Requirements server
render failed with a generic 500. Matrix list and RRM configuration reads returned
200 around the same period. The original `DATA_SERVICE_UNAVAILABLE` handler
collapsed HTTP response errors, transport errors and JSON errors into one code
without recording a safe failure category. The original upstream exception/status
cannot be recovered from those logs. Do not classify it as a confirmed pool or
Supabase fault.

Current observations: API health returned 200. A signed-in browser successfully
rendered `/app/requirements` twice, loaded the Junior Software Developer matrix
list/configuration, and loaded both SECURITY_TRAINING revisions in Candidates.
This confirms current recovery for these browser flows, not that the earlier
transient's underlying cause is known. A direct authenticated `/api/v1/me` or
`/api/v1/requirements` call was not independently captured because the session
credential was not exported from the browser. No issue or other live row changed.

The profile gateway now logs only the internal table name, exception class,
upstream HTTP status if a response arrived, response-received flag and shared
client closed flag. It never logs the token, request headers, upstream body or
raw exception message. The existing 503 response remains generic. Controlled
tests cover upstream 503, `ReadTimeout`, invalid JSON, safe logging, recovery
on the same pooled client and per-user Authorization isolation. A requirements
route error boundary now shows a retry action for a server-render data failure,
without exposing internal details. Auth/RLS/RBAC, query order and timeouts did
not change; no speculative retry was added.

Current gates: focused backend foundation/pool **61 passed**; full backend
**291 passed**, one existing Starlette warning, exit 0 and normal termination;
focused frontend RRM **19 passed**, all frontend **28 passed**; TypeScript,
ESLint, production build and `git diff --check` passed. Scoped changed/untracked
source scan found no credential pattern candidates or tracked real env files.
On recurrence, the new `skillsprint.supabase` warning and correlation/request
timing can distinguish upstream status from transport/parse failure. The live
root-cause classification remains open until a failing request is captured.
