"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenCheck, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { Me } from "@/lib/api";
import { cn } from "@/lib/utils";
import { navigation, canAccess } from "@/components/layout/navigation";

const groups = [
  { title: "Overview", routes: ["/app/dashboard"] },
  { title: "Documents", routes: ["/app/documents", "/app/requirements"] },
  { title: "Roles & Employees", routes: ["/app/employees", "/app/departments"] },
  { title: "Plans & Validation", routes: ["/app/plans", "/app/reviews"] },
  { title: "Reports", routes: ["/app/reports", "/app/audit"] },
];

export function SidebarNavItem({ label, href, icon: Icon, onNavigate, collapsed = false }: { label: string; href: string; icon: typeof BookOpenCheck; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(href + "/");
  return <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} aria-label={collapsed ? label : undefined} title={collapsed ? label : undefined}
    className={cn("group relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
      active && "bg-primary-soft text-primary hover:bg-primary-soft hover:text-primary", collapsed && "justify-center px-0")}
  ><Icon size={20} className="shrink-0" aria-hidden="true" /><span className={collapsed ? "sr-only" : "truncate"}>{label}</span>{collapsed && <span aria-hidden="true" className="pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-md bg-foreground px-3 py-2 text-xs text-background shadow-lg group-hover:block group-focus-visible:block">{label}</span>}</Link>;
}

export function Sidebar({ me, onNavigate, collapsed = false, onToggle }: { me: Me; onNavigate?: () => void; collapsed?: boolean; onToggle?: () => void }) {
  return <div className="flex h-full flex-col border-r border-border bg-sidebar text-sidebar-foreground">
    <div className={cn("flex h-18 shrink-0 items-center gap-3", collapsed ? "justify-center px-2" : "justify-between px-6")}>
      <Link href="/app/dashboard" onClick={onNavigate} className="flex min-w-0 items-center gap-2.5" aria-label="SkillSprint AI home">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-solid text-primary-foreground"><BookOpenCheck size={19} aria-hidden="true" /></span>
        {!collapsed && <span className="truncate text-lg font-semibold tracking-tight">SkillSprint <span className="text-primary">AI</span></span>}
      </Link>
      {onToggle && !collapsed && <button type="button" onClick={onToggle} aria-label="Collapse sidebar" aria-expanded="true" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"><PanelLeftClose size={20} /></button>}
    </div>
    {onToggle && collapsed && <button type="button" onClick={onToggle} aria-label="Expand sidebar" aria-expanded="false" className="mx-auto mb-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"><PanelLeftOpen size={20} /></button>}
    <nav aria-label="Main navigation" className={cn("min-h-0 flex-1 px-4 pb-6 pt-2", collapsed ? "overflow-visible px-3" : "overflow-y-auto")}>
      {groups.map(group => {
        const items = navigation.filter(item => group.routes.includes(item.href) && canAccess(me.roles, item));
        return items.length > 0 && <div key={group.title} className="mb-6 last:mb-0">
          <p className={collapsed ? "sr-only" : "sidebar-label px-3 pb-2 text-muted-foreground"}>{group.title}</p>
          <div className="space-y-1">{items.map(item => <SidebarNavItem key={item.href} {...item} collapsed={collapsed} onNavigate={onNavigate} />)}</div>
        </div>;
      })}
    </nav>
  </div>;
}
