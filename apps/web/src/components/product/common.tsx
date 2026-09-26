"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertCircle, Inbox, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { errorMessage, humanize } from "@/lib/product";
export const panel = "rounded-md border border-border bg-card p-5 shadow-panel sm:p-6";
export const selectStyle = "h-10 w-full rounded-md border border-border bg-card px-3 text-sm";
export function useResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let current = true;
    Promise.resolve().then(() => { if (current) { setLoading(true); setError(null); } });
    load().then((value) => { if (current) setData(value); }).catch((e) => { if (current) setError(e); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [load, revision]);
  return { data, error, loading, refresh: () => refresh((v) => v + 1) };
}
export function Loading() {
  return <div role="status" aria-label="Loading workspace" className="space-y-4"><span className="sr-only">Loading workspace…</span>{[1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-md border border-border bg-muted motion-reduce:animate-none" />)}</div>;
}
export function Problem({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div role="alert" className={`${panel} space-y-3 border-destructive/30`}><AlertCircle className="text-destructive" size={22} aria-hidden="true" /><p className="text-sm">{errorMessage(error)}</p><div className="flex flex-wrap gap-2">{retry && <Button variant="outline" onClick={retry}>Try again</Button>}<Button variant="ghost" asChild><Link href="/login">Sign in</Link></Button></div></div>;
}
export function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className={`${panel} flex flex-col items-start gap-3`}><Inbox className="text-muted-foreground" size={24} aria-hidden="true" /><h2 className="font-semibold">{title}</h2><div className="text-sm leading-6 text-muted-foreground">{children}</div></div>;
}
export function StateBadge({ value }: { value: string }) {
  const tone = ["VERIFIED", "APPROVED", "ACTIVE"].includes(value) ? "success" : ["FAILED", "CONTRADICTORY", "UNSUPPORTED", "REJECTED"].includes(value) ? "destructive" : ["UNVERIFIED", "MANUAL_REVIEW", "VERIFIED_WITH_WARNING", "INCOMPLETE", "SUBMITTED", "RUNNING"].includes(value) ? "warning" : "neutral";
  return <Badge tone={tone}>{humanize(value)}</Badge>;
}
export function DataTable({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return <div className="max-w-full overflow-x-auto rounded-md border border-border bg-card shadow-panel" tabIndex={0} role="region" aria-label={headers.join(", ") + " table"}><table className="w-full text-left text-sm"><thead className="border-b border-border bg-muted/60 text-xs text-muted-foreground"><tr>{headers.map((h) => <th scope="col" key={h} className="whitespace-nowrap px-4 py-3 font-semibold">{h}</th>)}</tr></thead><tbody className="divide-y divide-border [&_td]:px-4 [&_td]:py-4 [&_tr:hover]:bg-muted/30">{children}</tbody></table></div>;
}
export function Pager({ offset, count, more, change, limit = 30 }: { offset: number; count: number; more: boolean; change: (offset: number) => void; limit?: number }) {
  return <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground"><span>{count ? `${offset + 1}–${offset + count}` : "0 records"} · Visible to your account</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={offset === 0} onClick={() => change(Math.max(0, offset - limit))}>Previous</Button><Button variant="outline" size="sm" disabled={!more} onClick={() => change(offset + limit)}>Next</Button></div></div>;
}
export function Modal({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; children: React.ReactNode }) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-40 bg-sidebar/50" /><Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-md border border-border bg-card p-5 shadow-xl sm:p-7"><Dialog.Title className="pr-8 text-lg font-semibold">{title}</Dialog.Title><Dialog.Description className="mt-2 text-sm leading-6 text-muted-foreground">{description}</Dialog.Description><Dialog.Close className="absolute right-3 top-3 rounded-md p-2 hover:bg-muted" aria-label="Close dialog"><X size={18} /></Dialog.Close><div className="mt-5">{children}</div></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
export function Fields({ values }: { values: Record<string, React.ReactNode> }) {
  return <dl className="grid gap-4 text-sm sm:grid-cols-2">{Object.entries(values).map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words font-medium">{value ?? "Not recorded"}</dd></div>)}</dl>;
}
export function Technical({ values }: { values: Record<string, React.ReactNode> }) {
  return <details className="rounded-md border border-border p-4 text-sm"><summary className="cursor-pointer font-medium">Technical provenance</summary><div className="mt-4 break-all [overflow-wrap:anywhere]"><Fields values={values} /></div></details>;
}
