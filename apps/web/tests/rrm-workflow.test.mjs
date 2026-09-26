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

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (relative) => readFileSync(path.resolve(here, relative), 'utf8');
const lib = read('../src/lib/rrm.ts');
const workspace = read('../src/components/requirements/requirements-workspace.tsx');
const gateway = read('../src/app/api/document-gateway/[...path]/route.ts');
const page = read('../src/app/app/requirements/page.tsx');
const requirementsError = read('../src/app/app/requirements/error.tsx');
const apiSource = read('../src/lib/api.ts');
const protectedLayout = read('../src/app/app/layout.tsx');
const productHelpers = {};
vm.runInNewContext(ts.transpileModule(read('../src/lib/product.ts'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: productHelpers });

function loadWorkspace(stateOverrides = {}) {
  const compiled = ts.transpileModule(workspace, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const simple = (tag) => function SimpleComponent({ children, ...props }) {
    return React.createElement(tag, props, children);
  };
  const icon = () => React.createElement('span', { 'aria-hidden': true });
  let stateIndex = 0;
  const modules = {
    react: { ...React, useState(initial) { stateIndex += 1; return React.useState(stateIndex in stateOverrides ? stateOverrides[stateIndex] : initial); } },
    'react/jsx-runtime': jsxRuntime,
    'lucide-react': { ClipboardList: icon, FileCheck2: icon, Plus: icon, Search: icon },
    '@/components/ui/badge': { Badge: simple('span') },
    '@/components/ui/button': { Button: simple('button') },
    '@/components/ui/input': { Input: simple('input') },
    '@/components/shared/page-header': { PageHeader: ({ title }) => React.createElement('h1', null, title) },
    '@/lib/rrm': { jsonRequest() {}, locator: () => 'Source', rrmMessage: () => 'Error', rrmRequest() {} },
    '@/lib/product': productHelpers,
  };
  vm.runInNewContext(compiled, {
    exports, require: (name) => {
      assert.ok(name in modules, `Unexpected dependency: ${name}`);
      return modules[name];
    },
  });
  return function TestWorkspace(props) { stateIndex = 0; return React.createElement(exports.RequirementsWorkspace, props); };
}

function loadLibrary(fetch) {
  const compiled = ts.transpileModule(lib, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, fetch }, { filename: 'rrm.ts' });
  return exports;
}

test('RRM requests use only the authenticated gateway and surface safe errors', async () => {
  const calls = [];
  const api = loadLibrary(async (url, init) => {
    calls.push({ url, init });
    return { ok: false, json: async () => ({ code: 'RRM_STALE_SNAPSHOT' }) };
  });
  await assert.rejects(api.jsonRequest('matrices/test/approve', 'POST', { expected_version: 2 }), /RRM_STALE_SNAPSHOT/);
  assert.equal(calls[0].url, '/api/document-gateway/matrices/test/approve');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.cache, 'no-store');
  assert.equal(JSON.parse(calls[0].init.body).expected_version, 2);
  assert.match(api.rrmMessage(new Error('RRM_STALE_SNAPSHOT')), /no longer current or usable/i);
});

test('source labels cover PDF and Word traceability', () => {
  const api = loadLibrary(async () => ({ ok: true, json: async () => ({}) }));
  assert.match(api.locator({ kind: 'pdf', page: 2, block: 3 }), /PDF · Page 2 \/ block 3/);
  assert.match(api.locator({ kind: 'docx', table: 1, row: 2, cell: 3 }), /Word · table 1 \/ row 2 \/ cell 3/);
});

test('requirements server route denies Manager and Employee before rendering workflow', () => {
  assert.match(page, /\["ADMIN", "TRAINING_MANAGER", "REVIEWER"\]/);
  assert.match(page, /redirect\("\/access-denied"\)/);
  assert.match(page, /requestMe\(session\.access_token\)/);
});

test('Requirements page shows a retry state for a server data failure without exposing details', () => {
  const compiled = ts.transpileModule(requirementsError, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require(name) {
    if (name === 'react/jsx-runtime') return jsxRuntime;
    if (name === 'lucide-react') return { AlertCircle: () => null };
    if (name === '@/components/ui/button') return { Button: ({ children, ...props }) => React.createElement('button', props, children) };
    throw new Error(`Unexpected dependency: ${name}`);
  } });
  const html = renderToStaticMarkup(React.createElement(exports.default, {
    error: new Error('private upstream detail'), reset() {},
  }));
  assert.match(html, /Requirements are temporarily unavailable/);
  assert.match(html, /Try again/);
  assert.doesNotMatch(html, /private upstream detail/);
});

test('server identity lookup is deduplicated only within a render', () => {
  assert.match(apiSource, /requestMe = cache\(\(token: string\) => api\.me\(token\)\)/);
  assert.match(protectedLayout, /requestMe\(session\.access_token\)/);
  assert.match(page, /requestMe\(session\.access_token\)/);
  assert.match(apiSource, /cache: "no-store"/);
});

test('workspace gates author/reviewer actions and freezes non-draft editing', () => {
  assert.match(workspace, /canAuthor = me\.roles\.includes\("ADMIN"\) \|\| me\.roles\.includes\("TRAINING_MANAGER"\)/);
  assert.match(workspace, /canReview = me\.roles\.includes\("ADMIN"\) \|\| me\.roles\.includes\("REVIEWER"\)/);
  assert.match(workspace, /matrix\.status === "DRAFT" && matrix\.created_by === me\.id/);
  assert.match(workspace, /matrix\.status === "SUBMITTED" && canReview/);
  assert.match(workspace, /selectedChunks/);
  assert.match(workspace, /window\.confirm\(/);
  assert.match(workspace, /decisionReason/);
  assert.match(workspace, /groundError/);
});

test('rendered workspace exposes author controls only to Admin and Training Manager', () => {
  const Workspace = loadWorkspace();
  const props = { roles: [{ id: 'role-1', code: 'ENGINEER', name: 'Engineer' }], departments: [] };
  const render = (role) => renderToStaticMarkup(React.createElement(Workspace, {
    ...props, me: { id: 'person-1', display_name: 'Test', roles: [role] },
  }));
  assert.match(render('ADMIN'), /New matrix draft/);
  assert.match(render('ADMIN'), /Configure source authority/);
  assert.match(render('TRAINING_MANAGER'), /New matrix draft/);
  assert.doesNotMatch(render('TRAINING_MANAGER'), /Configure source authority/);
  assert.doesNotMatch(render('REVIEWER'), /New matrix draft/);
  assert.doesNotMatch(render('REVIEWER'), /Configure source authority/);
});

test('gateway allowlists RRM paths and PATCH, checks origin, and caps JSON writes', () => {
  assert.match(gateway, /const rrmPatch = new RegExp/);
  assert.match(gateway, /export async function PATCH/);
  assert.match(gateway, /origin !== request\.nextUrl\.origin/);
  assert.match(gateway, /rrmRequestLimit = 512 \* 1024/);
  assert.doesNotMatch(gateway, /\*\*|\.\*\$.*api\/v1/);
});

test('Requirements loads inactive datasets only when their workflow opens', () => {
  assert.match(workspace, /if \(pane !== "matrix" \|\| !roleId\) return/);
  assert.match(workspace, /if \(pane !== "candidates" \|\| loaded\.current\.candidates\) return/);
  assert.match(workspace, /if \(!\(showCandidate \|\| showConfig\) \|\| loaded\.current\.sources\) return/);
  assert.match(workspace, /loaded = useRef\(\{ candidates: false, configs: false, sources: false, matrixRole: "" \}\)/);
  assert.doesNotMatch(workspace, /Promise\.all\(\[\s*rrmRequest<Page<Requirement>>\("requirements\?limit=50"\)/);
});

const candidate = (overrides = {}) => ({
  id: 'r1', requirement_code: 'SECURITY_TRAINING', revision: 1, predecessor_id: null,
  statement: 'Security Awareness Training', category: 'POLICY', mandatory: true,
  requirement_type: 'MUST_COMPLETE', timing: { state: 'AMBIGUOUS', original_text: 'Within 7 days' },
  scopes: [{ role_id: null, department_id: null, location_code: null, experience: null }],
  competency: null, assessment_required: false, priority: 'MEDIUM', ...overrides,
});
const fields = (overrides = {}) => ({ code: 'SECURITY_TRAINING', statement: 'Security Awareness Training',
  category: 'POLICY', mandatory: true, mustType: 'MUST_COMPLETE', roleId: '', departmentId: '',
  timingText: 'Within 7 days', ...overrides });

test('revision form is author-only, locks code, requires fresh evidence, and keeps old revision', () => {
  assert.match(workspace, /canAuthor && <Button[^\n]*onClick=\{\(\) => void openRevision\(candidate\)\}>Revise candidate<\/Button>/);
  assert.match(workspace, /readOnly=\{Boolean\(revisionOf\)\}/);
  assert.match(workspace, /setSelectedChunks\(\[\]\).*setSourceId\(""\)/);
  assert.match(workspace, /The old candidate and its evidence remain in history/);
  assert.doesNotMatch(workspace, /jsonRequest\(`requirements\/\$\{.*\}`, "PATCH"/);
  const api = loadLibrary();
  const old = candidate({ scopes: [{ role_id: null, department_id: null, location_code: null, experience: null, ordinal: 1 }] });
  const payload = api.buildCandidatePayload(fields(), ['chunk-1', 'chunk-2', 'chunk-3'], old);
  assert.equal(payload.predecessor_id, old.id);
  assert.equal(payload.code, old.requirement_code);
  assert.equal(payload.scopes[0].ordinal, undefined);
  assert.deepEqual([...payload.chunk_ids], ['chunk-1', 'chunk-2', 'chunk-3']);
  assert.equal(old.revision, 1);
  assert.equal(old.predecessor_id, null);
  assert.throws(() => api.buildCandidatePayload(fields({ code: 'CHANGED_CODE' }), ['chunk-1'], old), /REVISION_REQUIRES_EXPLICIT_REVIEW/);
  assert.throws(() => api.buildCandidatePayload(fields(), [], old), /SELECT_EXACT_SOURCE_CHUNKS/);
  assert.throws(() => api.buildCandidatePayload(fields({ timingText: '' }), ['chunk-1'], old), /PRESERVE_AMBIGUOUS_TIMING/);
});

test('Revise candidate action renders for authors but not Reviewer, Manager, or Employee', () => {
  const Workspace = loadWorkspace({ 1: 'candidates', 3: { items: [candidate()], offset: 0, limit: 50, has_more: false } });
  const render = (role) => renderToStaticMarkup(React.createElement(Workspace, {
    me: { id: 'person-1', roles: [role] }, roles: [{ id: 'job-1', code: 'JOB', name: 'Job' }], departments: [],
  }));
  for (const role of ['ADMIN', 'TRAINING_MANAGER']) assert.match(render(role), /Revise candidate/);
  for (const role of ['REVIEWER', 'MANAGER', 'EMPLOYEE']) assert.doesNotMatch(render(role), /Revise candidate/);
});

test('human-readable Policy category maps to canonical POLICY and create still works', () => {
  const api = loadLibrary();
  assert.equal(api.requirementCategories.find((item) => item.label === 'Policy').value, 'POLICY');
  assert.match(workspace, /<select name="category"/);
  const payload = api.buildCandidatePayload(fields(), ['chunk-1'], null);
  assert.equal(payload.category, 'POLICY');
  assert.equal(payload.predecessor_id, undefined);
  assert.equal(payload.timing.state, 'AMBIGUOUS');
  assert.equal(payload.timing.original_text, 'Within 7 days');
  assert.equal(payload.timing.trigger, undefined);
});

test('draft replacement is one version-checked PATCH preserving unrelated entries and dependencies', () => {
  const api = loadLibrary();
  const old = candidate();
  const next = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const other = { requirement_id: 'other', sequence: 1, stage_id: 'stage-2' };
  const draft = { id: 'matrix-1', status: 'DRAFT', created_by: 'author-1', lock_version: 7,
    entries: [{ requirement_id: 'r1', sequence: 0, stage_id: 'stage-1' }, other],
    dependencies: [{ dependent_id: 'other', prerequisite_id: 'third' }] };
  const edit = api.buildDraftRevisionReplacement(draft, 'author-1', old, next);
  assert.equal(edit.expected_version, 7);
  assert.deepEqual(edit.entries.map((entry) => entry.requirement_id), ['r2', 'other']);
  assert.deepEqual({ ...edit.entries[1] }, other);
  assert.deepEqual(edit.dependencies.map((edge) => ({ ...edge })), draft.dependencies);
  assert.deepEqual(draft.entries.map((entry) => entry.requirement_id), ['r1', 'other']);
  assert.match(workspace, /jsonRequest\(`matrices\/\$\{freshMatrix\.id\}`, "PATCH", payload\)/);
  assert.match(workspace, /const freshMatrix = await rrmRequest<Matrix>/);
});

test('submitted, approved, non-owned, and relationship-dependent drafts fail closed', () => {
  const api = loadLibrary();
  const old = candidate();
  const next = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const draft = { status: 'DRAFT', created_by: 'author-1', lock_version: 1,
    entries: [{ requirement_id: 'r1', sequence: 0 }], dependencies: [] };
  for (const status of ['SUBMITTED', 'APPROVED']) {
    assert.throws(() => api.buildDraftRevisionReplacement({ ...draft, status }, 'author-1', old, next), /DRAFT_OWNER_REQUIRED/);
  }
  assert.throws(() => api.buildDraftRevisionReplacement(draft, 'someone-else', old, next), /DRAFT_OWNER_REQUIRED/);
  assert.throws(() => api.buildDraftRevisionReplacement({ ...draft, dependencies: [{ dependent_id: 'r1', prerequisite_id: 'other' }] }, 'author-1', old, next), /REVISION_RELATIONSHIP_REVIEW_REQUIRED/);
  assert.throws(() => api.buildDraftRevisionReplacement({ ...draft, entries: [{ requirement_id: 'r1', sequence: 0, exception_to: 'other' }] }, 'author-1', old, next), /REVISION_RELATIONSHIP_REVIEW_REQUIRED/);
  assert.throws(() => api.buildDraftRevisionReplacement({ ...draft, issues: [{ requirement_id: 'r1' }] }, 'author-1', old, next), /REVISION_RELATIONSHIP_REVIEW_REQUIRED/);
  assert.throws(() => api.buildDraftRevisionReplacement(draft, 'author-1', old, candidate({ id: 'wrong', revision: 2, predecessor_id: 'other' })), /INVALID_CANDIDATE_REVISION/);
});

test('ambiguous readiness disables submit and offers author-only manual review', () => {
  assert.match(workspace, /Ready for submission: \{matrix\.readiness\.blocking_codes\.length \? "No" : "Yes"\}/);
  assert.match(workspace, /matrix\.readiness\.blocking_codes\.length > 0\} onClick=\{\(\) => void transition\("submit"\)/);
  assert.match(workspace, /Create review issue/);
  assert.match(workspace, /canRaiseDraftIssue && <div className="mt-2 space-y-2"/);
  assert.match(workspace, /kind: "AMBIGUITY", requirement_id: req\.id/);
  assert.match(workspace, /fresh\.issues\.some\(\(issue\) => issue\.kind === "AMBIGUITY"/);
  assert.match(workspace, /Issue resolution does not resolve ambiguous timing/);
  const req = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const matrix = { id: 'matrix-1', role_id: 'job-1', revision: 1, status: 'DRAFT', current_edit: 13,
    lock_version: 13, created_by: 'author-1', submitted_by: null, decided_by: null, snapshot_hash: null,
    entries: [{ requirement_id: 'r2', sequence: 0 }], dependencies: [], issues: [],
    requirements: { r2: req }, readiness: { blocking_codes: ['RRM_TIMING_MANUAL_REVIEW'] } };
  const Workspace = loadWorkspace({ 8: matrix });
  const html = renderToStaticMarkup(React.createElement(Workspace, {
    me: { id: 'author-1', roles: ['TRAINING_MANAGER'] },
    roles: [{ id: 'job-1', code: 'JOB', name: 'Job' }], departments: [],
  }));
  assert.match(html, /Ready for submission: No/);
  assert.match(html, /Ambiguous timing — SECURITY_TRAINING r2/);
  assert.match(html, /Submit for independent review<\/button>/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Submit for independent review<\/button>/);
});

test('Training Manager who did not create the draft can reach its ambiguity issue action', () => {
  const req = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const matrix = { id: 'matrix-1', role_id: 'job-1', revision: 1, status: 'DRAFT', current_edit: 1,
    lock_version: 1, created_by: 'different-author', submitted_by: null, decided_by: null, snapshot_hash: null,
    entries: [{ requirement_id: 'r2', sequence: 0 }], dependencies: [], issues: [],
    requirements: { r2: req }, readiness: { blocking_codes: ['RRM_TIMING_MANUAL_REVIEW'] } };
  const render = (role, draft = matrix) => renderToStaticMarkup(React.createElement(loadWorkspace({ 8: draft }), {
    me: { id: 'test-manager', roles: [role] },
    roles: [{ id: 'job-1', code: 'JOB', name: 'Junior Software Developer' }], departments: [],
  }));
  const html = render('TRAINING_MANAGER');
  assert.match(html, /Ambiguous timing — SECURITY_TRAINING r2/);
  assert.match(html, /Create review issue/);
  assert.doesNotMatch(html, /Draft entries/);
  assert.doesNotMatch(render('MANAGER'), /Create review issue/);
  assert.doesNotMatch(render('EMPLOYEE'), /Create review issue/);
  assert.doesNotMatch(render('REVIEWER'), /Create review issue/);
  assert.doesNotMatch(render('TRAINING_MANAGER', { ...matrix, status: 'SUBMITTED' }), /Create review issue/);
});

test('structured timing needs literal evidence for all fields and never infers a trigger', () => {
  const api = loadLibrary();
  const old = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const content = 'Within 7 days of employment, measured in calendar days';
  const chunks = [{ id: 'chunk-1', content }];
  const evidence = Object.fromEntries(api.timingFields.map((field) => [field, { chunk_id: 'chunk-1', quote: ({
    original_text: 'Within 7 days', trigger: 'employment', relation: 'Within', value: '7', unit: 'days', calendar_basis: 'calendar',
  })[field] }]));
  const timing = api.buildStructuredTiming('Within 7 days', { trigger: 'employment', relation: 'WITHIN', value: 7,
    unit: 'DAY', calendar_basis: 'CALENDAR', evidence }, chunks, ['chunk-1']);
  assert.equal(timing.evidence.trigger.quote, 'employment');
  assert.equal(timing.evidence.trigger.start, content.indexOf('employment'));
  const payload = api.buildCandidatePayload(fields(), ['chunk-1'], old, timing);
  assert.equal(payload.predecessor_id, 'r2');
  assert.equal(payload.timing.state, 'STRUCTURED');
  assert.equal(old.timing.state, 'AMBIGUOUS');
  assert.throws(() => api.buildStructuredTiming('Within 7 days', { trigger: 'hire date', relation: 'WITHIN', value: 7,
    unit: 'DAY', calendar_basis: 'CALENDAR', evidence: { ...evidence, trigger: { chunk_id: 'chunk-1', quote: 'hire date' } } },
  chunks, ['chunk-1']), /TIMING_EXACT_SPAN_REQUIRED/);
  assert.throws(() => api.buildCandidatePayload(fields({ timingText: 'Changed' }), ['chunk-1'], old, timing), /PRESERVE_AMBIGUOUS_TIMING/);
});

test('explicit issue review allows atomic replacement but keeps review issue for reviewer', () => {
  const api = loadLibrary();
  const old = candidate({ id: 'r2', revision: 2, predecessor_id: 'r1' });
  const next = candidate({ id: 'r3', revision: 3, predecessor_id: 'r2', timing: { state: 'STRUCTURED' } });
  const issue = { id: 'issue-1', kind: 'AMBIGUITY', requirement_id: 'r2', blocking: true };
  const draft = { status: 'DRAFT', created_by: 'author-1', lock_version: 13,
    entries: [{ requirement_id: 'r2', sequence: 0 }, { requirement_id: 'other', sequence: 1 }],
    dependencies: [], issues: [issue] };
  assert.throws(() => api.buildDraftRevisionReplacement(draft, 'author-1', old, next), /REVISION_RELATIONSHIP_REVIEW_REQUIRED/);
  const edit = api.buildDraftRevisionReplacement(draft, 'author-1', old, next, true);
  assert.equal(edit.expected_version, 13);
  assert.deepEqual(edit.entries.map((item) => item.requirement_id), ['r3', 'other']);
  assert.equal(draft.issues[0], issue);
});

test('structured timing spans use Python/SQL Unicode code points', () => {
  const api = loadLibrary();
  const content = '📋 Within 7 days of 🧑 employment, measured in calendar days';
  const quotes = { original_text: 'Within 7 days', trigger: '🧑 employment', relation: 'Within',
    value: '7', unit: 'days', calendar_basis: 'calendar' };
  const evidence = Object.fromEntries(api.timingFields.map((field) => [field,
    { chunk_id: 'unicode-chunk', quote: quotes[field] }]));
  const timing = api.buildStructuredTiming('Within 7 days', { trigger: '🧑 employment', relation: 'WITHIN',
    value: 7, unit: 'DAY', calendar_basis: 'CALENDAR', evidence },
  [{ id: 'unicode-chunk', content }], ['unicode-chunk']);
  for (const span of Object.values(timing.evidence)) {
    assert.equal(Array.from(content).slice(span.start, span.end).join(''), span.quote);
  }
  assert.equal(timing.evidence.original_text.start, 2);
});
