"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Me } from "@/lib/api";
import { canAuthor, canReadGeneration, generateOnce, generationMessage, humanize, postProduct, productRequest, type Employee, type Page, type PlanModule, type Run, type Validation, ProductError } from "@/lib/product";
import type { Preflight } from "@/lib/phase4d-test";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { DataTable, Empty, Fields, Loading, Modal, Pager, Problem, StateBadge, Technical, panel, selectStyle, useResource } from "./common";
import { Traceability } from "./traceability";

function ModuleContent({ module }: { module: PlanModule }) {
  const groups = ["learning_objectives", "key_concepts", "activities", "checklist_items", "tasks", "scenarios", "quizzes", "assessments", "completion_criteria"];
  const raw = module as unknown as Record<string, unknown>;
  return <>{groups.map((group) => {
    const items = raw[group];
    if (!Array.isArray(items) || !items.length) return null;
    return <details key={group} className="mt-3 rounded-md border border-border p-3 text-sm"><summary className="cursor-pointer font-semibold">{humanize(group)} ({items.length})</summary><div className="mt-3 space-y-4">{items.map((item: Record<string, unknown>, i) => <div key={i} className="space-y-2 border-t border-border pt-3">{["title", "statement", "purpose", "activity", "description", "question", "prompt", "instructions", "expected_outcome", "explanation", "pass_condition", "responsible_role", "evidence_type", "threshold"].map((field) => typeof item[field] === "string" ? <p key={field} className="whitespace-pre-wrap"><span className="font-medium">{humanize(field)}: </span>{item[field] as string}</p> : null)}{["completion_criteria", "expected_actions", "success_criteria"].map((field) => Array.isArray(item[field]) ? <ul key={field} className="list-disc pl-5">{(item[field] as string[]).map((text, n) => <li key={n}>{text}</li>)}</ul> : null)}{Array.isArray(item.options) && <ul className="list-disc pl-5">{item.options.map((o: { text: string }, n: number) => <li key={n}>{o.text}</li>)}</ul>}{Array.isArray(item.rubric) && <div>{item.rubric.map((r: { criterion: string; weight_percent: number; expected_performance: string; pass_condition: string }, n: number) => <p key={n} className="mt-2">{r.criterion} ({r.weight_percent}%) · {r.expected_performance} · Pass: {r.pass_condition}</p>)}</div>}{Array.isArray(item.requirement_ids) && <Traceability ids={item.requirement_ids as string[]} />}</div>)}</div></details>;
  })}</>;
}

function GenerationForm({ me, employeeId, refresh }: { me: Me; employeeId: string; refresh: () => void }) {
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [confirm, setConfirm] = useState(false);
  const [attempted, setAttempted] = useState(true);
  const lock = useRef(false);
  const router = useRouter();
  const key = `product-generation-attempt:${me.id}:${employeeId}`;
  useEffect(() => { Promise.resolve().then(() => { try { setAttempted(Boolean(localStorage.getItem(key))); } catch { setAttempted(true); } }); }, [key]);
  const ready = preflight?.readiness === "READY" && preflight.employee_id === employeeId && !!preflight.input_hash && preflight.blocker_codes?.length === 0;
  async function check() {
    if (lock.current) return; lock.current = true; setBusy(true); setError(null); setPreflight(null);
    try { setPreflight(await productRequest<Preflight>(`generation-runs/preflight/${employeeId}`)); } catch (e) { setError(e); }
    finally { lock.current = false; setBusy(false); }
  }
  async function generate() {
    if (!ready || attempted || lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      // Persist before sending; uncertain outcomes stay locked across refreshes.
      if (localStorage.getItem(key)) { setAttempted(true); return; }
      setAttempted(true); setConfirm(false);
      const result = await generateOnce<{ id: string }>(localStorage, key, employeeId, (path, body, headers) => postProduct(path, body, headers));
      refresh(); if (result.id) router.push(`/app/plans/${result.id}`);
    } catch (e) { setError(e); } finally { lock.current = false; setBusy(false); }
  }
  return <section className={`${panel} space-y-4`}><h2 className="font-semibold">Prepare a new onboarding plan</h2><p className="text-sm text-muted-foreground">Check approved ground truth and employee context first. Generation calls the configured AI provider only after you confirm. Successful output starts as Unverified.</p><Button variant="outline" disabled={busy} onClick={() => void check()}>{busy ? "Working…" : "Check readiness"}</Button>{preflight && <div role="status" className="space-y-2"><StateBadge value={preflight.readiness ?? "BLOCKED"} /><p className="text-sm">{ready ? `${preflight.requirement_count} requirements · ${preflight.dependency_count} dependencies · Matrix revision ${preflight.matrix_revision} · Stage set v${preflight.stage_set_version}` : "Resolve the authoritative input blockers before generation."}</p>{preflight.blocker_codes?.map((b) => <p key={b} className="text-sm text-warning">{humanize(b)}</p>)}</div>}{!!error && <Problem error={error} />}<Button disabled={!ready || busy || attempted} onClick={() => setConfirm(true)}>Generate once</Button>{attempted && <p className="text-xs text-muted-foreground">Generation is locked in this browser for this employee. Inspect the run history before any further attempt; an uncertain request is never automatically repeated.</p>}<Modal open={confirm} onOpenChange={setConfirm} title="Generate onboarding plan?" description="This sends one generation request using approved evidence. A generated plan still requires independent Python validation and human review."><Button disabled={busy || attempted || !ready} onClick={() => void generate()}>Confirm generation</Button></Modal></section>;
}

export function Plans({ me, runId, employeeFilter }: { me: Me; runId?: string; employeeFilter?: string }) {
  const [offset, setOffset] = useState(0);
  const [employee, setEmployee] = useState(employeeFilter ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const lock = useRef(false);
  const allowed = canReadGeneration(me);
  const load = useCallback(async () => {
    if (!allowed) return null;
    if (runId) {
      const run = await productRequest<Run>(`generation-runs/${runId}`);
      const [person, validation] = await Promise.all([productRequest<Employee>(`employees/${run.employee_id}`).catch(() => null), run.plan ? productRequest<Validation>(`generated-plans/${run.plan.id}/validation`).catch((e) => { if (e instanceof ProductError && e.status === 404) return null; throw e; }) : Promise.resolve(null)]);
      return { run, person, validation, page: null, employees: [] as Employee[] };
    }
    const [page, employees] = await Promise.all([productRequest<Page<Run>>(`generation-runs?offset=${offset}&limit=30${employee ? `&employee_id=${employee}` : ""}`), productRequest<Employee[]>("employees?limit=100")]);
    return { run: null, person: null, validation: null, page, employees };
  }, [allowed, runId, offset, employee]);
  const state = useResource(load), data = state.data;
  async function validate() {
    if (lock.current || !data?.run?.plan) return;
    lock.current = true; setBusy(true); setError(null);
    try { await postProduct(`generated-plans/${data.run.plan.id}/validate`, {}); state.refresh(); } catch (e) { setError(e); }
    finally { lock.current = false; setBusy(false); }
  }
  return <div className="space-y-6"><PageHeader eyebrow="Onboarding" title={runId ? "Generation & plan detail" : "Onboarding Plans"} description="Generation history, source-backed plans and independent validation. AI output remains Unverified until separately evaluated." />
    {!allowed ? <Empty title="Plan access for your role">Generation drafts and Unverified plans are restricted to authors and reviewers. Published employee plan delivery is not available through the current application. Contact your Training Manager for your onboarding assignment.</Empty> : state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : data && <>
      {data.page && <><div className="flex flex-wrap items-end gap-3"><label className="max-w-lg flex-1 text-sm font-semibold">Employee filter / generation context<select className={selectStyle} value={employee} onChange={(e) => { setEmployee(e.target.value); setOffset(0); }}><option value="">All employees</option>{data.employees.map((e) => <option key={e.id} value={e.id}>{e.profiles?.display_name ?? e.employee_code}{e.employee_code.startsWith("P4D") ? " · Fictional test fixture" : ""}</option>)}</select></label><Button variant="outline" onClick={state.refresh}>Refresh history</Button></div><p className="text-xs text-muted-foreground">History is filtered by employee on the server. Up to 100 employee choices are loaded.</p>{employee && canAuthor(me) && <GenerationForm key={employee} me={me} employeeId={employee} refresh={state.refresh} />}
        {!data.page.items.filter((r) => !employee || r.employee_id === employee).length ? <Empty title="No generation runs in this view">Select an employee to check readiness. Historical failures remain visible when you select their employee or browse all history.</Empty> : <DataTable headers={["Employee", "Requested", "Generation status", "Provider", "Details"]}>{data.page.items.filter((r) => !employee || r.employee_id === employee).map((r) => <tr key={r.id}><td>{data.employees.find((e) => e.id === r.employee_id)?.employee_code ?? "Employee outside loaded directory"}</td><td>{new Date(r.created_at).toLocaleString()}</td><td><StateBadge value={r.status} /></td><td>{r.provider}</td><td><Link className="font-semibold text-primary hover:underline" href={`/app/plans/${r.id}`}>Inspect run</Link></td></tr>)}</DataTable>}<Pager offset={offset} count={data.page.items.length} more={data.page.has_more} change={setOffset} /></>}
      {data.run && <>
        <section className={`${panel} space-y-4`}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{data.person?.profiles?.display_name ?? data.person?.employee_code ?? "Employee generation"}</h2><StateBadge value={data.run.status} /></div><Fields values={{ "Requested": new Date(data.run.created_at).toLocaleString(), "Provider / model": `${data.run.provider} / ${data.run.model}`, "Approved matrix": `Revision ${data.run.matrix_revision}`, "Stage configuration": `Version ${data.run.stage_set_version}` }} /><div className="flex flex-wrap gap-2"><Button variant="outline" asChild><Link href={`/app/employees/${data.run.employee_id}`}>Employee context</Link></Button>{data.person?.role_id && <Button variant="outline" asChild><Link href={`/app/requirements?role=${data.person.role_id}`}>Role ground truth</Link></Button>}<Button variant="outline" onClick={state.refresh}>Refresh result</Button></div></section>
        {data.run.status === "FAILED" || data.run.status === "STALE_INPUT" ? <Empty title={data.run.status === "STALE_INPUT" ? "Inputs changed before completion" : "Generation could not be completed"}>{generationMessage(data.run.error_code)}</Empty> : !data.run.plan ? <Empty title="No persisted plan">{["QUEUED", "RUNNING"].includes(data.run.status) ? "The request is queued or running. Refresh this result to check completion; do not submit it again." : "This run has no accepted generated plan."}</Empty> : <>
          <section className={`${panel} space-y-4`}><h2 className="text-lg font-semibold">Independent Python validation</h2>{data.validation ? <><StateBadge value={data.validation.decision?.status ?? "UNKNOWN"} /><Button variant="outline" asChild><Link href={`/app/reviews/${data.validation.id}`}>View findings & human review</Link></Button></> : <p className="text-sm text-muted-foreground">No validation result recorded. The generated plan is Unverified.</p>}{canAuthor(me) && (me.roles.includes("ADMIN") || data.run.created_by === me.id) && !data.validation && <Button disabled={busy} onClick={() => void validate()}>{busy ? "Validating…" : "Run independent validation"}</Button>}{!!error && <Problem error={error} />}</section>
          {!!data.run.plan.content.insufficient_information?.length && <section className={`${panel} space-y-3`}><h2 className="font-semibold">Information gaps reported by generation</h2><p className="text-sm text-muted-foreground">These are model-reported gaps, not independent validator findings.</p>{data.run.plan.content.insufficient_information.map((item, i) => <div key={i} className="text-sm"><p className="font-medium">{item.topic} · {humanize(item.reason_code)}</p><p>{item.detail}</p>{item.requirement_id && <Traceability ids={[item.requirement_id]} />}</div>)}</section>}<section className="space-y-4"><h2 className="text-xl font-semibold">{data.run.plan.content.plan.title}</h2><p className="text-sm leading-6">{data.run.plan.content.plan.summary}</p>{data.run.plan.content.plan.stages.map((stage) => <article key={stage.stage_id} className={`${panel} space-y-4`}><h3 className="text-lg font-semibold">{stage.sequence}. {stage.label}</h3><p className="text-xs text-muted-foreground">Stage window: day {stage.target_start_day}–{stage.target_end_day}. Stage windows do not establish individual requirement deadlines.</p>{!stage.modules.length && <p className="text-sm text-muted-foreground">No modules in this stage.</p>}{stage.modules.map((m) => <div key={m.module_id} className="rounded-md border border-border p-4"><div className="flex flex-wrap items-center gap-2"><h4 className="font-semibold">{m.title}</h4><StateBadge value={m.mandatory ? "MANDATORY" : "OPTIONAL"} /></div><p className="mt-2 text-sm">{m.purpose}</p><p className="mt-2 text-xs text-muted-foreground">{humanize(m.difficulty)} · {m.estimated_minutes} minutes · {humanize(m.priority)} priority</p>{m.prerequisite_module_ids.length > 0 && <p className="mt-2 text-sm">Prerequisites: {m.prerequisite_module_ids.map((id) => data.run?.plan?.content.plan.stages.flatMap((s) => s.modules).find((other) => other.module_id === id)?.title ?? "Unknown prerequisite").join(", ")}</p>}<Traceability ids={m.requirement_ids} references={m.source_refs} /><ModuleContent module={m} /></div>)}</article>)}</section>
        </>}
        <section className={`${panel} space-y-3`}><h2 className="font-semibold">Recorded generation attempts</h2>{data.run.attempts?.map((a) => <div key={a.attempt_no} className="flex flex-wrap gap-3 border-t border-border pt-3 text-sm"><span>Attempt {a.attempt_no} · {humanize(a.attempt_type)}</span><StateBadge value={a.provider_outcome} /><span>{humanize(a.parse_outcome)}</span>{a.error_code && <span className="text-xs text-muted-foreground">{a.error_code}</span>}</div>)}{!data.run.attempts?.length && <p className="text-sm text-muted-foreground">No provider attempt recorded.</p>}</section>
        <Technical values={{ "Run ID": data.run.id, "Employee ID": data.run.employee_id, "Matrix ID": data.run.matrix_id, "Prompt contract": data.run.prompt_version, "Output schema": data.run.schema_version, "Input hash": data.run.input_hash, "Projection hash": data.run.projection_hash, "Template hash": data.run.template_hash, "Error code": data.run.error_code ?? "None" }} />
      </>}
    </>}
  </div>;
}
