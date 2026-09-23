import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { api } from "@/lib/api";
import { navigation, canAccess } from "@/components/layout/navigation";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";

const descriptions: Record<string, string> = {
  documents: "Upload, version, and approve source documents in the document intelligence phase.",
  requirements: "Define approved role requirements after document sources are available.",
  plans: "Validated onboarding plans will be managed here after generation is introduced.",
  employees: "Employee directory and training assignments will appear here.",
  departments: "Department structure and role relationships will appear here.",
  reports: "Onboarding and compliance reports will appear here after live data exists.",
  audit: "Administrative audit events will be available here after the audit API is introduced.",
  users: "User and role administration will be available here after the management workflow is introduced.",
  settings: "Workspace configuration will be available here.",
};

export default async function SectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const item = navigation.find((entry) => entry.href === `/app/${section}`);
  if (!item || section === "dashboard") notFound();
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  const me = await api.me(session.access_token);
  if (!canAccess(me.roles, item)) redirect("/access-denied");
  return <div className="space-y-7"><PageHeader eyebrow="Workspace" title={item.label} description={descriptions[section]} /><EmptyState icon={item.icon} title="This workspace is being prepared" description="The foundation is available. This workflow will be added in its planned implementation phase." /></div>;
}
