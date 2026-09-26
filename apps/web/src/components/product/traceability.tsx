"use client";
import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Requirement } from "@/lib/rrm";
import { locator } from "@/lib/rrm";
import { productRequest, timingLabel, type SourceRef } from "@/lib/product";
import { Loading, Problem, Technical, useResource } from "./common";

function Evidence({ id }: { id: string }) {
  const state = useResource(useCallback(() => productRequest<Requirement>(`requirements/${id}`), [id]));
  if (state.loading) return <Loading />;
  if (state.error) return <Problem error={state.error} retry={state.refresh} />;
  const requirement = state.data;
  if (!requirement) return null;
  return <div className="space-y-3 rounded-md border border-border bg-muted/30 p-4 text-sm"><p className="font-semibold">{requirement.requirement_code} · revision {requirement.revision}</p><p>{requirement.statement}</p><p className="text-xs text-muted-foreground">{timingLabel(requirement.timing)}</p>{requirement.evidence?.map((e, i) => <div key={e.chunk?.id ?? i} className="rounded-md border border-border bg-card p-3"><p className="font-semibold">{e.document?.document_code} · {e.document?.title ?? "Historical source"}</p><p className="mt-1 text-xs text-muted-foreground">Version {e.version?.version_label ?? "not available"} · {e.chunk ? locator(e.chunk.source_location) : "Locator unavailable"}</p><p className={`mt-1 text-xs ${e.current_eligible ? "text-success" : "text-warning"}`}>{e.current_eligible ? "Currently eligible source" : "Historical evidence: not currently eligible"}</p>{e.chunk && <details className="mt-3"><summary className="cursor-pointer text-primary">Read exact source excerpt</summary><p className="mt-2 whitespace-pre-wrap break-words">{e.chunk.content}</p></details>}</div>)}<Technical values={{ "Requirement revision ID": requirement.id }} /></div>;
}
export function Traceability({ ids, references = [] }: { ids: string[]; references?: SourceRef[] }) {
  const [open, setOpen] = useState(false);
  return <div className="mt-3 space-y-3"><Button size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide evidence" : "Why was this assigned?"}</Button>{open && <><p className="text-xs text-muted-foreground">Requirement revisions and their linked source evidence. Current source eligibility is shown separately from the historical generation snapshot.</p>{references.length > 0 && <details className="text-xs"><summary>Recorded plan citations ({references.length})</summary>{references.map((ref, i) => <div key={`${ref.chunk_id}-${i}`} className="mt-2 break-all"><p>Source location: {typeof ref.locator === "string" ? ref.locator : locator(ref.locator)}</p><p>Version {ref.document_version_id} · Chunk {ref.chunk_id}</p></div>)}</details>}{Array.from(new Set(ids)).map((id) => <Evidence id={id} key={id} />)}</>}</div>;
}
