# Runtime configuration investigation

The reported run ba52c169-5bd2-438e-b997-f9c9c3371538 persisted
nararouter / agnes-2.5-flash with prompt phase4d-content-only/4.1.2.
No provider call or database mutation was made during this investigation.

## Root cause and evidence

Before the fix, root .env contained AI_PROVIDER=nararouter,
NARAROUTER_MODEL=agnes-2.5-flash and GENERATION_CONTENT_ONLY=true.
There was no services/api/.env and no DEEPSEEK_MODEL entry in root .env.
The previous readiness command explicitly set AI_PROVIDER=deepseek in its own
PowerShell process. That override did not modify .env or an already-running
Uvicorn process. The earlier report documented the override but did not verify
the server serving the UI. This was an incomplete runtime handoff.

Pydantic BaseSettings precedence is constructor arguments, process environment,
working-directory .env, then defaults (ignoring unused dotenv keys).
app.config.Settings does not declare AI_PROVIDER. Its get_settings() is cached,
and main.py calls it at import for application settings such as CORS and Supabase.
AI selection instead used GeminiEnvironment().ai_provider, newly instantiated in
get_provider_bundle() on every generation request. Provider-specific settings and
SourceKeySettings were also newly instantiated per request. Thus the cached
application Settings was not the source of this stale provider selection.

AI_PROVIDER defaults to gemini in code, not nararouter.
NaraRouterEnvironment requires an explicit model (default None); it does not
silently default to agnes-2.5-flash. The old choices came from configuration.
DeepSeek selection does not catch configuration failures and switch providers.

Uvicorn inherits its launching terminal's environment. Its reload workers inherit
the server/reloader environment; another terminal's $env assignments do not alter
them. We did not dump the running process environment or credentials. The exact
historical terminal environment is not recoverable from the persisted run alone,
but the durable NaraRouter settings and isolated readiness override explain the
observed mismatch without any fallback or cache.

apps/web/.env.local has API_BASE_URL=http://127.0.0.1:8000.
The Next.js document-gateway route builds generation URLs using apiBaseUrl(),
which reads process.env.API_BASE_URL. Listeners were observed at 3000 and 8000.
The inspected Uvicorn command selected app.main:app, services/api and --reload.
Readiness was a separate CLI process, never an HTTP check of that server.
After the fix, a read-only GET of the existing listener's generation-config
returned exactly deepseek / deepseek-flash / content-only / 4.1.2.
Because --reload was active, edits were picked up without us launching another
server. A clean demo restart is still recommended.

## Changes

- Root .env now durably sets AI_PROVIDER=deepseek,
  DEEPSEEK_MODEL=deepseek-flash and GENERATION_CONTENT_ONLY=true.
  The DEEPSEEK_API_KEY line was preserved byte-for-byte and never displayed.
- generation_runtime.py centralizes provider configuration and accepted target
  checks. API and readiness use the same resolver, without caching or fallback.
- The API refuses mismatched 4.1.2 configuration with HTTP 503
  GENERATION_CONFIGURATION_MISMATCH before reserve/claim/provider calls.
  Explicit NaraRouter adapter selection remains available for historical modes.
- Startup logs only four safe configuration fields. Invalid configuration logs
  unavailable values without echoing exception inputs.
- GET /api/v1/generation-config resolves the serving process's current configuration,
  returns exactly those four fields, or a safe 503. No database/provider access.
- The existing authenticated frontend proxy now permits generation-config GET.
- scripts/start-demo-backend.ps1 anchors the working directory to the repository
  root and removes inherited AI_PROVIDER, DEEPSEEK_MODEL and
  GENERATION_CONTENT_ONLY overrides only. The root .env then owns demo selection.
  It refuses to start when port 8000 is occupied. It never prints credentials.

## Safe local settings

AI_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-flash
GENERATION_CONTENT_ONLY=true

Keep the existing DEEPSEEK_API_KEY unchanged. Do not paste or print its value.
All other provider credentials and historical settings remain intact.

## Stop, restart and prove the serving process

In the existing backend terminal, press Ctrl+C. This stops the reloader and worker.
From D:\SkillSprint-AI:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-demo-backend.ps1
```

In another terminal:

```powershell
$c = Invoke-RestMethod http://127.0.0.1:8000/api/v1/generation-config
if ($c.ai_provider -ne 'deepseek' -or $c.ai_model -ne 'deepseek-flash' -or
    $c.generation_mode -ne 'content-only' -or
    $c.prompt_target -ne 'phase4d-content-only/4.1.2') {
    throw 'STOP: backend generation configuration mismatch'
}
$c
```

In the signed-in frontend browser, visit
http://localhost:3000/api/document-gateway/generation-config.
It must return the same four fields. This traverses the same apiBaseUrl() and
authenticated proxy used by generation. A 401 requires login; 404 requires
updated/restarted frontend/backend; 503 blocks generation. These GETs do not
reserve a run or call a provider.

Direct Uvicorn launch is still supported when started from the root with clean
process variables, but the script is the deterministic demo entry point.
This check confirms runtime selection only; it does not authorize generation or
replace the separate database contract gate.

## Verification result

Complete backend suite: 1007 passed, 1 existing Starlette/httpx deprecation warning, 91.37 seconds. New configuration tests forbid outbound HTTP transport, verify both explicit adapter selections, reject fallback, compare API/readiness configuration, check startup/endpoint secret safety, and prove incompatible runs never reach reservation. The existing backend config GET returned the expected four values. No live generation, push, merge or deployment occurred.
