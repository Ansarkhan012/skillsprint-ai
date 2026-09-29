# Controlled DeepSeek generation / 4.1.2

The previous controlled provider was NaraRouter / agnes-2.5-flash. Run
d3427762-e831-4bd1-83ff-c3fdaa079698 returned complete but degenerate content under
4.1.1; validation correctly rejected duplicate quiz options. Historical contracts,
hashes, fixtures and failed-run evidence remain intact.

The current controlled adapter is Official DeepSeek / deepseek-flash, chosen for
documented native JSON Schema support and direct integration:
https://api-docs.deepseek.com/api/create-response/

It posts to https://api.deepseek.com/responses using the pooled HTTPX client.
The key comes from DEEPSEEK_API_KEY, is represented as SecretStr, and is sent only
in the Authorization header. Redirects are disabled. The request uses instructions,
the frozen projected context in input, text.format={type: json_schema,
name: onboarding_content, schema: ...}, reasoning.effort=none, temperature=0.1,
max_output_tokens=8192, and stream=false. No SDK dependency is required.

The new phase4d-content-only/4.1.2 contract retains plan_title and requirements,
with exactly the snapshot's R keys. The schema comes from ContentResponseV412 and
RequirementContentV412, with requirement keys bound from the snapshot. Environment
text caps do not alter it. Python validates the same model plus exact requirement keys.
Each requirement contains only module_title, objective, task, checklist,
quiz_question, quiz_options and correct_option_index.

| Field | Minimum | Maximum |
|---|---:|---:|
| plan_title | 8 | 120 |
| module_title | 5 | 120 |
| objective | 20 | 400 |
| task | 20 | 400 |
| checklist | 10 | 240 |
| quiz_question | 15 | 400 |
| each quiz option | 2 | 160 |

There are exactly three options, distinct ignoring case and whitespace; the correct
index is a strict integer 0..2. Extra fields and missing/extra keys fail closed.
Length floors are a baseline, not proof of semantic quality. Prompts prohibit
placeholder content and ground output in approved statements/evidence and experience.
Document instructions remain untrusted data.

Only a completed assistant message's output_text parts are concatenated. Reasoning
and tool items never become the plan. Incomplete token-limited output is
PROVIDER_TRUNCATED; other incomplete/failed results are rejected. Missing, ambiguous,
non-completed or empty assistant output fails closed. JSON/schema errors remain
separate downstream structural failures. Metadata is limited to known model,
normalized completion status, latency and bounded integer usage counters; arbitrary
provider metadata/error messages are never logged.

Python still owns identity, requirement metadata, IDs, stages/order/dependencies,
sources/evidence, mappings, prompt/schema metadata and deterministic assembly.
Final plan validation, coverage, traceability, dependency checks, hallucination checks,
contradiction handling, JEV and persistence integrity are unchanged.

DeepSeek has one shared retry allowance: at most two calls in total, with at most
one structural retry. The 295-second run budget must fit the entire next call plus
backoff. Default per-call deadline is 120 seconds (175-second retry window).
Auth, payment, deterministic configuration/request failures and persistence invariant
failures are not retried. No provider SDK retry loop exists.

Apply manually, after all migrations through 202609280012:
supabase/migrations/202609290001_deepseek_content_v412.sql

The migration adds the provider/model and exact new prompt/template pair, requires
the projection hash, retains all historical pairs, and leaves reservation invariants
and privileges intact. It changes no employee/matrix/run data. It also reloads the
PostgREST schema. The new template hash is:
c0402bdf188c55d1f467dcb01b94891d75955a442152af80f60e84a929d46180

From D:\SkillSprint-AI, run the following PowerShell commands. These process overrides
select DeepSeek without rewriting the secret-bearing root .env. Use the same
AI_PROVIDER and GENERATION_CONTENT_ONLY settings when restarting the backend.

```powershell
$env:PYTHONPATH='D:\SkillSprint-AI\services\api'
$env:AI_PROVIDER='deepseek'
$env:GENERATION_CONTENT_ONLY='true'
.\.venv\Scripts\python.exe -m app.generation_readiness --employee aa02c897-14d8-4c3c-994a-c707550677ad --snapshot snapshot_aa02c897.json --backend-dir D:\SkillSprint-AI
```

The gate builds the request without sending it. It uses the existing realistic
4.1.0 six-requirement test fixture (also valid under the strengthened 4.1.2 contract),
never a fallback production plan. Offline expected results: mandatory 6/6,
traceability 30/30, VERIFIED_WITH_WARNING (JEV-006, six pre-existing input timing
warnings), deterministic assembly and persistence dry-run success.

Run the read-only SQL printed by the gate after applying the migration. Save its
single JSON result as db_readiness_deepseek.json, then repeat the command with
--db-verification db_readiness_deepseek.json. The previous db_readiness.json is
historical evidence and must not be reused as a DeepSeek verification result.
No live generation is authorized by this implementation task.

## Verification recorded

Complete backend suite: 994 passed, 1 existing Starlette/httpx deprecation warning, 85.39 seconds. Command: .\.venv\Scripts\python.exe -m pytest services/api/tests -q -p no:cacheprovider.

The zero-provider gate was rerun with DNS blocked and the saved input hash checked. Result: DB_VERIFICATION_REQUIRED. See [offline report](deepseek_readiness.txt) and [read-only DB verification SQL](deepseek_db_verification.sql). The new migration has not been executed against PostgreSQL. Mock/static contract tests prove historical function invariants remain unchanged; live DB acceptance remains the manual gate.

Environment variable names detected in root .env (names only; no values):

- SUPABASE_URL
- SUPABASE_ANON_KEY
- SUPABASE_SERVICE_ROLE_KEY
- SUPABASE_JWT_AUDIENCE
- WEB_ORIGIN
- ENVIRONMENT
- GEMINI_API_KEY
- GEMINI_MODEL
- NARAROUTER_API_KEY
- NARAROUTER_BASE_URL
- AI_PROVIDER
- GROQ_API_KEY
- GROQ_MODEL
- GROQ_TIMEOUT_SECONDS
- GROQ_MAX_OUTPUT_TOKENS
- GROQ_TEMPERATURE
- NARAROUTER_MODEL
- NARAROUTER_TIMEOUT_SECONDS
- NARAROUTER_MAX_OUTPUT_TOKENS
- NARAROUTER_TEMPERATURE
- NARAROUTER_REASONING_EFFORT
- GEMINI_MAX_OUTPUT_TOKENS
- GEMINI_TIMEOUT_SECONDS
- GENERATION_MAX_OBJECTIVES_PER_MODULE
- GENERATION_MAX_TASKS_PER_MODULE
- GENERATION_MAX_CHECKLIST_PER_MODULE
- GENERATION_MAX_QUIZ_PER_MODULE
- GENERATION_MAX_KEY_CONCEPTS_PER_MODULE
- GENERATION_MAX_ACTIVITIES_PER_MODULE
- GENERATION_MAX_SCENARIOS_PER_MODULE
- GENERATION_MAX_ASSESSMENTS_PER_MODULE
- GENERATION_MAX_COMPLETION_CRITERIA_PER_MODULE
- GENERATION_MAX_TEXT_LENGTH
- GENERATION_SOURCE_KEYS
- GENERATION_CONTENT_ONLY
- DEEPSEEK_API_KEY

No live DeepSeek call, push, merge, deployment, secret exposure, controlled employee/matrix change or historical run change occurred. Root .env was not rewritten; select the new adapter with the documented process settings. Existing apps/web/next-env.d.ts edits predate this work and were preserved.
