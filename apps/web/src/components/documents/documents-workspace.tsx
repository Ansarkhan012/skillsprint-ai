"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Download, FilePlus2, FileText, Search, ShieldCheck, X } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { StateBadge } from "@/components/product/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CompanyDocument, DocumentChunk, DocumentPage, DocumentVersion, UploadResult, documentRequest, latestVersion } from "@/lib/documents";

type Department = { id: string; code: string; name: string };
type Props = { initialDocuments: DocumentPage<CompanyDocument>; departments: Department[]; canUpload: boolean; canReview: boolean; isAdmin: boolean; actorId: string };

function DocumentBadge({ status }: { status: string }) {
  return <StateBadge value={status} />;
}

function ErrorMessage({ message }: { message: string }) {
  return <p role="alert" className="rounded-panel bg-status-danger px-4 py-3 text-sm text-status-danger-fg">{message}</p>;
}

export function DocumentsWorkspace({ initialDocuments, departments, canUpload, canReview, isAdmin, actorId }: Props) {
  const [documentPage, setDocumentPage] = useState(initialDocuments);
  const documents = documentPage.items;
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [selected, setSelected] = useState<CompanyDocument | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<DocumentVersion | null>(null);
  const [chunkPage, setChunkPage] = useState<DocumentPage<DocumentChunk>>({ items: [], offset: 0, limit: 100, has_more: false });
  const chunks = chunkPage.items;
  const [currentEffective, setCurrentEffective] = useState<DocumentVersion | null>(null);
  const [override, setOverride] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [existingId, setExistingId] = useState("");
  const actionLock = useRef(false);
  const selfReview = selectedVersion?.uploaded_by === actorId || selectedVersion?.submitted_by === actorId;

  const visible = useMemo(() => documents.filter((document) => {
    const latest = latestVersion(document);
    const needle = search.trim().toLowerCase();
    return (!needle || `${document.document_code} ${document.title} ${document.category}`.toLowerCase().includes(needle))
      && (statusFilter === "ALL" || latest?.review_status === statusFilter || latest?.parse_status === statusFilter);
  }), [documents, search, statusFilter]);

  async function refreshDocuments(offset = documentPage.offset) {
    const fresh = await documentRequest<DocumentPage<CompanyDocument>>(`documents?offset=${offset}&limit=100`);
    setDocumentPage(fresh);
    return fresh;
  }

  async function loadChunkPage(versionId: string, offset: number) {
    setChunkPage(await documentRequest<DocumentPage<DocumentChunk>>(`document-versions/${versionId}/chunks?offset=${offset}&limit=100`));
  }

  async function openDocument(id: string, versionId?: string) {
    setError("");
    setLoadingDetail(true);
    try {
      const detail = await documentRequest<CompanyDocument>(`documents/${id}`);
      setSelected(detail);
      const version = detail.document_versions.find((item) => item.id === versionId) ?? latestVersion(detail) ?? null;
      setSelectedVersion(version);
      const effective = await documentRequest<DocumentVersion | null>(`documents/${id}/current-effective-version`);
      setCurrentEffective(effective);
      if (version) await loadChunkPage(version.id, 0);
      else setChunkPage({ items: [], offset: 0, limit: 100, has_more: false });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "DOCUMENT_DETAIL_UNAVAILABLE");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true); setError(""); setNotice("");
    try {
      const form = new FormData(event.currentTarget);
      const file = form.get("file");
      if (!(file instanceof File) || !file.size) throw new Error("Choose a non-empty PDF or DOCX file.");
      if (!form.get("department_id")) form.delete("department_id");
      if (!form.get("expiry_date")) form.delete("expiry_date");
      if (!form.get("document_id")) form.delete("document_id");
      const result = await documentRequest<UploadResult>("documents/uploads", { method: "POST", body: form });
      await refreshDocuments(0);
      setShowUpload(false);
      const flagged = result.security_flags?.length ?? 0;
      setNotice((result.parse_status === "PARSED"
        ? `Version uploaded and parsed (${result.chunk_count} chunks). Submit it for review when ready.`
        : `Upload retained as ${result.parse_status.replaceAll("_", " ")}: ${result.reason_code ?? "review required"}.`)
        + (flagged ? ` Security: ${flagged} chunk(s) contain possible prompt-injection or adversarial instructions. They are treated as data only; review them before approval.` : ""));
      await openDocument(result.document_id, result.version_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "UPLOAD_FAILED");
    } finally { actionLock.current = false; setBusy(false); }
  }

  async function act(action: "submit" | "approve" | "reject") {
    if (!selectedVersion || !selected || actionLock.current) return;
    if (!window.confirm(`Confirm ${action} for ${selected.title} ${selectedVersion.version_label}?`)) return;
    actionLock.current = true;
    setBusy(true); setError(""); setNotice("");
    try {
      await documentRequest(`document-versions/${selectedVersion.id}/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "submit" ? {} : { reason, admin_override: override }),
      });
      await refreshDocuments();
      await openDocument(selected.id, selectedVersion.id);
      setReason("");
      setOverride(false);
      setNotice(`Version ${action === "submit" ? "submitted" : action === "approve" ? "approved" : "rejected"}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "DOCUMENT_ACTION_FAILED");
    } finally { actionLock.current = false; setBusy(false); }
  }

  async function retryVersion() {
    if (!selectedVersion || !selected) return;
    setBusy(true); setError("");
    try {
      const form = new FormData();
      const replacement = document.getElementById("retry-original") as HTMLInputElement | null;
      if (replacement?.files?.[0]) form.append("file", replacement.files[0]);
      await documentRequest(`document-versions/${selectedVersion.id}/retry`, { method: "POST", body: form });
      await refreshDocuments();
      await openDocument(selected.id, selectedVersion.id);
      setNotice("Processing retried using the verified original.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "RETRY_FAILED"); }
    finally { setBusy(false); }
  }

  const chosenExisting = documents.find((item) => item.id === existingId);
  const meta = (label: string, value: React.ReactNode, wide = false) => <div className={wide ? "sm:col-span-2" : undefined}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-sm font-medium [overflow-wrap:break-word]">{value}</dd></div>;
  return <div className="space-y-6">
    <PageHeader title="Documents"
      description="Upload, review, and trace every source version before it becomes approved ground truth."
      action={canUpload ? <Button onClick={() => { setShowUpload((value) => !value); setError(""); }}>{showUpload ? <X size={16} /> : <FilePlus2 size={16} />}{showUpload ? "Close upload" : "Upload document"}</Button> : undefined} />

    <section className="workspace-panel" aria-label="Document evidence lifecycle"><ol className="grid grid-cols-2 divide-border sm:grid-cols-4 sm:divide-x">{["Upload source", "Parse & inspect", "Review evidence", "Approve version"].map((step, index) => <li key={step} className="flex items-center gap-3 px-5 py-4 text-sm font-medium"><span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{index + 1}</span>{step}</li>)}</ol><p className="border-t border-border px-5 py-2.5 text-xs text-muted-foreground">Process overview. Each version keeps its own processing and review state.</p></section>
    {error && <ErrorMessage message={error} />}
    {notice && <p role="status" className="rounded-panel bg-status-verified px-4 py-3 text-sm text-status-verified-fg">{notice}</p>}

    {showUpload && canUpload && <section className="workspace-panel p-6" aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="card-title">New document version</h2>
      <p className="mt-1 text-sm text-muted-foreground">PDF or DOCX. Initial server limit: 15 MB per file. Scanned PDFs need manual review; OCR is not available.</p>
      <form onSubmit={upload} className="mt-5 grid gap-5 md:grid-cols-2">
        <label className="space-y-1.5 text-sm font-medium md:col-span-2">Existing document (optional)
          <select name="document_id" value={existingId} onChange={(event) => setExistingId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-card px-3 font-normal">
            <option value="">Create a new document</option>
            {documents.map((item) => <option value={item.id} key={item.id}>{item.document_code} — {item.title}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium">Document code<Input name="document_code" required pattern="[A-Z0-9_-]{2,64}" defaultValue={chosenExisting?.document_code} key={`code-${existingId}`} placeholder="POLICY_001" /></label>
        <label className="space-y-1.5 text-sm font-medium">Title<Input name="title" required maxLength={240} defaultValue={chosenExisting?.title} key={`title-${existingId}`} /></label>
        <label className="space-y-1.5 text-sm font-medium">Category<Input name="category" required maxLength={100} defaultValue={chosenExisting?.category} key={`category-${existingId}`} placeholder="Policy" /></label>
        <label className="space-y-1.5 text-sm font-medium">Department
          <select name="department_id" defaultValue={chosenExisting?.department_id ?? ""} key={`department-${existingId}`} className="h-10 w-full rounded-md border border-border bg-card px-3 font-normal">
            <option value="">All departments / general</option>
            {departments.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium">Version label<Input name="version_label" required maxLength={64} placeholder="v1.0" /></label>
        <label className="space-y-1.5 text-sm font-medium">Effective date<Input name="effective_date" type="date" required /></label>
        <label className="space-y-1.5 text-sm font-medium">Expiry date (optional)<Input name="expiry_date" type="date" /></label>
        <label className="space-y-1.5 text-sm font-medium md:col-span-2">Original PDF or DOCX<Input name="file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required /></label>
        <div className="flex justify-end gap-2 md:col-span-2"><Button type="button" variant="outline" onClick={() => setShowUpload(false)}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? "Uploading and processing…" : "Upload and process"}</Button></div>
      </form>
    </section>}

    <section className="workspace-panel overflow-hidden" aria-labelledby="library-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-5">
        <div><h2 id="library-heading" className="card-title">Document library</h2><p className="text-sm text-muted-foreground">{visible.length} visible on this page · records {documents.length ? documentPage.offset + 1 : 0}–{documentPage.offset + documents.length}. Search and filters apply to this page.</p></div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          <label className="relative min-w-56 flex-1 sm:flex-none"><span className="sr-only">Search documents</span><Search size={16} className="absolute left-3 top-3 text-muted-foreground" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search title or code" className="pl-9" /></label>
          <label><span className="sr-only">Filter status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="h-10 rounded-md border border-border bg-card px-3 text-sm"><option value="ALL">All statuses</option><option value="DRAFT">Draft</option><option value="SUBMITTED">Submitted</option><option value="APPROVED">Approved</option><option value="NEEDS_REVIEW">Needs review</option><option value="FAILED">Failed</option></select></label>
        </div>
      </div>
      {visible.length ? <div className="max-h-[36rem] overflow-auto border-t border-border" tabIndex={0} role="region" aria-label="Document library table"><table className="w-full min-w-[760px] text-left text-sm">
        <thead className="sticky top-0 z-10 bg-surface-raised shadow-[inset_0_-1px_0_var(--border)]"><tr>{["Document", "Category", "Department", "Version", "Status", "Effective", ""].map((h) => <th scope="col" key={h} className="whitespace-nowrap p-3 first:pl-6">{h}</th>)}</tr></thead>
        <tbody className="[&_td]:p-3 [&_td:first-child]:pl-6 [&_tr:nth-child(even)]:bg-surface-raised [&_tr:hover]:bg-muted">{visible.map((item) => { const version = latestVersion(item); const active = selected?.id === item.id; return <tr key={item.id} className={`border-b border-border last:border-0 ${active ? "!bg-primary-soft" : ""}`}><td><span className="block font-medium">{item.title}</span><span className="font-mono text-xs text-muted-foreground">{item.document_code}</span></td><td>{item.category}</td><td>{departments.find((department) => department.id === item.department_id)?.name ?? "General"}</td><td>{version?.version_label ?? "—"}</td><td>{version ? <DocumentBadge status={version.review_status === "DRAFT" && version.parse_status !== "PARSED" ? version.parse_status : version.review_status} /> : "—"}</td><td className="whitespace-nowrap text-muted-foreground">{version?.effective_date ?? "—"}</td><td className="text-right"><Button type="button" variant="outline" size="sm" aria-pressed={active} onClick={() => openDocument(item.id)}>View details</Button></td></tr>; })}</tbody>
      </table></div> : <div className="border-t border-border p-6"><EmptyState icon={FileText} title="No documents match" description="Try another filter, or upload a source document if your role permits it." /></div>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-6 py-4 text-xs text-muted-foreground"><span>Document page {Math.floor(documentPage.offset / documentPage.limit) + 1}{documentPage.has_more ? " · more documents available" : " · last page"}</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={busy || documentPage.offset === 0} onClick={() => refreshDocuments(Math.max(0, documentPage.offset - documentPage.limit))}>Previous</Button><Button variant="outline" size="sm" disabled={busy || !documentPage.has_more} onClick={() => refreshDocuments(documentPage.offset + documentPage.limit)}>Next</Button></div></div>
    </section>

    {selected && <section className="workspace-panel overflow-hidden" aria-labelledby="detail-heading">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-6 py-5"><div className="min-w-0"><p className="eyebrow">Source detail</p><h2 id="detail-heading" className="mt-1 text-xl font-semibold">{selected.title}</h2><p className="text-sm text-muted-foreground"><span className="font-mono">{selected.document_code}</span> · {selected.category}</p></div><Button variant="ghost" size="sm" onClick={() => { setSelected(null); setSelectedVersion(null); }}><X size={16} />Close</Button></div>
      {loadingDetail ? <p role="status" className="px-6 py-5 text-sm text-muted-foreground">Loading document details…</p> : <div className="space-y-6 px-6 py-5">
        <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-muted-foreground">Versions</span><div className="flex flex-wrap gap-1 rounded-md bg-muted p-1" aria-label="Versions">{[...selected.document_versions].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((version) => <button key={version.id} type="button" aria-pressed={version.id === selectedVersion?.id} onClick={() => openDocument(selected.id, version.id)} className={`rounded-md px-3 py-1.5 text-xs font-medium ${version.id === selectedVersion?.id ? "bg-card text-foreground shadow-panel" : "text-muted-foreground hover:text-foreground"}`}>{version.version_label}</button>)}</div></div>
        {selectedVersion && <>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <dl className="grid gap-4 rounded-panel bg-surface-raised p-5 sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-xs text-muted-foreground">Processing</dt><dd className="mt-1"><DocumentBadge status={selectedVersion.parse_status} /></dd></div>
            <div><dt className="text-xs text-muted-foreground">Review</dt><dd className="mt-1"><DocumentBadge status={selectedVersion.review_status} /></dd></div>
            {meta("Latest version", latestVersion(selected)?.version_label ?? "—")}
            {meta("Current effective version", currentEffective?.version_label ?? "None")}
            {meta("Effective", selectedVersion.effective_date)}
            {meta("Uploaded", new Date(selectedVersion.created_at).toLocaleString())}{meta("Expires", selectedVersion.expiry_date ?? "Not set")}
            {meta("Original filename", selectedVersion.original_filename ?? "—", true)}
            <div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">Version ID</dt><dd className="mt-1 break-all font-mono text-xs">{selectedVersion.id}</dd></div>
          </dl>
          <div className="space-y-3 rounded-panel border border-border p-5">
            <h3 className="text-sm font-semibold">Actions</h3>
            <a className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline" href={`/api/document-gateway/document-versions/${selectedVersion.id}/original`}><Download size={16} aria-hidden="true" />Download original for source review</a>
            {selectedVersion.parse_error_code && <p className="rounded-md bg-status-warning px-3 py-2 text-sm text-status-warning-fg">Processing requires attention: {selectedVersion.parse_error_code}</p>}
            {canUpload && ["UPLOADED", "PROCESSING"].includes(selectedVersion.parse_status) && <div className="space-y-2"><label className="block text-sm">Original file (only needed if Storage upload did not complete)<Input id="retry-original" type="file" accept=".pdf,.docx" /></label><Button variant="outline" disabled={busy} onClick={retryVersion}>Retry processing</Button></div>}
            {canUpload && selectedVersion.parse_status === "PARSED" && selectedVersion.review_status === "DRAFT" && <Button className="w-full" disabled={busy} onClick={() => act("submit")}>Submit for review</Button>}
            {canReview && selectedVersion.review_status === "SUBMITTED" && <div className="space-y-3"><label className="block text-sm font-medium">Decision reason (required for rejection or Admin self-review)<Input className="mt-1.5" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} /></label>{isAdmin && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={override} onChange={(event) => setOverride(event.target.checked)} />Explicit emergency self-review override</label>}<div className="grid grid-cols-2 gap-2"><Button disabled={busy || (selfReview && !(isAdmin && override && reason.trim())) || (override && !reason.trim())} onClick={() => act("approve")}><ShieldCheck size={16} />Approve</Button><Button variant="outline" disabled={busy || !reason.trim() || (selfReview && !(isAdmin && override))} onClick={() => act("reject")}>Reject</Button></div></div>}
          </div>
        </div>
        <div><div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="card-title">Extracted source preview</h3>{chunks.some((chunk) => chunk.security_flags?.length) && <Badge tone="destructive"><AlertTriangle size={12} aria-hidden="true" />{chunks.filter((chunk) => chunk.security_flags?.length).length} flagged chunk(s) on this page</Badge>}</div><p className="mt-1 text-sm text-muted-foreground">Each chunk retains a stable key and its original page, paragraph, or table location.</p>
          {chunks.length ? <ol className="mt-4 space-y-3">{chunks.map((chunk) => <li key={chunk.id} className={`rounded-panel border p-4 ${chunk.security_flags?.length ? "border-status-danger-fg/40 bg-status-danger/30" : "border-border"}`}><div className="flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground"><span className="rounded-md bg-muted px-2 py-0.5 text-foreground">Chunk {chunk.sequence + 1}</span>{chunk.page_number && <span>PDF page {chunk.page_number}</span>}{chunk.paragraph_start && <span>DOCX paragraph {chunk.paragraph_start}</span>}{chunk.source_location.table != null && <span>Table {String(chunk.source_location.table)}, row {String(chunk.source_location.row)}, cell {String(chunk.source_location.cell)}</span>}{chunk.section_path && <span>Section: {chunk.section_path}</span>}{chunk.security_flags?.length ? <span role="alert"><Badge tone="destructive"><AlertTriangle size={12} aria-hidden="true" />Possible prompt injection: {chunk.security_flags.join(", ").replaceAll("_", " ").toLowerCase()} (treated as data only)</Badge></span> : null}</div><details className="mt-2 text-sm"><summary className="cursor-pointer font-medium text-primary">Read source excerpt</summary><p className="mt-2 whitespace-pre-wrap leading-6">{chunk.content}</p><p className="mt-3 break-all font-mono text-[11px] text-muted-foreground">Integrity key: {chunk.chunk_key}</p></details></li>)}</ol> : <div className="mt-4"><EmptyState icon={FileText} title="No extractable chunks" description="The original is retained. Review the processing status before submission." /></div>}
          {selectedVersion.parse_status === "PARSED" && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground"><span>Chunks {chunkPage.offset + 1}–{chunkPage.offset + chunks.length} · page {Math.floor(chunkPage.offset / chunkPage.limit) + 1}{chunkPage.has_more ? " · more chunks available" : " · last page"}</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={busy || chunkPage.offset === 0} onClick={() => loadChunkPage(selectedVersion.id, Math.max(0, chunkPage.offset - chunkPage.limit))}>Previous chunks</Button><Button variant="outline" size="sm" disabled={busy || !chunkPage.has_more} onClick={() => loadChunkPage(selectedVersion.id, chunkPage.offset + chunkPage.limit)}>Next chunks</Button></div></div>}
        </div></>}
      </div>}
    </section>}
  </div>;
}
