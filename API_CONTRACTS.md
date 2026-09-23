# REST API Contracts

Status: **Phase 0 target contracts; Phase 1 and the Phase 2 document subset are implemented as noted below, while later routes remain planned**. The MVP serves one fictional organization. Base path `/api/v1`; JSON UTF-8; UUID identifiers; ISO-8601 UTC times. Authentication uses Supabase bearer JWT verified by FastAPI. RBAC/RLS apply within the single organization; no tenant identifier is accepted or derived. Errors use `application/problem+json` with `type`, `title`, `status`, `code`, `detail`, `instance`, `correlation_id`, and field errors. Later-phase list endpoints target cursor pagination, bounded `limit`, sort, and domain filters; the implemented Phase 2 list uses a bounded initial result with client-side search/filter.

Role abbreviations: A=Admin, TM=Training Manager, R=Reviewer, M=Manager, E=Employee.

## Authentication and profiles

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `GET /me` | all | - -> profile, roles, permissions | 401 invalid token; 403 inactive profile |
| `GET /employees` | A,TM,R,M(scoped) | filters role/department/status -> page | filter allowlist; 403 scope |
| `POST /employees` | A,TM | employee context -> employee | role/department exist and align; unique code; 400/409/422 |
| `GET/PATCH /employees/{id}` | A,TM; M scoped; E self read | patchable profile fields -> employee | optimistic `If-Match`; no sensitive fields; 403/404/409/422 |
| `GET/POST /departments` | read A,TM,R,M; write A | filters/body -> page/entity | hierarchy cycle and unique code; 409/422 |
| `GET/POST /roles` | read A,TM,R,M; write A,TM | role body -> entity | data-driven code; valid department; 409/422 |
| `PATCH /roles/{id}` | A,TM | changes -> role | cannot archive with unresolved assignments without explicit policy; 409 |

## Documents

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `POST /documents/uploads` | A,TM | multipart file + code/title/category/optional department/version/effective/expiry -> `202` draft version + final synchronous processing result in Phase 2 | PDF/DOCX signature; configurable initial limit 15 MB; duplicate hash/date order; scanned or unextractable PDF -> NEEDS_REVIEW; 413/415/409/422 |
| `GET /documents` | A,TM,R | `offset`, `limit<=100` -> `{items,offset,limit,has_more}`; UI search/filter is page-local in Phase 2 | access scope; invalid page 422 |
| `GET /documents/{id}` | A,TM,R | - -> logical doc + versions | 404/403 |
| `GET /documents/{id}/current-effective-version` | A,TM,R | optional `on_date` -> approved, parsed, date-effective version or null | reusable database rule, not latest-created |
| `GET /document-versions/{id}` | A,TM,R | - -> version metadata and processing status | 404/403 |
| `GET /document-versions/{id}/original` | A,TM,R | - -> private original attachment via user-scoped Storage | 404/403 |
| `GET /document-versions/{id}/chunks` | A,TM,R | `offset`, `limit<=100` -> `{items,offset,limit,has_more}` traceable chunks | review permission; 403/422 |
| `POST /document-versions/{id}/retry` | uploader A/TM | optional original file -> `202` processing result | only stranded UPLOADED/PROCESSING draft; stored/replaced bytes must match reserved SHA-256 and size |
| `POST /document-versions/{id}/submit` | TM,A | comment, expected status -> submitted version | draft complete; records creator/submitter; 409/422 |
| `POST /document-versions/{id}/approve` | R,A | `reason`, `admin_override` (explicit Admin self-review only) -> approved version | successful parse; uploader/submitter cannot review own version unless Admin override with reason; creator and approver audited; 403/409/422 |
| `POST /document-versions/{id}/reject` | R,A | required `reason`, `admin_override` if Admin self-review -> rejected | same actor-identity separation; 403/409/422 |
| `GET /jobs/{id}` | initiating roles | - -> state, progress, safe error | 403/404 |

Phase 2 implements synchronous Python parsing inside the upload request, so the `202` response carries `document_id`, `version_id`, `parse_status`, `review_status`, `chunk_count`, and a safe `reason_code`; it does **not** claim a durable job ID. The planned `/jobs/{id}` route is not implemented in Phase 2. All Phase 2 document routes use the `/api/v1` base path.

The upload body has a bounded gateway/API request envelope in addition to the Python file-size check. Authoring RPCs use the user's JWT; only the backend infrastructure adapter may invoke the service-role-only processing finalization RPC. The service credential never appears in browser code or API output.

## Requirements and RRM

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `GET/POST /requirements` | read A,TM,R; draft A,TM | structured requirement/source refs -> draft entity | citations must reference reviewable/approved sources; enum/applicability; 409/422 |
| `PATCH /requirements/{id}` | A,TM | changes -> new revision | approved requirement immutable; create revision; 409 |
| `GET /roles/{role_id}/matrices` | A,TM,R | - -> revisions | 404 |
| `POST /roles/{role_id}/matrices` | A,TM | requirement mappings, conditions, prerequisites -> draft | IDs valid, no cycles/duplicates, source-backed; creator recorded; 409/422 |
| `POST /matrices/{id}/submit` | TM,A | comment, expected status -> submitted revision | draft complete; submitter audited; 409/422 |
| `POST /matrices/{id}/approve` | R,A | comment; Admin emergency override reason when applicable -> frozen snapshot | only approved/current-effective sources; approved role exception may outrank general policy; unresolved conflicts forbidden; TM self-approval forbidden; creator/approver recorded; 403/409/422 |
| `POST /matrices/{id}/reject` | R,A | required reason -> rejected revision | valid transition; creator/decider audited; 403/409/422 |
| `GET /matrices/{id}/coverage-preview` | A,TM,R | employee context -> applicable requirements | applicability config valid; 422 |

## Generation and plans

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `POST /generation-runs` | A,TM | employee_id, optional stage config, idempotency key -> `202` run | active approved RRM/source set; no concurrent duplicate; 409/422/429/503 |
| `GET /generation-runs/{id}` | A,TM,R | - -> metadata/status/retries (raw body restricted) | 403/404 |
| `GET /plans` | A,TM,R,M scoped,E self | filters -> page | scope; 403 |
| `GET /plans/{id}` | A,TM,R,M scoped,E self assigned | - -> current allowed revision, items, citations, JEV summary | draft visibility by role; 403/404 |
| `GET /plans/{id}/revisions/{rev}` | A,TM,R | - -> immutable revision/evidence | 403/404 |
| `POST /plans/{id}/regenerations` | A,TM,R | target requirement/item IDs, reason -> `202` run | targets belong to plan/issues; bounded retries; 409/422/429 |
| `POST /plans/{id}/finalize` | A,TM | expected revision -> final plan | VERIFIED/allowed reviewed disposition, concurrency; 409/422 |

## Validation and JEV

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `POST /plan-revisions/{id}/validations` | A,TM,R | optional rule-set version + idempotency -> `202` run | immutable complete revision; known rules; 409/422 |
| `GET /validation-runs/{id}` | A,TM,R | - -> metrics/issues/JEV link | 403/404 |
| `GET /validation-runs/{id}/issues` | A,TM,R | severity/code/status filters -> page | 400 |
| `GET /jev-decisions/{id}` | A,TM,R | - -> decision, matched rule, reasons/evidence/action | 403/404 |
| `POST /jev-decisions/{id}/replay` | A | expected rule version -> reproducibility result, no mutation | evidence available; 409/422 |

## Human review

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `GET /reviews/queue` | A,R,TM | filters/assignee -> page | scope; 403 |
| `POST /reviews/{decision_id}/actions` | A,R | action, required reason/comment, optional edited structured item | append-only review + resulting state/run | allowed transition; override permission; edit schema; 403/409/422 |
| `GET /plans/{id}/review-history` | A,TM,R | - -> decision/review audit timeline | 403/404 |

Actions are `APPROVE`, `REJECT`, `EDIT`, `REGENERATE`, `OVERRIDE`. Reason is mandatory for reject, edit, regenerate, and override. Edit creates a new revision then validation/JEV; it cannot directly mark content verified.

## Policy updates and impact

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `POST /document-versions/{id}/impact-analyses` | A,TM | predecessor version ID -> `202` analysis | same logical doc, candidate parsed; 409/422 |
| `GET /impact-analyses/{id}` | A,TM,R | - -> changed chunks/requirements/items/plans/employees | 403/404 |
| `POST /impact-analyses/{id}/submit` | A,TM | selected changes + comment -> submitted update | impact complete; creator/submitter recorded; 409/422 |
| `POST /impact-analyses/{id}/apply` | A,R | approved changes, activation time, reason if Admin emergency override -> result | source/RRM approvals complete, unresolved conflicts -> MANUAL_REVIEW, atomic activation; creator/approver audited; 409/422 |
| `POST /impact-analyses/{id}/regenerations` | A,TM | selected affected item IDs + reason -> batch `202` | only affected/stale targets; 409/422 |

## Progress, dashboards, reports

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `GET /employees/{id}/progress` | A,TM,M scoped,E self | - -> item/overall progress, milestones, weak areas | scope; 403/404 |
| `PATCH /progress/{id}` | A,TM,M scoped,E self for allowed completion | status/evidence/score + version -> progress | legal transitions, score bounds; 403/409/422 |
| `GET /dashboards/admin` | A,TM | filters -> aggregate metrics | bounded dates; 400 |
| `GET /dashboards/roles/{id}` | A,TM,R,M | filters -> requirements/completion | scope; 403 |
| `GET /reports` | A,TM,R,M scoped | type + filters -> report descriptor/data | allowed type and scope; 400/403 |
| `POST /reports/{type}/exports` | A,TM | filters, format CSV/JSON -> `202` export | CSV formula-injection escaping, row limits; PDF/XLSX are non-critical extensions; 422/429 |

## Audit

| Method/path | Roles | Request -> response | Major validation / errors |
|---|---|---|---|
| `GET /audit-logs` | A; R limited to review targets | filters -> redacted page | immutable/read-only; sensitive metadata redacted; 403 |

Mutating requests log actor, correlation ID, target, safe before/after hashes, and reason. Approval events also log original creator, submitter, approver, decision, and Admin emergency-override flag/reason. A Training Manager cannot normally approve a document or RRM draft they created. Rate limits are stricter for upload, generation, regeneration, export, and login. `404` may replace `403` where resource existence must not leak.
