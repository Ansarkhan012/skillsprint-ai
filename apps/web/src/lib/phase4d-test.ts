/** Internal, fixed-fixture Phase 4D verification display. No authorization decisions live here. */
export const fixtureEmployeeId = "aa02c897-14d8-4c3c-994a-c707550677ad";
export const fixtureEmployeeCode = "P4D-ENG-001";
export const fixturePromptVersion = "phase4d-compact-exact-output/1.0.0";
export const fixtureAttemptKey = `phase4d-generation-attempt:${fixtureEmployeeId}:${fixturePromptVersion}`;

export type Preflight = {
  readiness?: string;
  employee_id?: string;
  matrix_id?: string | null;
  matrix_revision?: number | null;
  stage_set_id?: string | null;
  stage_set_version?: number | null;
  requirement_count?: number | null;
  dependency_count?: number | null;
  input_hash?: string | null;
  blocker_codes?: string[];
};

export function fixtureIsReady(value: Preflight): boolean {
  return value.readiness === "READY" && value.employee_id === fixtureEmployeeId
    && value.requirement_count === 6 && value.dependency_count === 8
    && Array.isArray(value.blocker_codes) && value.blocker_codes.length === 0
    && typeof value.input_hash === "string" && /^[a-f0-9]{64}$/.test(value.input_hash);
}

export function safeCode(value: unknown, fallback: string): string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{2,79}$/.test(value) ? value : fallback;
}

type UnknownRow = Record<string, unknown>;
function row(value: unknown): UnknownRow { return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRow : {}; }
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function text(value: unknown): string | null { return typeof value === "string" ? value : null; }

export function safeRunSummary(value: unknown) {
  const run = row(value);
  const plan = row(run.plan);
  const content = row(plan.content);
  const planBody = row(content.plan);
  const stages = list(planBody.stages).map(row);
  const modules = stages.flatMap((stage) => list(stage.modules).map(row));
  const requirementIds = new Set(modules.flatMap((module) => list(module.requirement_ids).filter(
    (id): id is string => typeof id === "string")));
  return {
    run_id: text(run.id), status: text(run.status), error_code: text(run.error_code),
    provider: text(run.provider), model: text(run.model), prompt_version: text(run.prompt_version),
    schema_version: text(run.schema_version),
    input_hash_present: typeof run.input_hash === "string" && /^[a-f0-9]{64}$/.test(run.input_hash),
    projection_hash_present: typeof run.projection_hash === "string" && /^[a-f0-9]{64}$/.test(run.projection_hash),
    template_hash_present: typeof run.template_hash === "string" && /^[a-f0-9]{64}$/.test(run.template_hash),
    generated_plan_count: run.plan ? 1 : 0, plan_status: text(plan.status),
    plan_schema_version: text(plan.schema_version), employee_id: text(row(content.employee_context).employee_id),
    stage_count: stages.length, module_count: modules.length, referenced_requirement_count: requirementIds.size,
    attempts: list(run.attempts).map((item) => {
      const attempt = row(item);
      return { attempt_no: typeof attempt.attempt_no === "number" ? attempt.attempt_no : null,
        attempt_type: text(attempt.attempt_type), provider_outcome: text(attempt.provider_outcome),
        parse_outcome: text(attempt.parse_outcome), error_code: text(attempt.error_code) };
    }),
  };
}
