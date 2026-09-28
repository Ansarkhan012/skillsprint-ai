# SkillSprint AI

SkillSprint AI turns approved company documents into personalised, source-grounded employee onboarding plans. A **GenAI pipeline** drafts the plan as structured JSON, and an **independent, deterministic Python pipeline** verifies it against a human-approved Role Requirement Matrix (RRM) before anything is trusted.

| Layer | Technology | Location |
|---|---|---|
| Web UI | Next.js / React / TypeScript | `apps/web` |
| API | FastAPI, Python 3.12 | `services/api/app` |
| Database, auth, storage | Supabase (PostgreSQL + RLS, Auth, private Storage) | `supabase/migrations` |
| Document processing | PyMuPDF (PDF), python-docx (DOCX) | `document_processing.py`, `documents.py` |
| Adversarial-content scanner | Deterministic rules | `adversarial.py` |
| Role Requirement Matrix | Python rules + SQL | `rrm*.py` |
| GenAI pipeline | Gemini / Groq / NaraRouter (OpenAI-compatible) adapters | `generation_*.py`, `nararouter_provider.py` |
| Prompt templates and versions | Versioned, hashed templates | `generation_prompt.py` (`phase4d-compact-context/2.0.0`) |
| Output JSON schema | Strict Pydantic model (`onboarding-plan/1.0.0`) | `generation_output.py` |
| Python validation + decision | Validator, JEV decision table | `plan_validator.py`, `jev.py` |
| GenAI vs Python comparison | CSV report | `comparison_report.py` |

Design documents: `ARCHITECTURE.md`, `DATABASE_DESIGN.md`, `GENAI_CONTRACT.md`, `VALIDATION_DESIGN.md`, `JEV_DESIGN.md`, `API_CONTRACTS.md`, `SRS_MATRIX.md`. AI tool usage: `AI_USAGE.md`.

## 1. Prerequisites

- **Python 3.12** (pinned in `.python-version`). Python 3.14 is not supported: a mixed 3.14 venv fails with `No module named 'pydantic_core._pydantic_core'`.
- Node.js 20 or later and npm
- A Supabase project (PostgreSQL, Auth, Storage)
- An API key for at least one GenAI provider (see section 3)

## 2. Install

From the repository root (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services\api\requirements.txt
cd apps\web
npm install
```

## 3. Configure (secrets stay local)

1. Copy `.env.example` to `.env` in the **repository root**. It is used by the API, and `.env` is gitignored.
2. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (backend only), and `WEB_ORIGIN`.
3. Choose the GenAI provider with `AI_PROVIDER`. There is no automatic cross-provider fallback: each run records exactly one provider and model. To switch, change `AI_PROVIDER` and restart.

   | `AI_PROVIDER` | Required variables | Notes |
   |---|---|---|
   | `nararouter` (default) | `NARAROUTER_API_KEY`, `NARAROUTER_BASE_URL`, `NARAROUTER_MODEL=agnes-2.5-flash` | Free-plan model. Requires migrations up to `202609280005`. Use `NARAROUTER_MAX_OUTPUT_TOKENS=16384`, `NARAROUTER_TIMEOUT_SECONDS=290`. See the model notes below |
   | `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` | The Gemini free tier allows only about 20 requests/day per model |
   | `groq` | `GROQ_API_KEY` (`GROQ_MODEL=openai/gpt-oss-20b`) | Free-tier tokens-per-minute limits can reject full plans (HTTP 413) |

   **NaraRouter model notes** (measured 2026-09-28 with the repository's 6-requirement fixture; one full generation per row):

   | Model | Reasoning | Result |
   |---|---|---|
   | `agnes-2.5-flash` (**default**) | model default | Schema-valid in about 136 s: 5 modules, each with objectives, checklist, task and quiz; traceability 25/25 |
   | `agnes-2.5-flash` | `none` | Schema-valid in 17 s but **0 modules** (validator: Manual Review) |
   | `nemotron-3.5-lightning-free` | `none` | Schema-valid in 26 s but **0 modules** (validator: Incomplete) |
   | `nemotron-3.5-lightning-free` | model default | Two unusable responses, 136 s each |
   | `agnes-3-flash` | model default | Truncated at 16,384 output tokens after 3–5 minutes |
   | `gemini-3.8-flash-high` | — | Pay-as-you-go: HTTP 402 (`PROVIDER_PAYMENT_REQUIRED`) without credits |

   `NARAROUTER_TIMEOUT_SECONDS` (max 290, default 290) is a **total** deadline per provider call, below the 300 s gateway/Vercel request limit. Overruns fail with `PROVIDER_DEADLINE_EXCEEDED` and are not retried. A whole run is capped at 295 s: a retry happens only if it could still finish within that, so one long attempt runs at most. See Limitations.

4. Create `apps/web/.env.local` containing `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `API_BASE_URL=http://127.0.0.1:8000`, and the same `MAX_UPLOAD_BYTES`.

Never put a provider key, `SUPABASE_SERVICE_ROLE_KEY`, or `DATABASE_URL` in a `NEXT_PUBLIC_*` variable, and never commit `.env`.

## 4. Database

Apply the migrations in `supabase/migrations` **once each, in filename order**, using the Supabase SQL editor or your migration workflow. The later ones are manual, reviewed steps:

- `202609270002_nararouter_generation_provider.sql` and `202609280001_nararouter_model_constraint.sql`: run `docs/NARAROUTER_LIVE_CONTRACT_CHECK.sql` first.
- `202609280003_nararouter_free_models.sql`: allows the free-plan NaraRouter models `agnes-2.5-flash`, `agnes-3-flash` and `nemotron-3-ultra-free`.
- `202609280004_generation_timeout_180.sql`: raises the per-call deadline bound from 60 s to 180 s.
- `202609280005_generation_timeout_290.sql`: raises it to 290 s (below the 300 s gateway limit).
- `202609280002_validation_warning_findings.sql`: lets *Verified with Warning* results (for example staged timing warnings) be saved.

Bootstrap:

1. Create the first Auth user in Supabase. Insert its `profiles` row and an `ADMIN` role from the SQL editor; see `supabase/testing/bootstrap_existing_auth_user_role.sql`. Public signup cannot grant roles.
2. Create the standard onboarding stage set once. It has five stages: Orientation (day 0–1), Policies & Compliance (1–3), Role-Specific Training (2–5), Practical Application (4–7), and Assessment & Completion (day 7). There is no UI button, and the function requires an active Admin identity. Two options:

   **Option A (Supabase SQL editor):** runs as your existing Admin profile, with no token needed. It is safe to re-run; it returns the existing set.

   ```sql
   begin;
   select set_config('request.jwt.claims', json_build_object('role', 'authenticated', 'sub',
     (select p.auth_user_id from public.profiles p join public.profile_roles r on r.profile_id = p.id
       where r.role = 'ADMIN' and p.status = 'ACTIVE' order by p.created_at limit 1))::text, true);
   set local role authenticated;
   select public.bootstrap_standard_onboarding_stages() as stage_set_id;
   commit;
   ```

   **Option B (API):** `POST http://127.0.0.1:8000/api/v1/onboarding-stage-sets/bootstrap` with header `Authorization: Bearer <admin access token>`.

## 5. Run

Start the API from the **repository root**. `.env` is read from the working directory; starting elsewhere causes `GENERATION_PROVIDER_NOT_CONFIGURED`.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services\api --reload
```

In a second terminal:

```powershell
cd apps\web
npm run dev
```

Open `http://localhost:3000/login`. API health: `http://127.0.0.1:8000/api/v1/health`.

## 6. Test

```powershell
.\.venv\Scripts\python.exe -m pytest services\api\tests -q
cd apps\web
npm test
npm run lint
npm run typecheck
npm run build
```

All tests are offline: provider HTTP is mocked and there are no live API calls.

## 7. Evaluator walkthrough

1. **Login** as Admin or Training Manager.
2. **Upload documents** (Documents → Upload). Use PDF or DOCX with a code, title, category, version label, and effective date. Python validates the file type, size, signature, and duplicate checksum, then extracts text with page/paragraph/table locators and chunks it. Chunks with suspected prompt-injection or adversarial instructions show a **"Possible prompt injection"** badge. They are treated as data and never executed.
3. **Submit → approve** each version. A different reviewer approves it; a new version supersedes the old one once effective.
4. **Create roles and employees** (Departments & roles, Employees).
5. **Build the Role Requirement Matrix** (Ground Truth / RRM). Author requirements linked to evidence chunks with mandatory/optional status, priority, stage, timing, and dependencies. Resolve conflicts using the configured precedence, then submit and approve the matrix.
6. **Generate an onboarding plan** (Onboarding Plans → Check readiness → Generate once). The result is *Unverified* until validated.
7. **Run validation** (Validate on the plan). The deterministic Python validator reports:
   - mandatory coverage
   - source traceability
   - missing, unsupported, and contradictory requirements
   - dependency order
   - duplicates
   - stale or outdated sources

   The JEV decision is one of: Verified, Verified with Warning, Incomplete, Unsupported, Contradictory, or Manual Review.
8. **Review comparison, hallucination, and contradiction findings** (Validation & Reviews). Export **"GenAI vs Python comparison (CSV)"** for the requirement-level report.
9. **Approve, reject, regenerate, or override** (reviewer/Admin). The original JEV result is never rewritten.
10. **Update a policy.** Upload a new version of the same document. Re-validating plans that used the old evidence reports `OUTDATED_SOURCE` / `STALE_INPUT`.

## 8. Key behaviours

- **Coverage score** = covered mandatory requirements ÷ mandatory requirements. A requirement counts as covered only through a module with valid, approved source support.
- **Traceability score** = generated items whose every source reference (document version + chunk + locator) is approved evidence for each requirement they cite ÷ all generated items. It is also reported separately for mandatory-module content.
- **Hallucination handling.** Requirement IDs or sources not in the approved matrix are flagged `UNSUPPORTED_REQUIREMENT` / `SOURCE_REFERENCE_INVALID`. The model is instructed to use `insufficient_information` rather than invent rules, and any such entry is routed to Manual Review.
- **Prompt injection.**
  - The model receives the approved requirement statements and source references, never raw document text.
  - Supplied data is wrapped and labelled as untrusted.
  - The validator ignores any claims the model makes about its own output.
  - Uploads are scanned for adversarial instructions and flagged for review.
- **Structured output.** The provider receives a JSON Schema derived from the Pydantic model. Python then re-validates strictly. A schema failure gets exactly one format retry that names the failing fields.
- **Retries.** Timeouts, 5xx, and 429 responses get at most 3 attempts with 2 s / 4 s backoff (capped at 8 s). Every attempt is logged and persisted. HTTP 402 is reported as `PROVIDER_PAYMENT_REQUIRED`.
- **Timing.** Structured timing on a requirement with an assigned stage is checked at stage level and adds a warning (Verified with Warning). Ambiguous or unstaged timing requires manual review.
- **Policy precedence** is configurable per matrix (Ground Truth / RRM → precedence ranks; a higher rank means more authority). Document the hierarchy used for your company pack here: _Latest approved policy > Department SOP > FAQ > Informal guidance_ (edit to match your configuration).
- **Provenance.** Every run records the provider, model, prompt version, template hash, projection hash, input snapshot hash, and timestamps.

### Authoring requirements

When you create requirements for a role in Ground Truth / RRM, **link each requirement only to the chunk that states its obligation** (for example "The employee must complete X within 2 calendar days after the employee's joining date"). Do not also link shared chunks such as definitions ("Joining date: …", "Calendar day: …") or scope text ("This standard applies to …") unless the obligation genuinely cannot be evidenced without them.

This matters because the validator requires every generated item to cite *all* of its requirement's evidence. Each extra shared chunk is therefore repeated on every objective, task, quiz and checklist item, which inflates the model output and can push generation past its deadline. Structured timing can usually be evidenced entirely from the obligation sentence: it contains the relation, number, unit, calendar basis and trigger.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No module named 'pydantic_core._pydantic_core'` | The venv was not created with Python 3.12. Recreate `.venv` (section 2) |
| `GENERATION_PROVIDER_NOT_CONFIGURED` (503) | Missing provider variables, or the API was not started from the repository root |
| `PROVIDER_PAYMENT_REQUIRED` | The provider account has no credits. Top up or switch `AI_PROVIDER` |
| `PROVIDER_RATE_LIMIT` / `PROVIDER_UNAVAILABLE` after 3 attempts | Provider quota or overload. Wait, or switch provider |
| `GENERATION_PROJECTION_TOO_LARGE` on Groq | Free-tier tokens-per-minute limit. Use another provider |
| `SCHEMA_INVALID` | The model output did not match `onboarding-plan/1.0.0` after one retry. Server logs list only field paths |
| Generation fails at reservation (422/409) | The provider/model pair or prompt pin is not in the database. Apply the migrations in section 4 |
| `VALIDATION_STATE_CONFLICT` when saving a Verified-with-Warning result | Apply `202609280002_validation_warning_findings.sql` |

## 10. Permissions

| Role | Profile | Directory read | Create department | Create role/employee | Admin check |
|---|---|---|---|---|---|
| Admin | Own | Yes | Yes | Yes | Yes |
| Training Manager | Own | Yes | No | Yes | No |
| Reviewer | Own | Yes | No | No | No |
| Manager | Own | Departments/roles; own team employees | No | No | No |
| Employee | Own | No directory access | No | No | No |

The API enforces RBAC on the server before each operation, and Supabase RLS protects rows and writes. Client navigation visibility is not authorization. Detailed live RLS checks are in `docs/PHASE1_RBAC_RLS_VERIFICATION.md`.

## 11. Limitations

- Requirements are authored by people in the RRM (with evidence links). They are not extracted automatically, because the matrix is the approved ground truth.
- Factual entailment of generated prose is not machine-checked. Grounding is enforced through requirement IDs and approved source references.
- Employee progress tracking, weak-area detection, adaptive recommendations, impact analysis, selective regeneration, and the consistency score (SRS Steps 44–45, 50–59) are not implemented.
- **Latency:** full-plan generation on the free NaraRouter models takes about 136 s (agnes-2.5-flash), against the SRS 30-second target. The backend allows up to 290 s per provider call and 295 s per run so it completes. Per-stage parallel generation is designed as the fix but not implemented; see `docs/PER_STAGE_GENERATION_DESIGN.md`.
- OCR is not used. Scanned PDFs without text are marked *Needs review*.

## 12. Links

- Deployed application: _TODO_
- Demonstration video (.mp4): _TODO_
- Technical blog: _TODO_
