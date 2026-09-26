# Independent Python Validation Design

Status: **Phase 5 backend foundation implemented; pending migration and human review.** AI creates. Python verifies. JEV decides. Human controls. Checks compare structured attributes and references, not exact natural-language wording or semantic entailment.

## Implemented: python-validator/1.0.0

Pure Python `plan_validator.py`/`jev.py` check strict schema, request/employee identity, frozen role/department/location/experience applicability, mandatory module coverage, requirement-to-source/version/chunk/canonical-locator support, fixed stage identity/order/windows, mandatory/priority consistency, duplicates, dependencies/order/cycles and insufficient-information review. Every grounded child/rubric is checked. Consistent repetition is a warning; conflicting attributes block. Work mode is absent from the existing context and is not inferred.

Timing limitation: the output has stage windows/due-stage references but no per-module trigger/relation/value/unit/calendar tuple. Changed fixed windows produce TIMING_MISMATCH. Any source timing (structured or ambiguous) produces TIMING_UNRESOLVED/MANUAL_REVIEW. The current real Phase 4D deadline fixture cannot be VERIFIED. The 6/8/5 VERIFIED test fixture uses NOT_SPECIFIED timing; structured/ambiguous cases prove review. Phase 4 schema and live data are unchanged.

Entry requires a persisted UNVERIFIED plan, completed UNVERIFIED generation run, matching content/full-input hashes, projection/template provenance and active authorized actor. Current preflight rechecks authoritative state/source eligibility; outage aborts and stale input requires review. Comparison normalizes only the `as_of` date after current eligibility was checked. No document reparsing occurs.

## Persistence / API / human control

Unapplied migration `202609260002_python_validation_jev.sql` adds immutable validation_runs, validation_findings, jev_decisions and plan_review_actions. Linkage is plan → validation → finding → requirement → document/version/chunk/locator. Findings contain no source excerpts; unknown requirement IDs are recordable without an FK so invalid references remain auditable.

Caller JWT/RLS protects reads: Admin/Reviewer read all permitted validation results; Training Manager reads only their generation runs; Manager/Employee are denied. Admin/owning Training Manager may invoke validation. Direct writes are revoked for every role. Only the server-only trusted finalization RPC accepts computed Python results, following document-processing's existing service credential pattern; it rechecks actor/ownership and hashes. No browser JWT can forge findings/JEV. No service-role read shortcut is used.

Atomic persistence includes findings, JEV and audit. Unique identity is plan ID + validator version + content/input/projection hashes. Concurrent requests serialize per plan. Same evidence replays the same ID; changed evidence for the same identity conflicts without overwriting history. Timestamps are excluded from result hashing. Verified persistence and approval recheck database state under locks. Findings use counted bounded pages; incomplete retrieval fails closed.

Routes: POST `/api/v1/generated-plans/{plan_id}/validate`; GET `/api/v1/validation-runs/{validation_id}`; GET `/api/v1/generated-plans/{plan_id}/validation`; POST `/api/v1/validation-runs/{validation_id}/review`.

Reviewer/Admin actions: APPROVE, REJECT, REGENERATE, OVERRIDE. Meaningful reasons are required (1–2000 characters). APPROVE requires verified JEV plus current input. OVERRIDE is Admin-only and records a distinct disposition without changing JEV. Creator/employee self-review is denied even with multiple roles. Actions/reasons are immutable and audited. REGENERATE is a request only; publication/assignment/provider execution are outside this foundation. Phase 4 plans remain UNVERIFIED.

## Earlier design backlog (not additional implementation claims)

Automated foundation verification: 53 focused Phase 5 tests (pure validator/JEV, API/RBAC, repository and SQL contracts); full backend 474 passed, one existing warning, exit 0. Migration static verdict: SAFE_TO_APPLY after human review, unapplied. No live RLS/transaction/concurrency claim is made; provider execution and live validation were not performed. Diff/whitespace and scoped secret-pattern checks passed.

The following original design includes later work. General prose entailment, quiz-answer factual correctness, artifact-specific requirements absent from the frozen model, pedagogical quality and natural-language contradictions remain human responsibilities/future contracts. VERIFIED means the implemented structured checks passed, never autonomous publication or proof of every sentence.

## Common output

Each validator emits zero or more issues: `rule_code`, `validator_version`, `severity`, `entity_path`, `expected`, `actual`, `requirement_id`, evidence IDs, explanation, and recommended action. Severity is `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Metrics retain numerator/denominator. JEV uses issue codes and metrics, never prose guessing.

| Validator | INPUT | RULE | OUTPUT | SEVERITY | JEV EFFECT |
|---|---|---|---|---|---|
| Schema | Raw parsed JSON + schema version | Pydantic/JSON Schema; required fields, types, enums, bounds, unique IDs, forbidden extras | path-specific schema issues | ERROR; CRITICAL for control-field spoofing | `INCOMPLETE`; suspicious control spoofing `MANUAL_REVIEW` |
| Mandatory coverage | Approved role requirements + item mappings | Set containment; covered only when a valid item maps to the exact mandatory requirement and required artifact type | covered/total, missing IDs, exact score | ERROR | `<100%` -> `INCOMPLETE` |
| Traceability | Items, requirement/source edges, frozen source set | Mandatory factual items have resolvable approved chunk/version citations supporting mapped requirement; compute valid/required | missing/invalid citation issues and score | ERROR/CRITICAL | unsupported mandatory -> `UNSUPPORTED`; invalid critical source -> `MANUAL_REVIEW` |
| Source validity | Document versions/chunks, effective date, access/approval | IDs exist, chunk belongs to version, version approved/active for plan date, not expired/superseded, hash matches snapshot | invalid/stale source findings | ERROR/CRITICAL | critical invalid/stale -> `MANUAL_REVIEW`; otherwise warning |
| Policy version | Plan snapshot + RRM sources + current approval graph | Required policy version equals approved effective version; precedence winner used | outdated/mixed-version issues | ERROR/CRITICAL | `MANUAL_REVIEW`; possibly `CONTRADICTORY` when conflicting instructions remain |
| Role relevance | Employee context + applicability predicates + item requirement mappings | Every mandatory assignment applies to role/department/location/level; unrelated requirement mappings are forbidden | irrelevant/misassigned IDs | WARNING/ERROR | blocking irrelevant mandatory/factual item -> `MANUAL_REVIEW`; minor -> warning |
| Unsupported content | Claims/items + cited requirements/chunks | Exact identifiers and rule-based permitted templates must resolve; uncited factual claims are unsupported candidates | unsupported item/claim findings | ERROR/CRITICAL | mandatory factual -> `UNSUPPORTED`; uncertain wording -> `MANUAL_REVIEW` |
| Duplicate content | Normalized item fields + IDs | Exact normalized hash, same requirement/type, or high deterministic token similarity detects candidates | duplicate groups | WARNING/ERROR | missing unique required coverage -> `INCOMPLETE`; otherwise warning/review |
| Contradiction | Requirements, precedence rules, normalized structured attributes | Conflicting enumerated obligations/prohibitions, dates, limits, answers, or mutually exclusive states; apply precedence | conflict pair, authority result | CRITICAL if unresolved; WARNING if resolved | unresolved critical -> `CONTRADICTORY`; resolved -> warning |
| Prerequisite/sequence | Module DAG, stages, due days, assessment links | All refs exist; graph acyclic; prerequisite precedes dependent; learning precedes assessment; configured stage capacity honored | cycles/order violations | ERROR | `INCOMPLETE`; ambiguous dependency -> `MANUAL_REVIEW` |
| Quiz evidence | Questions/options/answers/explanations/citations | Valid question type; answer cardinality; correct answer traceable; explanation consistent with structured source facts; no duplicate options | question-level issues | ERROR/CRITICAL | unsupported answer -> `UNSUPPORTED`; missing quiz -> `INCOMPLETE` |
| Assessment evidence | Assessment/rubric + requirement | Required assessment exists; rubric fields present; weights total 100; pass rule valid; competency mapped | assessment/rubric issues | ERROR | `INCOMPLETE` or `MANUAL_REVIEW` for subjective support |
| Checklist/task completeness | RRM artifact obligations + item fields | Required artifacts exist with outcome, completion criteria, due stage, responsible role where required, citations | missing field/artifact issues | ERROR | `INCOMPLETE` |
| Consistency | Two or more controlled run projections | Compare sets of mandatory requirement IDs, source IDs, categories, assessment topics; Jaccard/field agreement | per-field and aggregate score, differences | WARNING/ERROR threshold config | major unexplained difference -> `MANUAL_REVIEW` |
| Prompt/security | Output strings + security findings | Reject instruction leakage, tool requests, secret patterns, external actions, HTML/script/control fields | security issues | CRITICAL | `MANUAL_REVIEW`; never VERIFIED |
| Business rules | Plan + versioned rule config | Stage distribution, duration bounds, allowed categories, no all-training-on-Day-1, company-specific invariants | rule-code findings | WARNING/ERROR | blocking -> `INCOMPLETE`; minor -> warning |

## Metric definitions

- Mandatory coverage = `validly covered mandatory requirement IDs / applicable mandatory requirement IDs * 100`.
- Mandatory traceability = `mandatory factual items with valid approved citations / mandatory factual items requiring citations * 100`.
- Requirement consistency = weighted agreement of role, mandatory flag, priority, due stage, competency, source, required task, and assessment topic against RRM.
- Generation consistency = weighted set/field agreement between controlled runs; wording is excluded.

Define zero-denominator behavior explicitly: a role with zero approved mandatory requirements is a ground-truth configuration error and routes to review, not an automatic 100%.

## What cannot be reliably deterministic

Human review is required for nuanced semantic entailment, whether instructional paraphrasing materially changes policy meaning, genuinely ambiguous clauses, conflicts not expressed in normalized attributes, quality/plausibility of quiz distractors, pedagogical quality, fairness, tone, subjective task difficulty, and exception interpretation. OCR is out of MVP: scanned or unextractable PDFs become `NEEDS_REVIEW`. Embeddings are not required for MVP; a post-competition similarity feature may prioritize review only if testing demonstrates need, and must never become proof. New candidate requirements extracted from prose also require approval before becoming ground truth.

## Execution and isolation

Run validators after schema acceptance and before JEV. Pin rule-set and schema versions; execute from immutable snapshots; persist the input hash. A validator crash creates a critical `VALIDATOR_FAILURE` and `MANUAL_REVIEW`, never success. Unit tests use golden fixtures and mutation tests; integration tests prove the validation package runs with network disabled and without importing the GenAI provider package.
