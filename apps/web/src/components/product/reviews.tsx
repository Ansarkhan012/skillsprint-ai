"use client";
import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import type { Me } from "@/lib/api";
import { canReviewRun, humanize, postProduct, productRequest, type Page, type Validation } from "@/lib/product";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { DataTable, Empty, Fields, Loading, Modal, Pager, Problem, StateBadge, Technical, panel, selectStyle, useResource } from "./common";
import { Traceability } from "./traceability";

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
  return <div className="space-y-6"><PageHeader eyebrow="Independent assurance" title="Validation & human review" description="Python checks evidence and rules. JEV makes a deterministic decision. Human actions are recorded separately." />
    {notice && <p role="status" className="text-sm text-success">{notice}</p>}
    {state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : <>
      {page && <>{!page.items.length ? <Empty title="No validation results on this page">Open a legitimate generated plan and run independent Python validation. Failed generation attempts cannot be validated.</Empty> : <DataTable headers={["Validation", "JEV decision", "Findings", "Completed", "Review"]}>{page.items.map((v) => <tr key={v.id}><td className="font-medium">{v.validator_version}</td><td><StateBadge value={v.jev_decisions?.status ?? "UNKNOWN"} /></td><td>{v.summary.finding_count}</td><td>{new Date(v.completed_at).toLocaleString()}</td><td><Link className="font-semibold text-primary hover:underline" href={`/app/reviews/${v.id}`}>View evidence & review</Link></td></tr>)}</DataTable>}<Pager offset={offset} count={page.items.length} more={page.has_more} change={setOffset} /></>}
      {detail && <>
        <section className={`${panel} space-y-4`}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">JEV decision</h2><StateBadge value={detail.decision?.status ?? "UNKNOWN"} /></div><Fields values={{ "Validator": detail.validator_version, "Completed": new Date(detail.completed_at).toLocaleString(), "Mandatory coverage": `${detail.summary.mandatory_covered} of ${detail.summary.mandatory_total} requirements`, "Findings": detail.summary.finding_count }} />{detail.plan_context && <Button variant="outline" asChild><Link href={`/app/plans/${detail.plan_context.id}`}>Open generated plan</Link></Button>}<p className="text-xs text-muted-foreground">Coverage is a count of required references, not an AI confidence score. Structured timing that cannot be established remains a manual-review finding.</p></section>
        <section className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">Validator findings</h2><label className="text-sm">Severity<select className={selectStyle} value={filter} onChange={(e) => setFilter(e.target.value)}>{["ALL", "ERROR", "REVIEW", "WARNING"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select></label></div>
          {!detail.findings?.length ? <Empty title="No findings recorded">The deterministic validator recorded no findings for this immutable input.</Empty> : detail.findings.filter((f) => filter === "ALL" || f.severity === filter).map((f) => <article key={f.id} className={`${panel} space-y-3`}><div className="flex flex-wrap gap-2"><StateBadge value={f.severity} /><h3 className="font-semibold">{humanize(f.code)}</h3></div><p className="text-sm">{f.explanation}</p>{f.requirement_id && <Traceability ids={[f.requirement_id]} />}<details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Recorded finding evidence ({f.evidence.length})</summary><p className="mt-2 break-all">{f.code} · {f.location}</p>{f.evidence.map((e, i) => <div key={i} className="mt-2 break-all"><p>Document {e.document_id ?? "See linked requirement"} · Version {e.document_version_id}</p><p>Chunk {e.chunk_id} · Locator {typeof e.locator === "string" ? e.locator : Object.entries(e.locator).map(([k, v]) => `${humanize(k)} ${String(v)}`).join(" / ")}</p></div>)}</details></article>)}
        </section>
        <section className={`${panel} space-y-4`}><h2 className="text-lg font-semibold">Human disposition</h2><p className="text-sm text-muted-foreground">A review or override does not rewrite the validator findings or turn the JEV decision into Verified. Request regeneration records a request; it does not call an AI provider.</p>
          {allowed ? <div className="flex flex-wrap gap-2">{["APPROVE", "REJECT", "REGENERATE", ...(me.roles.includes("ADMIN") ? ["OVERRIDE"] : [])].map((a) => <Button key={a} variant={a === "APPROVE" ? "primary" : "outline"} disabled={a === "APPROVE" && !["VERIFIED", "VERIFIED_WITH_WARNING"].includes(detail.decision?.status ?? "")} onClick={() => { setAction(a); setError(null); }}>{a === "REGENERATE" ? "Request regeneration" : a === "OVERRIDE" ? "Admin override" : humanize(a)}</Button>)}</div> : <p className="text-sm">An independent Reviewer or Admin must record the decision. Authors and employee subjects cannot review their own plan.</p>}
          {!detail.review_actions?.length && <p className="text-sm text-muted-foreground">No human review recorded.</p>}{detail.review_actions?.map((a) => <div key={a.id} className="rounded-md border border-border p-4"><div className="flex flex-wrap items-center gap-3"><StateBadge value={a.action} /><time className="text-xs text-muted-foreground">{new Date(a.created_at).toLocaleString()}</time></div><p className="mt-2 whitespace-pre-wrap text-sm">{a.reason}</p><details className="mt-2 text-xs"><summary>Reviewer identity</summary><p className="break-all">{a.actor_profile_id}</p></details></div>)}{detail.review_actions_has_more && <p className="text-xs text-muted-foreground">Showing the latest 100 review actions.</p>}
        </section><Technical values={{ "Validation ID": detail.id, "Generated plan ID": detail.generated_plan_id }} />
      </>}
    </>}
    <Modal open={!!action} onOpenChange={(open) => { if (!busy && !open) setAction(""); }} title={`Confirm ${humanize(action)}`} description="This creates an audited human action. Original validation evidence and JEV status remain unchanged."><form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void review(); }}><label className="block text-sm font-semibold">Decision reason<textarea className="mt-2 min-h-28 w-full rounded-md border border-border p-3" required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /></label>{!!error && <Problem error={error} />}<Button type="submit" disabled={busy || !reason.trim()}>{busy ? "Recording…" : "Record decision"}</Button></form></Modal>
  </div>;
}
