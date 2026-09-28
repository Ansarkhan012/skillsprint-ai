"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CalendarClock, ClipboardCheck, Cpu, RefreshCw, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import type { Me } from "@/lib/api";
import { canAuthor, canReadGeneration, canReleaseGenerationLock, generateOnce, releaseGenerationLock, generationMessage, humanize, postProduct, productRequest, type Employee, type Page, type PlanModule, type Run, type Validation, ProductError } from "@/lib/product";
import type { Preflight } from "@/lib/phase4d-test";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DataTable, Empty, Fields, Loading, Modal, Pager, Problem, StateBadge, Technical, panel, selectStyle, useResource } from "./common";
import { Traceability } from "./traceability";
import { WorkflowRail } from "./intelligence";

function ModuleContent({ module }: { module: PlanModule }) {
  const groups = ["learning_objectives", "key_concepts", "activities", "checklist_items", "tasks", "scenarios", "quizzes", "assessments", "completion_criteria"];
  const raw = module as unknown as Record<string, unknown>;
  return <div className="mt-3 space-y-2">{groups.map((group) => {
    const items = raw[group];
    if (!Array.isArray(items) || !items.length) return null;
    return <details key={group} className="rounded-md border border-border bg-surface-raised px-4 py-3 text-sm"><summary className="cursor-pointer font-medium">{humanize(group)} <span className="text-muted-foreground">({items.length})</span></summary><div className="mt-3 space-y-4">{items.map((item: Record<string, unknown>, i) => <div key={i} className="space-y-2 border-t border-border pt-3">{["title", "statement", "purpose", "activity", "description", "question", "prompt", "instructions", "expected_outcome", "explanation", "pass_condition", "responsible_role", "evidence_type", "threshold"].map((field) => typeof item[field] === "string" ? <p key={field} className="whitespace-pre-wrap"><span className="font-medium">{humanize(field)}: </span>{item[field] as string}</p> : null)}{["completion_criteria", "expected_actions", "success_criteria"].map((field) => Array.isArray(item[field]) ? <ul key={field} className="list-disc pl-5">{(item[field] as string[]).map((text, n) => <li key={n}>{text}</li>)}</ul> : null)}{Array.isArray(item.options) && <ul className="list-disc pl-5">{item.options.map((o: { text: string }, n: number) => <li key={n}>{o.text}</li>)}</ul>}{Array.isArray(item.rubric) && <div>{item.rubric.map((r: { criterion: string; weight_percent: number; expected_performance: string; pass_condition: string }, n: number) => <p key={n} className="mt-2">{r.criterion} ({r.weight_percent}%) · {r.expected_performance} · Pass: {r.pass_condition}</p>)}</div>}{Array.isArray(item.requirement_ids) && <Traceability ids={item.requirement_ids as string[]} />}</div>)}</div></details>;
  })}</div>;
}

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return <li className="relative flex gap-4 pb-6 last:pb-0"><span className={`relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${done ? "bg-primary-solid text-primary-foreground" : "bg-primary-soft text-primary"}`}>{n}</span><div className="min-w-0 flex-1 space-y-3 pt-1"><h3 className="text-sm font-semibold">{title}</h3>{children}</div></li>;
}

function GenerationForm({ me, employeeId, refresh, runs }: { me: Me; employeeId: string; refresh: () => void; runs: Run[] }) {
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [confirmRelease, setConfirmRelease] = useState(false);
  const [released, setReleased] = useState(false);
  const releasable = canAuthor(me) && canReleaseGenerationLock(runs);
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
    } catch (e) { setError(e); try { setAttempted(Boolean(localStorage.getItem(key))); } catch { setAttempted(true); } } finally { lock.current = false; setBusy(false); }
  }
  function release() {
    if (!releasable || busy || lock.current) return;
    try { releaseGenerationLock(localStorage, key); } catch { return; }
    setConfirmRelease(false); setPreflight(null); setError(null); setAttempted(false); setReleased(true);
  }
  return <>
    <Step n={2} title="Check readiness" done={ready}>
      <p className="text-sm text-muted-foreground">Confirms approved ground truth and employee context. No AI provider is called.</p>
      <Button variant="outline" disabled={busy} onClick={() => void check()}><ClipboardCheck size={16} aria-hidden="true" />{busy ? "Working…" : "Check readiness"}</Button>
      {preflight && <div role="status" className="space-y-3"><StateBadge value={busy ? "SUBMITTING" : attempted ? "LOCKED" : preflight.readiness ?? "BLOCKED"} />
        {ready ? <><dl className="grid grid-cols-2 gap-3">{[["Approved requirements", preflight.requirement_count], ["Dependencies", preflight.dependency_count]].map(([label, value]) => <div key={label} className="rounded-md bg-surface-raised p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="metric-value mt-1 text-xl font-semibold">{value}</dd></div>)}</dl><Technical values={{ "Matrix revision": preflight.matrix_revision, "Stage set version": preflight.stage_set_version }} /></> : <p className="text-sm">Resolve the authoritative input blockers before generation.</p>}
        {!!preflight.blocker_codes?.length && <ul className="space-y-1.5">{preflight.blocker_codes.map((b) => <li key={b}><Badge tone="warning">{humanize(b)}</Badge></li>)}</ul>}
      </div>}
    </Step>
    <Step n={3} title="Generate once">
      <p className="text-sm text-muted-foreground">Calls the configured AI provider only after you confirm. Output starts as Unverified.</p>
      {!!error && <Problem error={error} />}
      <Button disabled={!ready || busy || attempted} onClick={() => setConfirm(true)}><Sparkles size={16} aria-hidden="true" />{busy ? "Submitting…" : attempted ? "Generation locked" : "Generate once"}</Button>
      {attempted && <p className="text-xs text-muted-foreground">Generation is locked in this browser for this employee. Inspect the run history before any further attempt; a previous or uncertain request is never automatically repeated. Readiness does not release this lock.</p>}
      {attempted && canAuthor(me) && <div className="space-y-1.5"><Button variant="outline" size="sm" disabled={!releasable || busy} onClick={() => setConfirmRelease(true)}>Release lock</Button><p className="text-xs text-muted-foreground">{releasable ? "Available because this employee's run history shows no generation in progress." : "Unavailable while a generation for this employee is queued or running. Refresh the history once it completes."}</p></div>}
      {released && !attempted && <p role="status" className="text-xs text-muted-foreground">Lock released in this browser. Check readiness again before generating. This release is not recorded in the server audit trail.</p>}
    </Step>
    <Modal open={confirmRelease} onOpenChange={setConfirmRelease} title="Release the generation lock?" description="This lets this browser send one new generation request for this employee. Earlier attempts stay in the run history. Release only after confirming no request is still in progress."><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => setConfirmRelease(false)}>Cancel</Button><Button disabled={!releasable || busy} onClick={release}>Release lock</Button></div></Modal>
    <Modal open={confirm} onOpenChange={setConfirm} title="Generate onboarding plan?" description="This sends one generation request using approved evidence. A generated plan still requires independent Python validation and human review."><Button disabled={busy || attempted || !ready} onClick={() => void generate()}>Confirm generation</Button></Modal>
  </>;
}

function Tile({ icon: Icon, label, children }: { icon: typeof Cpu; label: string; children: React.ReactNode }) {
  return <div className="workspace-panel p-5"><div className="flex items-center gap-2 text-sm text-muted-foreground"><Icon size={16} aria-hidden="true" />{label}</div><div className="mt-3 text-sm font-medium [overflow-wrap:break-word]">{children}</div></div>;
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
  const selectedEmployee = data?.employees.find((e) => e.id === employee);
  return <div className="space-y-6"><PageHeader title={runId ? "Onboarding plan" : "Onboarding plans"} description="Generation history, source-backed plans and independent validation. AI output remains Unverified until separately evaluated."
      action={allowed ? <>{runId && <Button variant="outline" asChild><Link href="/app/plans">All plans</Link></Button>}{data?.run && <Button variant="outline" asChild><Link href={`/app/employees/${data.run.employee_id}`}>Employee context</Link></Button>}{data?.person?.role_id && <Button variant="outline" asChild><Link href={`/app/requirements?role=${data.person.role_id}`}>Role ground truth</Link></Button>}<Button variant="outline" onClick={state.refresh}><RefreshCw size={16} aria-hidden="true" />{runId ? "Refresh result" : "Refresh history"}</Button></> : undefined} />
    {!allowed ? <Empty title="Plan access for your role">Generation drafts and Unverified plans are restricted to authors and reviewers. Published employee plan delivery is not available through the current application. Contact your Training Manager for your onboarding assignment.</Empty> : state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : data && <>
      {data.page && <>
        <div className="grid gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
          <section className={`${panel} h-fit space-y-5`} aria-labelledby="generate-heading">
            <div><h2 id="generate-heading" className="card-title">Generate a plan</h2><p className="mt-1 text-sm text-muted-foreground">Choose an employee to filter history and prepare generation.</p></div>
            <ol className="relative before:absolute before:bottom-4 before:left-4 before:top-4 before:w-px before:bg-border">
              <Step n={1} title="Choose employee" done={!!employee}>
                <label className="block text-sm"><span className="sr-only">Employee filter / generation context</span><select className={selectStyle} value={employee} onChange={(e) => { setEmployee(e.target.value); setOffset(0); }}><option value="">All employees</option>{data.employees.map((e) => <option key={e.id} value={e.id}>{e.profiles?.display_name ?? e.employee_code}{e.employee_code.startsWith("P4D") ? " · Fictional test fixture" : ""}</option>)}</select></label>
                <p className="text-xs text-muted-foreground">History is filtered by employee on the server. Up to 100 employee choices are loaded.</p>
                {selectedEmployee && <div className="space-y-3 rounded-md bg-surface-raised p-4"><div className="flex flex-wrap items-center justify-between gap-2"><p className="flex items-center gap-2 text-sm font-medium"><UserRound size={16} className="text-primary" aria-hidden="true" />{selectedEmployee.profiles?.display_name ?? selectedEmployee.employee_code}</p><StateBadge value={selectedEmployee.training_status} /></div><Fields values={{ "Employee": selectedEmployee.employee_code, "Experience": humanize(selectedEmployee.experience_level), "Joining date": selectedEmployee.joining_date, "Role & department": <Link className="text-primary underline" href={`/app/employees/${selectedEmployee.id}`}>View authoritative employee context</Link> }} /></div>}
              </Step>
              {employee && canAuthor(me) ? <GenerationForm key={employee} me={me} employeeId={employee} refresh={state.refresh} runs={data.page.items.filter((r) => r.employee_id === employee)} /> : <Step n={2} title="Check readiness and generate"><p className="text-sm text-muted-foreground">{employee ? "Only Admins and Training Managers can generate plans." : "Select an employee to continue."}</p></Step>}
            </ol>
          </section>
          <section className="min-w-0 space-y-3" aria-labelledby="history-heading">
            <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 id="history-heading" className="card-title">Generation history</h2><span className="text-xs text-muted-foreground">{selectedEmployee ? `Filtered to ${selectedEmployee.employee_code}` : "All employees"}</span></div>
            {!data.page.items.filter((r) => !employee || r.employee_id === employee).length ? <Empty title="No generation runs in this view">Select an employee to check readiness. Historical failures remain visible when you select their employee or browse all history.</Empty> : <DataTable headers={["Employee", "Requested", "Generation status", "Provider", ""]}>{data.page.items.filter((r) => !employee || r.employee_id === employee).map((r) => <tr key={r.id}><td className="font-medium">{data.employees.find((e) => e.id === r.employee_id)?.employee_code ?? "Employee outside loaded directory"}</td><td className="whitespace-nowrap text-muted-foreground">{new Date(r.created_at).toLocaleString()}</td><td><StateBadge value={r.status} /></td><td>{r.provider}</td><td className="text-right"><Link className="whitespace-nowrap font-medium text-primary hover:underline" href={`/app/plans/${r.id}`}>Inspect run</Link></td></tr>)}</DataTable>}
            <Pager offset={offset} count={data.page.items.length} more={data.page.has_more} change={setOffset} />
          </section>
        </div>
        <WorkflowRail compact />
      </>}
      {data.run && <>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile icon={UserRound} label="Employee">{data.person?.profiles?.display_name ?? data.person?.employee_code ?? "Employee generation"}</Tile>
          <Tile icon={Sparkles} label="Generation status"><StateBadge value={data.run.status} /><span className="sr-only"> Plan status: {humanize(data.run.status)}</span></Tile>
          <Tile icon={ShieldCheck} label="Independent validation">{data.validation ? <StateBadge value={data.validation.decision?.status ?? "UNKNOWN"} /> : <span className="text-muted-foreground">Not validated</span>}</Tile>
          <Tile icon={CalendarClock} label="Requested">{new Date(data.run.created_at).toLocaleString()}</Tile>
        </div>
        {data.run.status === "FAILED" || data.run.status === "STALE_INPUT" ? <Empty title={data.run.status === "STALE_INPUT" ? "Inputs changed before completion" : "Generation could not be completed"}>{generationMessage(data.run.error_code)}</Empty> : !data.run.plan ? <Empty title="No persisted plan">{["QUEUED", "RUNNING"].includes(data.run.status) ? "The request is queued or running. Refresh this result to check completion; do not submit it again." : "This run has no accepted generated plan."}</Empty> : <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="min-w-0 space-y-4" aria-labelledby="plan-heading">
            <div className={panel}><p className="eyebrow">Generated plan · Unverified until validated</p><h2 id="plan-heading" className="mt-1 text-xl font-semibold">{data.run.plan.content.plan.title}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{data.run.plan.content.plan.summary}</p></div>
            {data.run.plan.content.plan.stages.map((stage) => <article key={stage.stage_id} className="plan-stage space-y-4 py-2"><div className={`${panel} space-y-4`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="card-title">{stage.sequence}. {stage.label}</h3><span className="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">Day {stage.target_start_day}–{stage.target_end_day}</span></div>
              <p className="text-xs text-muted-foreground">Stage windows do not establish individual requirement deadlines.</p>
              {!stage.modules.length && <p className="text-sm text-muted-foreground">No modules in this stage.</p>}
              {stage.modules.map((m) => <div key={m.module_id} className="rounded-panel border border-border p-5"><div className="flex flex-wrap items-center gap-2"><h4 className="font-semibold">{m.title}</h4><Badge tone={m.mandatory ? "info" : "neutral"}>{m.mandatory ? "Mandatory" : "Optional"}</Badge></div><p className="mt-2 text-sm">{m.purpose}</p><p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground"><span>{humanize(m.difficulty)}</span><span>· {m.estimated_minutes} minutes</span><span>· {humanize(m.priority)} priority</span></p>{m.prerequisite_module_ids.length > 0 && <p className="mt-2 text-sm"><span className="text-muted-foreground">Prerequisites: </span>{m.prerequisite_module_ids.map((id) => data.run?.plan?.content.plan.stages.flatMap((s) => s.modules).find((other) => other.module_id === id)?.title ?? "Unknown prerequisite").join(", ")}</p>}<Traceability ids={m.requirement_ids} references={m.source_refs} /><ModuleContent module={m} /></div>)}
            </div></article>)}
          </section>
          <aside className="space-y-6">
            <section className={`${panel} space-y-4`}><h2 className="card-title flex items-center gap-2"><ShieldCheck size={18} className="text-primary" aria-hidden="true" />Independent Python validation</h2>{data.validation ? <><StateBadge value={data.validation.decision?.status ?? "UNKNOWN"} /><Button variant="outline" className="w-full" asChild><Link href={`/app/reviews/${data.validation.id}`}>View findings & human review</Link></Button></> : <p className="text-sm text-muted-foreground">No validation result recorded. The generated plan is Unverified.</p>}{canAuthor(me) && (me.roles.includes("ADMIN") || data.run.created_by === me.id) && !data.validation && <Button className="w-full" disabled={busy} onClick={() => void validate()}>{busy ? "Validating…" : "Run independent validation"}</Button>}{!!error && <Problem error={error} />}</section>
            {!!data.run.plan.content.insufficient_information?.length && <section className={`${panel} space-y-3`}><h2 className="card-title">Information gaps reported by generation</h2><p className="text-sm text-muted-foreground">These are model-reported gaps, not independent validator findings.</p>{data.run.plan.content.insufficient_information.map((item, i) => <div key={i} className="rounded-md bg-status-warning/60 p-3 text-sm"><p className="font-medium">{item.topic} · {humanize(item.reason_code)}</p><p className="mt-1">{item.detail}</p>{item.requirement_id && <Traceability ids={[item.requirement_id]} />}</div>)}</section>}
          </aside>
        </div>}
        <details className={`${panel} text-sm`}><summary className="flex cursor-pointer items-center gap-2 font-semibold"><Cpu size={16} className="text-primary" aria-hidden="true" />Recorded generation attempts</summary><div className="space-y-3">{data.run.attempts?.map((a) => <div key={a.attempt_no} className="flex flex-wrap items-center gap-3 border-t border-border pt-3"><span>Attempt {a.attempt_no} · {humanize(a.attempt_type)}</span><StateBadge value={a.provider_outcome} /><span className="text-muted-foreground">{humanize(a.parse_outcome)}</span>{a.error_code && <span className="font-mono text-xs text-muted-foreground">{a.error_code}</span>}</div>)}{!data.run.attempts?.length && <p className="text-muted-foreground">No provider attempt recorded.</p>}</div></details>
        <Technical values={{ "Run ID": data.run.id, "Employee ID": data.run.employee_id, "Provider / model": `${data.run.provider} / ${data.run.model}`, "Matrix ID": data.run.matrix_id, "Matrix revision": data.run.matrix_revision, "Stage set version": data.run.stage_set_version, "Prompt contract": data.run.prompt_version, "Output schema": data.run.schema_version, "Input hash": data.run.input_hash, "Projection hash": data.run.projection_hash, "Template hash": data.run.template_hash, "Error code": data.run.error_code ?? "None" }} />
      </>}
    </>}
  </div>;
}
