"use client";
import { useCallback, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import type { Me } from "@/lib/api";
import { canAuthor, canReadGeneration, humanize, postProduct, productRequest, type Employee, type JobRole, type Department } from "@/lib/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/shared/page-header";
import { DataTable, Empty, Fields, Loading, Modal, Pager, Problem, StateBadge, Technical, panel, selectStyle, useResource } from "./common";

export function Directory({ me, kind, employeeId }: { me: Me; kind: "employees" | "departments"; employeeId?: string }) {
  const [offset, setOffset] = useState(0);
  const [tab, setTab] = useState<"departments" | "roles">("departments");
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<"employees" | "departments" | "roles" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const lock = useRef(false);
  const [departmentId, setDepartmentId] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    const [departments, roles, employees] = await Promise.all([
      productRequest<Department[]>(`departments?limit=100&offset=${kind === "departments" && tab === "departments" ? offset : 0}`),
      productRequest<JobRole[]>(`roles?limit=100&offset=${kind === "departments" && tab === "roles" ? offset : 0}`),
      kind === "employees" ? (employeeId ? productRequest<Employee>(`employees/${employeeId}`).then((x) => [x]) : productRequest<Employee[]>(`employees?offset=${offset}&limit=30`)) : Promise.resolve([] as Employee[]),
    ]);
    return { departments, roles, employees };
  }, [kind, offset, tab, employeeId]);
  const state = useResource(load), data = state.data;
  const roleName = (id: string) => data?.roles.find((r) => r.id === id)?.name ?? "Role outside loaded directory";
  const deptName = (id: string | null) => data?.departments.find((d) => d.id === id)?.name ?? "No department in loaded directory";
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (lock.current || !form) return;
    lock.current = true; setSaving(true); setError(null);
    const values = new FormData(event.currentTarget);
    const string = (name: string) => String(values.get(name) ?? "").trim();
    const body = form === "employees" ? { employee_code: string("employee_code"), role_id: string("role_id"), department_id: string("department_id"), experience_level: string("experience_level"), joining_date: string("joining_date"), ...(string("location_code") ? { location_code: string("location_code") } : {}) }
      : { code: string("code"), name: string("name"), ...(form === "roles" ? { department_id: string("department_id") } : {}) };
    try { await postProduct(form, body); setForm(null); setNotice("Record created. The directory has been refreshed."); state.refresh(); }
    catch (e) { setError(e); }
    finally { lock.current = false; setSaving(false); }
  }
  return <div className="space-y-6"><PageHeader eyebrow="People" title={employeeId ? "Employee context" : kind === "employees" ? "Employees" : "Departments & job roles"} description={kind === "employees" ? "Authoritative employee context for onboarding. Job roles are assigned by your organization." : "Your organization structure and business roles. Application permissions are managed separately."}
    action={!employeeId && <div className="flex flex-wrap gap-2">{kind === "employees" && canAuthor(me) && <Button onClick={() => setForm("employees")}>Add employee</Button>}{kind === "departments" && <>{me.roles.includes("ADMIN") && <Button onClick={() => setForm("departments")}>Add department</Button>}{canAuthor(me) && <Button variant="outline" onClick={() => setForm("roles")}>Add job role</Button>}</>}</div>} />
    {notice && <p role="status" className="text-sm text-success">{notice}</p>}
    {state.loading ? <Loading /> : state.error ? <Problem error={state.error} retry={state.refresh} /> : data && <>
      {employeeId ? <>{data.employees.map((e) => <section key={e.id} className={`${panel} space-y-5`}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">{e.profiles?.display_name ?? e.employee_code}</h2><StateBadge value={e.training_status} /></div><Fields values={{ "Employee code": e.employee_code, "Department": deptName(e.department_id), "Job role": roleName(e.role_id), "Experience": humanize(e.experience_level), "Joining date": e.joining_date, "Location": e.location_code ?? "Not specified" }} /><p className="text-xs text-muted-foreground">{e.profile_id ? "Linked to an account profile." : "No account profile linked. This employee record does not create a sign-in account."}{e.employee_code.startsWith("P4D") ? " Controlled fictional test fixture." : ""}</p>{canReadGeneration(me) && <Button asChild><Link href={`/app/plans?employee=${e.id}`}>View onboarding history</Link></Button>}<Technical values={{ "Employee ID": e.id, "Role ID": e.role_id, "Department ID": e.department_id, "Manager employee ID": e.manager_employee_id }} /></section>)}<Button variant="outline" asChild><Link href="/app/employees">Back to employees</Link></Button></> : <>
        {kind === "departments" && <div className="flex gap-2" aria-label="Directory view">{(["departments", "roles"] as const).map((t) => <Button key={t} variant={tab === t ? "primary" : "outline"} aria-pressed={tab === t} onClick={() => { setTab(t); setOffset(0); setSearch(""); }}>{t === "roles" ? "Job roles" : "Departments"}</Button>)}</div>}
        <label className="block max-w-md text-sm font-medium">Search this page<Input className="mt-2" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Code or name" /></label>
        {kind === "employees" ? <>{!data.employees.length ? <Empty title="No employees on this page">Employee records visible to your account appear here. {canAuthor(me) ? "Use Add employee to record onboarding context." : "Contact your Training Manager if an employee is missing."}</Empty> : <DataTable headers={["Employee", "Department / role", "Experience", "Joining date", "Onboarding", "Details"]}>{data.employees.filter((e) => `${e.employee_code} ${e.profiles?.display_name ?? ""}`.toLowerCase().includes(search.toLowerCase())).map((e) => <tr key={e.id}><td><p className="font-semibold">{e.profiles?.display_name ?? e.employee_code}</p><p className="text-xs text-muted-foreground">{e.employee_code}{e.employee_code.startsWith("P4D") ? " · Fictional test fixture" : ""}</p></td><td>{deptName(e.department_id)}<p className="text-xs text-muted-foreground">{roleName(e.role_id)}</p></td><td>{humanize(e.experience_level)}</td><td className="whitespace-nowrap">{e.joining_date}</td><td><StateBadge value={e.training_status} /></td><td><Link className="font-semibold text-primary hover:underline" href={`/app/employees/${e.id}`}>View employee</Link></td></tr>)}</DataTable>}<Pager offset={offset} count={data.employees.length} more={data.employees.length === 30} change={setOffset} /></>
        : <>{(tab === "departments" ? data.departments : data.roles).length === 0 ? <Empty title={`No ${tab === "roles" ? "job roles" : "departments"} on this page`}>This directory contains organization records visible to your account.</Empty> : <DataTable headers={["Name", "Code", tab === "roles" ? "Department" : "Roles in loaded page", "Status"]}>{(tab === "departments" ? data.departments : data.roles).filter((d) => `${d.name} ${d.code}`.toLowerCase().includes(search.toLowerCase())).map((d) => <tr key={d.id}><td className="font-semibold">{d.name}</td><td>{d.code}</td><td>{tab === "roles" ? deptName((d as JobRole).department_id) : data.roles.filter((r) => r.department_id === d.id).map((r) => r.name).join(", ") || "No roles in loaded page"}</td><td><StateBadge value={d.status} /></td></tr>)}</DataTable>}<Pager offset={offset} count={data[tab].length} more={data[tab].length === 100} change={setOffset} limit={100} /></>}
        <p className="text-xs text-muted-foreground">Search applies to this page. Department and role labels use up to 100 readable records. Editing and deletion are not exposed by the current application API.</p>
      </>}
    </>}
    <Modal open={!!form} onOpenChange={(open) => { if (!saving && !open) { setForm(null); setError(null); } }} title={form === "employees" ? "Add employee" : form === "roles" ? "Add job role" : "Add department"} description="Creates one organization record through the authenticated application. No user account or onboarding plan is created.">
      <form onSubmit={create} className="space-y-4">{form === "employees" ? <>
        <label className="block text-sm font-medium">Employee code<Input name="employee_code" required maxLength={40} /></label>
        <label className="block text-sm font-medium">Department<select name="department_id" className={selectStyle} required value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}><option value="">Select department</option>{data?.departments.filter((d) => d.status === "ACTIVE").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label className="block text-sm font-medium">Job role<select key={departmentId} name="role_id" className={selectStyle} required defaultValue=""><option value="">Select job role</option>{data?.roles.filter((r) => r.status === "ACTIVE" && r.department_id === departmentId).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
        <label className="block text-sm font-medium">Experience<select name="experience_level" className={selectStyle}><option value="BEGINNER">Beginner</option><option value="INTERMEDIATE">Intermediate</option><option value="ADVANCED">Advanced</option></select></label>
        <label className="block text-sm font-medium">Joining date<Input type="date" name="joining_date" required /></label><label className="block text-sm font-medium">Location code (optional)<Input name="location_code" /></label>
      </> : <><label className="block text-sm font-medium">Code<Input name="code" required pattern="[A-Z0-9_-]{2,32}" maxLength={32} /><span className="text-xs text-muted-foreground">2–32 uppercase letters, numbers, hyphens or underscores.</span></label><label className="block text-sm font-medium">Name<Input name="name" required maxLength={160} /></label>{form === "roles" && <label className="block text-sm font-medium">Department<select name="department_id" className={selectStyle} required><option value="">Select department</option>{data?.departments.filter((d) => d.status === "ACTIVE").map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}</>}
        {!!error && <Problem error={error} />}<Button type="submit" disabled={saving || !data}>{saving ? "Saving…" : "Create record"}</Button>
      </form>
    </Modal>
  </div>;
}
