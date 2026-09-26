import type { Me } from "@/lib/api";
import { Directory } from "./directory";
import { Plans } from "./plans";
import { Reviews } from "./reviews";
import { AuditActivity, Overview } from "./overview";
import { Settings } from "./settings";
export function ProductWorkspace({ section, me, id, employeeFilter }: { section: string; me: Me; id?: string; employeeFilter?: string }) {
  if (section === "employees" || section === "departments") return <Directory me={me} kind={section} employeeId={id} />;
  if (section === "plans") return <Plans me={me} runId={id} employeeFilter={employeeFilter} />;
  if (section === "reviews") return <Reviews me={me} validationId={id} />;
  if (section === "settings") return <Settings me={me} />;
  if (section === "audit") return <AuditActivity />;
  return <Overview me={me} reports={section === "reports"} />;
}
