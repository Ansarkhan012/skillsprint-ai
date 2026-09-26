import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requestMe } from "@/lib/api";
import { Overview } from "@/components/product/overview";

export default async function Dashboard() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");
  return <Overview me={await requestMe(session.access_token)} />;
}
