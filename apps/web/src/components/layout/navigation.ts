import { Building2, ClipboardList, FileText, FlaskConical, LayoutDashboard, LibraryBig, ScrollText, Settings, ShieldCheck, Users, UserRoundCog } from "lucide-react";
import type { AppRole } from "@/lib/api";

export const navigation = [
  { label: "Dashboard", href: "/app/dashboard", icon: LayoutDashboard, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER", "EMPLOYEE"] },
  { label: "Documents", href: "/app/documents", icon: FileText, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER"] },
  { label: "Requirement Matrix", href: "/app/requirements", icon: ClipboardList, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER"] },
  { label: "Phase 4D Test", href: "/app/phase4d-test", icon: FlaskConical, roles: ["ADMIN", "TRAINING_MANAGER"] },
  { label: "Onboarding Plans", href: "/app/plans", icon: LibraryBig, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER", "EMPLOYEE"] },
  { label: "Employees", href: "/app/employees", icon: Users, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER"] },
  { label: "Departments", href: "/app/departments", icon: Building2, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER"] },
  { label: "Reports", href: "/app/reports", icon: ScrollText, roles: ["ADMIN", "TRAINING_MANAGER", "REVIEWER", "MANAGER"] },
  { label: "Audit Logs", href: "/app/audit", icon: ShieldCheck, roles: ["ADMIN"] },
  { label: "User Management", href: "/app/users", icon: UserRoundCog, roles: ["ADMIN"] },
  { label: "System Settings", href: "/app/settings", icon: Settings, roles: ["ADMIN"] },
] as const satisfies ReadonlyArray<{ label: string; href: string; icon: typeof LayoutDashboard; roles: readonly AppRole[] }>;

export function canAccess(roles: AppRole[], item: (typeof navigation)[number]) {
  return roles.some((role) => (item.roles as readonly AppRole[]).includes(role));
}
