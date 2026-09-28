"use client";
import { useCallback, useState } from "react";
import Link from "next/link";
import { Users, Target, Link2, Flag, RefreshCw } from "lucide-react";
import type { Me } from "@/lib/api";
import { canReadGeneration, dashboardMetrics, humanize, productRequest, type Page, type Run, type Employee, type Validation } from "@/lib/product";
import type { CompanyDocument } from "@/lib/documents";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { StatCard } from "@/components/shared/stat-card";
import { DataTable, Empty, Loading, Pager, Problem, StateBadge, panel, useResource } from "./common";

import { WorkflowRail, RunSignals } from "./intelligence";
export type DashboardData = { documents: Page<CompanyDocument> | null; employees: Employee[] | null; runs: Page<Run> | null; validations: Page<Validation> | null; errors: number };

export function Overview({ me, reports = false }: { me: Me; reports?: boolean }) {
  const [offset, setOffset] = useState(0);
  const knowledge = canReadGeneration(me), people = me.roles.some((r) => r !== "EMPLOYEE");
  const load = useCallback(async (): Promise<DashboardData> => {
    const [documents, employees, runs, validations] = await Promise.allSettled([
      knowledge ? productRequest<Page<CompanyDocument>>(`documents?limit=30&offset=${offset}`) : Promise.resolve(null),
      people ? productRequest<Employee[]>(`employees?limit=30&offset=${offset}`) : Promise.resolve(null),
      knowledge ? productRequest<Page<Run>>(`generation-runs?limit=30&offset=${offset}`) : Promise.resolve(null),
      knowledge ? productRequest<Page<Validation>>(`validation-runs?limit=30&offset=${offset}`) : Promise.resolve(null),
    ]);
    return { documents: documents.status === "fulfilled" ? documents.value : null, employees: employees.status === "fulfilled" ? employees.value : null, runs: runs.status === "fulfilled" ? runs.value : null, validations: validations.status === "fulfilled" ? validations.value : null,
      errors: [documents, employees, runs, validations].filter((r) => r.status === "rejected").length };
  }, [knowledge, people, offset]);
  const state = useResource(load);
  return <DashboardView me={me} reports={reports} data={state.data} loading={state.loading} error={state.error} refresh={state.refresh} offset={offset} setOffset={setOffset} />;
}

const pct = (value: number | null) => value === null ? "—" : `${value}%`;

export function DashboardView({ me, reports, data, loading, error, refresh, offset, setOffset }: { me: Me; reports: boolean; data: DashboardData | null; loading: boolean; error: unknown; refresh: () => void; offset: number; setOffset: (offset: number) => void }) {
  const knowledge = canReadGeneration(me), people = me.roles.some((r) => r !== "EMPLOYEE");
  const metrics = data ? dashboardMetrics(data.validations?.items ?? null, data.employees) : null;
  return <div className="space-y-6"><PageHeader title={reports ? "Operational reports" : "Dashboard"} description={reports ? "Counts and records from the currently loaded, authorized data pages. These are not organization-wide totals." : `Welcome back, ${me.display_name}. Approved documents become ground truth, AI drafts role-aware plans, and independent Python validation decides what can be trusted.`} action={<Button variant="outline" onClick={refresh}><RefreshCw size={16} aria-hidden="true" />Refresh</Button>} />
    {loading ? <Loading /> : error ? <Problem error={error} retry={refresh} /> : data && metrics && <>
      {data.errors > 0 && <div role="alert" className={`${panel} flex flex-wrap items-center justify-between gap-3 text-sm`}>Some data could not be loaded. Unavailable counts are shown as “Unavailable”, never as zero. <Button variant="outline" size="sm" onClick={refresh}>Retry data</Button></div>}
      {(knowledge || people) && <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:gap-6">
        {knowledge && <>
          <StatCard icon={Target} tone="success" href="/app/reviews" label="Mandatory coverage" value={metrics.validationCount === null ? "Unavailable" : pct(metrics.coverage)} note={metrics.validationCount ? `${metrics.validationCount} validation results` : "No validations yet"} />
          <StatCard icon={Link2} tone="info" href="/app/reviews" label="Source traceability" value={metrics.validationCount === null ? "Unavailable" : pct(metrics.traceability)} note={!metrics.validationCount ? "No validations yet" : metrics.tracedCount ? `${metrics.tracedCount} results measured` : "Not recorded for these results"} />
          <StatCard icon={Flag} tone="danger" href="/app/reviews" label="Flagged items" value={metrics.flagged === null ? "Unavailable" : String(metrics.flagged)} note="Items needing review" />
        </>}
        {people && <StatCard icon={Users} tone="primary" href="/app/employees" label="Employees" value={metrics.employees === null ? "Unavailable" : String(metrics.employees)} note="Total employees" />}
      </div>}
      {knowledge && <RunSignals runs={data.runs?.items ?? null} validations={data.validations?.items ?? null} />}
      {!people && <Empty title="Your employee workspace">Your account is active. Contact your Training Manager for your onboarding assignment. Generation drafts and review evidence are restricted to authorized authors and reviewers.<div className="mt-4"><Button asChild variant="outline"><Link href="/app/settings">View your account</Link></Button></div></Empty>}
      {knowledge && <div className="grid gap-6 2xl:grid-cols-2">
        <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="card-title">Validation decisions</h2><Link href="/app/reviews" className="text-sm font-medium text-primary hover:underline">View all</Link></div>
          {data.validations === null ? <Empty title="Validation data unavailable">Retry to load recorded validation results.</Empty> : !data.validations.items.length ? <Empty title="No validation results yet">Only accepted generated plans can enter independent validation.</Empty> :
          <DataTable headers={["Decision", "Coverage", "Traceability", "Findings", "Completed"]}>{data.validations.items.slice(0, 6).map((v) => <tr key={v.id}><td><Link href={`/app/reviews/${v.id}`} aria-label={`Open validation ${v.id.slice(0, 8)}`}><StateBadge value={v.jev_decisions?.status ?? v.decision?.status ?? "UNKNOWN"} /></Link></td><td className="whitespace-nowrap">{v.summary.mandatory_covered}/{v.summary.mandatory_total}</td><td className="whitespace-nowrap">{v.summary.generated_items_total ? `${v.summary.generated_items_traceable ?? 0}/${v.summary.generated_items_total}` : "—"}</td><td>{v.summary.finding_count}</td><td className="whitespace-nowrap text-muted-foreground">{new Date(v.completed_at).toLocaleDateString()}</td></tr>)}</DataTable>}
        </section>
        <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="card-title">Recent documents</h2><Link href="/app/documents" className="text-sm font-medium text-primary hover:underline">Open library</Link></div>
          {data.documents === null ? <Empty title="Document data unavailable">Retry to load the document library.</Empty> : !data.documents.items.length ? <Empty title="No documents yet">Open the library to upload or review source evidence.</Empty> :
          <DataTable headers={["Document", "Code", "Category", "Status"]}>{data.documents.items.slice(0, 6).map((d) => <tr key={d.id}><td className="font-medium">{d.title}</td><td className="whitespace-nowrap font-mono text-xs text-muted-foreground">{d.document_code}</td><td>{humanize(d.category)}</td><td><StateBadge value={d.status} /></td></tr>)}</DataTable>}
        </section>
      </div>}
      {!reports && knowledge && <WorkflowRail />}
      {reports && <>
        {knowledge && <section className="space-y-3"><h2 className="card-title">JEV distribution in loaded page</h2>{data.validations?.items.length ? <DataTable headers={["Decision", "Recorded validations"]}>{Object.entries(data.validations.items.reduce<Record<string, number>>((counts, v) => { const status = v.jev_decisions?.status ?? "UNKNOWN"; counts[status] = (counts[status] ?? 0) + 1; return counts; }, {})).map(([status, count]) => <tr key={status}><td><StateBadge value={status} /></td><td>{count}</td></tr>)}</DataTable> : <Empty title={data.validations ? "No validation runs in this page" : "Validation data unavailable"}>No distribution is inferred without recorded validation results.</Empty>}</section>}
        {data.employees && <section className="space-y-3"><h2 className="card-title">Employee onboarding in loaded page</h2><DataTable headers={["Employee", "Onboarding status", "Joining date"]}>{data.employees.map((e) => <tr key={e.id}><td><Link className="text-primary hover:underline" href={`/app/employees/${e.id}`}>{e.employee_code}</Link></td><td><StateBadge value={e.training_status} /></td><td>{e.joining_date}</td></tr>)}</DataTable>{!data.employees.length && <p className="text-sm text-muted-foreground">No employee records in this page.</p>}</section>}
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
