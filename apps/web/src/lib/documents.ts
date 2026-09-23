export type ParseStatus = "UPLOADED" | "PROCESSING" | "PARSED" | "NEEDS_REVIEW" | "FAILED";
export type ReviewStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED" | "SUPERSEDED";

export type DocumentVersion = {
  id: string;
  document_id?: string;
  version_label: string;
  parse_status: ParseStatus;
  parse_error_code?: string | null;
  review_status: ReviewStatus;
  effective_date: string;
  expiry_date: string | null;
  original_filename?: string;
  mime_type?: string;
  size_bytes?: number;
  uploaded_by: string;
  created_at: string;
  approved_by?: string | null;
};

export type CompanyDocument = {
  id: string;
  document_code: string;
  title: string;
  category: string;
  department_id: string | null;
  status: string;
  created_at: string;
  document_versions: DocumentVersion[];
};

export type DocumentChunk = {
  id: string;
  chunk_key: string;
  sequence: number;
  content: string;
  heading: string | null;
  section_path: string | null;
  source_location: Record<string, unknown>;
  page_number: number | null;
  paragraph_start: number | null;
  paragraph_end: number | null;
};

export type UploadResult = {
  document_id: string;
  version_id: string;
  parse_status: ParseStatus;
  review_status: ReviewStatus;
  chunk_count: number;
  reason_code: string | null;
};

export type DocumentPage<T> = { items: T[]; offset: number; limit: number; has_more: boolean };

export function latestVersion(document: CompanyDocument): DocumentVersion | undefined {
  return [...document.document_versions].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

export async function documentRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/document-gateway/${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.code ?? "DOCUMENT_REQUEST_FAILED");
  }
  return response.json() as Promise<T>;
}
