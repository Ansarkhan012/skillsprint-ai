# SRS Traceability and Priority Matrix

Status: **Planning traceability baseline; implementation status varies by phase.** Phase 0/1/2 are locked, and Phase 3 is a complete/locked candidate pending its final commit. Phase 3 closeout explicitly deferred the final competition dataset inventory and expanded adversarial/live database attack verification to Phase 7; the SRS targets remain unchanged.
Source: SRS v1.0 sections 1.1-1.10. Priority labels are **engineering interpretation** for a ~3-day competition build unless marked `SRS explicit`. MUST means required for the core evaluated path or expressly mandatory; SHOULD means required by the SRS but sequenced after the core path; NICE means optional/extension wording or deferrable polish. This prioritization does not waive any SRS final-deliverable obligation.

Legend: F=Foundation, DI=Document Intelligence, RRM=Ground Truth, G=GenAI, VJ=Validation/JEV, UI=Product UI, QA=Hidden Evaluation/QA, D=Deployment/Submission.

## Functional requirements (SRS 1.6, i-lxvi)

| ID / SRS requirement | Priority | Implementation module | Planned API/service | Data/entity | Validation/test | Phase |
|---|---|---|---|---|---|---|
| FR-01 User authentication | MUST (SRS explicit) | auth | Supabase Auth, `/me` | profiles | invalid/expired JWT | F |
| FR-02 role-based access | MUST | security | auth dependency/RLS | profile_roles | five-role denial matrix within one organization | F |
| FR-03 employee profiles | MUST | employees | `/employees` | employees | CRUD, scope, constraints | F |
| FR-04 role management | MUST | roles | `/roles` | roles | new hidden role without code | F/RRM |
| FR-05 document upload | MUST | documents | `/documents/uploads` | documents/versions | PDF/DOCX upload | DI |
| FR-06 document validation | MUST | documents/security | upload service | versions/findings | type/hash/metadata/version/configurable 15 MB limit | DI |
| FR-07 Python parsing | MUST | document_processing | parse job | versions/chunks | golden PDF/DOCX | DI |
| FR-08 traceable chunking | MUST | document_processing | chunk job | chunks | boundary/overlap/location | DI |
| FR-09 source metadata | MUST | documents | chunk query | chunks | lineage integrity | DI |
| FR-10 version control | MUST | documents | approve/supersede | versions | active/obsolete/effective dates | DI |
| FR-11 requirement extraction | MUST | requirements | candidate/approval service | requirements/sources | mandatory-vs-optional fixtures | RRM |
| FR-12 Role Requirement Matrix | MUST | role_matrix | draft/submit/Reviewer-or-Admin approval APIs | matrices/role_requirements | coverage/source/approval separation | RRM |
| FR-13 GenAI integration | MUST | genai/providers | generation service | generation_runs | mocked provider + live smoke | G |
| FR-14 structured prompts | MUST | genai/prompts | prompt registry | prompt_versions | snapshot/version tests | G |
| FR-15 structured JSON | MUST | genai/contracts | provider adapter | plan_revisions | contract fixtures | G |
| FR-16 JSON validation | MUST | validation/schema | schema validator | validation issues | malformed/type/extra fields | VJ |
| FR-17 personalized plan | MUST | plans | generation API | plans/revisions | role/employee variation | G |
| FR-18 multi-stage onboarding | MUST | plans/config | generation API | stage plan_items | order/config/no Day-1 overload | G/VJ |
| FR-19 modules | MUST | plans | generation API | plan_items | required fields | G |
| FR-20 objectives | MUST | plans | generation API | item content | measurable/source mapped | G/VJ |
| FR-21 checklists | MUST | plans | generation API | plan_items | required/due/source/responsible | G/VJ |
| FR-22 tasks | MUST | plans | generation API | plan_items | role/outcome/completion/due | G/VJ |
| FR-23 scenarios | SHOULD | plans | generation API | plan_items | approved-process grounding | G/VJ |
| FR-24 quizzes | MUST | plans | generation API | plan_items | supported types/source | G |
| FR-25 quiz answer validation | MUST | validation | quiz validator | issues/sources | correct answer evidence | VJ |
| FR-26 assessments | MUST | plans | generation API | plan_items | knowledge/practical/role types | G |
| FR-27 assessment rubrics | MUST | plans/validation | generation API | item content | fields/weights/pass rule | G/VJ |
| FR-28 prerequisites | MUST | plans | generation API | item dependency | graph fixtures | G/VJ |
| FR-29 sequence validation | MUST | validation | sequence validator | validation issues | cycles/order/assessment-before-content | VJ |
| FR-30 source citation | MUST | traceability | plan evidence endpoint | item_sources | random statement trace-back | G/VJ |
| FR-31 independent Python validation | MUST (SRS explicit) | validation | validation runs | validation_runs | network-off/import-boundary test | VJ |
| FR-32 mandatory coverage | MUST | validation | coverage validator | requirement edges | missing requirement | VJ |
| FR-33 coverage score | MUST | validation | validation result | run metrics | numerator/denominator/boundaries | VJ |
| FR-34 traceability score | MUST | validation | validation result | run metrics | valid-source ratio | VJ |
| FR-35 hallucination detection | MUST | validation | support validator | issues | unsupported topic/claim | VJ/QA |
| FR-36 contradiction detection | MUST | validation | conflict validator | issues/precedence | policy/SOP/FAQ conflicts | VJ/QA |
| FR-37 policy precedence | MUST | ground truth/config | precedence service | precedence_rules | configurable winner/ambiguity | RRM/VJ |
| FR-38 duplicate detection | SHOULD | validation | duplicate validator | issues | exact/near duplicate fixtures | VJ |
| FR-39 role relevance | MUST | validation | relevance validator | applicability/issues | valid-but-wrong-role | VJ |
| FR-40 consistency testing | SHOULD | genai/validation | repeated run service | generation_runs | controlled repeated runs | QA |
| FR-41 consistency score | SHOULD | validation | consistency validator | run metrics | structured-set comparison | QA |
| FR-42 GenAI/Python comparison | MUST | comparison | validation detail | issues/metrics | 100-result report fixture | VJ/QA |
| FR-43 item verification status | MUST | validation/JEV | evidence endpoints | issues/decisions | state mapping | VJ |
| FR-44 manual review queue | MUST | reviews | `/reviews/queue` | reviews | routing/access | VJ/UI |
| FR-45 approve/reject/edit/regenerate | MUST | reviews | review actions | reviews/revisions | action/state/audit | VJ/UI |
| FR-46 reviewer override | MUST | reviews/security | review action | reviews | authorization + reason | VJ/UI |
| FR-47 audit trail | MUST | audit | audit query | audit_logs | immutable before/after | F/VJ |
| FR-48 prompt-injection protection | MUST | security | detector + prompt builder | security findings | adversarial docs | DI/G/QA |
| FR-49 adversarial detection | MUST | security | scan service | findings | 10-case minimum | DI/QA |
| FR-50 employee dashboard | SHOULD | frontend | plan/progress APIs | progress | persona E2E | UI |
| FR-51 admin dashboard | SHOULD | frontend | admin aggregates | plans/progress/issues | aggregate/filter | UI |
| FR-52 role dashboard | SHOULD | frontend | role dashboard | roles/RRM/progress | role statistics | UI |
| FR-53 progress tracking | SHOULD | progress | progress APIs | employee_progress | item/overall transitions | UI |
| FR-54 progress assessment | SHOULD | progress | evaluator service | progress | five outcomes | UI |
| FR-55 weak-area detection | NICE/SHOULD | recommendations | progress analysis | progress | score/error inputs | UI |
| FR-56 adaptive recommendations | NICE (SRS “should/may”) | recommendations | recommendation service | plan/progress | rule-derived recommendations | UI |
| FR-57 policy update detection | MUST | policy impact | impact API | change_sets | V1/V2 changed chunks | RRM/VJ |
| FR-58 impact analysis | MUST | policy impact | impact API | impact_records | plans/items/quizzes/employees | VJ |
| FR-59 selective regeneration | MUST | generation | impact regeneration | impact/revisions | only affected items | VJ/QA |
| FR-60 plan comparison | SHOULD | reporting | comparison endpoint | plans/revisions | role/dept/level/version filters | UI |
| FR-61 search/filter | SHOULD | query/UI | list endpoints | indexed entities | permissions/filter accuracy | UI |
| FR-62 reports | SHOULD | reporting | `/reports` | derived views | required report types | UI/D |
| FR-63 export | SHOULD | reporting | export job | export artifacts | CSV + JSON first; injection/limits; PDF/XLSX later | UI/D |
| FR-64 API error handling | MUST | orchestration | provider client | job/run errors | timeout/quota/invalid response | G |
| FR-65 controlled retry | MUST | orchestration | job runner | generation/job runs | caps/backoff/idempotency | G |
| FR-66 model/prompt logging | MUST | audit/genai | generation detail | generation_runs/prompts | metadata completeness/redaction | G |
| FR-67 responsive interface* | SHOULD | frontend | all UI | n/a | responsive/accessibility smoke | UI |

*The SRS numbers Responsive Web Interface as `lxvi`, but it follows retry and model/prompt logging; this matrix assigns FR-67 to avoid losing a requirement caused by the document’s numbering inconsistency.

## Non-functional and integrity requirements

| SRS requirement | Priority | Module/service/data | Validation/test | Phase |
|---|---|---|---|---|
| NFR-01 generate+validate within 30s normal conditions | MUST | telemetry/orchestration; run timings | representative percentile benchmark | QA/D |
| NFR-02 scale 1,000 employees/100 roles/1,000 docs without redesign | SHOULD | relational/index/job architecture | seeded load/query plan tests | QA |
| NFR-03 usable for five personas | SHOULD | UI/design system | persona task/accessibility test | UI/QA |
| NFR-04 100% mandatory coverage and mandatory traceability before approval | MUST | validators/JEV/finalize guard | invariant/property tests | VJ |
| NFR-05 99% evaluation availability excluding provider outage | SHOULD | health/circuit breaker/managed deployment | smoke/failure drill | D |
| Hidden PDF/DOCX and new role without core changes | MUST | adapters/data-driven RRM | evaluator-pack test | QA |
| Updated/outdated/conflicting policy challenge | MUST | versions/precedence/impact | approved/current-effective only; approved role exception; unresolved conflict -> MANUAL_REVIEW | QA |
| Prompt injection and unsupported-topic challenge | MUST | security/support validation | adversarial suite | QA |
| Live modification/debuggability | MUST | modular config/rules/schemas | timed change drills | QA |
| No hard-coded outputs/fake results | MUST (SRS explicit) | all domains | code review, randomized fixtures | all |
| GenAI never replaces validation/security/audit | MUST (SRS explicit) | architecture boundaries | dependency/import tests | VJ/QA |

## Dataset and submission obligations

| Obligation | Priority | Planned artifact/service | Verification | Phase |
|---|---|---|---|---|
| Unique fictional organization pack | MUST | `sample_data/` | originality/manual review | DI/RRM |
| >=20 documents, >=10 roles, >=150 requirements | MUST | company pack/RRM | inventory script | RRM/QA |
| >=50 mandatory, >=30 role-specific requirements | MUST | RRM | counts + source checks | RRM/QA |
| >=10 conflicts/ambiguities, >=10 policy changes, >=10 injection cases | MUST | adversarial/version fixtures | manifest counts/tests | QA |
| Plans for >=10 roles | MUST | evidence export | completeness validation | QA/D |
| >=100 requirement-level GenAI/Python comparisons | MUST | comparison report | row/schema audit | QA/D |
| Project report with diagrams/pipeline/security/testing | MUST | documentation | checklist/manual review | D |
| Validation and security testing reports | MUST | reports | evidence links/results | D |
| README/install/execution/evaluator instructions | MUST | docs | clean-machine rehearsal | D |
| Public GitHub, meaningful work across all five days, team contributions | MUST (SRS explicit) | repository/history | human/process audit; schedule conflict open | D |
| Public deployment + evaluator/admin credentials | MUST/SHOULD wording mixed | deployment handoff | external smoke test | D |
| Mandatory MP4 demonstration | MUST | demo video | content checklist | D |
| Technical blog >=2,000 words | MUST | published blog | word/content/link check | D |
| AI usage declaration | MUST | `AI_USAGE.md` | per-entry human verification | all/D |
| No committed secrets | MUST | env/secret controls | secret scan/history review | F/D |

## Coverage notes and ambiguities

- SRS uses both “five-day competition” and the project brief’s approximately three-day build window. Planning uses three days, but GitHub-across-five-days compliance needs organizer/team clarification.
- SRS alternates `must`, `should`, and `may`; section 1.8 says all functional and non-functional requirements are mandatory. Priority therefore sequences delivery rather than declaring items unnecessary.
- SRS lists both granular validation statuses and the approved six JEV outcomes. Granular labels are issue codes; JEV uses exactly six statuses.
- “Automatically ingest/analyze” conflicts slightly with required human approval of ground truth. Architecture automates candidate processing but requires approval before a candidate becomes validation truth.
- Accepted MVP decisions: one fictional organization; no MVP organization table/discriminator; Training Managers draft/submit while Reviewers/Admins approve/reject; configurable 15 MB file limit; OCR out of MVP with unextractable PDFs routed to NEEDS_REVIEW; RRM/source-first plus PostgreSQL lexical retrieval; embeddings not required; configurable stages with example defaults; approved/current-effective source precedence with approved role exceptions; CSV/JSON-first exports.
- Still unspecified: consistency threshold/run count, retention/deletion, malware-scanner product, deployment provider/region, and final evaluator credential handling.
- Multi-tenancy is a post-competition extension only and is not part of MVP requirements, data, or authorization.
