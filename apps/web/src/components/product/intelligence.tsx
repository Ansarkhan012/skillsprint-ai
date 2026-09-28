import { FileText, ListChecks, Users, Sparkles, ShieldCheck, Scale, UserCheck, ArrowUpRight, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { humanize, traceabilityLabel, type Run, type Validation } from "@/lib/product";
import { STATUS_BAR, StateBadge, panel, statusTone } from "./common";

const steps = [
  { label: "Documents", detail: "Company sources", icon: FileText },
  { label: "Ground truth", detail: "Approved requirements", icon: ListChecks },
  { label: "AI generation", detail: "Bounded, unverified draft", icon: Sparkles },
  { label: "Python validation", detail: "Independent checks", icon: ShieldCheck },
  { label: "JEV decision", detail: "Deterministic rules", icon: Scale },
  { label: "Human review", detail: "Accountable control", icon: UserCheck },
];
export function WorkflowRail({ compact = false }: { compact?: boolean }) {
  const journey = compact ? [steps[0], steps[1], { label: "Employee context", detail: "Role & applicability", icon: Users }, ...steps.slice(2)] : steps;
  return <section className="workspace-panel overflow-hidden" aria-label="Evidence to onboarding workflow">
    {!compact && <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-6 py-4"><h2 className="card-title">From evidence to accountable onboarding</h2><span className="text-xs text-muted-foreground">Process overview · not a completion indicator</span></div>}
    <ol className={`grid grid-cols-2 ${compact ? "sm:grid-cols-4 xl:grid-cols-7" : "sm:grid-cols-3 xl:grid-cols-6"}`}>{journey.map(({ label, detail, icon: Icon }, i) => <li key={label} className="relative flex min-w-0 gap-3 border-b border-r border-border p-4 [overflow-wrap:normal] last:border-r-0 sm:p-5 xl:border-b-0"><span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary"><Icon size={16} aria-hidden="true" /></span><div><p className="text-sm font-medium leading-5"><span className="mr-1.5 text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>{label}</p><p className="mt-1 text-xs leading-4 text-muted-foreground">{detail}</p></div></li>)}</ol>
  </section>;
}

export function TrustPanel({ validation }: { validation?: Validation | null }) {
  const status = validation?.decision?.status ?? validation?.jev_decisions?.status;
  const covered = validation?.summary.mandatory_covered ?? 0;
  const total = validation?.summary.mandatory_total ?? 0;
  return <section className={`${panel} border-t-2 border-t-primary`} aria-label="Independent assurance">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-center gap-3"><span className="rounded-full bg-primary-soft p-2.5 text-primary"><ShieldCheck size={21} aria-hidden="true" /></span><div><h2 className="card-title">Independent assurance</h2><p className="mt-1 text-xs text-muted-foreground">AI creates the draft. Evidence determines trust.</p></div></div><StateBadge value={status ?? "NOT_VALIDATED"} /></div>
    <div className="mt-5 grid gap-5 sm:grid-cols-3"><div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">01 · Python validation</p><p className="mt-2 text-sm">{validation ? `${covered} of ${total} mandatory requirements covered` : "No validation result recorded"}</p>{validation && total > 0 && <><progress aria-label="Mandatory requirement coverage" className="mt-2 h-1.5 w-full accent-primary" value={Math.min(covered,total)} max={total} /><p className="mt-1 text-[10px] text-muted-foreground">Reference coverage, not an AI confidence score</p></>}{validation && traceabilityLabel(validation.summary) && <p className="mt-2 text-xs">Source traceability: {traceabilityLabel(validation.summary)}</p>}</div><div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">02 · JEV decision</p><p className="mt-2 text-sm">{status ? humanize(status) : "Awaiting independent validation"}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Checks sources, applicability, dependencies and contradictions.</p></div><div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">03 · Human control</p><p className="mt-2 text-sm">{validation?.review_actions?.length ? `${validation.review_actions.length} recorded actions` : "Independent review remains separate"}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">A human disposition never rewrites the original JEV result.</p></div></div>
  </section>;
}

export function RunSignals({ runs, validations }: { runs: Run[] | null; validations: Validation[] | null }) {
  const failed = runs?.filter(r => ["FAILED", "STALE_INPUT"].includes(r.status));
  const unresolved = validations?.filter(v => !["VERIFIED", "VERIFIED_WITH_WARNING"].includes(v.jev_decisions?.status ?? v.decision?.status ?? "UNKNOWN"));
  const counts = runs?.reduce<Record<string, number>>((all, run) => { all[run.status] = (all[run.status] ?? 0) + 1; return all; }, {});
  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
    <section className={`${panel} space-y-4`}><div className="flex items-start justify-between gap-3"><div><h2 className="card-title">Recent onboarding runs</h2><p className="mt-1 text-xs text-muted-foreground">Drafts, failures and decisions stay traceable.</p></div><Link href="/app/plans" aria-label="View all onboarding runs" className="rounded-md p-2 text-primary hover:bg-primary-soft"><ArrowUpRight size={18} /></Link></div>
      {runs === null ? <p className="py-5 text-sm text-muted-foreground">Generation history is unavailable.</p> : !runs.length ? <div className="rounded-md border border-dashed border-border px-4 py-7 text-sm"><p className="font-medium">Your first plan starts with approved evidence</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Choose an employee in Onboarding Plans and check readiness. No generation happens automatically.</p></div> : <div className="divide-y divide-border">{runs.slice(0,5).map(run => <Link key={run.id} href={`/app/plans/${run.id}`} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="text-sm font-medium">Onboarding run <span className="font-mono text-xs text-muted-foreground">{run.id.slice(0,8)}</span></p><p className="mt-1 text-xs text-muted-foreground">{new Date(run.created_at).toLocaleString()} · Matrix r{run.matrix_revision}</p></div><StateBadge value={run.status} /></Link>)}</div>}
    </section>
    <section className={`${panel} space-y-4`}><div className="flex items-center gap-2"><AlertTriangle size={17} className="text-warning" aria-hidden="true" /><h2 className="card-title">Needs attention</h2></div><p className="text-xs text-muted-foreground">Within the currently loaded records</p><div className="grid grid-cols-2 gap-3"><div className="rounded-lg bg-surface-raised p-3"><p className="metric-value text-2xl font-semibold">{failed?.length ?? "—"}</p><p className="mt-1 text-xs text-muted-foreground">Failed or stale runs</p></div><div className="rounded-lg bg-surface-raised p-3"><p className="metric-value text-2xl font-semibold">{unresolved?.length ?? "—"}</p><p className="mt-1 text-xs text-muted-foreground">Non-verified decisions</p></div></div>
      {counts && runs && runs.length > 0 && <div className="space-y-3" aria-label="Generation status distribution">{Object.entries(counts).map(([status,count]) => <div key={status}><div className="mb-1.5 flex justify-between gap-2 text-xs"><span>{humanize(status)}</span><span className="font-semibold">{count}</span></div><div className={`h-1.5 overflow-hidden rounded-full ${STATUS_BAR[statusTone(status)].track}`}><div className={`h-full rounded-full ${STATUS_BAR[statusTone(status)].fill}`} style={{width:`${100*count/runs.length}%`}} /></div></div>)}</div>}
      <p className="border-t border-border pt-3 text-[11px] leading-5 text-muted-foreground">A generated plan is not a verified plan. Review recorded evidence before taking a human action.</p>
    </section>
  </div>;
}
