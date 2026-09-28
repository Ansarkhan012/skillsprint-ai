import type { Me } from "@/lib/api";
export type Page<T> = { items: T[]; offset: number; limit: number; has_more: boolean };
export type Department = { id: string; code: string; name: string; status: string };
export type JobRole = Department & { department_id: string | null };
export type Employee = { id: string; employee_code: string; profile_id: string | null; role_id: string; department_id: string; experience_level: string; joining_date: string; training_status: string; location_code: string | null; manager_employee_id: string | null; profiles?: { display_name: string } | null };
export type SourceRef = { document_id?: string; document_version_id: string; chunk_id: string; locator: string | Record<string, unknown> };
export type PlanModule = { module_id: string; title: string; purpose: string; category: string; mandatory: boolean; priority: string; difficulty: string; estimated_minutes: number; requirement_ids: string[]; source_refs: SourceRef[]; prerequisite_module_ids: string[]; checklist_items?: Array<{ checklist_item_id: string; activity: string; responsible_role: string; required: boolean }>; learning_objectives?: Array<{ objective_id: string; statement: string }>; assessments?: Array<{ assessment_id: string; title: string; instructions: string }> };
export type Run = { id: string; employee_id: string; employee_profile_id?: string | null; created_by: string; status: string; error_code: string | null; created_at: string; provider: string; model: string; prompt_version: string; schema_version: string; matrix_id: string; matrix_revision: number; stage_set_version: number; input_hash?: string; projection_hash?: string; template_hash?: string; attempts?: Array<{ attempt_no: number; attempt_type: string; provider_outcome: string; parse_outcome: string; error_code: string | null }>; plan?: { id: string; status: string; schema_version: string; content: { plan: { title: string; summary: string; stages: Array<{ stage_id: string; label: string; sequence: number; target_start_day: number; target_end_day: number; modules: PlanModule[] }> }; insufficient_information?: Array<{ request_path: string; topic: string; reason_code: string; detail: string; requirement_id?: string | null }> } } | null };
export type Finding = { id: string; code: string; severity: string; requirement_id: string | null; location: string; explanation: string; evidence: SourceRef[] };
export type Validation = { id: string; generated_plan_id: string; validator_version: string; completed_at: string; summary: { mandatory_total: number; mandatory_covered: number; finding_count: number; generated_items_total?: number; generated_items_traceable?: number; mandatory_items_total?: number; mandatory_items_traceable?: number }; jev_decisions?: { status: string }; decision?: { status: string; jev_version: string }; plan_context?: Pick<Run, "id" | "employee_id" | "employee_profile_id" | "created_by"> | null; findings?: Finding[]; review_actions?: Array<{ id: string; action: string; reason: string; actor_profile_id: string; created_at: string }>; review_actions_has_more?: boolean };
export class ProductError extends Error { constructor(public status: number, public code: string, public generationRetrySafe = false) { super(code); } }
export const needsSignIn = (error: unknown) => error instanceof ProductError && error.status === 401;
export async function productRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/document-gateway/${path}`, { ...init, credentials: "same-origin", cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ProductError(response.status, typeof body?.code === "string" && /^[A-Z0-9_]+$/.test(body.code) ? body.code : "REQUEST_FAILED", body?.generation_retry_safe === true);
  return body as T;
}
export function postProduct<T>(path: string, body: unknown, headers?: Record<string, string>) {
  return productRequest<T>(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
}
export const canAuthor = (me: Me) => me.roles.some((role) => role === "ADMIN" || role === "TRAINING_MANAGER");
export const canReadGeneration = (me: Me) => me.roles.some((role) => ["ADMIN", "TRAINING_MANAGER", "REVIEWER"].includes(role));
export function humanize(value: string) { return value.replaceAll("_", " ").toLowerCase().replace(/^./, (s) => s.toUpperCase()); }
export function errorMessage(error: unknown): string {
  if (error instanceof ProductError) {
    if (error.status === 401) return "Your session has expired. Sign in again to continue.";
    if (error.status === 403) return "Your account does not have permission for this action or record.";
    if (error.status === 404) return "This record is unavailable or has not been created yet.";
    if (error.status === 409) return "The record changed or an action conflicts with its current state. Refresh and review before continuing.";
    if (error.status === 422) return "Check the required fields and selected references, then try again.";
  }
  return "The data service could not complete this request. Check your connection and try again.";
}
export function generationMessage(code: string | null) {
  const messages: Record<string, string> = {
    GENERATION_PROJECTION_TOO_LARGE: "Generation could not be completed because the prepared onboarding context exceeded the current generation limit.",
    PROVIDER_UNAVAILABLE: "The generation provider was unavailable. No onboarding plan was created.",
    PROVIDER_RATE_LIMIT: "The provider rate limit was reached. No onboarding plan was created.",
    SCHEMA_INVALID: "The generated response did not meet the required plan structure. It was not accepted as a plan.",
    PROVIDER_REQUEST_FAILED: "The provider could not accept the generation request. No onboarding plan was created.",
    PROVIDER_DEADLINE_EXCEEDED: "The AI model did not finish within the configured time limit. No onboarding plan was created. Try a faster model or retry later.",
    PROVIDER_PAYMENT_REQUIRED: "The GenAI provider account has insufficient credits (HTTP 402). Top up the account or switch AI_PROVIDER. No onboarding plan was created.",
  };
  return messages[code ?? ""] ?? "Generation did not produce an accepted plan. The attempt is retained in the history below.";
}
/** Source traceability (SRS Step 30) from recorded validator counts; null for results recorded before it existed. */
export function traceabilityLabel(summary: Validation["summary"]) {
  const { generated_items_total: total, generated_items_traceable: traced, mandatory_items_total: mTotal, mandatory_items_traceable: mTraced } = summary;
  if (total == null || traced == null) return null;
  if (total === 0) return "No generated items to trace";
  const pct = (a: number, b: number) => `${Math.floor((a / b) * 1000) / 10}%`;
  return `${pct(traced, total)} (${traced} of ${total} items)` + (mTotal ? ` · mandatory ${pct(mTraced ?? 0, mTotal)}` : "");
}
/** Dashboard metrics over the loaded, authorized records only; null means the data was unavailable. */
export function dashboardMetrics(validations: Validation[] | null, employees: Employee[] | null) {
  const percent = (part: number, whole: number) => whole > 0 ? Math.floor((part / whole) * 1000) / 10 : null;
  const decision = (v: Validation) => v.jev_decisions?.status ?? v.decision?.status ?? "UNKNOWN";
  const traced = validations?.filter((v) => (v.summary.generated_items_total ?? 0) > 0) ?? [];
  return {
    validationCount: validations?.length ?? null,
    coverage: validations ? percent(validations.reduce((n, v) => n + v.summary.mandatory_covered, 0), validations.reduce((n, v) => n + v.summary.mandatory_total, 0)) : null,
    traceability: percent(traced.reduce((n, v) => n + (v.summary.generated_items_traceable ?? 0), 0), traced.reduce((n, v) => n + (v.summary.generated_items_total ?? 0), 0)),
    tracedCount: traced.length,
    flagged: validations ? validations.filter((v) => !["VERIFIED", "VERIFIED_WITH_WARNING"].includes(decision(v))).length : null,
    employees: employees?.length ?? null,
  };
}
export function canReviewRun(me: Me, run: Pick<Run, "created_by" | "employee_profile_id">) {
  return me.roles.some((r) => r === "ADMIN" || r === "REVIEWER") && me.id !== run.created_by && me.id !== run.employee_profile_id;
}
export function timingLabel(timing: Record<string, unknown>) {
  if (timing.state === "NOT_SPECIFIED") return "No deadline specified by source";
  const original = typeof timing.original_text === "string" ? timing.original_text : "";
  return `${original}${timing.state === "AMBIGUOUS" ? " · Manual review required" : " · Evidence-backed timing"}`;
}

/** Store before sending; release only an explicitly proven pre-generation rejection. */
export async function generateOnce<T>(storage: Pick<Storage, "getItem" | "setItem"> & Partial<Pick<Storage, "removeItem">>, key: string, employeeId: string,
  send: (path: string, body: unknown, headers: Record<string, string>) => Promise<T>) {
  if (storage.getItem(key)) throw new ProductError(409, "GENERATION_ALREADY_ATTEMPTED");
  const idempotencyKey = crypto.randomUUID();
  storage.setItem(key, idempotencyKey);
  try {
    return await send("generation-runs", { employee_id: employeeId }, { "Idempotency-Key": idempotencyKey });
  } catch (error) {
    if (error instanceof ProductError && error.status === 422 && error.generationRetrySafe
        && storage.getItem(key) === idempotencyKey) storage.removeItem?.(key);
    throw error;
  }
}
