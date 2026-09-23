"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronUp, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/browser";
import type { Me } from "@/lib/api";

export function UserMenu({ me }: { me: Me }) {
  const router = useRouter();
  async function signOut() {
    await createClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }
  return <DropdownMenu.Root>
    <DropdownMenu.Trigger className="flex w-full items-center gap-3 border-t border-white/10 px-5 py-4 text-left hover:bg-white/5" aria-label="Account menu">
      <span className="flex size-9 items-center justify-center rounded-md bg-white/12 text-sm font-bold">{me.display_name.charAt(0).toUpperCase()}</span>
      <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{me.display_name}</span><span className="block truncate text-xs capitalize text-sidebar-muted">{me.roles[0]?.toLowerCase().replaceAll("_", " ")}</span></span>
      <ChevronUp size={16} aria-hidden="true" />
    </DropdownMenu.Trigger>
    <DropdownMenu.Portal><DropdownMenu.Content side="top" align="start" className="z-50 min-w-56 rounded-md border border-border bg-card p-1 text-foreground shadow-lg">
      <DropdownMenu.Item onSelect={signOut} className="flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm outline-none focus:bg-muted"><LogOut size={16} />Sign out</DropdownMenu.Item>
    </DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root>;
}
