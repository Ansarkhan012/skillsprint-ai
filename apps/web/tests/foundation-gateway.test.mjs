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

function loadGateway({ authenticated = true } = {}) {
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
      return new Response(JSON.stringify({ id: "created-id", status: "ACTIVE" }), {
        status: 201, headers: { "Content-Type": "application/json" },
      });
    },
    Request, Response, TransformStream, URL, process,
  }, { filename: "document-gateway/route.ts" });
  return { gateway: exports, calls };
}

function request(path, { body = {}, contentType = "application/json", origin = "http://localhost:3000" } = {}) {
  const url = `http://localhost:3000/api/document-gateway/${path}`;
  const req = new Request(url, {
    method: "POST", headers: { Origin: origin, "Content-Type": contentType }, body: JSON.stringify(body),
  });
  Object.defineProperty(req, "nextUrl", { value: new URL(url) });
  return req;
}

async function post(gateway, path, options) {
  return gateway.POST(request(path, options), { params: Promise.resolve({ path: path.split("/") }) });
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
  for (const path of ["employees", "departments/extra", "roles/extra", "admin/check", "roles/not-a-uuid/matrices"]) {
    const response = await post(gateway, path);
    assert.equal(response.status, 404, path);
  }
  assert.equal(calls.length, 0);
});

test("existing document POST remains allowed with its original content type", async () => {
  const { gateway, calls } = loadGateway();
  const response = await post(gateway, "documents/uploads", { contentType: "multipart/form-data; boundary=test" });
  assert.equal(response.status, 201);
  assert.equal(calls[0].url, "http://api.test/api/v1/documents/uploads");
  assert.equal(calls[0].init.headers["Content-Type"], "multipart/form-data; boundary=test");
});
