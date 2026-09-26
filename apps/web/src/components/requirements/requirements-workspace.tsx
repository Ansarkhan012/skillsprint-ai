"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ClipboardList, FileCheck2, Plus, Search } from "lucide-react";
import type { Me } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/shared/page-header";
import { timingLabel } from "@/lib/product";
import { type Config, type GroundTruth, type Matrix, type MatrixSummary, type Page, type Requirement, type SourceChunk, type SourceVersion,
  buildCandidatePayload, buildDraftRevisionReplacement, buildStructuredTiming, jsonRequest, locator, requirementCategories, rrmMessage, rrmRequest, timingFields,
  type TimingField, type TimingSelection } from "@/lib/rrm";

type JobRole = { id: string; code: string; name: string };
type Department = { id: string; code: string; name: string };
type Props = { me: Me; roles: JobRole[]; departments: Department[]; initialRoleId?: string };
type Pane = "candidates" | "matrix" | "ground-truth";

const selectClass = "h-10 w-full rounded-md border border-border bg-card px-3 text-sm";
const boxClass = "rounded-md border border-border bg-card p-5 shadow-panel";
const emptyPage = <T,>(): Page<T> => ({ items: [], offset: 0, limit: 50, has_more: false });

function Status({ value }: { value: string }) {
  const tone = value === "APPROVED" ? "success" : value === "SUBMITTED" ? "warning"
    : value === "REJECTED" || value === "SUPERSEDED" ? "destructive" : "neutral";
  return <Badge tone={tone}>{value.replaceAll("_", " ")}</Badge>;
}

function EvidenceBlock({ requirement }: { requirement: Requirement }) {
  return <div className="mt-3 space-y-2">
    {(requirement.evidence ?? []).map((item) => <div key={item.chunk?.id ?? item.chunk_id} className="rounded-md border border-primary/20 bg-primary/5 p-3 text-sm">
      <div className="font-semibold text-primary">{item.document ? `${item.document.document_code} · ${item.document.title} · ${item.version?.version_label}` : "Historical source"}
        {!item.current_eligible && <span className="ml-2 text-destructive">Not currently eligible</span>}
      </div>
      {item.chunk && <><div className="mt-1 text-xs text-muted-foreground">{item.chunk.heading ? `${item.chunk.heading} · ` : ""}{locator(item.chunk.source_location)}</div>
        <details className="mt-2"><summary className="cursor-pointer text-primary">Exact source excerpt</summary><p className="mt-2 whitespace-pre-wrap">{item.chunk.content}</p></details></>}
    </div>)}
  </div>;
}

export function RequirementsWorkspace({ me, roles, departments, initialRoleId }: Props) {
  const canAuthor = me.roles.includes("ADMIN") || me.roles.includes("TRAINING_MANAGER");
  const canReview = me.roles.includes("ADMIN") || me.roles.includes("REVIEWER");
  const isAdmin = me.roles.includes("ADMIN");
  const [pane, setPane] = useState<Pane>("matrix");
  const [roleId, setRoleId] = useState(roles.find((role) => role.id === initialRoleId)?.id ?? roles[0]?.id ?? "");
  const [candidatePage, setCandidatePage] = useState<Page<Requirement>>(emptyPage());
  const [candidateReady, setCandidateReady] = useState(false);
  const [search, setSearch] = useState("");
  const [mandatoryFilter, setMandatoryFilter] = useState("ALL");
  const [matrices, setMatrices] = useState<Page<MatrixSummary>>(emptyPage());
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [sourcePage, setSourcePage] = useState<Page<SourceVersion>>(emptyPage());
  const [sourceId, setSourceId] = useState("");
  const [chunkPage, setChunkPage] = useState<Page<SourceChunk>>(emptyPage());
  const [selectedChunks, setSelectedChunks] = useState<string[]>([]);
  const [showCandidate, setShowCandidate] = useState(false);
  const [revisionOf, setRevisionOf] = useState<Requirement | null>(null);
  const [createdRevision, setCreatedRevision] = useState<{ predecessor: Requirement; successorId: string } | null>(null);
  const [structureTiming, setStructureTiming] = useState(false);
  const [timingEvidence, setTimingEvidence] = useState<Partial<Record<TimingField, TimingSelection>>>({});
  const [issueReviewAcknowledged, setIssueReviewAcknowledged] = useState(false);
  const [reviewContext, setReviewContext] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [configDocuments, setConfigDocuments] = useState<Record<string, string>>({});
  const [groundTruth, setGroundTruth] = useState<GroundTruth | null>(null);
  const [groundError, setGroundError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [adminOverride, setAdminOverride] = useState(false);
  const [dependentId, setDependentId] = useState("");
  const [prerequisiteId, setPrerequisiteId] = useState("");
  const loaded = useRef({ candidates: false, configs: false, sources: false, matrixRole: "" });

  const loadCandidates = useCallback(async (offset = 0, query = search, filter = mandatoryFilter) => {
    const params = new URLSearchParams({ offset: String(offset), limit: "50" });
    if (query.trim()) params.set("search", query.trim());
    if (filter !== "ALL") params.set("mandatory", filter);
    setCandidatePage(await rrmRequest<Page<Requirement>>(`requirements?${params}`));
    loaded.current.candidates = true;
    setCandidateReady(true);
  }, [search, mandatoryFilter]);

  const loadMatrices = useCallback(async (selectedRole = roleId, offset = 0) => {
    if (!selectedRole) return;
    setMatrices(await rrmRequest<Page<MatrixSummary>>(`roles/${selectedRole}/matrices?offset=${offset}&limit=50`));
    loaded.current.matrixRole = selectedRole;
  }, [roleId]);

  const loadMatrix = useCallback(async (id: string) => setMatrix(await rrmRequest<Matrix>(`matrices/${id}`)), []);

  useEffect(() => {
    if (pane !== "matrix" || !roleId) return;
    const needsMatrix = loaded.current.matrixRole !== roleId;
    const needsConfigs = !loaded.current.configs;
    if (!needsMatrix && !needsConfigs) return;
    if (needsMatrix) loaded.current.matrixRole = roleId;
    if (needsConfigs) loaded.current.configs = true;
    setLoading(true);
    Promise.all([
      needsMatrix ? rrmRequest<Page<MatrixSummary>>(`roles/${roleId}/matrices?limit=50`) : Promise.resolve(null),
      needsConfigs ? rrmRequest<Config[]>("rrm/configs") : Promise.resolve(null),
    ]).then(([revisions, configuration]) => {
      if (revisions && loaded.current.matrixRole === roleId) {
        setMatrices(revisions); setMatrix(null); setGroundTruth(null); setGroundError("");
      }
      if (configuration) setConfigs(configuration);
    }).catch((cause) => {
      if (needsMatrix && loaded.current.matrixRole === roleId) loaded.current.matrixRole = "";
      if (needsConfigs) loaded.current.configs = false;
      setError(rrmMessage(cause));
    }).finally(() => setLoading(false));
  }, [pane, roleId]);

  useEffect(() => {
    if (pane !== "candidates" || loaded.current.candidates) return;
    loaded.current.candidates = true;
    setLoading(true);
    rrmRequest<Page<Requirement>>("requirements?limit=50")
      .then((result) => { setCandidatePage(result); setCandidateReady(true); })
      .catch((cause) => { loaded.current.candidates = false; setError(rrmMessage(cause)); })
      .finally(() => setLoading(false));
  }, [pane]);

  useEffect(() => {
    if (!(showCandidate || showConfig) || loaded.current.sources) return;
    loaded.current.sources = true;
    rrmRequest<Page<SourceVersion>>("rrm/evidence?limit=30")
      .then(setSourcePage)
      .catch((cause) => { loaded.current.sources = false; setError(rrmMessage(cause)); });
  }, [showCandidate, showConfig]);

  async function loadSource(versionId: string) {
    setSourceId(versionId); setSelectedChunks([]); setChunkPage(emptyPage());
    if (!versionId) return;
    try { setChunkPage(await rrmRequest<Page<SourceChunk>>(`rrm/evidence/${versionId}/chunks?limit=50`)); }
    catch (cause) { setError(rrmMessage(cause)); }
  }

  async function run(operation: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); setNotice(success); }
    catch (cause) { setError(rrmMessage(cause)); }
    finally { setBusy(false); }
  }

  async function createCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const structured = structureTiming ? buildStructuredTiming(String(form.get("timing_text") ?? "").trim(), {
        trigger: String(form.get("timing_trigger") ?? ""), relation: String(form.get("timing_relation") ?? "") as "WITHIN",
        value: Number(form.get("timing_value")), unit: String(form.get("timing_unit") ?? "") as "DAY",
        calendar_basis: String(form.get("timing_calendar_basis") ?? "") as "CALENDAR",
        evidence: timingEvidence as Record<TimingField, TimingSelection>,
      }, chunkPage.items, selectedChunks) : undefined;
      const payload = buildCandidatePayload({
        code: String(form.get("code") ?? ""), statement: String(form.get("statement") ?? ""),
        category: String(form.get("category") ?? ""), mandatory: form.get("mandatory") === "mandatory",
        mustType: String(form.get("must_type") ?? ""), roleId: String(form.get("scope_role") ?? ""),
        departmentId: String(form.get("scope_department") ?? ""), timingText: String(form.get("timing_text") ?? ""),
      }, selectedChunks, revisionOf, structured);
      const result = await jsonRequest<{ id: string }>("requirements", "POST", payload);
      if (revisionOf) setCreatedRevision({ predecessor: revisionOf, successorId: result.id });
      setShowCandidate(false); setRevisionOf(null); setSelectedChunks([]); setSourceId(""); setChunkPage(emptyPage()); setStructureTiming(false); setTimingEvidence({});
      await loadCandidates(0);
    }, revisionOf ? "New immutable revision created. The old revision remains in history and in any draft until you explicitly replace it. Ambiguous timing still blocks submission."
      : "Source-backed candidate created. Ambiguous timing must be resolved before matrix submission.");
  }

  async function openRevision(candidate: Requirement) {
    if (!canAuthor) return;
    await run(async () => {
      const detail = await rrmRequest<Requirement>(`requirements/${candidate.id}`);
      if (detail.scopes?.length !== 1 || detail.timing.state === "STRUCTURED") throw new Error("REVISION_REQUIRES_EXPLICIT_REVIEW");
      setRevisionOf(detail); setShowCandidate(true); setSelectedChunks([]); setSourceId(""); setChunkPage(emptyPage()); setStructureTiming(false); setTimingEvidence({}); setPane("candidates");
    }, "Select fresh exact evidence for the new revision. The original remains unchanged.");
  }

  async function prepareDraftReplacement(candidate: Requirement) {
    if (!canAuthor) return;
    await run(async () => {
      const detail = await rrmRequest<Requirement>(`requirements/${candidate.id}`);
      if (!detail.predecessor_id) throw new Error("INVALID_CANDIDATE_REVISION");
      const predecessor = await rrmRequest<Requirement>(`requirements/${detail.predecessor_id}`);
      if (detail.requirement_code !== predecessor.requirement_code || detail.revision !== predecessor.revision + 1)
        throw new Error("INVALID_CANDIDATE_REVISION");
      setCreatedRevision({ predecessor, successorId: detail.id }); setIssueReviewAcknowledged(false); setPane("matrix");
    }, "Select the owned DRAFT matrix containing the old revision, then review the atomic replacement.");
  }

  async function replaceDraftRevision() {
    if (!matrix || !createdRevision || !canAuthor) return;
    await run(async () => {
      const freshMatrix = await rrmRequest<Matrix>(`matrices/${matrix.id}`);
      const successor = await rrmRequest<Requirement>(`requirements/${createdRevision.successorId}`);
      const payload = buildDraftRevisionReplacement(freshMatrix, me.id, createdRevision.predecessor, successor, issueReviewAcknowledged);
      await jsonRequest(`matrices/${freshMatrix.id}`, "PATCH", payload);
      await loadMatrix(freshMatrix.id); await loadMatrices(); setCreatedRevision(null); setIssueReviewAcknowledged(false);
    }, "Draft updated atomically: corrected revision replaces the old entry. The old candidate remains in history.");
  }

  async function createConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const latest = configs[0];
      await jsonRequest("rrm/configs", "POST", {
        config: { ranks: { DEPARTMENT_SOP: 40, COMPANY_POLICY: 30, FAQ: 20, INFORMAL_GUIDANCE: 10 },
          document_classes: { ...Object.fromEntries((latest?.documents ?? []).map((item) => [item.document_id, item.authority_class])),
            ...Object.fromEntries(Object.entries(configDocuments).filter(([, value]) => value)) } },
        reason: String(form.get("reason")), predecessor_id: latest?.id ?? null,
      });
      setConfigs(await rrmRequest<Config[]>("rrm/configs")); setShowConfig(false);
    }, "Authority configuration saved. Review document mappings before using it.");
  }

  async function createMatrix() {
    if (!roleId || !configs[0]) return;
    await run(async () => {
      const previous = matrices.items[0];
      const result = await jsonRequest<{ id: string }>(`roles/${roleId}/matrices`, "POST", {
        config_id: configs[0].id, predecessor_id: previous?.id ?? null,
      });
      await loadMatrices(); await loadMatrix(result.id);
    }, "Matrix draft created.");
  }

  async function saveDraft(ids: string[], dependencies = matrix?.dependencies ?? []) {
    if (!matrix || !ids.length) { setError("A draft needs at least one requirement."); return; }
    await run(async () => {
      await jsonRequest(`matrices/${matrix.id}`, "PATCH", {
        expected_version: matrix.lock_version,
        entries: ids.map((id, sequence) => {
          const existing = matrix.entries.find((entry) => entry.requirement_id === id);
          return { ...existing, requirement_id: id, sequence };
        }),
        dependencies: dependencies.filter((edge) => ids.includes(edge.dependent_id) && ids.includes(edge.prerequisite_id)),
        reason: "Updated the role requirement draft after source review.",
      });
      await loadMatrix(matrix.id); await loadMatrices();
    }, "Draft saved with a new immutable edit.");
  }

  async function transition(action: "submit" | "approve" | "reject") {
    if (!matrix) return;
    if (!window.confirm(`Confirm ${action} for matrix revision ${matrix.revision}?`)) return;
    await run(async () => {
      await jsonRequest(`matrices/${matrix.id}/${action}`, "POST", {
        expected_version: matrix.lock_version, reason: decisionReason || null,
        admin_override: action !== "submit" && adminOverride,
      });
      await loadMatrix(matrix.id); await loadMatrices(); setDecisionReason(""); setAdminOverride(false);
    }, `Matrix ${action === "submit" ? "submitted" : action === "approve" ? "approved" : "rejected"}.`);
  }

  async function loadGroundTruth() {
    if (!roleId) return;
    setGroundError(""); setGroundTruth(null); setBusy(true);
    try { setGroundTruth(await rrmRequest<GroundTruth>(`roles/${roleId}/ground-truth`)); }
    catch (cause) { setGroundError(rrmMessage(cause)); }
    finally { setBusy(false); }
  }

  const selectedRole = roles.find((role) => role.id === roleId);
  const isDraftOwner = Boolean(matrix && matrix.status === "DRAFT" && matrix.created_by === me.id && canAuthor);
  const canRaiseDraftIssue = Boolean(matrix && matrix.status === "DRAFT" && canAuthor);
  const canDecide = Boolean(matrix && matrix.status === "SUBMITTED" && canReview);
  const contributed = Boolean(matrix && (matrix.created_by === me.id || matrix.submitted_by === me.id
    || Object.values(matrix.requirements).some((requirement) => requirement.created_by === me.id)));
  const included = useMemo(() => new Set(matrix?.entries.map((entry) => entry.requirement_id) ?? []), [matrix]);
  const submittedCount = matrices.items.filter((item) => item.status === "SUBMITTED").length;

  return <div className="space-y-7">
    <PageHeader eyebrow="Approved ground truth" title="Requirement Matrix"
      description="Turn approved document evidence into independently reviewed role requirements." />
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="rounded-md border border-success/30 bg-success/5 p-3 text-sm text-success">{notice}</p>}
    <div className="grid gap-3 sm:grid-cols-3">
      <div className={boxClass}><p className="text-xs uppercase text-muted-foreground">Candidates on page</p><p className="mt-2 text-2xl font-semibold">{candidateReady ? candidatePage.items.length : "—"}</p></div>
      <div className={boxClass}><p className="text-xs uppercase text-muted-foreground">Selected role revisions</p><p className="mt-2 text-2xl font-semibold">{matrices.items.length}</p></div>
      <div className={boxClass}><p className="text-xs uppercase text-muted-foreground">Awaiting review</p><p className="mt-2 text-2xl font-semibold">{submittedCount}</p></div>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-64 space-y-1 text-sm font-semibold">Job role
        <select className={selectClass} value={roleId} onChange={(event) => { setRoleId(event.target.value); setMatrix(null); setGroundTruth(null); }}>
          {roles.map((role) => <option key={role.id} value={role.id}>{role.code} · {role.name}</option>)}
        </select>
      </label>
      <nav className="flex flex-wrap gap-2" aria-label="Requirement workspace">
        {(["matrix", "candidates", "ground-truth"] as const).map((tab) => <Button key={tab} variant={pane === tab ? "primary" : "outline"} onClick={() => setPane(tab)}>
          {tab === "matrix" ? "Role matrices" : tab === "candidates" ? "Candidates" : "Ground truth"}
        </Button>)}
      </nav>
    </div>
    {loading && <p role="status">Loading requirement evidence…</p>}

    {pane === "candidates" && <div className="space-y-4">
      <div className={`${boxClass} flex flex-wrap items-end justify-between gap-3`}>
        <div><h2 className="flex items-center gap-2 text-lg font-semibold"><FileCheck2 size={18} />Requirement candidates</h2>
          <p className="text-sm text-muted-foreground">Each candidate is an immutable revision backed by exact approved chunks.</p></div>
        {canAuthor && <Button onClick={() => { setShowCandidate(!showCandidate); setRevisionOf(null); setSelectedChunks([]); setSourceId(""); setChunkPage(emptyPage()); setStructureTiming(false); setTimingEvidence({}); }}><Plus size={16} />{showCandidate ? "Close form" : "Create candidate"}</Button>}
      </div>
      {createdRevision && <div role="status" className={boxClass}><p className="font-semibold">Corrected revision created for {createdRevision.predecessor.requirement_code}.</p>
        <p className="mt-1 text-sm">Revision r{createdRevision.predecessor.revision} remains immutable and stays in any draft until you explicitly replace it. Submitted and approved matrices are never changed here.</p>
        <Button className="mt-3" variant="outline" onClick={() => setPane("matrix")}>Open role matrices for draft replacement</Button></div>}
      {showCandidate && canAuthor && <section className={boxClass} aria-label={revisionOf ? "Revise requirement candidate" : "Create requirement candidate"}>
        <h3 className="text-lg font-semibold">{revisionOf ? `Revise ${revisionOf.requirement_code} · r${revisionOf.revision}` : "Source-backed candidate"}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{revisionOf ? "This creates a new immutable revision. The old candidate and its evidence remain in history; no matrix changes automatically. Re-select every exact source chunk." : "Only approved, parsed, current-effective versions appear below. Select exact chunks; never type a source ID."}</p>
        {revisionOf && <div className="mt-3 rounded-md border border-border p-3 text-sm"><strong>Previous evidence (read-only)</strong><EvidenceBlock requirement={revisionOf} /></div>}
        <label className="mt-4 block space-y-1 text-sm font-semibold">Approved source version
          <select className={selectClass} value={sourceId} onChange={(event) => void loadSource(event.target.value)}>
            <option value="">Choose a document/version</option>
            {sourcePage.items.map((source) => <option key={source.id} value={source.id}>{source.document.document_code} · {source.document.title} · {source.version_label}</option>)}
          </select>
        </label>
        {sourcePage.has_more && <Button className="mt-2" variant="outline" onClick={() => void run(async () => {
          const next = await rrmRequest<Page<SourceVersion>>(`rrm/evidence?offset=${sourcePage.offset + sourcePage.limit}&limit=30`);
          setSourcePage({ ...next, items: [...sourcePage.items, ...next.items] });
        }, "More sources loaded.")}>More sources</Button>}
        {sourceId && <div className="mt-4 space-y-2"><p className="text-sm font-semibold">Exact source chunks</p>
          {chunkPage.items.length === 0 && <p className="text-sm text-muted-foreground">No selectable text chunks on this page.</p>}
          {chunkPage.items.map((chunk) => <label key={chunk.id} className="flex gap-3 rounded-md border border-border p-3 text-sm">
            <input type="checkbox" checked={selectedChunks.includes(chunk.id)} onChange={(event) => setSelectedChunks(event.target.checked
              ? [...selectedChunks, chunk.id] : selectedChunks.filter((id) => id !== chunk.id))} />
            <span><span className="block font-semibold">{chunk.heading || chunk.section_path || "Source excerpt"} · {locator(chunk.source_location)}</span>
              <span className="mt-1 block whitespace-pre-wrap">{chunk.content}</span></span>
          </label>)}
          {chunkPage.has_more && <Button variant="outline" onClick={() => void run(async () => {
            const next = await rrmRequest<Page<SourceChunk>>(`rrm/evidence/${sourceId}/chunks?offset=${chunkPage.offset + chunkPage.limit}&limit=50`);
            setChunkPage({ ...next, items: [...chunkPage.items, ...next.items] });
          }, "More chunks loaded.")}>More chunks</Button>}
        </div>}
        <form key={revisionOf?.id ?? "new"} onSubmit={createCandidate} className="mt-5 grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm font-semibold">Code<Input name="code" required pattern="[A-Z][A-Z0-9_-]{1,63}" placeholder="SECURITY_TRAINING" defaultValue={revisionOf?.requirement_code ?? ""} readOnly={Boolean(revisionOf)} /></label>
          <label className="space-y-1 text-sm font-semibold">Category
            <select name="category" className={selectClass} required defaultValue={revisionOf?.category ?? ""}>
              <option value="" disabled>Choose category</option>
              {requirementCategories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              {revisionOf && !requirementCategories.some((item) => item.value === revisionOf.category) && <option value={revisionOf.category}>{revisionOf.category.replaceAll("_", " ").toLowerCase()}</option>}
            </select>
          </label>
          <label className="space-y-1 text-sm font-semibold md:col-span-2">Requirement statement<Input name="statement" required maxLength={4000} placeholder="Complete security awareness training" defaultValue={revisionOf?.statement ?? ""} /></label>
          <label className="space-y-1 text-sm font-semibold">Obligation
            <select name="mandatory" className={selectClass} defaultValue={revisionOf?.mandatory === false ? "optional" : "mandatory"}><option value="mandatory">Mandatory</option><option value="optional">Optional</option></select>
          </label>
          <label className="space-y-1 text-sm font-semibold">Mandatory type
            <select name="must_type" className={selectClass} defaultValue={revisionOf?.mandatory ? revisionOf.requirement_type : "MUST_COMPLETE"}><option value="MUST_COMPLETE">Must complete</option><option value="MUST_KNOW">Must know</option><option value="MUST_DEMONSTRATE">Must demonstrate</option><option value="MUST_ACKNOWLEDGE">Must acknowledge</option></select>
          </label>
          <label className="space-y-1 text-sm font-semibold">Applies to role
            <select name="scope_role" className={selectClass} defaultValue={revisionOf ? revisionOf.scopes?.[0]?.role_id ?? "" : roleId}><option value="">All roles</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select>
          </label>
          <label className="space-y-1 text-sm font-semibold">Department
            <select name="scope_department" className={selectClass} defaultValue={revisionOf?.scopes?.[0]?.department_id ?? ""}><option value="">All departments</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select>
          </label>
          <label className="space-y-1 text-sm font-semibold md:col-span-2">Original timing text (optional)
            <Input name="timing_text" maxLength={4000} placeholder="Within 7 days" defaultValue={typeof revisionOf?.timing.original_text === "string" ? revisionOf.timing.original_text : ""} />
            <span className="block text-xs font-normal text-muted-foreground">Timing text is retained verbatim as ambiguous until separately structured with exact span evidence. Ambiguous timing blocks submission.</span>
          </label>
          {revisionOf?.timing.state === "AMBIGUOUS" && <div className="md:col-span-2 space-y-3 rounded-md border border-warning/30 p-3 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={structureTiming} onChange={(event) => setStructureTiming(event.target.checked)} />Structure timing only when approved evidence explicitly states every field</label>
            {structureTiming && <><p>Do not infer a trigger from the original phrase. Each value needs an exact quoted span in a selected source chunk; independent review remains required.</p>
              <label className="block">Trigger named by source<Input name="timing_trigger" required maxLength={4000} placeholder="Exact source wording only" /></label>
              <label className="block">Relation<select name="timing_relation" required className={selectClass} defaultValue=""><option value="" disabled>Choose evidenced relation</option>{["WITHIN", "BEFORE", "AFTER", "AT"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="block">Value<Input name="timing_value" type="number" required min={0} max={100000} /></label>
              <label className="block">Unit<select name="timing_unit" required className={selectClass} defaultValue=""><option value="" disabled>Choose evidenced unit</option>{["HOUR", "DAY", "WEEK"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="block">Calendar basis<select name="timing_calendar_basis" required className={selectClass} defaultValue=""><option value="" disabled>Choose evidenced basis</option><option value="CALENDAR">Calendar</option><option value="BUSINESS">Business</option></select></label>
              {timingFields.map((field) => <div key={field} className="grid gap-2 border-t pt-2 sm:grid-cols-2"><label>{field.replaceAll("_", " ")} source chunk<select className={selectClass} aria-label={`${field} evidence chunk`} value={timingEvidence[field]?.chunk_id ?? ""} onChange={(event) => setTimingEvidence({ ...timingEvidence, [field]: { chunk_id: event.target.value, quote: timingEvidence[field]?.quote ?? "" } })}><option value="">Choose selected chunk</option>{chunkPage.items.filter((chunk) => selectedChunks.includes(chunk.id)).map((chunk) => <option key={chunk.id} value={chunk.id}>{locator(chunk.source_location)} · {chunk.content.slice(0, 80)}</option>)}</select></label>
                <label>Exact quote<Input aria-label={`${field} evidence quote`} value={timingEvidence[field]?.quote ?? ""} onChange={(event) => setTimingEvidence({ ...timingEvidence, [field]: { chunk_id: timingEvidence[field]?.chunk_id ?? "", quote: event.target.value } })} required /></label></div>)}
            </>}
          </div>}
          <div className="md:col-span-2"><Button type="submit" disabled={busy || !selectedChunks.length}>{revisionOf ? "Create new revision" : "Save candidate"}</Button></div>
        </form>
      </section>}
      <div className={boxClass}>
        <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void run(() => loadCandidates(0), "Candidates refreshed."); }}>
          <label className="relative flex-1"><span className="sr-only">Search candidates</span><Search size={16} className="absolute left-3 top-3 text-muted-foreground" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search code or statement" className="pl-9" /></label>
          <select aria-label="Filter obligation" className={selectClass + " w-auto"} value={mandatoryFilter} onChange={(event) => setMandatoryFilter(event.target.value)}><option value="ALL">All</option><option value="true">Mandatory</option><option value="false">Optional</option></select>
          <Button type="submit" variant="outline">Filter</Button>
        </form>
        {candidatePage.items.length === 0 && <p className="mt-4 text-sm text-muted-foreground">No candidates match. Select evidence and create the first source-backed candidate.</p>}
        <div className="mt-4 divide-y divide-border">{candidatePage.items.map((candidate) => <div key={candidate.id} className="py-3">
          <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{candidate.requirement_code} · r{candidate.revision}</span><Status value={candidate.mandatory ? "MANDATORY" : "OPTIONAL"} /><span className="text-xs text-muted-foreground">{candidate.origin}</span></div>
          <p className="mt-1 text-sm">{candidate.statement}</p><p className="mt-1 text-xs text-muted-foreground">{candidate.requirement_type} · {candidate.category}</p>
          <Button className="mt-2" variant="outline" size="sm" onClick={() => void run(async () => {
            const detail = await rrmRequest<Requirement>(`requirements/${candidate.id}`);
            setCandidatePage({ ...candidatePage, items: candidatePage.items.map((item) => item.id === detail.id ? detail : item) });
          }, "Evidence loaded.")}>Inspect evidence</Button>
          {canAuthor && <Button className="mt-2 ml-2" variant="outline" size="sm" onClick={() => void openRevision(candidate)}>Revise candidate</Button>}
          {canAuthor && candidate.revision > 1 && <Button className="mt-2 ml-2" variant="outline" size="sm" onClick={() => void prepareDraftReplacement(candidate)}>Replace predecessor in draft</Button>}
          {candidate.evidence && <EvidenceBlock requirement={candidate} />}
        </div>)}</div>
        {candidatePage.offset > 0 && <Button variant="outline" onClick={() => void loadCandidates(Math.max(0, candidatePage.offset - candidatePage.limit))}>Previous</Button>}
        {candidatePage.has_more && <Button variant="outline" className="ml-2" onClick={() => void loadCandidates(candidatePage.offset + candidatePage.limit)}>Next</Button>}
      </div>
    </div>}

    {pane === "matrix" && <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className={boxClass}>
        <div className="flex items-center gap-2"><ClipboardList size={18} /><h2 className="text-lg font-semibold">{selectedRole?.name ?? "Role"} revisions</h2></div>
        {canAuthor && <Button className="mt-4 w-full" onClick={() => void createMatrix()}
          disabled={busy || !configs.length || (matrices.items.length > 0 && !["APPROVED", "REJECTED", "SUPERSEDED"].includes(matrices.items[0].status))}>
          <Plus size={16} />New matrix draft</Button>}
        {!configs.length && <p className="mt-3 text-sm text-muted-foreground">An Admin must map approved documents to an authority configuration before creating a matrix.</p>}
        {isAdmin && <Button className="mt-2 w-full" variant="outline" onClick={() => {
          setConfigDocuments(Object.fromEntries((configs[0]?.documents ?? []).map((item) => [item.document_id, item.authority_class])));
          setShowConfig(!showConfig);
        }}>{showConfig ? "Close authority setup" : "Configure source authority"}</Button>}
        {showConfig && isAdmin && <form onSubmit={createConfig} className="mt-3 space-y-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">Explicitly classify each approved source. Later revisions must retain mappings still needed by existing matrices.</p>
          {sourcePage.items.map((source) => <label key={source.document_id} className="block space-y-1 text-xs font-semibold">{source.document.document_code}
            <select className={selectClass} value={configDocuments[source.document_id] ?? ""} onChange={(event) => setConfigDocuments({ ...configDocuments, [source.document_id]: event.target.value })}>
              <option value="">Unmapped</option><option value="DEPARTMENT_SOP">Department SOP</option><option value="COMPANY_POLICY">Company policy</option><option value="FAQ">FAQ</option><option value="INFORMAL_GUIDANCE">Informal guidance</option>
            </select>
          </label>)}
          <Input name="reason" required aria-label="Reason for authority mapping" placeholder="Reason for authority mapping" /><Button type="submit" disabled={busy}>Save configuration</Button>
        </form>}
        <div className="mt-4 space-y-2">{matrices.items.map((item) => <button key={item.id} className={`w-full rounded-md border p-3 text-left text-sm ${matrix?.id === item.id ? "border-primary bg-primary/5" : "border-border"}`} onClick={() => void run(() => loadMatrix(item.id), "Matrix loaded.")}>
          <span className="font-semibold">Revision {item.revision}</span> <Status value={item.status} /><span className="mt-1 block text-xs text-muted-foreground">Edit lock {item.lock_version}</span>
        </button>)}{!matrices.items.length && <p className="text-sm text-muted-foreground">No matrix revisions for this role.</p>}</div>
        {matrices.has_more && <Button className="mt-3" variant="outline" onClick={() => void loadMatrices(roleId, matrices.offset + matrices.limit)}>More revisions</Button>}
      </aside>
      <section className={boxClass}>
        {!matrix && <p className="text-sm text-muted-foreground">Select a revision to inspect the role requirements, evidence, issues, and review status.</p>}
        {matrix && <><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-xl font-semibold">{selectedRole?.name} · revision {matrix.revision}</h2><Status value={matrix.status} /></div>
          <p className="mt-2 text-xs text-muted-foreground">Creator {matrix.created_by} · Submitter {matrix.submitted_by ?? "—"} · Approver {matrix.decided_by ?? "—"} · Edit {matrix.current_edit}</p>
          {matrix.snapshot_hash && <p className="mt-1 break-all text-xs text-muted-foreground">Snapshot SHA-256: {matrix.snapshot_hash}</p>}
          <div role="status" className="mt-4 rounded-md border border-warning/30 bg-warning/5 p-3 text-sm"><strong>Ready for submission: {matrix.readiness.blocking_codes.length ? "No" : "Yes"}</strong>
            {matrix.readiness.blocking_codes.length > 0 && <p>Blocking checks: {matrix.readiness.blocking_codes.join(", ")}</p>}
            {matrix.entries.map((entry) => { const req = matrix.requirements[entry.requirement_id]; return req?.timing.state === "AMBIGUOUS" ? <div key={entry.requirement_id} className="mt-2">
              <p>Ambiguous timing — {req.requirement_code} r{req.revision}: “{String(req.timing.original_text ?? "")}”. Manual review required.</p>
              {canRaiseDraftIssue && <div className="mt-2 space-y-2"><label className="block">Manual-review context<Input value={reviewContext} maxLength={4000} onChange={(event) => setReviewContext(event.target.value)} placeholder="Explain precisely what the approved source leaves unresolved" /></label><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={busy || !reviewContext.trim() || matrix.issues.some((issue) => issue.kind === "AMBIGUITY" && issue.requirement_id === req.id && issue.blocking)} onClick={() => void run(async () => {
                const fresh = await rrmRequest<Matrix>(`matrices/${matrix.id}`);
                if (fresh.issues.some((issue) => issue.kind === "AMBIGUITY" && issue.requirement_id === req.id && issue.blocking)) throw new Error("AMBIGUITY_ISSUE_ALREADY_OPEN");
                await jsonRequest(`matrices/${matrix.id}/issues`, "POST", { expected_version: fresh.lock_version, kind: "AMBIGUITY", requirement_id: req.id,
                  detail: reviewContext.trim() });
                await loadMatrix(matrix.id); setReviewContext("");
              }, "Manual-review issue created. Independent resolution does not resolve timing.")}>Create review issue</Button>
                <Button type="button" variant="outline" onClick={() => { setPane("candidates"); void openRevision(req); }}>Revise candidate / inspect evidence</Button></div></div>}
            </div> : null; })}</div>
          {createdRevision && isDraftOwner && matrix.entries.some((entry) => entry.requirement_id === createdRevision.predecessor.id) && <div className="mt-4 rounded-md border border-primary/30 bg-primary/5 p-4 text-sm">
            <p className="font-semibold">Replace {createdRevision.predecessor.requirement_code} r{createdRevision.predecessor.revision} in this DRAFT matrix?</p>
            <p className="mt-1">This sends one complete, version-checked draft edit. Unrelated entries and dependencies are retained. If the old revision participates in a dependency or exception, replacement stops for explicit review. The historical candidate is never deleted.</p>
            {matrix.issues.some((issue) => issue.requirement_id === createdRevision.predecessor.id || issue.related_requirement_id === createdRevision.predecessor.id) && <label className="mt-2 flex gap-2"><input type="checkbox" checked={issueReviewAcknowledged} onChange={(event) => setIssueReviewAcknowledged(event.target.checked)} />I reviewed the linked issue. It remains blocking after replacement until an independent reviewer resolves it for the new edit.</label>}
            <Button className="mt-3" type="button" disabled={busy} onClick={() => void replaceDraftRevision()}>Replace old revision atomically</Button>
          </div>}
          {createdRevision && matrix.entries.some((entry) => entry.requirement_id === createdRevision.predecessor.id) && !isDraftOwner && <p className="mt-4 text-sm text-muted-foreground">This matrix references the old revision but is not your editable DRAFT. It will not be changed by this workflow.</p>}
          {matrix.issues.length > 0 && <div className="mt-4"><h3 className="font-semibold">Review issues</h3>{matrix.issues.map((issue) => <div key={issue.id} className="mt-2 rounded-md border border-border p-3 text-sm">
            <p>{issue.blocking ? "Blocking" : "Issue resolved"} · {issue.kind}: {issue.detail}</p>
            {issue.kind === "AMBIGUITY" && <p className="mt-1 text-warning">Issue resolution does not resolve ambiguous timing. A new evidence-backed requirement revision is still required.</p>}
            {issue.blocking && matrix.status === "DRAFT" && canReview && <form className="mt-2 flex flex-wrap gap-2" onSubmit={(event) => {
              event.preventDefault();
              const reason = String(new FormData(event.currentTarget).get("reason") ?? "");
              void run(async () => {
                await jsonRequest(`issues/${issue.id}/resolve`, "POST", { expected_version: matrix.lock_version, reason, admin_override: false });
                await loadMatrix(matrix.id);
              }, "Issue resolution recorded for this draft edit.");
            }}><Input name="reason" required maxLength={2000} aria-label="Independent resolution reason" placeholder="Independent resolution reason" /><Button type="submit" variant="outline" disabled={busy}>Resolve issue</Button></form>}
          </div>)}</div>}
          {isDraftOwner && <div className="mt-5 rounded-md border border-border p-4"><h3 className="font-semibold">Draft entries</h3><p className="mt-1 text-xs text-muted-foreground">Select current requirement revisions, then save a new immutable edit. Submitted history is read-only.</p>
            <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">{candidatePage.items.map((candidate) => <label key={candidate.id} className="flex gap-2 text-sm"><input type="checkbox" checked={included.has(candidate.id)} onChange={(event) => {
              const ids = event.target.checked ? [...matrix.entries.map((entry) => entry.requirement_id), candidate.id] : matrix.entries.map((entry) => entry.requirement_id).filter((id) => id !== candidate.id);
              void saveDraft(ids);
            }} disabled={busy} /><span>{candidate.requirement_code} · {candidate.statement}</span></label>)}</div>
            <p className="mt-2 text-xs text-muted-foreground">Use the Candidates tab to find more. One change creates one edit; dependencies and exceptions already attached to retained entries are preserved.</p>
            {matrix.entries.length > 1 && <div className="mt-4 grid gap-2 sm:grid-cols-2"><label className="text-xs font-semibold">Dependent requirement
              <select className={selectClass} value={dependentId} onChange={(event) => setDependentId(event.target.value)}><option value="">Select</option>{matrix.entries.map((entry) => <option key={entry.requirement_id} value={entry.requirement_id}>{matrix.requirements[entry.requirement_id]?.requirement_code ?? entry.requirement_id}</option>)}</select></label>
              <label className="text-xs font-semibold">Prerequisite requirement
                <select className={selectClass} value={prerequisiteId} onChange={(event) => setPrerequisiteId(event.target.value)}><option value="">Select</option>{matrix.entries.map((entry) => <option key={entry.requirement_id} value={entry.requirement_id}>{matrix.requirements[entry.requirement_id]?.requirement_code ?? entry.requirement_id}</option>)}</select></label>
              <Button type="button" variant="outline" disabled={busy || !dependentId || !prerequisiteId || dependentId === prerequisiteId} onClick={() => void saveDraft(matrix.entries.map((entry) => entry.requirement_id), [...matrix.dependencies, { dependent_id: dependentId, prerequisite_id: prerequisiteId }])}>Add dependency</Button>
            </div>}
          </div>}
          <div className="mt-5 space-y-4">{matrix.entries.map((entry) => { const req = matrix.requirements[entry.requirement_id]; return <article key={entry.requirement_id} className="rounded-md border border-border p-4">
            <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{entry.sequence + 1}. {req?.requirement_code ?? entry.requirement_id}</span>{req && <Status value={req.mandatory ? "MANDATORY" : "OPTIONAL"} />}</div>
            {req && <><p className="mt-2 text-sm">{req.statement}</p><p className="mt-1 text-xs text-muted-foreground">Type {req.requirement_type} · Category {req.category} · Timing {timingLabel(req.timing)}</p>
              <p className="mt-1 text-xs text-muted-foreground">Applies to {req.scopes?.map((scope) => roles.find((role) => role.id === scope.role_id)?.name ?? "all roles").join(", ") || "not specified"}</p><EvidenceBlock requirement={req} /></>}
            {entry.exception_to && <p className="mt-2 text-xs">Exception to {entry.exception_to} {entry.downgrade_requested ? "· mandatory downgrade requested" : ""}</p>}
          </article>; })}</div>
          {matrix.dependencies.length > 0 && <div className="mt-4 text-sm"><h3 className="font-semibold">Dependencies</h3>{matrix.dependencies.map((edge) => <p key={`${edge.dependent_id}-${edge.prerequisite_id}`} className="mt-1 flex items-center gap-2">{matrix.requirements[edge.dependent_id]?.requirement_code ?? edge.dependent_id} requires {matrix.requirements[edge.prerequisite_id]?.requirement_code ?? edge.prerequisite_id}
            {isDraftOwner && <Button size="sm" variant="ghost" onClick={() => void saveDraft(matrix.entries.map((entry) => entry.requirement_id), matrix.dependencies.filter((item) => item !== edge))}>Remove</Button>}</p>)}</div>}
          {isDraftOwner && <div className="mt-5"><Button disabled={busy || !matrix.entries.length || matrix.readiness.blocking_codes.length > 0} onClick={() => void transition("submit")}>Submit for independent review</Button></div>}
          {canDecide && <div className="mt-5 space-y-3 border-t border-border pt-5"><h3 className="font-semibold">Independent review</h3>
            <p className="text-sm text-muted-foreground">Inspect every source and issue before deciding. The database rejects contributor self-review even for dual-role users.</p>
            {contributed && !isAdmin && <p role="alert" className="text-sm text-destructive">You contributed to this matrix, so an independent reviewer must decide.</p>}
            {contributed && isAdmin && <p role="alert" className="text-sm text-warning">You contributed to this matrix. Only an explicit, reasoned Admin emergency override can proceed.</p>}
            <label className="block space-y-1 text-sm font-semibold">Decision reason<Input value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} maxLength={2000} placeholder="Required for rejection or emergency override" /></label>
            {isAdmin && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={adminOverride} onChange={(event) => setAdminOverride(event.target.checked)} />Emergency Admin self-review override (audited; reason required)</label>}
            <div className="flex gap-2"><Button disabled={busy || matrix.readiness.blocking_codes.length > 0 || (contributed && !(isAdmin && adminOverride)) || (adminOverride && !decisionReason.trim())} onClick={() => void transition("approve")}>{adminOverride ? "Emergency override approval" : "Approve"}</Button>
              <Button variant="outline" disabled={busy || !decisionReason.trim() || (contributed && !(isAdmin && adminOverride))} onClick={() => void transition("reject")}>Reject with reason</Button></div>
          </div>}
        </>}
      </section>
    </div>}

    {pane === "ground-truth" && <section className={boxClass}>
      <h2 className="text-lg font-semibold">Approved role ground truth</h2><p className="mt-1 text-sm text-muted-foreground">Read live eligibility through the trusted database function. A stale or blocked snapshot is never shown as usable.</p>
      <Button className="mt-4" onClick={() => void loadGroundTruth()} disabled={!roleId || busy}>Check current usability</Button>
      {groundError && <p role="alert" className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><strong>NOT CURRENTLY USABLE.</strong> {groundError}</p>}
      {groundTruth && <div className="mt-5 space-y-3"><Badge tone="success">CURRENTLY USABLE</Badge><p className="break-all text-xs text-muted-foreground">Snapshot SHA-256: {groundTruth.snapshot_hash}</p>
        <p className="text-sm">Role {selectedRole?.name} · approved matrix revision {groundTruth.snapshot.revision}. All source and issue integrity checks passed at retrieval.</p>
        <p className="text-xs text-muted-foreground">Submitted by {groundTruth.approval.submitted_by} · approved by {groundTruth.approval.decided_by} on {groundTruth.approval.decided_at}{groundTruth.approval.admin_override ? " · audited Admin emergency override" : ""}</p>
        {groundTruth.snapshot.entries.map((item) => <article key={item.entry.requirement_id} className="rounded-md border border-border p-4">
          <div className="flex flex-wrap gap-2"><h3 className="font-semibold">{item.requirement.requirement_code} · {item.requirement.statement}</h3><Status value={item.requirement.mandatory ? "MANDATORY" : "OPTIONAL"} /></div>
          <p className="mt-1 text-xs text-muted-foreground">{item.requirement.requirement_type} · {item.requirement.category} · Timing {timingLabel(item.requirement.timing)}</p>
          <p className="mt-1 text-xs text-muted-foreground">Applicability: {item.scopes.map((scope) => roles.find((role) => role.id === scope.role_id)?.name ?? "all roles").join(", ")}</p>
          {item.entry.exception_to && <p className="mt-2 text-sm">Approved role exception to {item.entry.exception_to}{item.entry.downgrade_requested ? " · mandatory downgrade" : ""}</p>}
          {item.sources.map((source, index) => <div key={`${source.version_id}-${index}`} className="mt-3 rounded-md border border-primary/20 bg-primary/5 p-3 text-sm">
            <p className="font-semibold text-primary">Document {source.document_id} · version {source.version_id} · {source.review_status}</p>
            <p className="mt-1 text-xs text-muted-foreground">{source.chunk.heading ? `${source.chunk.heading} · ` : ""}{locator(source.chunk.source_location)}</p>
            <p className="mt-2 whitespace-pre-wrap">{source.chunk.content}</p>
          </div>)}
        </article>)}
        {groundTruth.snapshot.dependencies.length > 0 && <div className="rounded-md border border-border p-4 text-sm"><h3 className="font-semibold">Prerequisites</h3>{groundTruth.snapshot.dependencies.map((edge) => <p key={`${edge.dependent_id}-${edge.prerequisite_id}`}>{edge.dependent_id} requires {edge.prerequisite_id}</p>)}</div>}
      </div>}
    </section>}
  </div>;
}
