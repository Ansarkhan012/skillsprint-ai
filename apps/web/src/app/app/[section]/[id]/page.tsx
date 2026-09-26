import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe } from "@/lib/api";
import { navigation, canAccess } from "@/components/layout/navigation";
import { ProductWorkspace } from "@/components/product/workspace";
export default async function DetailPage({ params }: { params: Promise<{ section: string; id: string }> }) {
  const { section, id } = await params;
  if (!["employees", "plans", "reviews"].includes(section) || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) notFound();
  const item = navigation.find((n) => n.href === `/app/${section}`);
  if (!item) notFound();
  const client = await createClient();
  const { data: { session } } = await client.auth.getSession();
  if (!session) redirect("/login");
  const me = await requestMe(session.access_token);
  if (!canAccess(me.roles, item)) redirect("/access-denied");
  return <ProductWorkspace section={section} me={me} id={id} />;
}
