import type { LucideIcon } from "lucide-react";

export function EmptyState({ icon: Icon, title, description, action }: { icon: LucideIcon; title: string; description: string; action?: React.ReactNode }) {
  return <div className="flex min-h-52 flex-col items-center justify-center rounded-md border border-dashed border-border bg-card p-8 text-center">
    <div className="mb-4 rounded-md bg-secondary p-3 text-primary"><Icon size={22} aria-hidden="true" /></div>
    <h2 className="text-base font-semibold">{title}</h2>
    <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">{description}</p>
    {action && <div className="mt-5">{action}</div>}
  </div>;
}
