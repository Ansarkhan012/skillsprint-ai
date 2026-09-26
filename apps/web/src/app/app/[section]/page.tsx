import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe } from "@/lib/api";
import { navigation, canAccess } from "@/components/layout/navigation";
import { ProductWorkspace } from "@/components/product/workspace";

export default async function SectionPage({ params, searchParams }: { params: Promise<{ section: string }>; searchParams: Promise<{ employee?: string }> }) {
  const { section } = await params;
  const item = navigation.find((entry) => entry.href === `/app/${section}`);
  if (!item || section === "dashboard" || section === "requirements") notFound();
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  const me = await requestMe(session.access_token);
  if (!canAccess(me.roles, item)) redirect("/access-denied");
  const { employee } = await searchParams;
  return <ProductWorkspace section={section} me={me} employeeFilter={employee && /^[0-9a-f-]{36}$/i.test(employee) ? employee : undefined} />;
}
