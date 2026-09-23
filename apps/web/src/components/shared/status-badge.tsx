import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: "Not started" | "Pending" | "Active" }) {
  const tone = status === "Active" ? "success" : status === "Pending" ? "warning" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}
