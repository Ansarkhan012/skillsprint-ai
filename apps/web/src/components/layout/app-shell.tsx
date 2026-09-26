"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import type { Me } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sidebar } from "@/components/layout/sidebar";
import { navigation } from "@/components/layout/navigation";

export function AppShell({ me, children }: { me: Me; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const current = navigation.find((item) => pathname === item.href || pathname.startsWith(item.href + "/"));
  return <div className="min-h-screen lg:grid lg:grid-cols-[252px_minmax(0,1fr)]">
    <a href="#main-content" className="sr-only z-50 rounded-md bg-card p-3 focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to main content</a>
    <aside className="sticky top-0 hidden h-screen lg:block"><Sidebar me={me} /></aside>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogTitle className="sr-only">Navigation</DialogTitle><Sidebar me={me} onNavigate={() => setOpen(false)} /></DialogContent></Dialog>
    <div className="min-w-0">
      <header className="sticky top-0 z-20 flex h-18 items-center justify-between border-b border-border bg-card px-5 sm:px-8">
        <div className="flex min-w-0 items-center gap-3"><Button variant="ghost" size="icon" className="shrink-0 lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={21} /></Button><nav aria-label="Breadcrumb" className="truncate text-sm text-muted-foreground"><Link href="/app/dashboard" className="hover:text-primary">Workspace</Link><span className="mx-2">/</span><span className="font-semibold text-foreground">{current?.label ?? "Internal tools"}</span></nav></div>
        <Link href="/app/settings" className="ml-3 hidden truncate text-sm text-muted-foreground hover:text-primary sm:block">{me.display_name}</Link>
      </header>
      <main id="main-content" className="mx-auto w-full min-w-0 max-w-7xl px-5 py-7 sm:px-8 sm:py-9">{children}</main>
    </div>
  </div>;
}
