import { cn } from "@/lib/utils";

/** Status pill: soft background + dark text. Callers must always pass a visible text label. */
export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "success" | "warning" | "destructive" | "info" }) {
  return <span className={cn("inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium leading-5", {
    "bg-status-neutral text-status-neutral-fg": tone === "neutral",
    "bg-status-verified text-status-verified-fg": tone === "success",
    "bg-status-warning text-status-warning-fg": tone === "warning",
    "bg-status-danger text-status-danger-fg": tone === "destructive",
    "bg-status-review text-status-review-fg": tone === "info",
  })}>{children}</span>;
}
