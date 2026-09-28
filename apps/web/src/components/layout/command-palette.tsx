"use client";

import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Search, ArrowUpRight, X } from "lucide-react";
import Link from "next/link";
import type { Me } from "@/lib/api";
import { navigation, canAccess } from "./navigation";

/** Navigation only: no search endpoint, writes, or generation actions. */
export function CommandPalette({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const results = useRef<HTMLDivElement>(null);
  const items = navigation.filter(item => canAccess(me.roles, item) && item.label.toLowerCase().includes(query.toLowerCase().trim()));
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setOpen(value => !value);
      }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
  return <Dialog.Root open={open} onOpenChange={value => { setOpen(value); if (!value) setQuery(""); }}>
    <Dialog.Trigger className="flex h-11 w-11 items-center justify-center gap-3 rounded-md border border-border bg-surface-raised text-sm text-muted-foreground hover:border-border-strong md:w-full md:max-w-md md:justify-start md:px-4" aria-label="Search pages (Control or Command K)">
      <Search size={18} className="shrink-0" aria-hidden="true" /><span className="hidden flex-1 text-left md:inline">Search pages…</span><kbd className="hidden rounded-md border border-border bg-card px-2 py-0.5 text-xs md:inline">Ctrl K</kbd>
    </Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-40 bg-overlay" />
      <Dialog.Content className="fixed left-1/2 top-[15vh] z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 overflow-hidden rounded-panel border border-border bg-card shadow-xl">
        <Dialog.Title className="sr-only">Navigate your workspace</Dialog.Title>
        <Dialog.Description className="sr-only">Find pages available to your role. Use the arrow keys to move through results.</Dialog.Description>
        <div className="flex items-center gap-3 border-b border-border px-4 py-3"><Search size={18} className="text-muted-foreground" aria-hidden="true" />
          <input aria-label="Find a page" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "ArrowDown") { e.preventDefault(); results.current?.querySelector<HTMLAnchorElement>("a")?.focus(); } }} className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none" placeholder="Where would you like to go?" />
          <Dialog.Close className="rounded-md p-2 hover:bg-muted" aria-label="Close navigation search"><X size={16} /></Dialog.Close>
        </div>
        <div ref={results} className="max-h-[55vh] overflow-y-auto p-2" onKeyDown={e => {
          if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
          const links = Array.from(results.current?.querySelectorAll<HTMLAnchorElement>("a") ?? []);
          const index = links.indexOf(document.activeElement as HTMLAnchorElement);
          if (!links.length) return;
          e.preventDefault(); links[e.key === "Home" ? 0 : e.key === "End" ? links.length - 1 : (index + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length]?.focus();
        }}>
          <p className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Workspace pages</p>
          {items.length ? items.map(({ href, label, icon: Icon }) => <Link key={href} href={href} onClick={() => { setOpen(false); setQuery(""); }} className="flex items-center gap-3 rounded-md px-3 py-3 text-sm hover:bg-secondary focus:bg-secondary"><Icon size={17} className="text-primary" aria-hidden="true" /><span className="flex-1">{label}</span><ArrowUpRight size={14} className="text-muted-foreground" aria-hidden="true" /></Link>) : <p role="status" className="p-6 text-center text-sm text-muted-foreground">No matching pages available to your role.</p>}
        </div>
        <p className="border-t border-border bg-surface-raised px-4 py-3 text-xs text-muted-foreground">Navigation search · Esc to close · No records are searched</p>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
