import { ClipboardCheck, FileText, LibraryBig, Users, ArrowRight, Activity } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/shared/page-header";
import { StatCard } from "@/components/shared/stat-card";
import { EmptyState } from "@/components/shared/empty-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export default async function Dashboard() {
  const health = await api.health().catch(() => null);
  return <div className="space-y-8">
    <PageHeader eyebrow="Overview" title="Your workspace" description="A clear starting point for onboarding work. Live plan and document metrics will appear as those workflows are introduced." action={<div className="flex items-center gap-2 text-xs text-muted-foreground"><span>API</span><StatusBadge status={health?.status === "ok" ? "Active" : "Pending"} /></div>} />
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard icon={FileText} label="Approved documents" value="—" note="Available after document intelligence is enabled" />
      <StatCard icon={LibraryBig} label="Active plans" value="—" note="Available after plan generation is enabled" />
      <StatCard icon={ClipboardCheck} label="Pending reviews" value="—" note="Available after review workflow is enabled" />
      <StatCard icon={Users} label="Employees onboarding" value="—" note="Available after onboarding is enabled" />
    </div>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(270px,1fr)]">
      <section className="space-y-4"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Recent activity</h2><StatusBadge status="Not started" /></div><EmptyState icon={Activity} title="No activity to show yet" description="Document, review, and plan events will appear here once those workflows are available." /></section>
      <section className="rounded-md border border-border bg-card p-6 shadow-panel"><p className="text-xs font-bold uppercase tracking-wider text-primary">Foundation ready</p><h2 className="mt-3 text-lg font-semibold">Set up your team</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">The workspace is prepared for role-based access and employee records. Content workflows will be added in later phases.</p><Button asChild variant="outline" className="mt-5"><Link href="/app/employees">View employees <ArrowRight size={16} /></Link></Button></section>
    </div>
  </div>;
}
