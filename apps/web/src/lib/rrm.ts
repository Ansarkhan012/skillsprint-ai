export type Page<T> = { items: T[]; offset: number; limit: number; has_more: boolean };
export type Requirement = {
  id: string; requirement_code: string; revision: number; statement: string;
  requirement_type: string; category: string; mandatory: boolean; timing: Record<string, unknown>;
  origin: string; created_by: string; predecessor_id?: string | null;
  competency?: string | null; assessment_required?: boolean; priority?: "LOW" | "MEDIUM" | "HIGH";
  scopes?: Array<{ role_id: string | null; department_id: string | null; location_code: string | null; experience: string | null; ordinal?: number }>;
  evidence?: Evidence[];
};
export type Evidence = {
  current_eligible: boolean; chunk_id?: string;
  chunk?: { id: string; content: string; heading: string | null; section_path: string | null; source_location: Record<string, unknown> };
  version?: { id: string; version_label: string };
  document?: { id: string; document_code: string; title: string };
};
export type SourceVersion = { id: string; document_id: string; version_label: string; document: { id: string; document_code: string; title: string } };
export type SourceChunk = { id: string; content: string; heading: string | null; section_path: string | null; source_location: Record<string, unknown> };
export type MatrixEntry = { requirement_id: string; sequence: number; stage_id?: string | null; exception_to?: string | null; downgrade_requested?: boolean; downgrade_justification?: string | null; downgrade_evidence?: Record<string, unknown> | null };
export type Matrix = {
  id: string; role_id: string; revision: number; status: string; current_edit: number; lock_version: number;
  created_by: string; submitted_by: string | null; decided_by: string | null; decision_reason?: string | null;
  snapshot_hash: string | null; entries: MatrixEntry[];
  dependencies: Array<{ dependent_id: string; prerequisite_id: string }>;
  issues: Array<{ id: string; kind: string; detail: string; blocking: boolean; requirement_id?: string | null; related_requirement_id?: string | null }>;
  requirements: Record<string, Requirement>;
  readiness: { blocking_codes: string[] };
};
export type MatrixSummary = Pick<Matrix, "id" | "role_id" | "revision" | "status" | "lock_version" | "created_by">;
export type Config = { id: string; revision: number; documents: Array<{ document_id: string; authority_class: string }> };
export type GroundTruth = { snapshot_hash: string; approval: { decided_by: string; decided_at: string; submitted_by: string; admin_override: boolean; decision_reason: string | null }; snapshot: {
  role_id: string; revision: number;
  entries: Array<{ entry: MatrixEntry; requirement: Requirement;
    scopes: Array<{ role_id: string | null; department_id: string | null; location_code: string | null; experience: string | null }>;
    sources: Array<{ chunk: { content: string; source_location: Record<string, unknown>; heading: string | null };
      document_id: string; version_id: string; review_status: string; parse_status: string }> }>;
  dependencies: Array<{ dependent_id: string; prerequisite_id: string }>;
} };

export const requirementCategories = [
  { value: "POLICY", label: "Policy" }, { value: "SECURITY", label: "Security" },
  { value: "COMPLIANCE", label: "Compliance" }, { value: "PROCEDURE", label: "Procedure" },
  { value: "SAFETY", label: "Safety" }, { value: "GENERAL", label: "General" },
] as const;

export type CandidateFields = {
  code: string; statement: string; category: string; mandatory: boolean; mustType: string;
  roleId: string; departmentId: string; timingText: string;
};

export const timingFields = ["original_text", "trigger", "relation", "value", "unit", "calendar_basis"] as const;
export type TimingField = typeof timingFields[number];
export type TimingSelection = { chunk_id: string; quote: string };
export type StructuredTimingInput = {
  trigger: string; relation: "WITHIN" | "BEFORE" | "AFTER" | "AT";
  value: number; unit: "HOUR" | "DAY" | "WEEK"; calendar_basis: "CALENDAR" | "BUSINESS";
  evidence: Record<TimingField, TimingSelection>;
};

export function buildStructuredTiming(original: string, input: StructuredTimingInput,
  chunks: SourceChunk[], linkedIds: string[]) {
  if (!original.trim() || !input.trigger.trim() || !["WITHIN", "BEFORE", "AFTER", "AT"].includes(input.relation)
    || !["HOUR", "DAY", "WEEK"].includes(input.unit) || !["CALENDAR", "BUSINESS"].includes(input.calendar_basis)
    || !Number.isInteger(input.value) || input.value < 0 || input.value > 100000)
    throw new Error("TIMING_FIELDS_REQUIRED");
  const evidence = Object.fromEntries(timingFields.map((field) => {
    const selection = input.evidence[field];
    const chunk = chunks.find((item) => item.id === selection?.chunk_id && linkedIds.includes(item.id));
    const quote = selection?.quote ?? "";
    const start = chunk?.content.indexOf(quote) ?? -1;
    const expected = String(field === "original_text" ? original : input[field]).toLowerCase();
    if (!chunk || !quote.trim() || start < 0 || !([expected, ...(field === "unit" ? [expected + "s"] : [])].includes(quote.trim().toLowerCase())))
      throw new Error("TIMING_EXACT_SPAN_REQUIRED");
    // SQL substring and Python slicing count Unicode code points, not UTF-16 units.
    const codePointStart = Array.from(chunk.content.slice(0, start)).length;
    return [field, { chunk_id: chunk.id, start: codePointStart, end: codePointStart + Array.from(quote).length, quote }];
  }));
  return { state: "STRUCTURED", original_text: original, trigger: input.trigger.trim(),
    relation: input.relation, value: input.value, unit: input.unit,
    calendar_basis: input.calendar_basis, evidence };
}

export function buildCandidatePayload(fields: CandidateFields, chunkIds: string[], predecessor: Requirement | null,
  structured?: ReturnType<typeof buildStructuredTiming>) {
  const code = fields.code.trim();
  const statement = fields.statement.trim();
  if (predecessor && (code !== predecessor.requirement_code || predecessor.scopes?.length !== 1
    || predecessor.timing.state === "STRUCTURED")) throw new Error("REVISION_REQUIRES_EXPLICIT_REVIEW");
  if (!/^[A-Z][A-Z0-9_-]{1,63}$/.test(code)) throw new Error("ENTER_VALID_REQUIREMENT_CODE");
  if (!statement) throw new Error("ENTER_REQUIREMENT_STATEMENT");
  if (!requirementCategories.some((item) => item.value === fields.category)
    && fields.category !== predecessor?.category) throw new Error("SELECT_REQUIREMENT_CATEGORY");
  if (!chunkIds.length || new Set(chunkIds).size !== chunkIds.length) throw new Error("SELECT_EXACT_SOURCE_CHUNKS");
  if (fields.mandatory && !["MUST_COMPLETE", "MUST_KNOW", "MUST_DEMONSTRATE", "MUST_ACKNOWLEDGE"].includes(fields.mustType))
    throw new Error("SELECT_MANDATORY_TYPE");
  const previousScope = predecessor?.scopes?.[0];
  const original = fields.timingText.trim();
  if (predecessor?.timing.state === "AMBIGUOUS" && !original) throw new Error("PRESERVE_AMBIGUOUS_TIMING");
  if (structured && (!predecessor || predecessor.timing.state !== "AMBIGUOUS" || original !== predecessor.timing.original_text
    || structured.original_text !== original)) throw new Error("PRESERVE_AMBIGUOUS_TIMING");
  return {
    ...(predecessor ? { predecessor_id: predecessor.id } : {}),
    code, statement, category: fields.category, mandatory: fields.mandatory,
    requirement_type: fields.mandatory ? fields.mustType : "OPTIONAL",
    chunk_ids: chunkIds,
    scopes: [{ role_id: fields.roleId || null, department_id: fields.departmentId || null,
      location_code: previousScope?.location_code ?? null, experience: previousScope?.experience ?? null }],
    timing: structured ?? (original ? { state: "AMBIGUOUS", original_text: original } : { state: "NOT_SPECIFIED" }),
    ...(predecessor ? { competency: predecessor.competency ?? null,
      assessment_required: predecessor.assessment_required ?? false,
      priority: predecessor.priority ?? "MEDIUM" } : {}),
  };
}

export function buildDraftRevisionReplacement(matrix: Matrix, actorId: string, predecessor: Requirement, successor: Requirement,
  issueReviewAcknowledged = false) {
  if (matrix.status !== "DRAFT" || matrix.created_by !== actorId) throw new Error("DRAFT_OWNER_REQUIRED");
  if (successor.predecessor_id !== predecessor.id || successor.requirement_code !== predecessor.requirement_code
    || successor.revision !== predecessor.revision + 1) throw new Error("INVALID_CANDIDATE_REVISION");
  if (matrix.entries.filter((entry) => entry.requirement_id === predecessor.id).length !== 1
    || matrix.entries.some((entry) => entry.requirement_id === successor.id)) throw new Error("DRAFT_REVISION_NOT_REPLACEABLE");
  if (matrix.dependencies.some((edge) => edge.dependent_id === predecessor.id || edge.prerequisite_id === predecessor.id)
    || ((matrix.issues ?? []).some((issue) => issue.requirement_id === predecessor.id || issue.related_requirement_id === predecessor.id)
      && !issueReviewAcknowledged)
    || matrix.entries.some((entry) => entry.exception_to === predecessor.id)
    || matrix.entries.some((entry) => entry.requirement_id === predecessor.id && (entry.exception_to || entry.downgrade_requested)))
    throw new Error("REVISION_RELATIONSHIP_REVIEW_REQUIRED");
  return {
    expected_version: matrix.lock_version,
    entries: matrix.entries.map((entry) => entry.requirement_id === predecessor.id
      ? { ...entry, requirement_id: successor.id } : { ...entry }),
    dependencies: matrix.dependencies.map((edge) => ({ ...edge })),
    reason: `Replaced ${predecessor.requirement_code} r${predecessor.revision} with corrected r${successor.revision}; historical revision retained.`,
  };
}

export async function rrmRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/document-gateway/${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.code ?? "RRM_REQUEST_FAILED");
  }
  return response.json() as Promise<T>;
}

export function jsonRequest<T>(path: string, method: "POST" | "PATCH", value: object) {
  return rrmRequest<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
}

export function locator(value: Record<string, unknown>): string {
  const kind = value.kind === "pdf" ? "PDF" : value.kind === "docx" ? "Word" : "Source";
  const parts = [value.page != null ? `Page ${value.page}` : null,
    value.block != null ? `block ${value.block}` : null,
    value.heading != null ? `heading ${value.heading}` : null,
    value.paragraph != null ? `paragraph ${value.paragraph}` : null,
    value.table != null ? `table ${value.table}` : null,
    value.row != null ? `row ${value.row}` : null,
    value.cell != null ? `cell ${value.cell}` : null].filter(Boolean);
  return `${kind} · ${parts.join(" / ") || "traceable chunk"}`;
}

const messages: Record<string, string> = {
  RRM_MATRIX_DETAIL_LIMIT: "This matrix exceeds the safe detail-read limit. No partial edit was loaded; contact an administrator.",
  RRM_EDIT_CONFLICT: "This draft changed. Reload it before editing again.",
  RRM_STALE_SUBMISSION: "The submitted evidence changed. Create a new matrix revision before approval.",
  RRM_STALE_SNAPSHOT: "This approved snapshot is no longer current or usable. Create a new revision.",
  RRM_INVALID_OR_STALE_SOURCE: "This source is no longer current. Select approved current evidence.",
  RRM_SELF_REVIEW_FORBIDDEN: "An independent Reviewer or Admin must review this work.",
  RRM_BLOCKING_ISSUE_OR_EMPTY_MATRIX: "Resolve blocking issues and add requirements before submitting.",
  RRM_REASON_REQUIRED: "Enter a meaningful reason.",
  RRM_TIMING_MANUAL_REVIEW: "Timing requires manual review. An approved source must explicitly support every timing field before submission.",
  TIMING_FIELDS_REQUIRED: "Enter all structured timing fields, including an evidence-backed trigger.",
  TIMING_EXACT_SPAN_REQUIRED: "Select an exact quoted span in a linked, approved source chunk for every timing field.",
  AMBIGUITY_ISSUE_ALREADY_OPEN: "An ambiguity issue is already open for this requirement. Review it before creating another.",
  RRM_NO_APPROVED_MATRIX: "No approved matrix is available for this role.",
  REVISION_REQUIRES_EXPLICIT_REVIEW: "This revision has multiple scopes or structured timing. Use the evidence-backed workflow before revising it here.",
  ENTER_VALID_REQUIREMENT_CODE: "Enter an uppercase requirement code such as SECURITY_TRAINING.",
  ENTER_REQUIREMENT_STATEMENT: "Enter a requirement statement.",
  SELECT_REQUIREMENT_CATEGORY: "Choose a category from the list.",
  SELECT_EXACT_SOURCE_CHUNKS: "Select the exact approved source chunks for this revision.",
  SELECT_MANDATORY_TYPE: "Choose a supported mandatory type.",
  DRAFT_OWNER_REQUIRED: "Only the author of a DRAFT matrix can replace its candidate revision.",
  INVALID_CANDIDATE_REVISION: "The replacement must be the next immutable revision of the same requirement code.",
  DRAFT_REVISION_NOT_REPLACEABLE: "This draft must contain exactly one old revision and no new revision. Reload and inspect it.",
  REVISION_RELATIONSHIP_REVIEW_REQUIRED: "A dependency, exception, or review issue involves the old revision. Review that relationship explicitly before replacement.",
  PRESERVE_AMBIGUOUS_TIMING: "Keep the original ambiguous timing text until it is separately resolved with exact evidence.",
};
export function rrmMessage(error: unknown): string {
  const code = error && typeof error === "object" && "message" in error && typeof error.message === "string"
    ? error.message : "RRM_REQUEST_FAILED";
  return messages[code] ?? "The requirement service could not complete this action. Refresh the workspace and check the selected evidence and permissions.";
}
