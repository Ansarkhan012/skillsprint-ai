import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe } from "@/lib/api";
import { Phase4DTestSurface } from "@/components/phase4d/phase4d-test-surface";

export default async function Phase4DTestPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  const me = await requestMe(session.access_token);
  if (!me.roles.some((role) => role === "ADMIN" || role === "TRAINING_MANAGER")) redirect("/access-denied");
  return <Phase4DTestSurface />;
}
