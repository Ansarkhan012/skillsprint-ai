import { cn } from "@/lib/utils";

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "success" | "warning" | "destructive" | "info" }) {
  return <span className={cn("inline-flex max-w-full items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.055em] leading-4", {
    "border-border bg-muted text-muted-foreground": tone === "neutral",
    "border-success/20 bg-success/10 text-success": tone === "success",
    "border-warning/20 bg-warning/10 text-warning": tone === "warning",
    "border-destructive/20 bg-destructive/10 text-destructive": tone === "destructive",
    "border-info/20 bg-info/8 text-info": tone === "info",
  })}>{children}</span>;
}
