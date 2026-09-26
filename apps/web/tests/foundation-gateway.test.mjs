import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.resolve(here, "../src/app/api/document-gateway/[...path]/route.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadGateway({ authenticated = true, upstreamStatus = 201, upstreamBody = { id: "created-id", status: "ACTIVE" } } = {}) {
  const calls = [];
  const exports = {};
  class NextResponse extends Response {
    static json(value, init) {
      return new NextResponse(JSON.stringify(value), {
        status: init?.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }
  }
  const modules = {
    "next/server": { NextResponse },
    "@/lib/supabase/server": { createClient: async () => ({ auth: {
      getSession: async () => ({ data: { session: authenticated ? { access_token: "synthetic-test-session" } : null } }),
    } }) },
    "@/lib/env": { apiBaseUrl: () => "http://api.test" },
  };
  vm.runInNewContext(compiled, {
    exports,
    require(name) {
      assert.ok(name in modules, `Unexpected dependency: ${name}`);
      return modules[name];
    },
    fetch: async (url, init) => {
      calls.push({ url, init, body: init.body ? await new Response(init.body).text() : "" });
      return new Response(JSON.stringify(upstreamBody), {
        status: upstreamStatus, headers: { "Content-Type": "application/json" },
      });
    },
    Request, Response, TransformStream, URL, process,
  }, { filename: "document-gateway/route.ts" });
  return { gateway: exports, calls };
}

function request(path, { body = {}, contentType = "application/json", origin = "http://localhost:3000", headers = {} } = {}) {
  const url = `http://localhost:3000/api/document-gateway/${path}`;
  const req = new Request(url, {
    method: "POST", headers: { Origin: origin, "Content-Type": contentType, ...headers }, body: JSON.stringify(body),
  });
  Object.defineProperty(req, "nextUrl", { value: new URL(url) });
  return req;
}

async function post(gateway, path, options) {
  return gateway.POST(request(path, options), { params: Promise.resolve({ path: path.split("/") }) });
}

async function get(gateway, path) {
  const url = `http://localhost:3000/api/document-gateway/${path}`;
  const req = new Request(url);
  Object.defineProperty(req, "nextUrl", { value: new URL(url) });
  return gateway.GET(req, { params: Promise.resolve({ path: path.split("/") }) });
}

test("authenticated Department POST forwards the exact JSON to FastAPI with server-side session", async () => {
  const { gateway, calls } = loadGateway();
  const payload = { code: "ENG", name: "Engineering" };
  const response = await post(gateway, "departments", { body: payload });
  assert.equal(response.status, 201);
  assert.deepEqual(JSON.parse(calls[0].body), payload);
  assert.equal(calls[0].url, "http://api.test/api/v1/departments");
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.doesNotMatch(await response.text(), /synthetic-test-session/);
});

test("authenticated Job Role POST forwards the returned department relationship", async () => {
  const { gateway, calls } = loadGateway();
  const payload = { code: "JUNIOR_SOFTWARE_DEVELOPER", name: "Junior Software Developer", department_id: "created-id" };
  const response = await post(gateway, "roles", { body: payload });
  assert.equal(response.status, 201);
  assert.equal(calls[0].url, "http://api.test/api/v1/roles");
  assert.deepEqual(JSON.parse(calls[0].body), payload);
});

test("foundation POSTs require a session, same origin, and JSON", async () => {
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await post(anonymous.gateway, "departments")).status, 401);
  assert.equal(anonymous.calls.length, 0);
  const authenticated = loadGateway();
  assert.equal((await post(authenticated.gateway, "roles", { origin: "https://other.test" })).status, 403);
  assert.equal((await post(authenticated.gateway, "roles", { contentType: "text/plain" })).status, 415);
  assert.equal(authenticated.calls.length, 0);
});

test("unrelated POST paths remain blocked before session lookup or forwarding", async () => {
  const { gateway, calls } = loadGateway();
  for (const path of ["employees/extra", "departments/extra", "roles/extra", "admin/check", "roles/not-a-uuid/matrices"]) {
    const response = await post(gateway, path);
    assert.equal(response.status, 404, path);
  }
  assert.equal(calls.length, 0);
});

test("authenticated Employee GET forwards session and preserves read response", async () => {
  const rows = [{ id: "employee-id", employee_code: "P4D_FIXTURE" }];
  const { gateway, calls } = loadGateway({ upstreamStatus: 200, upstreamBody: rows });
  const response = await get(gateway, "employees");
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), rows);
  assert.equal(calls[0].url, "http://api.test/api/v1/employees");
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.equal(calls[0].body, "");
});

test("authenticated Employee POST forwards the exact creation body", async () => {
  const { gateway, calls } = loadGateway();
  const payload = {
    employee_code: "P4D_FIXTURE", role_id: "role-id", department_id: "department-id",
    experience_level: "BEGINNER", joining_date: "2026-09-26",
  };
  const response = await post(gateway, "employees", { body: payload });
  assert.equal(response.status, 201);
  assert.deepEqual(JSON.parse(calls[0].body), payload);
  assert.equal(calls[0].url, "http://api.test/api/v1/employees");
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.doesNotMatch(await response.text(), /synthetic-test-session/);
});

test("Employee gateway rejects anonymous and cross-origin requests", async () => {
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await get(anonymous.gateway, "employees")).status, 401);
  assert.equal((await post(anonymous.gateway, "employees")).status, 401);
  assert.equal(anonymous.calls.length, 0);
  const authenticated = loadGateway();
  assert.equal((await post(authenticated.gateway, "employees", { origin: "https://other.test" })).status, 403);
  assert.equal((await post(authenticated.gateway, "employees", { contentType: "text/plain" })).status, 415);
  assert.equal(authenticated.calls.length, 0);
});

test("Employee gateway preserves upstream RBAC denial and safe validation errors", async () => {
  const forbidden = loadGateway({ upstreamStatus: 403, upstreamBody: { code: "FORBIDDEN_ROLE" } });
  const denied = await post(forbidden.gateway, "employees");
  assert.equal(denied.status, 403);
  assert.deepEqual(await denied.json(), { code: "FORBIDDEN_ROLE" });
  const invalid = loadGateway({ upstreamStatus: 422, upstreamBody: { code: "INVALID_REQUEST" } });
  const rejected = await post(invalid.gateway, "employees");
  assert.equal(rejected.status, 422);
  assert.deepEqual(await rejected.json(), { code: "INVALID_REQUEST" });
});

test("Employee gateway does not expose additional methods or nested paths", async () => {
  const { gateway, calls } = loadGateway();
  const url = "http://localhost:3000/api/document-gateway/employees";
  const req = new Request(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: "{}" });
  Object.defineProperty(req, "nextUrl", { value: new URL(url) });
  const patch = await gateway.PATCH(req, { params: Promise.resolve({ path: ["employees"] }) });
  assert.equal(patch.status, 404);
  assert.equal((await get(gateway, "employees/extra")).status, 404);
  assert.equal(calls.length, 0);
});

test("generation preflight GET forwards only the intended UUID route with session", async () => {
  const employeeId = "aa02c897-14d8-4c3c-994a-c707550677ad";
  const result = { readiness: "READY", employee_id: employeeId, blocker_codes: [], requirement_count: 6 };
  const { gateway, calls } = loadGateway({ upstreamStatus: 200, upstreamBody: result });
  const response = await get(gateway, `generation-runs/preflight/${employeeId}`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), result);
  assert.equal(calls[0].url, `http://api.test/api/v1/generation-runs/preflight/${employeeId}`);
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.equal((await get(gateway, "generation-runs/preflight/not-a-uuid")).status, 404);
  assert.equal((await post(gateway, `generation-runs/preflight/${employeeId}`)).status, 404);
  assert.equal(calls.length, 1);
});

test("generation preflight gateway preserves anonymous rejection and upstream RBAC denial", async () => {
  const path = "generation-runs/preflight/aa02c897-14d8-4c3c-994a-c707550677ad";
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await get(anonymous.gateway, path)).status, 401);
  assert.equal(anonymous.calls.length, 0);
  const denied = loadGateway({ upstreamStatus: 403, upstreamBody: { detail: "FORBIDDEN_ROLE" } });
  const response = await get(denied.gateway, path);
  assert.equal(response.status, 403);
  assert.deepEqual(await response.json(), { detail: "FORBIDDEN_ROLE" });
});

test("generation detail GET is narrowly forwarded with session and preserves RBAC denial", async () => {
  const runId = "538c24a9-744c-4db5-992e-762edb7652f9";
  const { gateway, calls } = loadGateway({ upstreamStatus: 200, upstreamBody: { id: runId, status: "FAILED" } });
  const response = await get(gateway, `generation-runs/${runId}`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { id: runId, status: "FAILED" });
  assert.equal(calls[0].url, `http://api.test/api/v1/generation-runs/${runId}`);
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.equal((await get(gateway, "generation-runs/not-a-uuid")).status, 404);
  assert.equal((await post(gateway, `generation-runs/${runId}`)).status, 404);
  assert.equal(calls.length, 1);
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await get(anonymous.gateway, `generation-runs/${runId}`)).status, 401);
  const forbidden = loadGateway({ upstreamStatus: 403, upstreamBody: { detail: "FORBIDDEN_ROLE" } });
  assert.equal((await get(forbidden.gateway, `generation-runs/${runId}`)).status, 403);
});

test("generation create forwards exactly one POST with body and Idempotency-Key under the server session", async () => {
  const { gateway, calls } = loadGateway({ upstreamStatus: 202, upstreamBody: { id: "run-id", status: "UNVERIFIED" } });
  const payload = { employee_id: "aa02c897-14d8-4c3c-994a-c707550677ad" };
  const response = await post(gateway, "generation-runs", {
    body: payload, headers: { "Idempotency-Key": "phase4d-smoke-test-unique-key" },
  });
  assert.equal(response.status, 202);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://api.test/api/v1/generation-runs");
  assert.deepEqual(JSON.parse(calls[0].body), payload);
  assert.equal(calls[0].init.headers["Idempotency-Key"], "phase4d-smoke-test-unique-key");
  assert.equal(calls[0].init.headers.Authorization, "Bearer synthetic-test-session");
  assert.deepEqual(await response.json(), { id: "run-id", status: "UNVERIFIED" });
});

test("generation create remains session/origin gated and does not expose other generation writes", async () => {
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await post(anonymous.gateway, "generation-runs")).status, 401);
  assert.equal(anonymous.calls.length, 0);
  const { gateway, calls } = loadGateway();
  assert.equal((await post(gateway, "generation-runs", { origin: "https://other.test" })).status, 403);
  assert.equal((await post(gateway, "generation-runs/extra")).status, 404);
  assert.equal((await post(gateway, "generation-runs/preflight/aa02c897-14d8-4c3c-994a-c707550677ad")).status, 404);
  assert.equal(calls.length, 0);
});

test("existing document POST remains allowed with its original content type", async () => {
  const { gateway, calls } = loadGateway();
  const response = await post(gateway, "documents/uploads", { contentType: "multipart/form-data; boundary=test" });
  assert.equal(response.status, 201);
  assert.equal(calls[0].url, "http://api.test/api/v1/documents/uploads");
  assert.equal(calls[0].init.headers["Content-Type"], "multipart/form-data; boundary=test");
});

test("product read routes remain exact and preserve caller auth", async () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const { gateway, calls } = loadGateway({ upstreamStatus: 200, upstreamBody: [] });
  for (const path of ["departments", "roles", "generation-runs", "validation-runs", "audit-events", `employees/${id}`, `validation-runs/${id}`, `generated-plans/${id}/validation`]) {
    assert.equal((await get(gateway, path)).status, 200, path);
    assert.equal(calls.at(-1).init.headers.Authorization, "Bearer synthetic-test-session");
  }
  for (const path of ["profiles", "profile_roles", "audit_logs", "validation-runs/extra", `employees/${id}/delete`]) assert.equal((await get(gateway, path)).status, 404);
});

test("validation writes enforce origin session JSON and forward exact human request", async () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const path = `validation-runs/${id}/review`, body = { action: "OVERRIDE", reason: "Independent reviewed exception" };
  const { gateway, calls } = loadGateway({ upstreamStatus: 409, upstreamBody: { code: "VALIDATION_STATE_CONFLICT" } });
  assert.equal((await post(gateway, path, { body })).status, 409);
  assert.deepEqual(JSON.parse(calls[0].body), body);
  assert.equal((await post(gateway, path, { origin: "https://other.test" })).status, 403);
  assert.equal((await post(gateway, path, { contentType: "text/plain" })).status, 415);
  assert.equal((await post(gateway, "validation-runs", { body })).status, 404);
  assert.equal((await post(gateway, `generated-plans/${id}/validate`)).status, 409);
  const anonymous = loadGateway({ authenticated: false });
  assert.equal((await post(anonymous.gateway, path, { body })).status, 401);
  assert.equal(anonymous.calls.length, 0);
});
