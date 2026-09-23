import { cn } from "@/lib/utils";

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "success" | "warning" | "destructive" }) {
  return <span className={cn("inline-flex rounded-md border px-2 py-0.5 text-xs font-semibold", {
    "border-border bg-muted text-muted-foreground": tone === "neutral",
    "border-success/20 bg-success/10 text-success": tone === "success",
    "border-warning/20 bg-warning/10 text-warning": tone === "warning",
    "border-destructive/20 bg-destructive/10 text-destructive": tone === "destructive",
  })}>{children}</span>;
}
