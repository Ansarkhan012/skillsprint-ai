"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, Settings } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/browser";
import type { Me } from "@/lib/api";
import { humanize } from "@/lib/product";

export function UserMenu({ me }: { me: Me }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const role = humanize(me.roles[0] ?? "Account");
  async function signOut() {
    try {
      const result = await createClient().auth.signOut();
      if (result.error) throw result.error;
      router.replace("/login"); router.refresh();
    } catch { setError("Sign out failed. Use Settings to try again."); }
  }
  return <DropdownMenu.Root>
    <DropdownMenu.Trigger className="flex shrink-0 items-center gap-3 rounded-md py-1 pl-1 pr-2 text-left hover:bg-muted" aria-label={`Account menu for ${me.display_name}, ${role}`}>
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary-soft text-sm font-semibold text-primary">{me.display_name.charAt(0).toUpperCase()}</span>
      <span className="hidden min-w-0 sm:block"><span className="block max-w-40 truncate text-sm font-medium">{me.display_name}</span><span className="block max-w-40 truncate text-xs text-muted-foreground">{role}</span></span>
      <ChevronDown size={18} className="hidden text-muted-foreground sm:block" aria-hidden="true" />
    </DropdownMenu.Trigger>
    <DropdownMenu.Portal><DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-60 rounded-panel border border-border bg-card p-1.5 text-foreground shadow-lg">
      <div className="border-b border-border px-3 pb-3 pt-2"><p className="truncate text-sm font-medium">{me.display_name}</p><p className="text-xs text-muted-foreground">{role}</p></div>
      <DropdownMenu.Item asChild><Link href="/app/settings" className="mt-1 flex items-center gap-2 rounded-md px-3 py-2 text-sm outline-none focus:bg-muted"><Settings size={16} />Profile & settings</Link></DropdownMenu.Item>
      {error && <p role="alert" className="max-w-64 p-3 text-xs text-destructive">{error}</p>}
      <DropdownMenu.Item onSelect={signOut} className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm outline-none focus:bg-muted"><LogOut size={16} />Log out</DropdownMenu.Item>
    </DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root>;
}
