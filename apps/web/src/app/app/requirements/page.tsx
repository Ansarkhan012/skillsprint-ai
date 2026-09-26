import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe, apiRequest } from "@/lib/api";
import { RequirementsWorkspace } from "@/components/requirements/requirements-workspace";

type JobRole = { id: string; code: string; name: string; status: string };
type Department = { id: string; code: string; name: string; status: string };

export default async function RequirementsPage({ searchParams }: { searchParams: Promise<{ role?: string }> }) {
  const query = await searchParams;
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  const me = await requestMe(session.access_token);
  if (!me.roles.some((role) => ["ADMIN", "TRAINING_MANAGER", "REVIEWER"].includes(role))) redirect("/access-denied");
  const [roles, departments] = await Promise.all([
    apiRequest<JobRole[]>("/api/v1/roles", session.access_token),
    apiRequest<Department[]>("/api/v1/departments", session.access_token),
  ]);
  return <RequirementsWorkspace me={me} roles={roles.filter((role) => role.status === "ACTIVE")} initialRoleId={query.role}
    departments={departments.filter((department) => department.status === "ACTIVE")} />;
}
