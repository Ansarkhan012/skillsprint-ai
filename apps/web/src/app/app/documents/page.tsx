import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe, apiRequest } from "@/lib/api";
import type { CompanyDocument, DocumentPage } from "@/lib/documents";
import { DocumentsWorkspace } from "@/components/documents/documents-workspace";

type Department = { id: string; code: string; name: string };

export default async function DocumentsPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  const me = await requestMe(session.access_token);
  if (!me.roles.some((role) => ["ADMIN", "TRAINING_MANAGER", "REVIEWER"].includes(role))) {
    redirect("/access-denied");
  }
  const [documents, departments] = await Promise.all([
    apiRequest<DocumentPage<CompanyDocument>>("/api/v1/documents", session.access_token),
    apiRequest<Department[]>("/api/v1/departments", session.access_token),
  ]);
  return <DocumentsWorkspace initialDocuments={documents} departments={departments}
    canUpload={me.roles.some((role) => role === "ADMIN" || role === "TRAINING_MANAGER")}
    canReview={me.roles.some((role) => role === "ADMIN" || role === "REVIEWER")}
    isAdmin={me.roles.includes("ADMIN")} actorId={me.id} />;
}
