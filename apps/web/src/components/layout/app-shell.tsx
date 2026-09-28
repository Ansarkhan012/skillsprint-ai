"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, PanelLeftClose, PanelLeftOpen, ChevronRight } from "lucide-react";
import type { Me } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sidebar } from "@/components/layout/sidebar";
import { navigation } from "@/components/layout/navigation";
import { CommandPalette } from "./command-palette";
import { humanize } from "@/lib/product";

export function AppShell({ me, children }: { me: Me; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const current = navigation.find((item) => pathname === item.href || pathname.startsWith(item.href + "/"));
  return <div className={`min-h-screen lg:grid ${collapsed ? "lg:grid-cols-[76px_minmax(0,1fr)]" : "lg:grid-cols-[248px_minmax(0,1fr)]"}`}>
    <a href="#main-content" className="sr-only z-50 rounded-md bg-card p-3 focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to main content</a>
    <aside className="sticky top-0 hidden h-dvh lg:block"><Sidebar me={me} collapsed={collapsed} /></aside>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogTitle className="sr-only">Navigation</DialogTitle><Sidebar me={me} onNavigate={() => setOpen(false)} /></DialogContent></Dialog>
    <div className="min-w-0">
      <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-border bg-card px-4 sm:px-7">
        <div className="flex min-w-0 items-center gap-3"><Button variant="ghost" size="icon" className="shrink-0 lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={20} /></Button><Button variant="ghost" size="icon" className="hidden shrink-0 lg:inline-flex" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</Button><nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground"><Link href="/app/dashboard" className="hidden hover:text-primary sm:inline">Workspace</Link><ChevronRight size={13} className="hidden shrink-0 sm:block" aria-hidden="true" /><span className="truncate font-semibold text-foreground">{current?.label ?? "Internal tools"}</span></nav></div>
        <div className="flex shrink-0 items-center gap-3"><CommandPalette me={me} /><span className="hidden rounded-md border border-border px-2 py-1 text-[10px] font-medium text-muted-foreground xl:block">{humanize(me.roles[0] ?? "Account")}</span><Link href="/app/settings" aria-label={`Account settings for ${me.display_name}`} title={me.display_name} className="flex size-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-primary">{me.display_name.charAt(0).toUpperCase()}</Link></div>
      </header>
      <main id="main-content" className="mx-auto w-full min-w-0 max-w-[1460px] px-4 py-7 sm:px-7 sm:py-9 xl:px-10">{children}</main>
    </div>
  </div>;
}
