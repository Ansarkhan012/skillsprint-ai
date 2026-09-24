import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as jsxRuntime from 'react/jsx-runtime';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const source = readFileSync(path.resolve(__dirname, '../src/app/login/page.tsx'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadPage({ mockedHooks = false, authResult = { error: null }, search = '' } = {}) {
  const state = [];
  const effects = [];
  const calls = { auth: [], navigation: [], refresh: 0, logs: [] };
  let hookIndex = 0;
  const useState = (initial) => {
    const index = hookIndex++;
    if (!(index in state)) state[index] = initial;
    return [state[index], (value) => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
  };
  const react = mockedHooks ? { useState, useEffect: (effect) => effects.push(effect) } : React;
  const jsx = (type, props) => ({ type, props: props || {} });
  const Input = (props) => React.createElement('input', props);
  const Button = (props) => React.createElement('button', props);
  const icon = (props) => React.createElement('span', { 'aria-hidden': true, ...props });
  const modules = {
    react,
    'react/jsx-runtime': mockedHooks ? { jsx, jsxs: jsx } : jsxRuntime,
    'next/navigation': { useRouter: () => ({ replace: (value) => calls.navigation.push(value), refresh: () => calls.refresh++ }) },
    'lucide-react': { BookOpenCheck: icon, Eye: icon, EyeOff: icon, LockKeyhole: icon, ShieldCheck: icon },
    '@/components/ui/button': { Button },
    '@/components/ui/input': { Input },
    '@/lib/supabase/browser': { createClient: () => ({ auth: { signInWithPassword: async (value) => {
      calls.auth.push(value);
      return authResult;
    } } }) },
  };
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    require: (name) => {
      assert.ok(name in modules, `Unexpected dependency: ${name}`);
      return modules[name];
    },
    window: { location: { search } },
    requestAnimationFrame: (fn) => { fn(); return 1; },
    cancelAnimationFrame: () => {},
    console: { log: (...args) => calls.logs.push(args), error: (...args) => calls.logs.push(args) },
    URLSearchParams,
  }, { filename: 'login/page.tsx' });
  const Page = exports.default;
  return { Page, calls, effects, render: () => { hookIndex = 0; return Page(); } };
}

function find(node, predicate) {
  if (Array.isArray(node)) {
    for (const child of node) { const result = find(child, predicate); if (result) return result; }
    return undefined;
  }
  if (node == null || typeof node !== 'object') return undefined;
  if (predicate(node)) return node;
  return find(node.props?.children, predicate);
}

test('server markup cannot natively GET submit credentials', () => {
  const { Page } = loadPage();
  const html = renderToStaticMarkup(React.createElement(Page));
  const form = html.match(/<form\b[^>]*>/)?.[0];
  const email = html.match(/<input\b[^>]*id="email"[^>]*>/)?.[0];
  const password = html.match(/<input\b[^>]*id="password"[^>]*>/)?.[0];
  const submit = html.match(/<button\b[^>]*type="submit"[^>]*>/)?.[0];
  assert.ok(form && email && password && submit);
  assert.match(form, /\bmethod="post"/);
  assert.match(form, /\baction="\/login"/);
  assert.doesNotMatch(form, /\bmethod="get"/i);
  assert.doesNotMatch(email, /\bname=/i);
  assert.doesNotMatch(password, /\bname=/i);
  assert.match(password, /\btype="password"/);
  assert.match(submit, /\bdisabled(?:=|\s|>)/);
  // Native form serialization includes only named controls, even if a password is typed.
  const namedCredentials = [email, password].filter((tag) => /\bname=/.test(tag));
  assert.equal(namedCredentials.length, 0);
  assert.equal(new URL('/login', 'http://localhost:3000').searchParams.has('password'), false);
});

test('hydrated form retains the existing Supabase login and navigation behavior', async () => {
  const app = loadPage({ mockedHooks: true, search: '?next=/app/documents' });
  let tree = app.render();
  const initialSubmit = find(tree, (node) => node.type?.name === 'Button' && node.props.type === 'submit');
  // Button is a module mock; locating by prop also covers transpiled component names.
  assert.equal((initialSubmit || find(tree, (node) => node.props?.type === 'submit')).props.disabled, true);
  for (const effect of app.effects) effect();
  tree = app.render();
  assert.equal(find(tree, (node) => node.props?.type === 'submit').props.disabled, false);
  find(tree, (node) => node.props?.id === 'email').props.onChange({ target: { value: '  admin@example.test  ' } });
  find(tree, (node) => node.props?.id === 'password').props.onChange({ target: { value: 'synthetic-test-value' } });
  tree = app.render();
  let prevented = false;
  await find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.deepEqual(JSON.parse(JSON.stringify(app.calls.auth)), [{ email: 'admin@example.test', password: 'synthetic-test-value' }]);
  assert.deepEqual(app.calls.navigation, ['/app/documents']);
  assert.equal(app.calls.refresh, 1);
  assert.equal(app.calls.logs.length, 0);
});

test('failed authentication preserves generic error and never logs the password', async () => {
  const app = loadPage({ mockedHooks: true, authResult: { error: new Error('synthetic provider detail') } });
  let tree = app.render();
  find(tree, (node) => node.props?.id === 'email').props.onChange({ target: { value: 'test@example.test' } });
  find(tree, (node) => node.props?.id === 'password').props.onChange({ target: { value: 'synthetic-test-value' } });
  tree = app.render();
  await find(tree, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} });
  tree = app.render();
  assert.equal(find(tree, (node) => node.props?.role === 'alert').props.children, 'The email or password was not accepted.');
  assert.deepEqual(app.calls.navigation, []);
  assert.equal(app.calls.logs.length, 0);
  assert.doesNotMatch(source, /console\.(?:log|info|warn|error|debug)\s*\(/);
});

test('backend application request logger logs path only, never query or credentials', () => {
  const backend = readFileSync(path.resolve(__dirname, '../../../services/api/app/main.py'), 'utf8');
  const logger = backend.match(/async def request_log\([\s\S]*?return response/)?.[0];
  assert.ok(logger);
  assert.match(logger, /request\.url\.path/);
  assert.doesNotMatch(logger, /request\.url\.(?:query|params)|str\(request\.url\)|request\.body\(/);
});
