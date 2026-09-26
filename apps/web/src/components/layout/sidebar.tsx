"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenCheck } from "lucide-react";
import type { Me } from "@/lib/api";
import { cn } from "@/lib/utils";
import { navigation, canAccess } from "@/components/layout/navigation";
import { UserMenu } from "@/components/layout/user-menu";

export function SidebarNavItem({ label, href, icon: Icon, onNavigate }: { label: string; href: string; icon: typeof BookOpenCheck; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(href + "/");
  return <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
    className={cn("flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-sidebar-muted transition-colors hover:bg-white/10 hover:text-sidebar-foreground", active && "bg-white/12 text-sidebar-foreground")}
  ><Icon size={18} aria-hidden="true" /><span>{label}</span></Link>;
}

export function Sidebar({ me, onNavigate }: { me: Me; onNavigate?: () => void }) {
  const general = navigation.filter((item) => !["Audit Logs", "Settings"].includes(item.label) && canAccess(me.roles, item));
  const admin = navigation.filter((item) => ["Audit Logs", "Settings"].includes(item.label) && canAccess(me.roles, item));
  return <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
    <div className="flex h-18 items-center gap-3 border-b border-white/10 px-5">
      <div className="rounded-md bg-primary p-2 text-primary-foreground"><BookOpenCheck size={21} aria-hidden="true" /></div>
      <div><p className="text-base font-bold tracking-tight">SkillSprint</p><p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-sidebar-muted">Training intelligence</p></div>
    </div>
    <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-3 py-5">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">Workspace</p>
      <div className="space-y-1">{general.map((item) => <SidebarNavItem key={item.href} {...item} onNavigate={onNavigate} />)}</div>
      {admin.length > 0 && <><p className="px-3 pb-2 pt-7 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">Administration</p><div className="space-y-1">{admin.map((item) => <SidebarNavItem key={item.href} {...item} onNavigate={onNavigate} />)}</div></>}
    </nav>
    <UserMenu me={me} />
  </div>;
}
