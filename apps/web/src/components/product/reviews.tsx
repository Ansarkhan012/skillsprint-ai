"use client";
import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { Download, FileSearch, Gavel, History, ListChecks, Target, Link2 } from "lucide-react";
import type { Me } from "@/lib/api";
import { canReviewRun, humanize, postProduct, productRequest, traceabilityLabel, type Page, type Validation } from "@/lib/product";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DataTable, Empty, Loading, Modal, Pager, Problem, StateBadge, Technical, panel, useResource } from "./common";
import { Traceability } from "./traceability";

function Metric({ icon: Icon, label, value, children }: { icon: typeof Target; label: string; value: React.ReactNode; children?: React.ReactNode }) {
  return <div className="workspace-panel p-5"><div className="flex items-center gap-2 text-sm text-muted-foreground"><Icon size={16} aria-hidden="true" />{label}</div><div className="mt-3 text-xl font-semibold text-foreground">{value}</div>{children && <div className="mt-1 text-xs text-muted-foreground">{children}</div>}</div>;
}

export function Reviews({ me, validationId }: { me: Me; validationId?: string }) {
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("ALL");
  const load = useCallback(() => validationId ? productRequest<Validation>(`validation-runs/${validationId}`) : productRequest<Page<Validation>>(`validation-runs?offset=${offset}&limit=30`), [validationId, offset]);
  const state = useResource<Validation | Page<Validation>>(load);
  const [action, setAction] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [notice, setNotice] = useState("");
  async function review() {
    if (lock.current || !validationId || !reason.trim()) return;
    lock.current = true; setBusy(true); setError(null);
    try { await postProduct(`validation-runs/${validationId}/review`, { action, reason }); setAction(""); setReason(""); setNotice("Human decision recorded. The original JEV result is preserved."); state.refresh(); }
    catch (e) { setError(e); } finally { lock.current = false; setBusy(false); }
  }
  const detail = validationId ? state.data as Validation | null : null;
  const page = !validationId ? state.data as Page<Validation> | null : null;
  const allowed = detail?.plan_context && canReviewRun(me, detail.plan_context);
  const severities = ["ALL", "ERROR", "REVIEW", "WARNING"];
  const count = (s: string) => detail?.findings?.filter((f) => s === "ALL" || f.severity === s).length ?? 0;
  const traceability = detail ? traceabilityLabel(detail.summary) : null;
  return <div className="space-y-6">
    <PageHeader title={detail ? "Validation result" : "Validation & reviews"} description={detail ? "Python checks evidence and rules, JEV makes a deterministic decision, and human actions are recorded separately." : "Independent Python validation results for generated onboarding plans. Open a result to inspect findings and record a human decision."}
      action={detail ? <><Button variant="outline" asChild><Link href="/app/reviews">All results</Link></Button>{detail.plan_context && <Button variant="outline" asChild><Link href={`/app/plans/${detail.plan_context.id}`}>Open generated plan</Link></Button>}<Button asChild><a href={`/api/document-gateway/validation-runs/${detail.id}/comparison.csv`} download><Download size={16} aria-hidden="true" />Export GenAI vs Python comparison (CSV)</a></Button></> : undefined} />
    {notice && <p role="status" className="rounded-panel bg-status-verified px-4 py-3 text-sm text-status-verified-fg">{notice}</p>}
    {state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : <>
      {page && <>{!page.items.length ? <Empty title="No validation results on this page">Open a legitimate generated plan and run independent Python validation. Failed generation attempts cannot be validated.</Empty> :
        <DataTable headers={["JEV decision", "Mandatory coverage", "Traceability", "Findings", "Completed", ""]}>{page.items.map((v) => <tr key={v.id}>
          <td><StateBadge value={v.jev_decisions?.status ?? "UNKNOWN"} /></td>
          <td className="whitespace-nowrap">{v.summary.mandatory_covered} / {v.summary.mandatory_total}</td>
          <td className="whitespace-nowrap">{v.summary.generated_items_total ? `${v.summary.generated_items_traceable ?? 0} / ${v.summary.generated_items_total}` : "—"}</td>
          <td>{v.summary.finding_count}</td>
          <td className="whitespace-nowrap text-muted-foreground">{new Date(v.completed_at).toLocaleString()}</td>
          <td className="text-right"><Link className="whitespace-nowrap font-medium text-primary hover:underline" href={`/app/reviews/${v.id}`}>View evidence & review</Link></td>
        </tr>)}</DataTable>}<Pager offset={offset} count={page.items.length} more={page.has_more} change={setOffset} /></>}
      {detail && <>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Metric icon={Gavel} label="JEV decision" value={<StateBadge value={detail.decision?.status ?? "UNKNOWN"} />}>{detail.validator_version}</Metric>
          <Metric icon={Target} label="Mandatory coverage" value={`${detail.summary.mandatory_covered} of ${detail.summary.mandatory_total}`}>Required references, not an AI confidence score</Metric>
          <Metric icon={Link2} label="Source traceability" value={traceability ? traceability.split(" (")[0] : "—"}>{traceability ?? "Not recorded for this result"}</Metric>
          <Metric icon={ListChecks} label="Findings" value={detail.summary.finding_count}>Completed {new Date(detail.completed_at).toLocaleString()}</Metric>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className={`${panel} min-w-0 space-y-4`}>
            <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="card-title flex items-center gap-2"><FileSearch size={18} className="text-primary" aria-hidden="true" />Validator findings</h2>
              <div role="tablist" aria-label="Filter findings by severity" className="flex flex-wrap gap-1 rounded-md bg-muted p-1">{severities.map((s) => <button key={s} type="button" role="tab" aria-selected={filter === s} onClick={() => setFilter(s)} className={cn("rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground", filter === s && "bg-card text-foreground shadow-panel")}>{humanize(s)} <span className="text-muted-foreground">({count(s)})</span></button>)}</div></div>
            {!detail.findings?.length ? <Empty title="No findings recorded">The deterministic validator recorded no findings for this immutable input.</Empty> : !count(filter) ? <p className="py-6 text-center text-sm text-muted-foreground">No {humanize(filter).toLowerCase()} findings.</p> :
              <ul className="divide-y divide-border">{detail.findings.filter((f) => filter === "ALL" || f.severity === filter).map((f) => <li key={f.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2"><StateBadge value={f.severity} /><h3 className="text-sm font-semibold">{humanize(f.code)}</h3></div>
                <p className="text-sm text-muted-foreground">{f.explanation}</p>
                {f.requirement_id && <Traceability ids={[f.requirement_id]} />}
                <details className="text-xs text-muted-foreground"><summary className="cursor-pointer text-primary">Recorded finding evidence ({f.evidence.length})</summary><p className="mt-2 break-all">{f.code} · {f.location}</p>{f.evidence.map((e, i) => <div key={i} className="mt-2 break-all"><p>Document {e.document_id ?? "See linked requirement"} · Version {e.document_version_id}</p><p>Chunk {e.chunk_id} · Locator {typeof e.locator === "string" ? e.locator : Object.entries(e.locator).map(([k, v]) => `${humanize(k)} ${String(v)}`).join(" / ")}</p></div>)}</details>
              </li>)}</ul>}
          </section>
          <aside className="space-y-6">
            <section className={`${panel} space-y-4`}><h2 className="card-title flex items-center gap-2"><Gavel size={18} className="text-primary" aria-hidden="true" />Human disposition</h2><p className="text-sm text-muted-foreground">A review or override does not rewrite the validator findings or turn the JEV decision into Verified. Request regeneration records a request; it does not call an AI provider.</p>
              {allowed ? <div className="grid gap-2">{["APPROVE", "REJECT", "REGENERATE", ...(me.roles.includes("ADMIN") ? ["OVERRIDE"] : [])].map((a) => <Button key={a} variant={a === "APPROVE" ? "primary" : "outline"} disabled={a === "APPROVE" && !["VERIFIED", "VERIFIED_WITH_WARNING"].includes(detail.decision?.status ?? "")} onClick={() => { setAction(a); setError(null); }}>{a === "REGENERATE" ? "Request regeneration" : a === "OVERRIDE" ? "Admin override" : humanize(a)}</Button>)}</div> : <p className="rounded-md bg-muted p-3 text-sm">An independent Reviewer or Admin must record the decision. Authors and employee subjects cannot review their own plan.</p>}
            </section>
            <section className={`${panel} space-y-4`}><h2 className="card-title flex items-center gap-2"><History size={18} className="text-primary" aria-hidden="true" />Review history</h2>
              {!detail.review_actions?.length && <p className="text-sm text-muted-foreground">No human review recorded.</p>}
              {!!detail.review_actions?.length && <ol className="space-y-4 border-l-2 border-border pl-4">{detail.review_actions.map((a) => <li key={a.id}><div className="flex flex-wrap items-center gap-2"><StateBadge value={a.action} /><time className="text-xs text-muted-foreground">{new Date(a.created_at).toLocaleString()}</time></div><p className="mt-2 whitespace-pre-wrap text-sm">{a.reason}</p><details className="mt-1 text-xs text-muted-foreground"><summary>Reviewer identity</summary><p className="break-all">{a.actor_profile_id}</p></details></li>)}</ol>}
              {detail.review_actions_has_more && <p className="text-xs text-muted-foreground">Showing the latest 100 review actions.</p>}
            </section>
            <Technical values={{ "Validation ID": detail.id, "Generated plan ID": detail.generated_plan_id }} />
          </aside>
        </div>
        <p className="text-xs text-muted-foreground">Traceability counts generated items whose every source reference is approved evidence for the requirement it cites. Ambiguous or unstaged timing remains a manual-review finding; staged structured timing is a warning.</p>
      </>}
    </>}
    <Modal open={!!action} onOpenChange={(open) => { if (!busy && !open) setAction(""); }} title={`Confirm ${humanize(action)}`} description="This creates an audited human action. Original validation evidence and JEV status remain unchanged."><form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void review(); }}><label className="block text-sm font-medium">Decision reason<textarea className="mt-2 min-h-28 w-full rounded-md border border-border p-3" required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /></label>{!!error && <Problem error={error} />}<Button type="submit" disabled={busy || !reason.trim()}>{busy ? "Recording…" : "Record decision"}</Button></form></Modal>
  </div>;
}
