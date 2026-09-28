import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const cache = new Map();
function load(file) {
  const full = [file, file + ".ts", file + ".tsx"].find(existsSync);
  assert.ok(full, file);
  if (cache.has(full)) return cache.get(full);
  const exports = {};
  const code = ts.transpileModule(readFileSync(full, "utf8"), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  vm.runInNewContext(code, { exports, crypto: webcrypto, console, require(name) {
    if (name === "next/link") return { __esModule: true, default: ({ href, children, prefetch: _prefetch, ...props }) => React.createElement("a", { href, ...props }, children) };
    if (name === "next/navigation") return { useRouter: () => ({}), usePathname: () => "/app/dashboard" };
    if (name === "@/lib/supabase/browser") return { createClient: () => { throw Error("No auth side effects in render"); } };
    if (name.startsWith("@/")) return load(path.join(root, name.slice(2)));
    if (name.startsWith(".")) return load(path.resolve(path.dirname(full), name));
    return require(name);
  } }, { filename: full });
  cache.set(full, exports); return exports;
}
const product = load(path.join(root, "lib/product.ts"));
const me = (role) => ({ id: "actor", display_name: "Test account", roles: [role] });

test("trust panel never implies verification without an independent result", () => {
  const { TrustPanel } = load(path.join(root, "components/product/intelligence"));
  const html = renderToStaticMarkup(React.createElement(TrustPanel));
  assert.match(html, /No validation result recorded/);
  assert.match(html, /Awaiting independent validation/);
  assert.doesNotMatch(html, /<progress/);
});

test("run signals distinguish unavailable data from an empty loaded page", () => {
  const { RunSignals } = load(path.join(root, "components/product/intelligence"));
  const render = props => renderToStaticMarkup(React.createElement(RunSignals, props));
  assert.match(render({ runs: null, validations: null }), /Generation history is unavailable/);
  assert.match(render({ runs: [], validations: [] }), /Your first plan starts with approved evidence/);
  const html = render({ runs: [{ id: "failed-run", status: "FAILED", created_at: "2026-09-27T00:00:00Z", matrix_revision: 1 }], validations: [] });
  assert.match(html, /href="\/app\/plans\/failed-run"/);
  assert.match(html, /Failed/);
  assert.match(html, /width:100%/);
});

test("workflow overview makes human control explicit without claiming completion", () => {
  const { WorkflowRail } = load(path.join(root, "components/product/intelligence"));
  const html = renderToStaticMarkup(React.createElement(WorkflowRail));
  for (const label of ["Ground truth", "Python validation", "JEV decision", "Human review", "not a completion indicator"]) assert.ok(html.includes(label));
});

test("only genuine 401 offers sign-in; generation errors never render login navigation", () => {
  const { Problem } = load(path.join(root, "components/product/common"));
  for (const status of [401, 403, 409, 422, 500, 503]) {
    const error = new product.ProductError(status, "SAFE_ERROR");
    const html = renderToStaticMarkup(React.createElement(Problem, { error }));
    assert.equal(html.includes('href="/login"'), status === 401);
    assert.equal(product.needsSignIn(error), status === 401);
  }
});

test("proven pre-provider 422 releases only its own lock; valid request shape is preserved", async () => {
  const values = new Map();
  const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) };
  let calls = 0;
  const employee = "00000000-0000-0000-0000-000000000001";
  const send = async (route, body, headers) => {
    calls++;
    assert.equal(route, "generation-runs");
    assert.deepEqual(JSON.parse(JSON.stringify(body)), { employee_id: employee });
    assert.match(headers["Idempotency-Key"], /^[A-Za-z0-9_-]{8,128}$/);
    throw new product.ProductError(422, "GEN4_INVALID_INPUT", true);
  };
  await assert.rejects(product.generateOnce(storage, "lock", employee, send));
  assert.equal(calls, 1); assert.equal(storage.getItem("lock"), undefined);
});

test("uncertain 422, auth, conflict and service errors retain duplicate protection", async () => {
  for (const status of [401,403,409,422,503]) {
    const values = new Map();
    const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k) };
    let calls = 0;
    const send = async () => { calls++; throw new product.ProductError(status, "SAFE_ERROR"); };
    await assert.rejects(product.generateOnce(storage, "lock", "employee", send));
    await assert.rejects(product.generateOnce(storage, "lock", "employee", send));
    assert.equal(calls, 1); assert.ok(storage.getItem("lock"));
  }
});

test("successful generation retains duplicate protection", async () => {
  const values = new Map(); const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v) };
  let calls = 0; const send = async () => { calls++; return { id: "run" }; };
  await product.generateOnce(storage, "lock", "employee", send);
  await assert.rejects(product.generateOnce(storage, "lock", "employee", send));
  assert.equal(calls, 1);
});

test("all five roles have coherent navigation; debug and unsupported user CRUD are absent", () => {
  const { navigation, canAccess } = load(path.join(root, "components/layout/navigation.ts"));
  assert.ok(!navigation.some((x) => /phase4d|users/.test(x.href)));
  for (const role of ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER", "EMPLOYEE"]) {
    const visible = navigation.filter((n) => canAccess([role], n)).map((n) => n.href);
    assert.ok(visible.includes("/app/settings") && visible.includes("/app/dashboard"));
    if (["MANAGER", "EMPLOYEE"].includes(role)) assert.ok(!visible.includes("/app/reviews") && !visible.includes("/app/documents"));
  }
});
test("directory create controls reflect role permissions in rendered UI", () => {
  const { Directory } = load(path.join(root, "components/product/directory.tsx"));
  const render = (role, kind) => renderToStaticMarkup(React.createElement(Directory, { me: me(role), kind }));
  assert.match(render("ADMIN", "departments"), /Add department/);
  assert.doesNotMatch(render("TRAINING_MANAGER", "departments"), /Add department/);
  assert.match(render("TRAINING_MANAGER", "departments"), /Add job role/);
  assert.doesNotMatch(render("REVIEWER", "employees"), /Add employee/);
  assert.match(render("ADMIN", "employees"), /Add employee/);
});
test("Employee and Manager plan surface does not fetch or expose generation controls", () => {
  const { Plans } = load(path.join(root, "components/product/plans.tsx"));
  for (const role of ["EMPLOYEE", "MANAGER"]) {
    const html = renderToStaticMarkup(React.createElement(Plans, { me: me(role) }));
    assert.match(html, /Plan access for your role/);
    assert.doesNotMatch(html, /Generate once|Check readiness/);
    assert.equal(product.canReadGeneration(me(role)), false);
  }
});
test("self review stays hidden even for Admin and employee subject; independent Reviewer is allowed", () => {
  assert.equal(product.canReviewRun(me("ADMIN"), { created_by: "actor", employee_profile_id: null }), false);
  assert.equal(product.canReviewRun(me("REVIEWER"), { created_by: "other", employee_profile_id: "actor" }), false);
  assert.equal(product.canReviewRun(me("REVIEWER"), { created_by: "other", employee_profile_id: null }), true);
  assert.equal(product.canReviewRun(me("EMPLOYEE"), { created_by: "other" }), false);
});
test("generation lock persists before POST and failure cannot trigger a second POST", async () => {
  const values = new Map(); const storage = { getItem: (k) => values.get(k), setItem: (k, v) => values.set(k, v) };
  let calls = 0;
  const send = async (route, body, headers) => {
    calls++; assert.equal(route, "generation-runs"); assert.equal(body.employee_id, "test-employee");
    assert.equal(values.get("new-product-lock"), headers["Idempotency-Key"]);
    throw Error("Synthetic transport failure");
  };
  values.set("historical-phase4d-lock", "unchanged");
  await assert.rejects(product.generateOnce(storage, "new-product-lock", "test-employee", send));
  await assert.rejects(product.generateOnce(storage, "new-product-lock", "test-employee", send));
  assert.equal(calls, 1); assert.equal(values.get("historical-phase4d-lock"), "unchanged");
});
test("product errors never display raw exception messages and timing ambiguity is preserved", () => {
  assert.doesNotMatch(product.errorMessage(Error("SECRET_OR_STACK")), /SECRET_OR_STACK/);
  assert.match(product.generationMessage("GENERATION_PROJECTION_TOO_LARGE"), /exceeded the current generation limit/);
  assert.match(product.timingLabel({ state: "AMBIGUOUS", original_text: "Within 7 days" }), /Within 7 days · Manual review required/);
});
test("settings renders real account roles with no fake editable provider controls", () => {
  const { Settings } = load(path.join(root, "components/product/settings.tsx"));
  const html = renderToStaticMarkup(React.createElement(Settings, { me: me("TRAINING_MANAGER") }));
  assert.match(html, /Test account/); assert.match(html, /Training manager/); assert.match(html, /Sign out/);
  assert.doesNotMatch(html, /type="checkbox"|API_KEY|Bearer /);
});

function withResource(data, render) {
  const common = load(path.join(root, "components/product/common"));
  const original = common.useResource;
  common.useResource = () => ({ data, loading: false, error: null, refresh() {} });
  try { return render(); } finally { common.useResource = original; }
}
test("failed generation is history, never a plan or a validation action", () => {
  const { Plans } = load(path.join(root, "components/product/plans.tsx"));
  const run = { id: "test-run", status: "FAILED", error_code: "GENERATION_PROJECTION_TOO_LARGE", employee_id: "test-employee", created_by: "actor", created_at: "2026-01-01T00:00:00Z", provider: "groq", model: "test-model", matrix_revision: 1, stage_set_version: 1, attempts: [], plan: null };
  const html = withResource({ run, person: null, validation: null, page: null, employees: [] }, () => renderToStaticMarkup(React.createElement(Plans, { me: me("ADMIN"), runId: "test-run" })));
  assert.match(html, /prepared onboarding context exceeded/);
  assert.match(html, /Recorded generation attempts/);
  assert.doesNotMatch(html, /Run independent validation|Why was this assigned/);
});
test("human override stays separate from contradictory JEV decision in rendered review", () => {
  const { Reviews } = load(path.join(root, "components/product/reviews.tsx"));
  const data = { id: "test-validation", generated_plan_id: "test-plan", validator_version: "test-validator", completed_at: "2026-01-01T00:00:00Z", summary: { mandatory_total: 6, mandatory_covered: 6, finding_count: 0 }, decision: { status: "CONTRADICTORY" }, findings: [], plan_context: { id: "test-run", employee_id: "test-employee", created_by: "other", employee_profile_id: null }, review_actions: [{ id: "action", action: "OVERRIDE", reason: "Recorded independent disposition", created_at: "2026-01-02T00:00:00Z", actor_profile_id: "reviewer" }] };
  const html = withResource(data, () => renderToStaticMarkup(React.createElement(Reviews, { me: me("REVIEWER"), validationId: "test-validation" })));
  assert.match(html, /Contradictory/); assert.match(html, /Override/);
  assert.match(html, /Recorded independent disposition/);
  assert.doesNotMatch(html, />Admin override</);
  assert.match(html, /disabled=""[^>]*>Approve/);
});
test("generation lock release: helpers only allow it with no run in progress and remove only that key", () => {
  assert.equal(product.canReleaseGenerationLock([{ status: "FAILED" }, { status: "UNVERIFIED" }]), true);
  assert.equal(product.canReleaseGenerationLock([]), true);
  assert.equal(product.canReleaseGenerationLock([{ status: "FAILED" }, { status: "RUNNING" }]), false);
  assert.equal(product.canReleaseGenerationLock([{ status: "QUEUED" }]), false);
  assert.equal(product.canReleaseGenerationLock(null), false);
  const values = new Map([["lock-a", "key"], ["lock-b", "other"]]);
  const storage = { getItem: (k) => values.get(k), removeItem: (k) => values.delete(k) };
  assert.equal(product.releaseGenerationLock(storage, "lock-a"), true);
  assert.equal(values.has("lock-a"), false); assert.equal(values.get("lock-b"), "other");
  assert.equal(product.releaseGenerationLock(storage, "lock-a"), false);
});
test("Release lock is shown to authors, disabled while a run is in progress, hidden from Manager", () => {
  const { Plans } = load(path.join(root, "components/product/plans.tsx"));
  const employee = { id: "emp-1", employee_code: "EMP-1", training_status: "NOT_STARTED", experience_level: "BEGINNER", joining_date: "2026-10-01", profiles: { display_name: "Test employee" } };
  const run = (status) => ({ id: `run-${status}`, employee_id: "emp-1", status, created_at: "2026-09-28T00:00:00Z", provider: "nararouter" });
  const render = (role, statuses) => withResource({ run: null, person: null, validation: null, employees: [employee], page: { items: statuses.map(run), offset: 0, limit: 30, has_more: false } },
    () => renderToStaticMarkup(React.createElement(Plans, { me: me(role), employeeFilter: "emp-1" })));
  const failedOnly = render("TRAINING_MANAGER", ["FAILED", "FAILED"]);
  assert.match(failedOnly, /<button(?![^>]*disabled="")[^>]*>Release lock/);
  assert.match(failedOnly, /shows no generation in progress/);
  const running = render("ADMIN", ["FAILED", "RUNNING"]);
  assert.match(running, /disabled=""[^>]*>Release lock/);
  assert.match(running, /queued or running/);
  assert.doesNotMatch(render("MANAGER", ["FAILED"]), /Release lock/);
});
