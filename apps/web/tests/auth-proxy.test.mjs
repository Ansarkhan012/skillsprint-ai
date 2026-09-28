import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../src/proxy.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
function load(user, error) {
  const exports = {};
  class NextResponse {
    constructor(body, init = {}) { this.status = init.status ?? 200; this.cookies = { set() {}, getAll: () => [] }; }
    static next() { return new NextResponse(); }
    static redirect(url) { const r = new NextResponse(null, { status: 307 }); r.location = String(url); return r; }
  }
  vm.runInNewContext(compiled, { exports, URL, process: { env: { NEXT_PUBLIC_SUPABASE_URL: "https://auth.test", NEXT_PUBLIC_SUPABASE_ANON_KEY: "dummy" } }, require(name) {
    if (name === "next/server") return { NextResponse };
    if (name === "@supabase/ssr") return { createServerClient: () => ({ auth: { getUser: async () => ({ data: { user }, error }) } }) };
    throw Error("Unexpected dependency");
  } });
  const url = new URL("http://localhost:3000/app/dashboard"); url.clone = () => new URL(url);
  return () => exports.proxy({ url: String(url), nextUrl: url, cookies: { getAll: () => [], set() {} } });
}
test("authenticated dashboard does not redirect", async () => {
  assert.equal((await load({ id: "test-user" }, null)()).status, 200);
});
test("genuine missing or invalid session redirects to login", async () => {
  for (const error of [null, { name: "AuthSessionMissingError" }, { status: 401 }]) {
    const response = await load(null, error)();
    assert.equal(response.status, 307); assert.match(response.location, /\/login/);
  }
});
test("auth outage returns service error rather than sign-in redirect", async () => {
  for (const error of [{ name: "AuthRetryableFetchError", status: 0 }, { status: 503 }]) {
    const response = await load(null, error)();
    assert.equal(response.status, 503); assert.equal(response.location, undefined);
  }
});
