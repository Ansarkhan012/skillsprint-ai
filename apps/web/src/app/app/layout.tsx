import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { api, ApiError, type Me } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  let me: Me;
  try {
    me = await api.me(session.access_token);
  } catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status)) redirect("/access-denied");
    throw error;
  }
  if (!me.roles.length) redirect("/access-denied");
  return <AppShell me={me}>{children}</AppShell>;
}
