# SkillSprint AI Delivery Plan

Status: **PLANNED**. Acceptance criteria are gates, not claims of completion. With approximately three days, phases overlap and must be executed as vertical slices.

## Phase 1 - Foundation

**Scope:** repository/application skeleton (only after Phase 0 approval), environment config, Supabase Auth, profile/RBAC model, FastAPI/Next.js health path, audit foundation, CI test/secret checks.  
**Dependencies:** approved architecture; Supabase project/environment choice.  
**Acceptance criteria:** five personas authenticate; deny-by-default RBAC/RLS work within the single fictional organization; no service key reaches browser; audit event written for a mutation; clean setup documented.  
**Tests:** auth/JWT, five-role permission matrix, record-level RLS, approval separation, config/secret scan, health integration.  
**Risks:** RLS complexity and setup time. Multi-tenancy and organization discriminators are explicitly outside the MVP and may be considered post-competition.

## Phase 2 - Document Intelligence

**Scope:** PDF/DOCX upload, quarantine/validation, metadata, parsing, traceable chunking, version lifecycle, injection-pattern findings.  
**Dependencies:** storage, database, job mechanism, security limits.  
**Acceptance criteria:** unseen extractable PDF and DOCX parse without code change; every chunk resolves to version and page/section/paragraph; duplicate/empty/invalid/version/over-15-MB cases fail safely; suspicious document is flagged; scanned or unextractable PDF becomes NEEDS_REVIEW because OCR is out of MVP.  
**Tests:** golden parsers, corrupt/encrypted/oversize/spoofed MIME, duplicate hash, page/paragraph traceability, adversarial documents.  
**Risks:** scanned PDFs, malformed DOCX, extraction drift. OCR is out of MVP; poor/unextractable content is review-required.

## Phase 3 - Role Requirement Matrix / Ground Truth

**Scope:** departments/roles, requirement candidates and approval, sources, RRM revisions, applicability, precedence, prerequisites, minimum fictional dataset.  
**Dependencies:** Phase 2 source lineage and Phase 1 RBAC.  
**Acceptance criteria:** add a new role/configuration without code; Training Manager drafts/submits while Reviewer/Admin approves/rejects; creator and approver are recorded; approved RRM freezes source snapshot; only approved/current-effective sources enter active ground truth; approved role exceptions can outrank general policy; unresolved conflicts route to MANUAL_REVIEW.  
**Tests:** source integrity, revision immutability, self-approval denial, Admin emergency-override reason/audit, applicability, prerequisite cycles, precedence, count/inventory checks.  
**Risks:** creating >=150 sourced requirements is labor-intensive and is the largest content blocker.

## Phase 4 - GenAI Engine

**Scope:** provider abstraction, Gemini adapter, versioned prompts, constrained retrieval, structured contract, run logging, retry/recovery, plan persistence.  
**Dependencies:** approved RRM, source retrieval, schema/prompt decisions.  
**Acceptance criteria:** generates schema-valid, role-distinct, staged plan with modules/objectives/checklists/tasks/quizzes/assessments/citations; refuses unsupported topic; provider can be replaced behind interface.  
**Tests:** provider mock/contract, malformed JSON, timeout/quota, retry cap, idempotency, citation allowlist, prompt/data separation, optional live smoke.  
**Risks:** latency/token limits/quota/schema compliance; minimize evidence pack and use bounded retries.

## Phase 5 - Python Validation + JEV

**Scope:** independent validators, metrics, issue records, comparison, six-state JEV, review actions, targeted regeneration, policy impact lineage.  
**Dependencies:** immutable plan/RRM/source snapshots.  
**Acceptance criteria:** injected missing/unsupported/stale/contradictory/duplicate/wrong-role/sequence defects produce expected evidence and JEV; VERIFIED is impossible below 100% mandatory coverage or traceability; override needs a reason and preserves original result.  
**Tests:** table/golden/property tests, dependency boundary with network disabled, replay determinism, state transitions, selective regeneration.  
**Risks:** semantic claims cannot all be deterministic; route uncertainty to review and do not overclaim hallucination detection.

## Phase 6 - Product UI / Dashboards

**Scope:** document/RRM draft-submit-approve workflows, generation status, evidence viewer, review queue, employee/admin/role/manager views, progress, search/filter, CSV/JSON reports/export.  
**Dependencies:** stable APIs and persona authorization.  
**Acceptance criteria:** evaluator completes login-upload-role/RRM-generate-validate-review-finalize-progress-policy-update path; explanations and citations are visible; responsive critical screens.  
**Tests:** Playwright persona E2E, accessibility/keyboard checks, loading/error/empty states, scope tests.  
**Risks:** dashboard/report breadth. Prefer complete core workflows over decorative analytics; PDF/XLSX exports are non-critical extensions unless later required.

## Phase 7 - Hidden Evaluation / QA

**Scope:** unseen pack harness, minimum dataset/adversarial/version cases, 10-role plans, >=100 comparisons, performance/security/boundary testing, timed live-change drills.  
**Dependencies:** complete vertical slice and representative dataset.  
**Acceptance criteria:** hidden PDF/DOCX/new role/revised policy/outdated SOP/conflicting FAQ/missing requirement/ambiguous clause/exception/injection/unsupported content handled without core change; standard run measured against 30-second target.  
**Tests:** all SRS test categories, seeded load (1k employees/100 roles/1k docs where practical), unauthorized access, invalid provider response, consistency runs, deliberate defects.  
**Risks:** insufficient fixture diversity and flaky external API; retain recorded contract fixtures plus a clearly labeled live smoke.

## Phase 8 - Deployment / Submission

**Scope:** production environment, observability/backups, evaluator accounts, reports/evidence, README/install/execution, report diagrams, screenshots, demo MP4, technical blog, AI usage and contribution record.  
**Dependencies:** release candidate, hosting decision, team assignments.  
**Acceptance criteria:** public URL and credentials work; secrets absent from repository/history; clean install/evaluation rehearsal passes; every SRS final-checklist item has an owner and link.  
**Tests:** external smoke, restore/readiness drill, link/credential check, documentation rehearsal, secret/dependency scan.  
**Risks:** submission work is extensive and cannot be left to the final hours; five-day Git history rule conflicts with stated three-day window.

## Recommended three-day critical path

**Day 1:** Phase 1; PDF/DOCX ingestion and lineage; minimal approved RRM for two representative roles; begin dataset in parallel by humans.  
**Day 2:** structured Gemini generation; core validators (schema, coverage, citations, versions, unsupported, contradiction, sequence); JEV and review queue.  
**Day 3:** policy V2 impact/selective regeneration; evaluator-facing UI; adversarial/hidden fixtures; deployment and evidence capture.

After the vertical slice is stable, expand to 10 roles and submission minimums. Do not trade away independent validation, traceability, JEV explainability, or prompt-injection boundaries for dashboard polish.

## Accepted Phase 0 MVP decisions

1. One fictional organization; no MVP organizations table, tenant discriminator, or tenant-derived authorization. Multi-tenancy is post-competition only.
2. Training Managers create/edit and submit document/RRM drafts. Reviewers or Admins approve/reject. Training Manager self-approval is prohibited. Admin emergency override requires a reason and complete audit record.
3. Configurable initial upload limit: 15 MB per file.
4. OCR is out of MVP; scanned/unextractable PDFs become NEEDS_REVIEW.
5. Retrieval starts from approved RRM/source edges and may use PostgreSQL lexical/full-text search. Embeddings are not required unless future testing demonstrates need.
6. Stages are configurable data; examples are Day 1, Week 1, Week 2, Day 30, Day 60, Day 90. Validators use IDs/order rather than fixed labels.
7. Only approved/current-effective sources enter active ground truth. Approved role-specific exceptions outrank applicable general policy; unresolved conflicts route to MANUAL_REVIEW; precedence remains data/config driven.
8. CSV and JSON are the MVP export formats. PDF/XLSX are non-critical extensions.
9. Deployment provider remains open until a later phase.

## Remaining open decisions

1. Malware-scanner product, retention/deletion periods, and maximum page/decompression limits.
2. Controlled consistency-run count, threshold, and scoring weights.
3. Exact onboarding stage timing/duration beyond the configurable example defaults.
4. Deployment provider/region, availability measurement, evaluator credential handling, and budget/quota.
5. Resolution of three-day schedule versus the SRS requirement for meaningful commits across five competition days.

## Phase 0 audit / blocker assessment

- **Missing SRS requirements in design:** none knowingly omitted; FR numbering inconsistency is explicitly preserved as FR-67.
- **Ambiguous:** support/contradiction semantic thresholds, consistency formula, retention/deletion, malware-scanner choice, and deployment provider/region.
- **Architecture/SRS conflicts:** no technical conflict; approved six JEV states are reconciled with granular SRS labels as issue codes. Human approval of extracted requirements is an intentional safety gate around “automatic” ingestion.
- **Too large for three days:** full 10-role/20-document/150-requirement dataset, all dashboards/reports/exports, 1k-document load proof, polished video/blog/report, and full production hardening.
- **Hidden-evaluation risks:** poor extraction, incomplete lineage, hard-coded stages/roles/precedence, semantic false positives, and inadequate exception/conflict fixtures.
- **Security risks:** service-key exposure, broken RLS, prompt injection, malicious files, sensitive document logging, export formula injection, and unsafe reviewer override.
- **Dataset requirements:** minimum counts listed in `SRS_MATRIX.md` require immediate human content ownership and source review.
- **Submission requirements:** public repository, deployment, report, comparison/validation/security evidence, MP4, >=2,000-word blog, instructions, links, and team/AI declarations need named owners.

Following the requested architecture corrections, Phase 0 is **READY_FOR_FINAL_REVIEW**, not locked. Final human approval remains required before implementation begins.
