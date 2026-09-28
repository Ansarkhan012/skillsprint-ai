# SkillSprint AI — Pre-Submission Audit Report

Date: 2026-09-28 · Scope: read-only audit against `docs/SkillSprint AI-Generative AI PowerPlay_SRS.pdf` (there is no `documentation/` folder; the SRS lives in `docs/`).
No source files were modified during this audit. All live API probes used tiny or fixture-based prompts; no key values were printed.

---

## 0. Project map

| Area | Location | Notes |
|---|---|---|
| Frontend | `apps/web` (Next.js 16 / React, TypeScript) | Pages under `src/app`, product UI under `src/components/product` |
| Backend entry point | `services/api/app/main.py` (FastAPI) | Run from **repo root**: `uvicorn app.main:app --app-dir services/api` (`.env` is read relative to CWD) |
| Database / auth | Supabase Postgres + Auth + RLS | 12 SQL migrations in `supabase/migrations` |
| Document processing | `services/api/app/document_processing.py`, `documents.py` | PyMuPDF (PDF), python-docx (DOCX), deterministic chunking |
| Role Requirement Matrix | `rrm.py`, `rrm_rules.py`, `rrm_service.py`, `rrm_models.py` | Requirements are authored manually (`origin: "MANUAL"`) |
| GenAI pipeline | `generation_api.py` → `generation_service.py` → `generation_provider.py` / `nararouter_provider.py` | Providers: `gemini`, `groq`, `nararouter` selected by `AI_PROVIDER` |
| Prompt templates | `generation_prompt.py` (active, `phase4d-compact-context/2.0.0`), `generation_prompt_v1.py` | Python constants, versioned + SHA-256 template hash |
| Output schema | `generation_output.py` (`onboarding-plan/1.0.0`, strict Pydantic) | |
| Python validation | `plan_validator.py`, `jev.py`, `validation_service.py`, `validation_api.py` | Deterministic; no provider imports |
| Tests | `services/api/tests` (652), `apps/web/tests` (64) | |

SRS §1.10 asks for folders like `genai_pipeline/`, `python_validation/`, `prompt_templates/`, `schemas/`, `sample_documents/`. The code equivalents exist (table above) but under different names; `sample_documents/`, `reports/`, `screenshots/`, `LICENSE`, and a root `requirements.txt` do not exist.

---

## 1. ROOT CAUSE of the GenAI "rejection"

There are **two independent causes**. Both were reproduced live today.

### Cause A — The API itself rejects every call: HTTP 402 (out of credits)

Live probe with the configured `.env` (`AI_PROVIDER=nararouter`):

| Check | Result |
|---|---|
| `GET https://router.bynara.id/v1/models` | **200**. Key is valid, and `gemini-3.8-flash-high` is listed |
| `POST /chat/completions` | **402** `{"type":"payment_required","message":"Insufficient credits. Please top up your balance."}` |

- Ruled out: base_url is correct, the model ID format is valid, the key has no quotes/spaces/CR, and `.env` loads (when started from the repo root).
- In code, `nararouter_provider.py:174-175` maps any unlisted status (including 402) to the generic `PROVIDER_REQUEST_FAILED`. It also logs `upstream_status=402 upstream_hint=balance`, so the UI shows only "failed/rejected".

### Cause B — When a response does come back, our own schema validation rejects it (`SCHEMA_INVALID`)

The real pipeline (`build_prompt` → provider → `parse_plan`) was run with the repo's own 6-requirement/5-stage fixture against the other configured providers:

| Provider | Runs | Outcome |
|---|---|---|
| Groq `openai/gpt-oss-20b` | 5 | 3 × **SCHEMA_INVALID** (ours), 1 × HTTP 400 `json_validate_failed` (Groq's JSON mode), 1 × parsed (≈1 KB, i.e. essentially no modules) |
| Gemini direct `gemini-3.8-flash` | 2 | HTTP **503** "model experiencing high demand" (Google-side, temporary). The tiny probe returned 200 |

Exact schema errors (from `generation_service.py:111`, `OnboardingPlan.model_validate_json`):

```
plan.stages[i].modules[i].purpose            missing   (6 of 6 modules)
plan.stages[i].modules[i].priority           missing   (6 of 6)
plan.stages[i].modules[i].difficulty         missing   (6 of 6)
plan.stages[i].modules[i].estimated_minutes  missing   (6 of 6)
schema_version                               missing   + plan.schema_version extra_forbidden
plan.stages                                  too_short
```

Why the model gets it wrong:
1. **The schema is sent only as a custom compressed notation.** `generation_prompt.py:57-97` sends `compact_output_contract()`, where types are aliases like `"purpose":"s2"` and optional fields use a `?` suffix. Models don't reliably follow this made-up notation.
2. **The provider never enforces the schema.** Requests use `response_format: {"type":"json_object"}` (`generation_provider.py:179`, `nararouter_provider.py:100`) and Gemini `responseMimeType` only. That guarantees *valid JSON*, not *our fields*.
3. **The format retry is blind.** `FORMAT_RETRY_RULE = "Previous response was not schema-valid. Regenerate JSON only."` (`generation_prompt.py:36`) doesn't say which fields were wrong, so the retry repeats the same mistake.
4. **`OUTPUT_MAPPING` ends with "Use concise prose and only useful optional learning elements."** Combined with every learning array being optional, models return modules with **no objectives, tasks, quizzes, or assessments**. That fails SRS Steps 14–24 even when parsing succeeds.

Things checked and **not** the cause: ```json fences (not observed in JSON mode, and would be rejected as `MALFORMED_JSON` anyway), truncation (`finish_reason=stop`, 774–4001 completion tokens against a max of 8192), invalid source IDs (not reached), and request size (≈14 KB < 24,576 guard).

### Precise fix

| # | Fix | Where | DB migration? |
|---|---|---|---|
| A1 | Get a working provider: **either** top up NaraRouter credits, **or** set `AI_PROVIDER=gemini` (the DB accepts any Gemini model), and keep Groq as the known-good fallback | `.env` only | No for `gemini`. For `nararouter`, migrations `202609270002` + `202609280001` must be applied (see §6) |
| A2 | Map HTTP 402 to a distinct `PROVIDER_PAYMENT_REQUIRED` (and add it to `SAFE_PROVIDER_ERRORS` plus the error allowlist) so the UI states the real reason | `nararouter_provider.py`, `generation_provider.py`, `generation_service.py:160` | No (the code matches `^[A-Z][A-Z0-9_]{1,79}$`) |
| B1 | **Enforce the schema at the provider.** Send the real JSON Schema from `OnboardingPlan.model_json_schema()`: OpenAI-compatible `response_format: {"type":"json_schema","json_schema":{...}}` for Groq/NaraRouter, and `responseJsonSchema` for Gemini. Keep the strict Pydantic validation unchanged as the independent check | request builders in both provider files | **No.** `template_hash` is computed from the prompt constants, not the payload envelope |
| B2 | Make the format retry say what failed: append the already-sanitised `safe_validation_diagnostics` (field path + error type only, no model text) to the retry system message | `generation_service.py` (pass diagnostics into `provider.generate`) | No, as long as the `FORMAT_RETRY_RULE` constant is unchanged |

⚠️ **Constraint:** the DB function `reserve_generation_run_bounded` hard-pins `prompt_version='phase4d-compact-context/2.0.0'` and `template_hash='11b1127d…'` (`202609270001_compact_context_v2.sql:30-31`). Any change to the `SYSTEM`/`RULES`/`OUTPUT_MAPPING` text (for example, removing "only useful optional learning elements") will make **every generation fail at reservation** until a matching migration is applied. B1+B2 avoid this. Changing the prompt text is possible, but it costs a migration.

---

## 2. Does the app run? (Phase 1 step 3)

| Check | Result |
|---|---|
| Backend with project `.venv` | ❌ **BROKEN.** `.venv` was created by Python **3.14.0** but contains **cp312** wheels, so `ModuleNotFoundError: pydantic_core._pydantic_core`. Neither the app nor the tests start |
| Backend with a fresh Python 3.12 venv | ✅ Starts; `/api/v1/health` → 200 |
| Backend tests (Py 3.12) | ⚠️ **651 passed, 1 failed**: `test_phase7_evaluation.py::test_h17_malformed_and_deep_json…` raises `RecursionError` on deeply nested JSON in `parse_plan` (not caught as `ValueError`). At runtime it degrades to `GENERATION_INTERNAL_ERROR` |
| Frontend `tsc --noEmit` | ✅ clean |
| Frontend `eslint` | ✅ 0 errors, 1 warning (`tests/product-experience.test.mjs:23` unused `_prefetch`) |
| Frontend tests (`node --test tests/*.mjs`) | ✅ 64/64. Note: there is no `npm test` script |
| Frontend `next build` | ✅ succeeds |
| Uncommitted work | ⚠️ 31 modified + ~12 untracked files, including the whole NaraRouter adapter, not yet committed |

---

## 3. SRS Functional Requirements (i – lxvi)

Legend: ✅ Done · 🟡 Partial · ❌ Missing · 💥 Broken. "(UI not deeply verified)" means the backend was confirmed but the full UI flow was not exercised.

| # | Requirement | Status | Evidence / gap |
|---|---|---|---|
| i | User authentication | ✅ | Supabase Auth, `security.py`, `/login` |
| ii | RBAC (admin/TM/reviewer/manager/employee) | ✅ | `require_roles`, RLS migrations, README matrix |
| iii | Employee profile mgmt | 🟡 | `employees` table + directory UI; only 1 employee in live DB; competencies/training status not confirmed |
| iv | Role management | ✅ | `roles` (10 in live DB) |
| v | Document upload | ✅ | `documents.py:59`, PDF + DOCX |
| vi | Document validation | ✅ | `validate_file` (signature, size, hash dup, dates) |
| vii | Document parsing | ✅ | `parse_pdf`, `parse_docx` |
| viii | Chunking | ✅ | `chunk_units` |
| ix | Source metadata | ✅ | chunk locator/page/paragraph |
| x | Version control | ✅ | `current-effective-version`, approval flow |
| xi | Requirement extraction | 🟡 | Manual authoring only (`rrm.py:151`, `origin: MANUAL`); no automatic extraction from chunks |
| xii | Role Requirement Matrix | ✅ | matrices, approve/reject, ground-truth endpoint |
| xiii | GenAI API integration | 💥 | See §1: 402 on configured provider; SCHEMA_INVALID on Groq |
| xiv | Structured prompt templates | 🟡 | Versioned + hashed, but kept in Python constants, not configurable template files (Step 40) |
| xv | Structured JSON output | ✅ | `generation_output.py` |
| xvi | JSON schema validation | ✅ | strict Pydantic + ref checks in `parse_plan` |
| xvii | Personalized plan | 💥 | Blocked by xiii |
| xviii | Multi-stage onboarding | ✅ | stage sets (Day 1 … 90 days) |
| xix–xx | Modules / objectives | 🟡 | Schema supports them; real outputs omit objectives (all optional + "only useful optional elements") |
| xxi–xxiv | Checklists / tasks / scenarios / quizzes | 🟡 | Same: in schema, absent in real output |
| xxv | Quiz answer validation vs source | ❌ | Validator only checks answer IDs ∈ options (`generation_output.py:88`); nothing checks the answer against the source |
| xxvi–xxvii | Assessments / rubrics | 🟡 | Schema supports them (weights sum 100); absent in real output |
| xxviii | Prerequisite detection | ✅ | RRM dependencies |
| xxix | Sequence validation | ✅ | `DEPENDENCY_ORDER_VIOLATION`, cycle check |
| xxx | Source citation | ✅ | `source_refs` required on every node |
| xxxi | Independent Python pipeline | ✅ | `plan_validator.py` (no provider imports) |
| xxxii | Mandatory coverage check | ✅ | `MISSING_MANDATORY_REQUIREMENT` |
| xxxiii | Coverage score | ✅ | `mandatory_covered/mandatory_total`, shown as "x of y" and a progress bar |
| xxxiv | Traceability score | 🟡 | Findings exist but no numeric traceability % is computed |
| xxxv | Hallucination detection | 🟡 | Unsupported req/source refs flagged; `insufficient_information` exists; free-text claims are not checked; off-topic refusal not demoed |
| xxxvi | Contradiction detection | 🟡 | Generated-vs-RRM mandatory/priority conflicts; source conflicts via manual RRM issues; no automatic FAQ-vs-policy detection |
| xxxvii | Policy precedence | ✅ | `rrm_precedence_configs`, `rrm_rules.precedence` |
| xxxviii | Duplicate detection | 🟡 | Requirement-level duplicates only; no module/task/quiz text duplicates |
| xxxix | Role-relevance check | 🟡 | Applicability + unsupported refs; no "valid but irrelevant to role" check |
| xl–xli | Consistency testing / score | ❌ | Not implemented |
| xlii | GenAI/Python comparison | 🟡 | Per-requirement findings with evidence; no side-by-side "Python expected / GenAI / Match" table (UI not deeply verified) |
| xliii | Verification status | ✅ | `jev.py` (6 statuses) |
| xliv | Manual review queue | ✅ | Validation & Reviews page |
| xlv | Reviewer decision | 🟡 | APPROVE/REJECT/REGENERATE/OVERRIDE + reason; no Edit |
| xlvi | Reviewer override | ✅ | `OVERRIDE` |
| xlvii | Audit trail | ✅ | `audit_logs`, `plan_review_actions` |
| xlviii | Prompt injection protection | ✅ | system/user separation, `<untrusted_generation_data>` wrapper, `<`/`>` escaping, validator ignores model claims. **Needs a live demo** |
| xlix | Adversarial document detection (flagging) | ❌ | No scan/flag of suspicious instructions in uploaded chunks |
| l | Employee dashboard | 🟡 | Dashboard exists; no progress data model |
| li | Admin dashboard | 🟡 | Overview with runs/validation (UI not deeply verified) |
| lii | Role dashboard | ❌ | No per-role completion stats |
| liii | Progress tracking | ❌ | No completion tables for modules/checklists/tasks/quiz scores |
| liv | Progress assessment | ❌ | — |
| lv | Weak-area detection | ❌ | — |
| lvi | Adaptive recommendations | ❌ | — |
| lvii | Policy update detection | 🟡 | Re-validation flags `STALE_INPUT`/`OUTDATED_SOURCE`; no proactive "what changed" |
| lviii | Impact analysis | ❌ | No listing of affected plans/modules/quizzes/employees |
| lix | Selective regeneration | ❌ | Only whole-plan regenerate |
| lx | Search & filtering | 🟡 | Some filters (employee filter, requirements search) |
| lxi | Reports | 🟡 | "Reports" nav reuses Overview (`workspace.tsx:13`) |
| lxii | Export (CSV/PDF/Excel) | ❌ | No export code anywhere |
| lxiii | API error handling | ✅ | Typed provider failures (402 lacks its own code, see A2) |
| lxiv | Retry management | ✅ | ≤4 calls, bounded backoff, every attempt persisted |
| lxv | Model & prompt logging | ✅ | provider, model, prompt_version, template_hash, projection_hash per run |
| lxvi | Responsive web UI | ✅ | Tailwind responsive; screenshots 375–1920 in `tmp/ui-redesign-audit` |

**Totals:** ✅ 30 · 🟡 20 · ❌ 12 · 💥 2 (grouped rows counted once).

### Key development Steps 1–63 (summary)

| Steps | Topic | Status | Note |
|---|---|---|---|
| 1, 3 | Company dataset & variation | ❌ | No `sample_documents/` in repo; live DB has **3 documents** (SRS minimum: 20 docs, 150 reqs, 50 mandatory, 10 conflicts, 10 version changes, 10 adversarial) |
| 2 | ≥10 roles | ✅ | 10 roles in DB |
| 4–8 | Upload, validation, parsing, chunking, versions | ✅ | |
| 9 | Employee profile | 🟡 | 1 employee |
| 10–11 | RRM, requirement extraction | ✅ / 🟡 | Extraction is manual |
| 12–13 | Personalized, multi-stage plan | 💥 / ✅ | |
| 14–25 | Modules … difficulty levels | 🟡 | Schema-ready, but real output is empty of learning items |
| 26–27 | Prerequisites, sequence | ✅ | |
| 28–30 | Validation engine, coverage, traceability | ✅ / ✅ / 🟡 | |
| 31–33 | Hallucination, unsupported, contradiction | 🟡 | |
| 34 | Precedence rules | ✅ | Hierarchy must be documented in README |
| 35–36 | Duplicate, role relevance | 🟡 | |
| 37–39 | JSON output, schema validation, retry | ✅ | Retry is blind (B2) |
| 40–41 | Prompt templates & version tracking | 🟡 / ✅ | |
| 42–43 | Injection defense, adversarial docs | ✅ / ❌ | No adversarial test documents or flagging |
| 44–45 | Consistency check & score | ❌ | |
| 46–47 | Comparison & final status | 🟡 / ✅ | |
| 48–49 | Human review, override | 🟡 / ✅ | |
| 50–56 | Dashboards, progress, recommendations | 🟡 / ❌ | |
| 57–59 | Policy update, impact, selective regen | 🟡 / ❌ / ❌ | |
| 60 | Plan comparison | ❌ | |
| 61–63 | Search, reports, export | 🟡 / 🟡 / ❌ | |

### Section 1.8 integrity rules

| Rule | Status | Note |
|---|---|---|
| 1 Unique company pack | ❌ | Dataset not in repo |
| 2–3 Hidden docs / hidden role | 🟡 | Upload + role creation work, but RRM requirements must be authored by hand for a new role/doc |
| 4 Policy update challenge | 🟡 | Stale detection only, no impact report |
| 5 Prompt injection challenge | 🟡 | Defense exists; no demo document/flagging |
| 6 Contradiction challenge | 🟡 | Precedence config exists; demo data missing |
| 7 Source traceability | ✅ | Every node carries doc-version/chunk/locator |
| 8 Hallucination challenge | 🟡 | `insufficient_information` exists; not demoed |
| 9–10 Live modification / defect | ✅ | Code is modular and well tested |
| 11 GitHub activity | 🟡 | Commits on 23, 24, 26, 27 Sep. **None on 25 or 28** yet; large uncommitted diff |
| **12 No hard-coded output** | ✅ **PASS** | See §4 |
| 14 GenAI must not replace validation | ✅ | Validator/JEV have no provider imports |
| 16 AI_USAGE.md | 🟡 | Exists (Codex entries with verifier fields); must add this session's Claude usage |

---

## 4. SRS 1.8 rule 12 — hard-coded output scan

**No violation found.**
- No hard-coded plans, quiz answers, scores, or comparison results in `services/api/app` or `apps/web/src`. Coverage and status come from `plan_validator.py`/`jev.py`, and the UI renders `detail.summary.mandatory_covered` from the API.
- No fake API responses in app code. Mocked HTTP exists only in `services/api/tests` (allowed).
- Watch items:
  - `apps/web/src/app/visual-check/page.tsx` (untracked) is a static, data-free demo page marked "Remove before handoff". It renders the app shell for a fake "Visual preview" ADMIN **without authentication**. It holds no fake results, but delete it so evaluators don't misread it.
  - `apps/web/src/app/app/phase4d-test/page.tsx` triggers a *real* generation for a fixture employee. That's fine, but rename or hide it from evaluators.

---

## 5. Secrets

- ✅ No secrets in tracked files or anywhere in git history (scanned for `sk-`, `gsk_`, `AIza`, `sb_secret_`, JWT, `AQ.` patterns).
- ✅ `.env` and `apps/web/.env.local` are gitignored; `.env.example` has empty values.
- ⚠️ Local `.env` holds live NaraRouter, Groq, Gemini, and Supabase **service-role** keys. Never commit it. The deployed backend must receive them as host environment variables.
- ⚠️ The GitHub repo must be **public** for submission. Re-run the scan right before making it public.

---

## 6. Other findings

1. **DB contract pins.** `reserve_generation_run_bounded` accepts only `provider/model` pairs: `nararouter`+`gemini-3.8-flash-high`, `groq`+`openai/gpt-oss-20b`, `gemini`+any. `docs/NARAROUTER_ADAPTER.md` says `202609270002_nararouter_generation_provider.sql` "has not been applied", and `202609280001` is new. If they're unapplied, NaraRouter runs fail at reservation even after a top-up. Verify with `docs/NARAROUTER_LIVE_CONTRACT_CHECK.sql` in the Supabase SQL editor.
2. **VERIFIED is nearly unreachable.** `plan_validator.py:106-107` adds `TIMING_UNRESOLVED` (REVIEW) for **every** requirement whose timing isn't `NOT_SPECIFIED`, and `:199-200` adds REVIEW for any `insufficient_information`. Any RRM with timed requirements therefore always ends in `MANUAL_REVIEW`. That is documented and defensible, but evaluators expect to see a Verified plan in the demo. Pick at least one demo role whose requirements are all `NOT_SPECIFIED` timing, or add a module-level stage comparison.
3. Service-role REST access to `generation_runs`/`generation_attempts` returns `42501 permission denied` (no grant). That's intentional, but it means debugging past runs needs a user JWT or the SQL editor.
4. `.env` is resolved relative to the CWD. Starting uvicorn from inside `services/api` silently loses all provider config (→ 503 `GENERATION_PROVIDER_NOT_CONFIGURED`).
5. Groq free tier: a 429 with `Retry-After` > 2 s is never retried (`generation_service.py:211-214`). Hit once in testing.

---

## 7. PRIORITIZED FIX LIST — today only

Estimates assume one developer working with an AI assistant. Each fix = one small commit plus a test run.

### P0 — Blockers (app can't generate at all) · ≈ 3–4 h

| # | Item | Est. |
|---|---|---|
| 0 | Commit the current uncommitted work as-is (tests are 651/652 green) so today has history and nothing is lost | 10 min |
| 1 | Recreate `.venv` with Python 3.12; note the Python version in README | 15 min |
| 2 | Choose the working provider (A1): top up NaraRouter **or** switch `.env` to `AI_PROVIDER=gemini` (+ Groq as backup); verify DB pins/migrations (§6.1) | 15–30 min |
| 3 | A2: distinct `PROVIDER_PAYMENT_REQUIRED` for 402 (+ test) | 20 min |
| 4 | **B1: provider-enforced JSON Schema** (json_schema / responseJsonSchema from the Pydantic model), no prompt-text change, + tests + one live run | 1.5–2 h |
| 5 | B2: pass safe diagnostics into the format retry (+ test) | 30–45 min |
| 6 | Catch `RecursionError` in `parse_plan` → `MALFORMED_JSON` (fixes the 1 failing test) | 10 min |

### P1 — Mandatory items evaluators will test · ≈ 6–9 h (can't all fit; do in this order)

| # | Item | Est. |
|---|---|---|
| 7 | **Company dataset**: fictional docs as PDF/DOCX in `sample_documents/` (policy v1+v2, conflicting FAQ, outdated SOP, injection doc, role descriptions), then upload/approve, author the RRM, and make one Verified-capable demo role. *Content must be authored by the team; it can't be faked* | 3–4 h (minimum viable set) |
| 8 | **Traceability score** (% of generated nodes whose refs are valid) added to validation evidence + UI | 1 h |
| 9 | **Adversarial document flagging**: deterministic scan of chunks for injection phrases → flag/`NEEDS_REVIEW` + tests | 1–1.5 h |
| 10 | **Hallucination demo**: make sure the `insufficient_information` output is shown in the UI as "Insufficient source / manual review" | 45 min |
| 11 | **Policy update impact**: endpoint listing plans/modules/employees whose frozen snapshot references a superseded document version | 1.5–2 h |
| 12 | Contradiction and precedence: document the actual hierarchy in README and demo it with dataset conflicts | 30 min |
| 13 | Consistency check (run twice, compare requirement/source/category sets → score) | 2 h (**likely cut**) |

### P2 — Deliverables · ≈ 3–5 h

| # | Item | Est. |
|---|---|---|
| 14 | README rewrite: install (Py 3.12, Node 20+), env/API-key config, DB migrations, run, tests, evaluator walkthrough (login → upload → RRM → generate → validate → review), precedence hierarchy, assumptions, limitations, troubleshooting | 1 h |
| 15 | `AI_USAGE.md`: add this Claude Code session (tool, purpose, files, changes, tests, verifying member) | 15 min |
| 16 | `LICENSE`, root `requirements.txt` (→ `-r services/api/requirements.txt`), `npm test` script | 10 min |
| 17 | Deployment: API on Render/Railway (env vars, Py 3.12), web on Vercel/Render, set `WEB_ORIGIN`/`API_BASE_URL`, evaluator + admin logins | 1.5–2.5 h |
| 18 | CSV export of validation findings/coverage (Step 63) | 1 h |
| 19 | Delete `visual-check` page, hide `phase4d-test` | 10 min |
| — | Project report, demo video (.mp4), 2,000-word blog, comparison report (≥100 rows), plans for 10 roles | team; not code |

### P3 — Nice-to-have (skip today unless time remains)

Progress tracking / progress assessment / weak areas / adaptive recommendations (Steps 53–56), selective regeneration, plan comparison, role dashboard, quiz answer-vs-source check, Edit action in review, lint warning.

**Honest reality check:** P0 plus items 7–10 and 14–17 already fill a full day. Progress tracking and recommendations (Steps 50–56) are effectively missing and can't be built properly today. Say so in the report's *Limitations* section rather than faking them.
