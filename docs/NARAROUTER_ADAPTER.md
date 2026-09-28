# NaraRouter adapter

The backend selects this transport only with `AI_PROVIDER=nararouter`. There is no
provider fallback. `NARAROUTER_API_KEY`, `NARAROUTER_BASE_URL`, and
`NARAROUTER_MODEL` are mandatory; invalid configuration fails with a safe 503.
The local backend environment now selects `gemini-3.8-flash-high`, discovered
with the replacement key through authenticated `/v1/models` on 2026-09-28.
No provider credential is stored in frontend configuration.

The adapter posts to `<base URL>/chat/completions` with a Bearer credential,
the existing V2 system/rules and user messages, JSON-object response format,
`stream=false`, temperature, and `max_tokens`. This OpenAI-compatible envelope
matches the documented chat endpoint; model-specific JSON mode and completion
behavior remain untested. Redirects are disabled. Neither credentials nor raw error bodies
are logged by the adapter.

The existing projection budget and 24,576-byte serialized provider body limit
apply before HTTP, including format retries. Requests are never truncated.
Successful responses require one choice, a stop finish reason, and nonempty
text. The response parsing limit is 2,000,000 bytes after HTTP buffering.

401 maps to authentication failure; 403 maps to `PROVIDER_ACCESS_DENIED`.
404 and other non-success statuses map
to request failure; 413 maps to the projection-size failure. These are permanent.
408/timeouts and transport/5xx failures use existing bounded retries. 429 is
retryable only with the existing bounded Retry-After value (0.5–2 seconds).
Malformed or empty responses use the existing single format retry. Provider
error bodies are never passed into errors or retry prompts.

Requested provider and configured model remain generation-run provenance.
Returned model identity is optional, limited to 100 safe identifier characters,
and never authorizes or validates output. Allowlisted nonnegative integer token
counts and request latency are available on ProviderResult. Returned identity
and token usage are not persisted by the current schema; persistence is deferred.
Existing attempt latency persistence remains unchanged.

`202609270002_nararouter_generation_provider.sql` extends the provider allowlist
and accepts only the discovered NaraRouter alias `gemini-3.8-flash-high`. It preserves the V2 reservation
function's authorization, idempotency, lifecycle and contract pins. Historical
runs and old migrations are unchanged. This migration has not been applied.

Offline tests use mocked HTTP, fictional model identifiers and dummy credentials.
They cover factory/configuration, envelopes and guards, error/retry behavior,
normalization, redirects, provenance, and SQL parity with the V2 function.

The replacement key passed model discovery (HTTP 200); the old key had returned
403 with `telegram_required`. No completion request was made. The catalog reports
a 1,000,000-token context window for the selected alias, but no output-token maximum
or JSON-mode capability. The configured 8192 output tokens preserve the existing
budget; they are not a measured guarantee of successful completion.

Before live use, run `docs/NARAROUTER_LIVE_CONTRACT_CHECK.sql` in the current
Supabase project's SQL Editor. Live introspection is not yet verified: no SQL
credential/session was available, and the read-only REST check returned 403.
Only if the installed body matches local V2, manually execute
`supabase/migrations/202609270002_nararouter_generation_provider.sql`.
The final migration pins the exact discovered alias; other NaraRouter aliases are rejected.
Do not reapply V2 or run an unrestricted migration push.

The adapter adds explicit JSON-only presentation instructions without modifying
the shared V2 projection, template hash, schema, parser, or validator. Both request
variants still pass the serialized-byte guard. Four new mocked tests reject code
fences, leading/trailing prose and reasoning wrappers without repair or extraction.

Offline six-requirement/eight-dependency fixture measurements using the selected
alias: projection 4479 bytes; initial system 7906, user 4619, combined 12525,
serialized request 14160 bytes; format-retry serialized request 14223 bytes.
The final request guard is 24576 bytes. This is the repository's controlled test
fixture, not a fresh live fixture preflight. No full document text is sent.
Maximum calls remain four: two format attempts plus two shared transport retries.
429 permits at most one retry, only for numeric Retry-After from 0.5 to 2 seconds,
and consumes that shared transport budget.

Validation: 644 backend tests passed, including provider, generation, V2, strict
output parsing, independent Python validator and JEV tests. One existing
Starlette/httpx deprecation warning remains. A future authorized E2E run must
verify actual JSON compatibility, output budget and latency after manual DB setup.
