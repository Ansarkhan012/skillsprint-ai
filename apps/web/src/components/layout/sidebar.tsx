"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenCheck } from "lucide-react";
import type { Me } from "@/lib/api";
import { cn } from "@/lib/utils";
import { navigation, canAccess } from "@/components/layout/navigation";
import { UserMenu } from "@/components/layout/user-menu";

export function SidebarNavItem({ label, href, icon: Icon, onNavigate, collapsed = false }: { label: string; href: string; icon: typeof BookOpenCheck; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(href + "/");
  return <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} aria-label={collapsed ? label : undefined} title={collapsed ? label : undefined}
    className={cn("group relative flex items-center gap-3 rounded-sm border-l-2 border-transparent px-3 py-2.5 text-[13px] font-medium text-sidebar-muted transition-colors hover:bg-white/7 hover:text-sidebar-foreground", active && "border-l-[#d6ddcb] bg-white/10 text-sidebar-foreground", collapsed && "justify-center")}
  ><Icon size={18} className="shrink-0" aria-hidden="true" /><span className={collapsed ? "sr-only" : "truncate"}>{label}</span>{collapsed && <span aria-hidden="true" className="pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-md bg-foreground px-3 py-2 text-xs text-white shadow-lg group-hover:block group-focus-visible:block">{label}</span>}</Link>;
}

export function Sidebar({ me, onNavigate, collapsed = false }: { me: Me; onNavigate?: () => void; collapsed?: boolean }) {
  const groups = [
    { title: "Overview", routes: ["/app/dashboard"] },
    { title: "Workspace", routes: ["/app/employees", "/app/documents", "/app/requirements", "/app/plans"] },
    { title: "Governance", routes: ["/app/reviews", "/app/reports", "/app/audit"] },
    { title: "Administration", routes: ["/app/departments", "/app/settings"] },
  ];
  return <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
    <div className={`flex h-16 shrink-0 items-center gap-3 border-b border-white/10 ${collapsed ? "justify-center px-2" : "px-5"}`}>
      <div className="rounded-sm border border-white/25 p-2 text-sidebar-foreground"><BookOpenCheck size={20} aria-hidden="true" /></div>
      {!collapsed && <div><p className="text-[15px] font-semibold tracking-tight">SkillSprint <span className="text-sidebar-muted">AI</span></p><p className="text-[9px] font-medium uppercase tracking-[0.16em] text-sidebar-muted">Onboarding intelligence</p></div>}
    </div>
    <nav aria-label="Main navigation" className={`min-h-0 flex-1 px-3 py-4 ${collapsed ? "overflow-visible" : "overflow-y-auto"}`}>
      {groups.map(group => { const items = navigation.filter(item => group.routes.includes(item.href) && canAccess(me.roles, item)); return items.length > 0 && <div key={group.title} className="mb-5 last:mb-0"><p className={collapsed ? "sr-only" : "sidebar-label px-3 pb-2 text-sidebar-muted"}>{group.title}</p><div className="space-y-0.5">{items.map(item => <SidebarNavItem key={item.href} {...item} collapsed={collapsed} onNavigate={onNavigate} />)}</div></div>; })}
    </nav>
    <UserMenu me={me} compact={collapsed} />
  </div>;
}
