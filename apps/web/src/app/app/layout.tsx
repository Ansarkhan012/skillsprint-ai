import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { requestMe, ApiError, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError && authError.name !== "AuthSessionMissingError" && ![400, 401, 403].includes(authError.status ?? 0)) {
    throw new Error("AUTH_SERVICE_UNAVAILABLE");
  }
  if (!user) redirect("/login");
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  let me: Me;
  try {
    me = await requestMe(session.access_token);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/login");
    if (error instanceof ApiError && error.status === 403) redirect("/access-denied");
    throw error;
  }
  if (!me.roles.length) redirect("/access-denied");
  return <AppShell me={me}>{children}</AppShell>;
}
