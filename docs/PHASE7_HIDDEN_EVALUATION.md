# Phase 7 — hidden evaluation, adversarial inputs and resilience

Date: 2026-09-26. Scope: offline code/tests only. Fictional SkillSprint Technologies
fixtures are TEST/EVALUATION data, not seed data or production success evidence.
No external provider, live database or browser was used. No migration was changed.

## Coverage audit before additions

Existing tests already cover PDF/DOCX extraction, source locators, scanned/invalid
files, upload/review roles, immutable versions and current-effective SQL contracts
(`test_documents.py`); typed applicability, precedence, explicit exceptions,
ambiguity, immutable revisions, stale snapshots and all-contributor self-review
(`test_rrm*.py`); frozen context, JSON schema, prompt golden pins, bounded projection,
provider MockTransport failures, retries, idempotent replay and postflight staleness
(`test_generation*.py`); all six JEV outcomes, evidence, review authorization,
backend-only findings, hash-bound idempotency and immutable SQL evidence
(`test_validation*.py`). Foundation tests check the complete original RBAC matrix.

New tests therefore focus on unseen data, combinatorial mandatory omission,
cross-reference attacks, all JEV blocker codes, exact size-boundary behavior,
Unicode parsing and malformed response resilience. Existing tests are reused as
evidence rather than copied. Factories in `services/api/tests/phase7_fixtures.py`
reuse the six-requirement/eight-dependency/five-stage structural fixture with new
evaluation labels. They use fixed IDs/dates and no random data or wall-clock rules.
The new suite denies external socket connections (Windows asyncio's internal
loopback wakeup socket remains allowed); provider simulations use in-memory fakes.

## Scenario outcomes

Test names below are in `services/api/tests/`. P7 means
`test_phase7_evaluation.py`; references identify executable evidence, not live SQL.

| ID | Scenario / expected | Actual outcome | Result / evidence / component |
|---|---|---|---|
| H01 | Unseen supported policy retains provenance, requires approval | New DOCX parsed into chunk; hash/locator retained through context; DRAFT source blocked | PASS — P7 `test_h01_unseen_docx_to_ground_truth_with_traceability`; parser/RRM. Existing document review API tests cover workflow authorization |
| H02 | Revised policy makes old evidence stale, preserves history | Changed current-version ID rejects v1; v2 changes input hash; original object unchanged | PASS — P7 `test_h02_h05_policy_revision_preserves_history_and_rejects_old_source`; RRM/context; current-effective/lineage SQL contracts in document/RRM suites |
| H03 | New role participates without code-specific inference | EVAL_LAB_COORDINATOR passes; mismatched role blocked | PASS — P7 `test_h03_unseen_business_role_is_data_driven`; applicability/context |
| H04 | Configured policy outranks conflicting FAQ, both remain evidence | Deterministic rank chooses policy; equal authority requires review; existing snapshot keeps linked evidence | PASS — P7 `test_h04_h10_configured_authority_and_explicit_role_exception`, RRM snapshot/precedence tests; no LLM conflict interpretation claimed |
| H05 | Outdated SOP/source cannot override current truth | Ineligible old version blocked; stale context yields review | PASS — P7 H02/H05, `test_validation.py::test_stale_context_never_verifies`, `test_rrm.py::test_one_stale_source_blocks_whole_multi_source_requirement` |
| H06 | Missing mandatory control blocks VERIFIED | Missing final control → INCOMPLETE with exact requirement/source evidence; removing prerequisites can additionally yield higher-precedence CONTRADICTORY | PASS — P7 six omission cases; validator/JEV |
| H07 | Injection text cannot directly approve or alter trusted contract | Poisoned text confined to escaped data; template/system unchanged; missing control stays INCOMPLETE; status=VERIFIED output rejected | PASS — P7 `test_h07_injection_cannot_redefine_contract_or_decision`; prompt/schema/validator. Not a claim that a live LLM will resist every injection |
| H08 | Unknown requirement → UNSUPPORTED | Appended foreign UUID rejected by ingestion and validator | PASS — P7 `test_h08_h15_h22_foreign_reference_fails_closed[requirement_ids]` |
| H09 | Mandatory compliance/applicability/source support survives | Each of six omitted mandatory controls blocks positive decision; missing finding retains source identity | PASS — P7 H06/H09 plus existing context scope/timing preservation tests |
| H10 | Explicit approved applicable role exception wins only for that role | Unapproved/non-applicable exception loses; approved role exception selects specific requirement and retains both sources | PASS — P7 H04/H10; `test_rrm.py::test_explicit_role_exception_keeps_general_and_specific_evidence` |
| H11 | Promptly/ambiguous deadline is not invented | Projection retains null value/trigger; TIMING_UNRESOLVED → MANUAL_REVIEW | PASS — P7 `test_h11_ambiguous_promptly_does_not_acquire_a_deadline` |
| H12 | Requirement deadline 2 versus generated 5 → CONTRADICTORY | Fixed stage-window contradiction does produce CONTRADICTORY. Requirement-level deadline tuple cannot be expressed by output v1; existing structured-source timing correctly yields MANUAL_REVIEW | LIMITED — P7 `test_h12_fixed_window_contradiction_is_not_deadline_inference`; `test_validation.py::test_timing_without_output_timing_tuple_requires_review`. Exact requested deadline comparison is NOT proven |
| H13 | Missing/reversed prerequisite → blocking contradiction | Missing edge/order/cycle detected | PASS — P7 H13/H14; `test_validation.py::test_cycle_and_order_are_detected` |
| H14 | Distinguish benign versus contradictory duplication | Consistent duplicate → VERIFIED_WITH_WARNING; mandatory conflict → CONTRADICTORY | PASS — P7 H13/H14 |
| H15 | Unknown source version/chunk/locator fails closed | UNSUPPORTED and ingestion rejection; extra unknown document field is forbidden by strict output contract | PASS — P7 foreign-reference cases, existing structural-rejection tests |
| H16 | Changed authority cannot silently validate old frozen input | MANUAL_REVIEW; old plan/hash unchanged; postflight never publishes stale result | PASS — P7 H16; `test_generation_api.py::test_stale_postflight_never_publishes_plan` |
| H17 | Malformed JSON/fields/IDs/stages rejected | Invalid scalar/deep JSON controlled; missing/extra/type/duplicate/reference attacks rejected; no partial accepted plan | PASS — P7 H17 plus `test_generation_service.py::test_structural_rejections` and `test_array_bound_and_duplicate_json_keys` |
| H18 | Offline timeout/429/5xx/malformed response respects budgets | Timeout/5xx max3; 429 without safe delay1; one short Retry-After retry only; malformed format max2; failed attempt retained | PASS — P7 H18, existing provider MockTransport/service/API tests |
| H19 | Replay does not regenerate or create conflicting duplicates | Fake-store replay skips provider; SQL uniqueness/conflict/hash checks present | PASS (unit/static) — `test_generation_api.py::test_replay_does_not_call_provider`, `test_generation_sql_contract.py::test_generation_lifecycle_idempotency_and_stale_guards`. Real concurrent SQL transactions NOT executed |
| H20 | Unauthorized privileged actions denied | API role matrices return403; Employee review/override denied, Manager validation denied, dual-role author self-review denied | PASS — P7 H20; foundation/RRM/generation/validation API role tests; SQL all-contributor guard contracts |
| H21 | Override abuse rejected; valid action preserves evidence | Blank/Unicode whitespace/oversize reasons rejected; valid Admin request forwarded; append-only audit/original JEV retention statically asserted | PASS (unit/static) — P7 H21; validation API and SQL review tests. Live audit insertion NOT claimed |
| H22 | Foreign context IDs fail closed | Unknown requirement/source/stage and employee-role mismatch rejected | PASS — P7 foreign-reference cases; existing generation structural/context tests |
| H23 | Empty/unapproved/incomplete input blocks safely | BLOCKED with canonical code and no snapshot/provider work; missing DB row404 and absent employee canonical blocker | PASS — P7 H23, existing generation preflight and validation missing-plan tests |
| H24 | Bounded input never silently truncates | Exact projection byte bound accepted; one byte lower fails guard with identical full data; existing oversized test proves zero fake-provider invocations | PASS — P7 H24; service/Groq final wire-body guard tests. Not a heap/load benchmark |
| H25 | Unicode/hostile text parses safely | Multilingual DOCX deterministic locators/hashes; invalid Unicode provider text now rejects and records attempts | PASS after fix — P7 H25 and H18/H25 |

Summary: **25 explicit outcomes: 24 PASS, 1 LIMITED (H12 exact deadline tuple)**.
No known remaining Critical/High defect found within the exercised scope. This is
not blanket assurance about unexecuted live database concurrency or model behavior.

## Defect and bounded correction

F7-01: `parse_plan` encoded provider text before its guarded parsing path. An
unpaired surrogate caused UnicodeEncodeError, losing normal malformed-output
classification/attempt recording. Reproduced first as a failing test. Corrected
only `generation_service.py`: invalid Unicode becomes MALFORMED_JSON; failure
telemetry uses null hash/size when valid UTF-8 bytes do not exist. It never repairs
or accepts text, fabricates a fingerprint, or stores raw content. Existing bounded
format retry remains unchanged. The existing SQL contract allows null hash/size
for SCHEMA_INVALID (requires them only for SCHEMA_VALID); no migration needed.
Regression proves two failed attempts, no plan, no VERIFIED output.

An initial test expected UNSUPPORTED after replacing a prerequisite reference;
actual CONTRADICTORY was correct because a dependency also broke and has higher
JEV precedence. The isolated hallucination case appends an unknown reference;
production JEV precedence was not changed to satisfy the test.

## Validator/JEV and security invariants

All JEV blocking codes tested against otherwise positive evidence prevent VERIFIED.
Validator and JEV have no provider dependency; injected client findings are ignored
by the production validation API, which computes its own evidence. Privileged
finalization ACL and read-only authenticated table grants are SQL/static evidence.
Human dispositions append separately without erasing original decisions. Exact
source identity is retained in findings. Prose entailment and deadline inference
are not claimed; unresolved structured timing remains MANUAL_REVIEW.

## Fixture-specific production hardcoding audit

Searched backend/frontend for fixture IDs, codes, role labels and equality branches.
No evaluation-specific approval, eligibility, validator, JEV or role-selection
branch was found in backend domain logic. Existing deliberate exceptions are:

- restricted `apps/web/src/lib/phase4d-test.ts`: fixed internal test employee;
- product directory/plans UI: `P4D` prefix labels fictional fixtures only;
- requirement form/message: SECURITY_TRAINING example placeholder.

These are disclosed, not claimed absent; none grants access, fabricates success or
changes deterministic rules. Phase 7 fixture identities live only in tests.

## Competition dataset readiness — not test-case counts

No versioned `sample_data/` competition pack/inventory was found. Existing local
unit factories and the new evaluation pack are NOT a reviewed 20-document dataset.
No live count query was authorized/performed in this offline task. Prior controlled
fixture evidence does not establish a complete current live inventory.

| Inventory | CURRENT evidenced complete competition count | TARGET | GAP |
|---|---|---:|---|
| Documents | Unknown; no inventory manifest | >=20 | Unquantified; inventory/source review required |
| Job roles | Unknown; no inventory manifest | >=10 | Unquantified |
| Requirements | Unknown; no inventory manifest | >=150 | Unquantified |
| Mandatory requirements | Unknown; no inventory manifest | >=50 | Unquantified |
| Role-specific requirements | Unknown; no inventory manifest | >=30 | Unquantified |
| Conflict/ambiguity cases | Unknown as reviewed dataset | >=10 | Unquantified |
| Policy-version changes | Unknown as reviewed dataset | >=10 | Unquantified |
| Adversarial cases | Unknown as reviewed dataset | >=10 | Unquantified |

The evaluation factory has six obligation records, one unseen role, multilingual
and injection source text and a 7-to-3 revision scenario. Parametrized test counts
must not be relabeled as unique reviewed competition documents or requirements.
Dataset readiness is **NOT ESTABLISHED**, and remains a competition-delivery gap.

## Quality gates and evidence levels

- Focused new Phase 7 suite: **43 passed**.
- Relevant document/RRM/generation/validator/JEV/RBAC/SQL regression selection:
  **517 passed**, one existing Starlette deprecation warning.
- Full backend suite: **526 passed**, one existing warning; normal exit0.
- Frontend unchanged; no frontend rerun required.
- Final diff/whitespace check: PASS. Scoped credential-pattern scan: zero matches.
  An unrelated generated `apps/web/next-env.d.ts` change appeared after the
  interrupted turn; it was not edited or reverted by this Phase 7 work.
- UNIT/FIXTURE VERIFIED: outcomes above, including fake-provider retry counts.
- STATICALLY VERIFIED: prompt separation, SQL grants/immutability/concurrency
  contracts and production fixture-hardcoding review.
- LIVE DATABASE VERIFIED this phase: **none**.
- LIVE PROVIDER VERIFIED this phase: **none; external provider calls = 0**.
- BROWSER VERIFIED this phase: **none**.

Run locally from `services/api` using the existing Python3.12 environment:
`D:\SkillSprint-AI\tmp\phase4d-py312\Scripts\python.exe -m pytest tests/test_phase7_evaluation.py -q`
and `D:\SkillSprint-AI\tmp\phase4d-py312\Scripts\python.exe -m pytest -q`.

Ready for review of offline safety evidence, not a claim that all SRS competition
dataset obligations or H12's absent requirement-timing output representation are
complete. No schema/prompt/provider policy change was made to hide those limits.
