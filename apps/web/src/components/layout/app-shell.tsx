"use client";

import { useState } from "react";
import { Menu } from "lucide-react";
import type { Me } from "@/lib/api";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sidebar } from "@/components/layout/sidebar";
import { CommandPalette } from "./command-palette";
import { ThemeToggle } from "./theme-toggle";
import { UserMenu } from "./user-menu";

export function AppShell({ me, children }: { me: Me; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  return <div className={`min-h-screen bg-background lg:grid ${collapsed ? "lg:grid-cols-[76px_minmax(0,1fr)]" : "lg:grid-cols-[var(--sidebar-width)_minmax(0,1fr)]"}`}>
    <a href="#main-content" className="sr-only z-50 rounded-md bg-card p-3 focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to main content</a>
    <aside className="sticky top-0 hidden h-dvh lg:block"><Sidebar me={me} collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} /></aside>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogTitle className="sr-only">Navigation</DialogTitle><Sidebar me={me} onNavigate={() => setOpen(false)} /></DialogContent></Dialog>
    <div className="min-w-0">
      <header className="sticky top-0 z-20 flex h-18 items-center gap-3 border-b border-border bg-card px-4 sm:gap-4 sm:px-6 xl:px-8">
        <button type="button" className="flex size-10 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:text-foreground lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={20} /></button>
        <div className="flex min-w-0 flex-1 items-center"><CommandPalette me={me} /></div>
        <div className="flex shrink-0 items-center gap-2 sm:gap-3"><ThemeToggle /><UserMenu me={me} /></div>
      </header>
      <main id="main-content" className="mx-auto w-full min-w-0 max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 xl:px-8">{children}</main>
    </div>
  </div>;
}
