"use client";

import { useRef, useState, useSyncExternalStore } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/page-header";
import { fixtureAttemptKey, fixtureEmployeeCode, fixtureEmployeeId, fixtureIsReady,
  safeCode, safeRunSummary, type Preflight } from "@/lib/phase4d-test";

const gateway = "/api/document-gateway/generation-runs";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type GenerationResponse = { http_status: number; id?: string; status?: string; error_code?: string; idempotent_replay?: boolean };
type RunSummary = ReturnType<typeof safeRunSummary>;

async function jsonResponse(response: Response): Promise<Record<string, unknown>> {
  const value: unknown = await response.json().catch(() => null);
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function subscribeToAttemptStorage(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function storedAttempt(): boolean {
  try { return Boolean(window.localStorage.getItem(fixtureAttemptKey)); }
  catch { return true; } // Missing storage must never enable another POST.
}

export function Phase4DTestSurface() {
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [preflightStatus, setPreflightStatus] = useState<number | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [generationBusy, setGenerationBusy] = useState(false);
  const [locallyAttempted, setLocallyAttempted] = useState(false);
  const storedAttempted = useSyncExternalStore(subscribeToAttemptStorage, storedAttempt, () => true);
  const attempted = locallyAttempted || storedAttempted;
  const [generation, setGeneration] = useState<GenerationResponse | null>(null);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState("");
  const postStarted = useRef(false);

  async function runPreflight() {
    if (preflightBusy || generationBusy) return;
    setPreflightBusy(true);
    setPreflight(null);
    setPreflightStatus(null);
    setError("");
    try {
      const response = await fetch(`${gateway}/preflight/${fixtureEmployeeId}`, {
        method: "GET", credentials: "same-origin", cache: "no-store",
      });
      const body = await jsonResponse(response);
      setPreflightStatus(response.status);
      if (!response.ok) { setError(safeCode(body.code ?? body.detail, `HTTP_${response.status}`)); return; }
      setPreflight(body as Preflight);
    } catch { setError("PREFLIGHT_REQUEST_FAILED"); }
    finally { setPreflightBusy(false); }
  }

  async function generateOnce() {
    if (postStarted.current || attempted || generationBusy || preflightBusy || !preflight || !fixtureIsReady(preflight)) return;
    postStarted.current = true;
    setError("");
    // Persist the guard BEFORE the POST. An ambiguous network failure must not invite another run.
    try {
      if (window.localStorage.getItem(fixtureAttemptKey)) { setLocallyAttempted(true); return; }
      window.localStorage.setItem(fixtureAttemptKey, "ATTEMPTED");
    } catch { setError("BROWSER_STORAGE_UNAVAILABLE"); return; }
    setLocallyAttempted(true);
    setGenerationBusy(true);
    try {
      const response = await fetch(gateway, {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ employee_id: fixtureEmployeeId }),
      });
      const body = await jsonResponse(response);
      const result: GenerationResponse = {
        http_status: response.status,
        id: typeof body.id === "string" ? body.id : undefined,
        status: typeof body.status === "string" ? body.status : undefined,
        error_code: typeof body.error_code === "string" ? safeCode(body.error_code, "GENERATION_FAILED") : undefined,
        idempotent_replay: body.idempotent_replay === true,
      };
      setGeneration(result);
      if (!response.ok) { setError(safeCode(body.code ?? body.detail, `HTTP_${response.status}`)); return; }
      if (response.status !== 202 || !result.id || !uuidPattern.test(result.id)) {
        setError("GENERATION_RESPONSE_UNEXPECTED"); return;
      }
      // One authenticated, read-only detail lookup. Never display the stored plan or snapshot.
      const detailResponse = await fetch(`${gateway}/${result.id}`, {
        method: "GET", credentials: "same-origin", cache: "no-store",
      });
      const detail = await jsonResponse(detailResponse);
      if (!detailResponse.ok) { setError(safeCode(detail.code ?? detail.detail, `HTTP_${detailResponse.status}`)); return; }
      setRun(safeRunSummary(detail));
    } catch { setError("GENERATION_RESULT_UNAVAILABLE_NO_RETRY"); }
    finally { setGenerationBusy(false); }
  }

  const ready = preflightStatus === 200 && preflight !== null && fixtureIsReady(preflight);
  return <div className="space-y-6">
    <PageHeader eyebrow="Internal verification · Phase 4D" title="Controlled generation test"
      description="This one-shot test surface is not the final Onboarding Plans workspace. Generation stays UNVERIFIED; Phase 5 validation is not run here." />
    <section className="space-y-3 rounded-md border border-border bg-card p-5 shadow-panel">
      <h2 className="font-semibold">Controlled employee</h2>
      <p className="text-sm">{fixtureEmployeeCode} · Fictional Engineering Developer</p>
      <p className="break-all font-mono text-xs text-muted-foreground">{fixtureEmployeeId}</p>
      <Button type="button" variant="outline" disabled={preflightBusy || generationBusy} onClick={runPreflight}>
        {preflightBusy ? "Checking…" : "Run Preflight"}
      </Button>
      {preflightStatus !== null && <div className="space-y-1 text-sm" aria-live="polite">
        <p>HTTP {preflightStatus} · <Badge tone={ready ? "success" : "warning"}>{preflight?.readiness ?? "Unavailable"}</Badge></p>
        {preflight && <><p>Employee: {preflight.employee_id ?? "—"}</p>
          <p>Requirements: {preflight.requirement_count ?? "—"} · Dependencies: {preflight.dependency_count ?? "—"}</p>
          <p>Matrix: {preflight.matrix_id ?? "—"} · revision {preflight.matrix_revision ?? "—"}</p>
          <p>Stage set: {preflight.stage_set_id ?? "—"} · version {preflight.stage_set_version ?? "—"}</p>
          <p>Frozen input hash present: {typeof preflight.input_hash === "string" && /^[a-f0-9]{64}$/.test(preflight.input_hash) ? "Yes" : "No"}</p>
          <p>Blockers: {preflight.blocker_codes?.length ? preflight.blocker_codes.join(", ") : "None"}</p>
        </>}
      </div>}
    </section>
    <section className="space-y-3 rounded-md border border-border bg-card p-5 shadow-panel">
      <h2 className="font-semibold">One controlled provider run</h2>
      <p className="text-sm text-muted-foreground">Only you can start this request. The button locks before its single POST and stays locked if the outcome is uncertain.</p>
      <Button type="button" disabled={!ready || attempted || generationBusy || preflightBusy} onClick={generateOnce}>
        {generationBusy ? "Generating…" : attempted ? "Generation already attempted in this browser" : "Generate Once"}
      </Button>
      {generation && <div className="space-y-1 text-sm" aria-live="polite">
        <p>HTTP {generation.http_status} · Run ID: {generation.id ?? "Unavailable"}</p><p>Status: {generation.status ?? "Unavailable"}</p>
        <p>Error: {generation.error_code ?? "None"} · Idempotent replay: {generation.idempotent_replay ? "Yes" : "No"}</p>
      </div>}
      {run && <div className="space-y-1 text-sm" aria-live="polite">
        <p>Persisted: {run.status ?? "Unavailable"} · {run.provider ?? "—"} / {run.model ?? "—"}</p>
        <p>Prompt: {run.prompt_version ?? "—"} · schema: {run.schema_version ?? "—"}</p>
        <p>Hashes present — input: {run.input_hash_present ? "Yes" : "No"}, projection: {run.projection_hash_present ? "Yes" : "No"}, template: {run.template_hash_present ? "Yes" : "No"}</p>
        <p>Plan count: {run.generated_plan_count} · status: {run.plan_status ?? "—"} · schema: {run.plan_schema_version ?? "—"}</p>
        <p>Plan employee: {run.employee_id ?? "—"} · stages: {run.stage_count} · modules: {run.module_count} · referenced requirements: {run.referenced_requirement_count}</p>
        <p>Attempts: {run.attempts.map((item) => `${item.attempt_no ?? "?"} ${item.attempt_type ?? "?"}/${item.provider_outcome ?? "?"}/${item.parse_outcome ?? "?"}${item.error_code ? ` (${item.error_code})` : ""}`).join(" · ") || "None"}</p>
      </div>}
    </section>
    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
  </div>;
}
