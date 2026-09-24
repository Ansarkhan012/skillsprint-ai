# Phase 3A — RRM foundation and human workflow

STATUS: **COMPLETE / LOCKED CANDIDATE**. The project owner accepted Phase 3
behavior and deferred the competition dataset inventory and expanded live
adversarial/database checks to Phase 7. The earlier checkpoint notes below are
historical; see `PHASE3_FINAL_QA.md` for the current closure record.
The migration was applied before 3A.2 work began. This implementation did not edit or
run it, create Auth users, deploy, commit, or push. Direct live RLS/RPC checks remain pending.
Phase 0/1/2 remain locked; their migrations and application workflows are unchanged.

## Implemented versus planned

Implemented: strict Python domain contracts, pure deterministic preparation rules,
an additive transactional SQL migration, mutation/read RPC contracts, static SQL
security tests, domain/adversarial tests, and now user-JWT FastAPI routes and a
role-aware Next.js requirements workspace.

Planned checkpoints:

1. 3A.1: database foundation applied separately; live authorization/concurrency checks pending.
2. 3A.2: human candidate/evidence and matrix workflow API/UI implemented locally;
   real persona workflows and direct database attacks remain manual tests.
3. Later 3A: richer timing/exception authoring, end-to-end verification,
   source-impact views and documented live attack tests.
4. 3B: optional Gemini candidate extraction after manual 3A works. Provider output
   remains `AI_CANDIDATE`, never automatically approved ground truth.

No Gemini, extraction automation, onboarding generation, Phase 5 validator/JEV,
progress, fictional dataset or deployment was implemented.

## Domain and schema

`rrm_models.py` defines requirement revisions, exact evidence spans, typed scopes,
timing, matrix review metadata, entries, source records, stages and precedence.
`rrm_rules.py` has no network, database, FastAPI or provider dependency.

| New table | Purpose |
|---|---|
| `requirements` | Immutable candidates: stable code/revision/predecessor, statement, type/category, mandatory, priority, competency/assessment obligation, timing, MANUAL/AI_CANDIDATE origin, actual author |
| `requirement_sources` | Requirement revision to exact existing chunk; no writable document/version/locator assertion |
| `requirement_applicability` | OR clauses with typed job-role/department/location/experience conditions |
| `role_requirement_matrices` | Role revision, pinned precedence configuration, creator, optimistic lock version, lifecycle, submission snapshot/hash, reviewer and override metadata |
| `rrm_matrix_edits` | Append-only draft compositions with author/reason; older edits are never deleted |
| `role_requirements` | Exact candidate revisions, sequence, immutable stage reference, explicit exception target per edit |
| `requirement_dependencies` | Multiple prerequisite edges, both ends constrained to the same matrix edit |
| `rrm_issues` | Immutable conflict/ambiguity/duplicate/suspicious/missing-evidence findings |
| `rrm_issue_resolutions` | Independent reviewer resolution for one issue and one edit; edits require new resolutions |
| `rrm_precedence_configs` | Immutable versioned rank configuration with author/reason |
| `rrm_document_authorities` | Explicit document-to-authority mappings pinned to a configuration |
| `onboarding_stage_definitions` | Versioned stage data: arbitrary label, sequence and day window |

All history foreign keys restrict deletion. All new tables have RLS and explicit
SELECT-only authenticated grants. Append-only tables reject UPDATE/DELETE via
triggers; matrix deletion is also denied. No service-role grant is added; inherited
new-object privileges are explicitly revoked from PUBLIC/anon/authenticated/service_role
before the intended authenticated read/function grants.

Candidates have no global APPROVED flag. Approval applies to exact candidate
revisions and mappings inside an approved role matrix. New candidate revisions do
not mutate other matrices. A successor uses the same code and next revision; unique
predecessor constraints prevent silent branching or competing revision overwrites.

## Lifecycle, ownership and concurrency

`DRAFT -> SUBMITTED -> APPROVED -> SUPERSEDED`; `SUBMITTED -> REJECTED`.
Rejected/approved content is changed through a successor draft. Draft edits are
complete bounded compositions stored as new edit rows, not overwrites. Empty drafts
can exist but cannot submit. Invalid/incomplete candidate evidence may remain in
drafts for repair; it cannot become active ground truth.

Only a draft's creator may edit/submit it. Admin can create its own successor draft;
Admin does not silently edit another author's composition. Mutations carry an exact
expected `lock_version`, lock the matrix row, and increment the version. A stale
request raises `40001/RRM_EDIT_CONFLICT`; it must be reloaded, not blindly retried.

Submission checks all structural/source rules and freezes a complete database
snapshot. Approval repeats those checks and compares the canonical snapshot hash.
Role-row locking serializes competing approvals. An older revision cannot supersede
a newer approved revision. Automatic supersession records a separate audit event.

Source-document rows are locked while checking/submitting/approving/resolving
ground truth, coordinating with Phase 2's document lock during supersession.
No source version can be silently rebound to a replacement. A new source invalidates
use of the old matrix but preserves its historical approval and citations. Date
expiry is checked on every ground-truth read, so it does not need a background job.
Consumers in later checkpoints must recheck eligibility at use/finalization; a
returned snapshot is not a permanent guarantee that its sources will stay current.

## Source integrity

The only submitted source identifier is `chunk_id`. SQL derives the chunk's version
and logical document, stores their historical evidence in the snapshot, and checks:

- ACTIVE document, PARSED version, APPROVED review state;
- effective date reached and expiry not passed, using `(statement_timestamp() AT TIME ZONE 'UTC')::date`;
- chunk text SHA-256 matches stored `text_hash`;
- at least one exact source per candidate and explicit authority mapping;
- all requirements, including optional ones, pass: invalid entries are not dropped.

Phase 2's unique approved-version constraint supplies current-version uniqueness.
Its future-effective approval restriction is preserved. DRAFT, SUBMITTED, REJECTED,
SUPERSEDED, NEEDS_REVIEW, FAILED, expired or future-effective evidence blocks active
truth. Raw SELECT access includes historical rows and must never be mistaken for a
ground-truth eligibility check.

DOCX table cells remain separate chunks. A requirement can link the training name,
audience and timing cells, plus header/context evidence. No parser changes are needed.
Python `Source` objects must be constructed by the later repository from those
database joins; they are not trusted client assertions.

## Deterministic rules

- Applicability is OR between clauses and AND within a clause. Null role/department
  is an explicit wildcard; a supplied ID is a job-role/department FK, never an app
  permission. Missing context for a potentially applicable clause gives
  `MANUAL_REVIEW`. A known nonmatching clause does not become unknown merely because
  another field is missing.
- Exact duplicate candidates use whitespace normalization and lowercase, preserving
  numbers, punctuation and negation. This is not semantic duplicate detection.
- Dependency IDs must resolve in the same matrix. Python uses an iterative DAG
  check; SQL requires strictly preceding sequence numbers for every edge, which
  also makes cycles impossible in an approvable matrix.
- Original timing is preserved. `NOT_SPECIFIED`, `AMBIGUOUS`, and `STRUCTURED` are
  explicit. Ambiguous timing blocks submission/use. Structured timing requires
  exact source spans for original text, trigger, relation, value, unit and calendar
  basis. Offsets are zero-based in stored normalized text. No calendar/business-day
  basis or starting trigger is guessed. Current lexical support accepts explicit
  numeric values and HOUR/DAY/WEEK terms (including plurals); unsupported wording
  remains ambiguous. Exact spans prove presence, not semantic entailment: the human
  reviewer must confirm that the structured fields describe the same obligation.
- Complete Python snapshots reject stale sources, unresolved issues, duplicate
  requirements, broken prerequisites, unknown applicability and unmapped authority.
  Both general and exception evidence remain in the snapshot; `effective_ids` and
  `exception_resolutions` describe the context-specific explicit replacement.
- Canonical hashing uses sorted UTF-8 object keys, ordered arrays, finite decimal
  numbers and SHA-256. SQL builds ordered relational arrays. Python can hash that
  same JSON payload; its context-resolved envelope (`rrm-1`) is distinct from the
  database submission envelope (`rrm-db-1`) and has its own hash. Non-finite numbers
  are rejected, and no current timestamp is invented during hashing.

RRM timestamps use exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ` (six fractional digits,
UTC, for example `2026-09-24T00:00:00.000001Z`). SQL explicitly converts each typed
timestamp with `AT TIME ZONE 'UTC'` before formatting: requirement/stage/chunk/issue
creation, issue resolution and source approval. Null remains JSON null. JSON evidence
text is not interpreted as a timestamp. Submission, approval and retrieval all use
the same snapshot builder and hash function. No session setting or request timezone
preference controls this representation. No Phase 1/2 function or global timezone
setting is changed. Eligibility uses UTC at statement start, consistently throughout
that operation; consumers must recheck before subsequent use. Python `utc_timestamp`
and `utc_date` accept aware instants only; future adapters must obtain the instant
from a trusted backend clock, never client-supplied date/time preferences.

No arbitrary semantic contradiction detector is claimed. Authors/reviewers can
raise issues; only an independent Reviewer/Admin can resolve them with a reason.
An Admin's issue-resolution self-review also requires explicit override. Resolutions
cannot bypass structural/source/timing/graph checks.

## Precedence and exceptions

Approved applicable role exception > Department SOP > Company Policy > FAQ >
Informal Guidance. Initial rank values are `DEPARTMENT_SOP=40`, `COMPANY_POLICY=30`,
`FAQ=20`, `INFORMAL_GUIDANCE=10`; they are configuration data, not filename/category
heuristics. Admin creates the actual immutable configuration and explicitly maps
document IDs. No fictional document mappings or dataset is seeded.

Different document classes may share a rank; a conflicting tie requires review.
Unmapped authority fails closed. The pure precedence function handles an already
identified comparable conflict; it does not discover arbitrary semantic conflict.
Its approved-exception flags must come from approved matrix data, never client input.

An exception is an explicit entry-to-general-entry edge, with its own source
evidence. Its scopes must specify the matrix job role and be subsets of the general
requirement's scope. Exception chains and overlapping competing exceptions are
blocked. Matrix approval approves the exception; candidates alone cannot override.
Configuration and stages are pinned, immutable revisions. Changing configuration
requires a new matrix revision to adopt it; historical approved decisions retain
their original configuration.

A mandatory general requirement replaced by any nonmandatory exception (including
OPTIONAL, RECOMMENDED or NOT_APPLICABLE) requires `downgrade_requested=true`, a
meaningful `downgrade_justification`, and `downgrade_evidence` containing an exact
linked exception-source chunk/span/quote. `exception_to` identifies the mandatory
target. Missing metadata or invalid evidence blocks submission, approval and truth
retrieval with a downgrade review/integrity error; no partial snapshot is returned.
Metadata on a non-downgrade is rejected. Evidence still must be current, approved
and role-applicable. Presence does not prove entailment: the independent reviewer
must confirm that the cited policy actually permits the downgrade. The client flag
is a request, not authorization; the existing matrix approval/contributor controls
remain mandatory. The existing audited Admin emergency self-review exception does
not bypass downgrade integrity. The target, reason and span are frozen in the
submission hash and recorded in transition audit metadata. No Gemini path exists.

## RBAC and database boundary

| Operation | Admin | Training Manager | Reviewer | Manager/Employee |
|---|---|---|---|---|
| Read RRM/evidence/history | Yes | Yes | Yes | No |
| Create candidate or own draft | Yes | Yes | No | No |
| Edit/submit own draft | Yes | Yes | No | No |
| Raise issue on a draft | Yes | Yes | Yes | No |
| Resolve issue; approve/reject | Yes | No | Yes | No |
| Configure authority/stages | Yes | No | No | No |
| Direct table writes/deletion | No | No | No | No |

Database functions resolve the actor from the authenticated ACTIVE profile. Missing,
inactive and unauthorized identities fail closed. Approval checks matrix creator,
submitter, all edit authors, and authors of all candidate revisions contributed to
the matrix, including earlier edits. Dual-role author/review membership is no escape.
Only actual ADMIN membership with explicit override and nonblank reason permits
self-review; it never bypasses integrity gates. Rejection remains available when
evidence has become stale, allowing a successor draft to repair it.

All public RPCs explicitly authorize. Helpers live in a non-exposed private schema
with revoked execution/usage. Every function has fixed empty `search_path` and uses
qualified application objects. PUBLIC/anon cannot execute mutations; authenticated
users receive only the listed public entry points. The existing Phase 2 service
credential and processing RPC are untouched.

Prepared public RPCs: `create_rrm_precedence_config`, `create_rrm_stage`,
`create_requirement_candidate`, `create_rrm_matrix`, `edit_rrm_matrix`,
`raise_rrm_issue`, `resolve_rrm_issue`, `transition_rrm_matrix`, `get_rrm_ground_truth`.
The last returns the complete eligible role reference snapshot. Employee-context
resolution belongs to the pure Python rules and later API service; this checkpoint
does not expose a generation endpoint.

## Audit

Candidate/config/stage/matrix creation, each draft edit, issue creation/resolution,
submission, approval, rejection and supersession append events to the existing
Admin-only `audit_logs`. Events include actual actor, targets, revision/edit or
snapshot identifiers, reasons, and creator/submitter/override evidence where relevant.
No audit-table access is broadened. SQL rejects roll back the transaction, including
any writes; later FastAPI endpoints must log safe rejection/correlation metadata.

Phase 3 security-sensitive reasons use the same deterministic SQL/Python predicate:
1–2000 characters and at least one character outside the explicit whitespace set
U+0009–000D, U+001C–0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028–2029,
U+202F, U+205F and U+3000. Original nonblank text is preserved. This covers config,
draft-edit, issue-resolution, supplied transition/decision, Admin override and
downgrade reasons. It does not rely on database locale or regex whitespace classes.

## Pre-migration review and limits

One migration: `202609230003_rrm_foundation.sql`, wrapped in BEGIN/COMMIT. It creates
new objects only. Existing Phase 1/2 tables, functions, grants, storage policies and
migration files are not changed. Re-execution fails on existing new objects and
rolls back; it is deliberately not an idempotent repair script.

Local tests comprise executable Python rules and STATIC SQL contract inspections.
No PostgreSQL server/parser tooling is available in the local Python environment.
These checks do not prove SQL runtime, RLS, lock behavior, or PostgREST exposure.
Before production reliance, execute the reviewed migration in an authorized test
environment and verify all five personas, anon/PUBLIC denial, direct table/RPC
attacks, immutable history, stale edits, concurrent source supersession/approval,
concurrent matrix approvals, expired-source reads, issue-resolution invalidation,
cross-matrix references, Admin override audit and SQL/Python canonical hash parity.
Those checks remain **MANUAL DATABASE TEST REQUIRED**. Prior Phase 2 live attack
checks remain pending as documented in its verification notes.

Audit-fix live cases remain **REQUIRED LIVE TEST**, not automated database PASS:

- In an authorized database environment, submit as the author in UTC, approve as
  an independent reviewer with a different session/request timezone, then retrieve
  in UTC, Asia/Karachi, America/Los_Angeles and Pacific/Kiritimati. Compare identical
  payloads/hashes; unchanged evidence must not cause stale errors. Actual source or
  content changes must still fail. Include issue-resolution and stage timestamps.
- Check effective/expiry boundaries around UTC midnight with differing session
  timezones. Compare eligibility against UTC statement date, not each local date.
- Compare SQL canonical output/hashes with Python for the exact same database JSON,
  including all timestamp fields, nulls, Unicode, numeric values and ordering.
  SQL/Python parity is **not proven locally** by the pure-Python tests.
- Submit ordinary optional exceptions to mandatory bases, flag-only requests,
  missing/whitespace reasons, missing/forged/cross-requirement/stale evidence and
  wrong-role scopes. All must fail closed, including with Admin override. Confirm
  a valid independently reviewed downgrade succeeds and its target/reason/span are
  present in the frozen snapshot and audit log. Confirm author dual-role denial.
- Try each listed whitespace character through config, edit, resolution, override
  and downgrade RPC fields; confirm rejection and rollback without history changes.

At the 3A.1 pre-migration checkpoint, HTTP integration/UI and domain-safe database
error mapping were not yet implemented; 3A.2 adds those below. Still open now:
semantic entailment remains human-reviewed, no timing inference or automatic
source-impact jobs, no provider, and no dataset/count evidence yet. SQLSTATE
`40001` is a reload conflict, not authorization to retry stale input.

## Local verification

After the F1–F3 audit fixes, backend `pytest -q -p no:cacheprovider`: **249 passed**,
one existing upstream TestClient deprecation warning. This includes **74 existing
regression cases** and **175 Phase 3 cases** (142 domain/rule, 33 static SQL contract).
The Phase 3 focused rerun also passed all **175** tests. The fix pass added **35**
cases covering equivalent instants across five offsets at UTC day boundaries,
canonical payload/hash comparisons, naive-instant rejection, whitespace reasons,
downgrade integrity/approval and static SQL UTC/ACL/control contracts. These are
Python execution and SQL text checks, not live PostgreSQL results. Frontend lint, TypeScript
check and production build all passed. The build was rerun with filesystem
permission after the sandbox denied its generated trace-file write.

`git diff --check`, seven-file trailing-whitespace review and secret-pattern scan
passed. Phase 1/2 migrations have no diff. Nothing is staged, committed or pushed.
No live verification result is inferred from unit tests or SQL text checks.

Focused read-only re-audit after implementation: F1 now uses explicit UTC date and
timestamp conversion at every canonical timestamp field; F2 requires a reason and
exact linked evidence in the existing reviewed, hashed matrix; F3 shares explicit
whitespace semantics across SQL/Python. Locked migrations and Phase 2 code are
unchanged; RLS/RPC grants and service-role responsibilities are not broadened.

Pre-migration verdict: **FIXES READY FOR REVIEW**, with no known remaining
Blocker/High defect in the scoped local/static re-audit. The migration is suitable
for separately authorized application after human review. This is not a claim of successful SQL
execution or completed live authorization/concurrency checks. Human review and
explicit authorization still precede applying the migration.

## Phase 3A.2 local implementation (post-application; pending manual review)

The prior pre-migration notes above are historical and do not describe the current
deployment state. The project owner reports that the reviewed 3A.1 migration was
applied successfully. This local pass did not run SQL against Supabase.

The FastAPI `rrm.py` routes reuse Phase 1 JWT/profile/RBAC dependencies.
`rrm_repository.py` sends the same end-user bearer token and public Supabase key to
PostgREST, never the service-role credential. `rrm_service.py` composes source and
matrix reads, checks approved/parsed/current-effective evidence against the UTC date
and stored SHA-256, and exposes explicit readiness blockers. The SQL RPC remains
authoritative for immutable revisions, draft edit locks, issue resolutions,
separation of duties, source/config integrity, submission snapshots, audit and
ground-truth retrieval. API errors expose only allowlisted machine codes.

| Capability | HTTP route(s) |
|---|---|
| Candidates | `GET/POST /api/v1/requirements`, `GET /api/v1/requirements/{id}` |
| Source discovery | `GET /api/v1/rrm/evidence`, `GET /api/v1/rrm/evidence/{version_id}/chunks` |
| Authority setup | `GET/POST /api/v1/rrm/configs` (write Admin only) |
| Role matrices | `GET/POST /api/v1/roles/{role_id}/matrices`, `GET/PATCH /api/v1/matrices/{id}` |
| Decisions | `POST /api/v1/matrices/{id}/submit`, `/approve`, `/reject` |
| Issues | `POST /api/v1/matrices/{id}/issues`, `POST /api/v1/issues/{id}/resolve`; issue reads are in matrix detail |
| Ground truth | `GET /api/v1/roles/{role_id}/ground-truth` |

All lists are bounded. Candidate list supports search, origin, mandatory, author and
source-document filtering; matrix and evidence lists support offset/limit. New
candidate input is `MANUAL` and exact chunk IDs are rechecked server-side before the
creation RPC. The Next.js gateway explicitly allowlists these paths and PATCH,
checks write origin, requires a server-side session and caps RRM JSON writes. It is
not a wildcard proxy. The backend CORS method list adds PATCH only.

The `/app/requirements` workspace selects a role; displays candidates, approved
source versions, exact chunk text/locators and matrix revisions; creates manual
candidates and authority mappings; composes and saves draft entries/dependencies;
submits; displays issues/evidence/readiness; supports independent approve/reject;
and queries live ground truth. Draft edits create new immutable edit records.
Submitted/decided revisions are read-only. Admin emergency override has a distinct
control and requires a reason; the SQL actor/contributor check is authoritative.
Manager/Employee are denied by the protected page and FastAPI routes, not merely
by navigation. Reviewer cannot author; Training Manager cannot decide. A stale
ground-truth RPC is displayed as **not currently usable**, never as a partial set.

Known 3A.2 limitations before product approval: the UI records original timing
text as `AMBIGUOUS` and deliberately blocks its submission until separately
structured with exact spans. The matrix now includes `RRM_TIMING_MANUAL_REVIEW`
in its advisory readiness output, so the UI shows the original phrase and
disables submission. SQL `valid_timing` remains the final authority.

Authors can raise an `AMBIGUITY` issue on a DRAFT entry using the existing
user-JWT issue RPC. Open duplicate issues for the same requirement are avoided
in the UI; the database does not enforce a uniqueness constraint here. A
later UI correction removed an accidental matrix-creator visibility gate from
the issue action: Training Managers can raise an issue on a DRAFT they did not
create, as already allowed by the API/RPC. Edit and submit remain creator-only.
The live action requires retesting after this correction. A
Reviewer/Admin can record an independent reasoned resolution, but that never
changes the immutable requirement's timing. A new revision may mark timing
`STRUCTURED` only with exact linked-source spans for original text, trigger,
relation, value, unit and calendar basis. The UI never infers a trigger from
“Within 7 days.” If no approved source supplies the missing semantics, the
requirement remains `AMBIGUOUS` and the matrix remains blocked for manual
review. An author can atomically replace the predecessor in an owned DRAFT;
where a review issue references the predecessor, explicit acknowledgement is
required and the issue still needs independent resolution on the new edit.
No live matrix or requirement was changed by this UI implementation.
The API and UI support source-backed successor revisions, locked codes, fresh
evidence selection and atomic predecessor replacement in owned DRAFTs.
Advanced exception/downgrade editing is API/SQL-backed
but not yet exposed as a dedicated UI editor. Matrix candidate selection operates
on the currently loaded candidate page, so search/filter should be used to find
others. Ground truth displays structured requirement/evidence cards with a
technical hash; named document lookup for each snapshot source is still limited.
These are explicit UX
limits, not permission to bypass database gates. Semantic entailment still needs
independent human judgment.

Automated local checks: 15 new RRM API tests passed, exercising JWT forwarding,
role denials, candidate source checks, matrix lifecycle RPC invocation, stale edits,
reason/override boundaries, blocked ground truth and safe errors. Six frontend
RRM tests passed (request behavior/locator functions plus gateway/role-control
contract checks). Existing login regression and full backend suite must also pass
at final handoff; final counts are reported in the task response. These are
**AUTOMATED PASS**, not proof of a live SQL/RLS attack outcome.

**MANUAL LIVE TEST REQUIRED:** Training Manager approved source → candidate →
matrix → submit; independent Reviewer evidence inspection → approve; Admin approved
ground truth and snapshot; Manager/Employee API/page denial. Also retain the 3A.1
catalog ACL/RLS inspection, direct authenticated table/RPC writes, actor spoofing,
self-review, source-state and downgrade attacks, timezone/SQL-Python hash parity,
and concurrency tests. Phase 2 direct table/RPC/Storage attack checks remain as
separately documented. Phase 3B Gemini extraction is **NOT IMPLEMENTED**.

## Final QA — 2026-09-24

Earlier counts above are historical. See `PHASE3_FINAL_QA.md` for the current
audit, corrections, automated results and outstanding closure gates.
Backend: **287 passed**, one existing warning, normal exit 0; focused RRM:
**213 passed**. Frontend: **26 passed**, including **17 focused RRM tests**.
TypeScript, ESLint and production build passed.
Matrix relation pagination now prevents silent dependency/issue truncation;
structured timing spans use Python/SQL-compatible Unicode code-point offsets.
No migration or live row was changed. No signed-in browser session was available.
The earlier manual acceptance/security and dataset gap assessments were made
before the owner's final closure decisions. They are retained as historical
test provenance; the accepted Phase 7 deferrals are documented above and in
`PHASE3_FINAL_QA.md`. The matrix remains blocked by valid ambiguous timing.
