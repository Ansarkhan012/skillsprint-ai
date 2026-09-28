import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const tones = {
  primary: "bg-primary-soft text-primary",
  success: "bg-status-verified text-status-verified-fg",
  info: "bg-status-review text-status-review-fg",
  danger: "bg-status-danger text-status-danger-fg",
  warning: "bg-status-warning text-status-warning-fg",
};

export function StatCard({ icon: Icon, label, value, note, tone = "primary", href }: { icon: LucideIcon; label: string; value: string; note: string; tone?: keyof typeof tones; href?: string }) {
  const body = <>
    <span className={cn("flex size-12 items-center justify-center rounded-full", tones[tone])}><Icon size={22} aria-hidden="true" /></span>
    <p className="metric-value mt-6 text-[28px] font-bold leading-none text-foreground">{value}</p>
    <p className="mt-2 text-sm font-medium text-muted-foreground">{label}</p><p className="mt-0.5 text-xs text-muted-foreground">{note}</p>
  </>;
  const style = "workspace-panel block p-6";
  return href ? <Link href={href} className={cn(style, "hover:border-border-strong")}>{body}</Link> : <div className={style}>{body}</div>;
}
