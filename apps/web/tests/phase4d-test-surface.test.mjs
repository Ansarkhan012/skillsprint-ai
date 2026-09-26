import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const helperSource = readFileSync(path.resolve(here, "../src/lib/phase4d-test.ts"), "utf8");
const surfaceSource = readFileSync(path.resolve(here, "../src/components/phase4d/phase4d-test-surface.tsx"), "utf8");
const pageSource = readFileSync(path.resolve(here, "../src/app/app/phase4d-test/page.tsx"), "utf8");
const exports = {};
vm.runInNewContext(ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports }, { filename: "phase4d-test.ts" });
const { fixtureEmployeeId, fixturePromptVersion, fixtureAttemptKey, fixtureIsReady,
  safeCode, safeRunSummary } = exports;

const ready = () => ({ readiness: "READY", employee_id: fixtureEmployeeId,
  requirement_count: 6, dependency_count: 8, blocker_codes: [], input_hash: "a".repeat(64) });

test("generation unlock requires the real fixed-fixture READY shape", () => {
  assert.equal(fixtureIsReady(ready()), true);
  for (const change of [
    { readiness: "BLOCKED" }, { employee_id: "wrong" }, { requirement_count: 5 },
    { dependency_count: 7 }, { blocker_codes: ["STALE_SOURCE"] }, { input_hash: null },
  ]) assert.equal(fixtureIsReady({ ...ready(), ...change }), false);
});

test("compact contract uses a fresh lock key without clearing the historical attempt", () => {
  const oldKey = `phase4d-generation-attempt:${fixtureEmployeeId}`;
  const storage = new Map([[oldKey, "ATTEMPTED"]]);
  assert.equal(fixturePromptVersion, "phase4d-compact-exact-output/1.0.0");
  assert.equal(fixtureAttemptKey, `${oldKey}:${fixturePromptVersion}`);
  assert.equal(storage.has(fixtureAttemptKey), false);
  storage.set(fixtureAttemptKey, "ATTEMPTED");
  assert.equal(storage.get(oldKey), "ATTEMPTED");
  assert.equal(storage.get(fixtureAttemptKey), "ATTEMPTED");
});

test("safe run summary exposes counts and provenance, never raw plan or snapshot", () => {
  const summary = safeRunSummary({ id: "run-id", status: "UNVERIFIED", provider: "groq",
    model: "openai/gpt-oss-20b", prompt_version: "phase4d-exact-output/1.0.0",
    input_hash: "a".repeat(64), projection_hash: "b".repeat(64), template_hash: "c".repeat(64),
    input_snapshot: { secret: "PRIVATE_SOURCE_TEXT" },
    attempts: [{ attempt_no: 1, attempt_type: "INITIAL", provider_outcome: "RESPONSE", parse_outcome: "SCHEMA_VALID", response_hash: "SECRET_RESPONSE" }],
    plan: { status: "UNVERIFIED", schema_version: "onboarding-plan/1.0.0", content: {
      employee_context: { employee_id: fixtureEmployeeId }, plan: { stages: [
        { modules: [{ requirement_ids: ["a", "b"], purpose: "PRIVATE_PLAN_TEXT" }] },
        { modules: [{ requirement_ids: ["b"], purpose: "PRIVATE_PLAN_TEXT" }] },
      ] },
    } },
  });
  assert.equal(summary.generated_plan_count, 1);
  assert.equal(summary.stage_count, 2);
  assert.equal(summary.module_count, 2);
  assert.equal(summary.referenced_requirement_count, 2);
  assert.equal(summary.attempts.length, 1);
  assert.doesNotMatch(JSON.stringify(summary), /PRIVATE_SOURCE_TEXT|PRIVATE_PLAN_TEXT|SECRET_RESPONSE/);
  assert.equal(safeCode("FORBIDDEN_ROLE", "FALLBACK"), "FORBIDDEN_ROLE");
  assert.equal(safeCode("secret-bearing message", "FALLBACK"), "FALLBACK");
});

test("internal page is server role-gated and generation is explicitly user-triggered once", () => {
  assert.match(pageSource, /role === "ADMIN" \|\| role === "TRAINING_MANAGER"/);
  assert.match(surfaceSource, /onClick=\{runPreflight\}/);
  assert.match(surfaceSource, /onClick=\{generateOnce\}/);
  assert.match(surfaceSource, /postStarted\.current = true/);
  assert.match(surfaceSource, /localStorage\.setItem\(fixtureAttemptKey, "ATTEMPTED"\)/);
  assert.match(surfaceSource, /"Idempotency-Key": crypto\.randomUUID\(\)/);
  assert.match(surfaceSource, /method: "POST"/);
  assert.match(surfaceSource, /!ready \|\| attempted \|\| generationBusy/);
  assert.match(surfaceSource, /useSyncExternalStore\(subscribeToAttemptStorage, storedAttempt, \(\) => true\)/);
  assert.doesNotMatch(surfaceSource, /useEffect\(/);
});
