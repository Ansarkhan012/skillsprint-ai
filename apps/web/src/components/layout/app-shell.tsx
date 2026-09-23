"use client";

import { useState } from "react";
import { Menu } from "lucide-react";
import type { Me } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sidebar } from "@/components/layout/sidebar";

export function AppShell({ me, children }: { me: Me; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className="min-h-screen lg:grid lg:grid-cols-[252px_minmax(0,1fr)]">
    <aside className="sticky top-0 hidden h-screen lg:block"><Sidebar me={me} /></aside>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogTitle className="sr-only">Navigation</DialogTitle><Sidebar me={me} onNavigate={() => setOpen(false)} /></DialogContent></Dialog>
    <div className="min-w-0">
      <header className="sticky top-0 z-20 flex h-18 items-center justify-between border-b border-border bg-card px-5 sm:px-8">
        <div className="flex items-center gap-3"><Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={21} /></Button><span className="text-sm font-semibold text-muted-foreground">SkillSprint AI <span className="mx-2 text-border">/</span> Workspace</span></div>
        <span className="hidden text-xs font-medium text-muted-foreground sm:block">Single organization workspace</span>
      </header>
      <main className="mx-auto w-full max-w-7xl px-5 py-7 sm:px-8 sm:py-9">{children}</main>
    </div>
  </div>;
}
