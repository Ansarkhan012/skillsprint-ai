import type { LucideIcon } from "lucide-react";

export function StatCard({ icon: Icon, label, value, note }: { icon: LucideIcon; label: string; value: string; note: string }) {
  return <div className="rounded-md border border-border bg-card p-5 shadow-panel">
    <div className="flex items-start justify-between gap-4"><p className="text-sm font-medium text-muted-foreground">{label}</p><Icon size={18} className="text-primary" aria-hidden="true" /></div>
    <p className="mt-3 text-3xl font-bold tracking-tight">{value}</p>
    <p className="mt-2 text-xs text-muted-foreground">{note}</p>
  </div>;
}
