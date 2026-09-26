"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileText, Users, ShieldCheck, LibraryBig } from "lucide-react";
import type { Me } from "@/lib/api";
import { canReadGeneration, humanize, productRequest, type Page, type Run, type Employee, type Validation } from "@/lib/product";
import type { CompanyDocument } from "@/lib/documents";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { DataTable, Empty, Loading, Pager, Problem, StateBadge, panel, useResource } from "./common";

const workflow = ["Source documents", "Approved ground truth", "Employee context", "AI generation", "Python validation", "JEV decision", "Human review"];
export function Overview({ me, reports = false }: { me: Me; reports?: boolean }) {
  const [offset, setOffset] = useState(0);
  const knowledge = canReadGeneration(me), people = me.roles.some((r) => r !== "EMPLOYEE");
  const load = useCallback(async () => {
    const [documents, employees, runs, validations] = await Promise.allSettled([
      knowledge ? productRequest<Page<CompanyDocument>>(`documents?limit=30&offset=${offset}`) : Promise.resolve(null),
      people ? productRequest<Employee[]>(`employees?limit=30&offset=${offset}`) : Promise.resolve(null),
      knowledge ? productRequest<Page<Run>>(`generation-runs?limit=30&offset=${offset}`) : Promise.resolve(null),
      knowledge ? productRequest<Page<Validation>>(`validation-runs?limit=30&offset=${offset}`) : Promise.resolve(null),
    ]);
    return { documents: documents.status === "fulfilled" ? documents.value : null, employees: employees.status === "fulfilled" ? employees.value : null, runs: runs.status === "fulfilled" ? runs.value : null, validations: validations.status === "fulfilled" ? validations.value : null,
      errors: [documents, employees, runs, validations].filter((r) => r.status === "rejected").length };
  }, [knowledge, people, offset]);
  const state = useResource(load), data = state.data;
  return <div className="space-y-7"><PageHeader eyebrow={reports ? "Insights" : "Overview"} title={reports ? "Operational reports" : `Welcome, ${me.display_name}`} description={reports ? "Counts and records from the currently loaded, authorized data pages. These are not organization-wide totals." : "Move from approved evidence to accountable onboarding, with human oversight at every decision."} action={<Button variant="outline" onClick={state.refresh}>Refresh data</Button>} />
    {!reports && <section className={panel}><h2 className="mb-4 text-sm font-semibold">Your onboarding workflow</h2><ol className="flex flex-wrap gap-x-3 gap-y-4">{workflow.map((step, i) => <li key={step} className="flex items-center gap-3 text-xs"><span className="flex size-6 items-center justify-center rounded-full bg-secondary font-bold text-primary">{i + 1}</span><span>{step}</span>{i < workflow.length - 1 && <ArrowRight size={12} className="text-muted-foreground" aria-hidden="true" />}</li>)}</ol></section>}
    {state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : data && <>
      {data.errors > 0 && <div role="alert" className={`${panel} text-sm`}>Some data could not be loaded. Unavailable counts are shown as “Unavailable”, never as zero. <Button variant="outline" size="sm" onClick={state.refresh}>Retry data</Button></div>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[
        ...(knowledge ? [{ label: "Documents", count: data.documents?.items.length, icon: FileText, href: "/app/documents" }, { label: "Generation runs", count: data.runs?.items.length, icon: LibraryBig, href: "/app/plans" }, { label: "Validation results", count: data.validations?.items.length, icon: ShieldCheck, href: "/app/reviews" }] : []),
        ...(people ? [{ label: "Employees", count: data.employees?.length, icon: Users, href: "/app/employees" }] : []),
      ].map(({ label, count, icon: Icon, href }) => <Link href={href} key={label} className={`${panel} hover:border-primary/40`}><div className="flex items-center justify-between text-sm text-muted-foreground"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><p className="mt-4 text-3xl font-semibold">{count ?? "Unavailable"}</p><p className="mt-2 text-xs text-muted-foreground">Loaded page · up to 30 records</p></Link>)}</div>
      {!people && <Empty title="Your employee workspace">Your account is active. Contact your Training Manager for your onboarding assignment. Generation drafts and review evidence are restricted to authorized authors and reviewers.<div className="mt-4"><Button asChild variant="outline"><Link href="/app/settings">View your account</Link></Button></div></Empty>}
      {knowledge && <div className="grid gap-5 xl:grid-cols-2"><section className={`${panel} space-y-4`}><div className="flex items-center justify-between"><h2 className="font-semibold">Recent documents</h2><Link href="/app/documents" className="text-sm text-primary hover:underline">Open library</Link></div>{data.documents === null ? <p className="text-sm">Document data unavailable.</p> : !data.documents.items.length ? <p className="text-sm text-muted-foreground">No documents in this page. Open the library to upload or review source evidence.</p> : data.documents.items.slice(0, 5).map((d) => <div key={d.id} className="border-t border-border pt-3"><p className="text-sm font-medium">{d.title}</p><p className="mt-1 text-xs text-muted-foreground">{d.document_code} · {humanize(d.category)}</p></div>)}</section>
      <section className={`${panel} space-y-4`}><div className="flex items-center justify-between"><h2 className="font-semibold">Validation decisions</h2><Link href="/app/reviews" className="text-sm text-primary hover:underline">Review evidence</Link></div>{data.validations === null ? <p className="text-sm">Validation data unavailable.</p> : !data.validations.items.length ? <p className="text-sm text-muted-foreground">No validation runs in this page. Only accepted generated plans can enter validation.</p> : data.validations.items.slice(0, 5).map((v) => <Link href={`/app/reviews/${v.id}`} key={v.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3"><StateBadge value={v.jev_decisions?.status ?? "UNKNOWN"} /><span className="text-xs">{v.summary.finding_count} findings · {new Date(v.completed_at).toLocaleDateString()}</span></Link>)}</section></div>}
      {reports && <>
        {knowledge && <section className="space-y-4"><h2 className="font-semibold">JEV distribution in loaded page</h2>{data.validations?.items.length ? <DataTable headers={["Decision", "Recorded validations"]}>{Object.entries(data.validations.items.reduce<Record<string, number>>((counts, v) => { const status = v.jev_decisions?.status ?? "UNKNOWN"; counts[status] = (counts[status] ?? 0) + 1; return counts; }, {})).map(([status, count]) => <tr key={status}><td><StateBadge value={status} /></td><td>{count}</td></tr>)}</DataTable> : <Empty title={data.validations ? "No validation runs in this page" : "Validation data unavailable"}>No distribution is inferred without recorded validation results.</Empty>}</section>}
        {data.employees && <section className="space-y-4"><h2 className="font-semibold">Employee onboarding in loaded page</h2><DataTable headers={["Employee", "Onboarding status", "Joining date"]}>{data.employees.map((e) => <tr key={e.id}><td><Link className="text-primary hover:underline" href={`/app/employees/${e.id}`}>{e.employee_code}</Link></td><td><StateBadge value={e.training_status} /></td><td>{e.joining_date}</td></tr>)}</DataTable>{!data.employees.length && <p className="text-sm text-muted-foreground">No employee records in this page.</p>}</section>}
        <Pager offset={offset} count={Math.max(data.employees?.length ?? 0, data.documents?.items.length ?? 0, data.runs?.items.length ?? 0, data.validations?.items.length ?? 0)} more={!!(data.documents?.has_more || data.runs?.has_more || data.validations?.has_more || data.employees?.length === 30)} change={setOffset} />
      </>}
    </>}
  </div>;
}

type Audit = { id: string; action: string; target_type: string; target_id: string | null; actor_profile_id: string | null; occurred_at: string };
export function AuditActivity() {
  const [offset, setOffset] = useState(0);
  const state = useResource(useCallback(() => productRequest<Page<Audit>>(`audit-events?offset=${offset}&limit=30`), [offset]));
  return <div className="space-y-6"><PageHeader eyebrow="Administration" title="Audit activity" description="Read-only administrative events. Original records and evidence are preserved." />{state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : state.data && <>{!state.data.items.length ? <Empty title="No audit events in this page">Audited application actions appear here as they are recorded.</Empty> : <DataTable headers={["Event", "Target", "Time", "Technical identifiers"]}>{state.data.items.map((a) => <tr key={a.id}><td>{humanize(a.action)}</td><td>{humanize(a.target_type)}</td><td>{new Date(a.occurred_at).toLocaleString()}</td><td><details><summary className="cursor-pointer text-primary">Inspect identifiers</summary><p className="mt-2 break-all text-xs">Target: {a.target_id ?? "Not recorded"}<br />Actor: {a.actor_profile_id ?? "System"}</p></details></td></tr>)}</DataTable>}<Pager offset={offset} count={state.data.items.length} more={state.data.has_more} change={setOffset} /></>}</div>;
}
