# Phase 2 document intelligence — implementation review

Status: **Phase 2 locked after project-owner closeout**. The Phase 2 migration was applied to the live Supabase project by the project owner. Phase 0 and Phase 1 remain locked. This phase adds no RRM extraction, GenAI, onboarding generation, embeddings, OCR, or deployment.

## Architecture and portability

`services/api/app/document_processing.py` owns signature/content validation, SHA-256 hashing, whitespace normalization, PDF/DOCX parsing, and deterministic chunking. It has no Supabase imports. `documents.py` orchestrates upload and review with FastAPI JWT/RBAC dependencies. `document_repository.py` is the only infrastructure adapter holding the optional backend-only `SUPABASE_SERVICE_ROLE_KEY`: user-scoped JWTs are used for reservation, Storage and review; the service credential is used **only** to finalize trusted Python processing. The Next.js Documents page has no service credential. Neither an uploader JWT nor an authenticated table grant can finalize chunks.

Reviewers can download the private original through `GET /api/v1/document-versions/{id}/original` and compare it with extracted chunks before approval. The download is user-token-scoped and subject to the private bucket's read policy.

Flow: bounded request envelope (file limit plus multipart overhead), validate metadata/file, hash the actual bytes, reserve metadata with the user's JWT, upload those exact bytes to private Storage, mark `PROCESSING`, parse/chunk in Python, then atomically finalize through a service-role-only RPC. A failed Storage operation attempts to mark the version `FAILED`; an uncertain failure can leave `UPLOADED` or `PROCESSING`. The uploader may call `POST /document-versions/{id}/retry`: it downloads and rehashes the existing object, or for `UPLOADED` with no object accepts the same file only if size and SHA-256 match the reservation. It never creates duplicate chunks/originals: finalization requires `PROCESSING`, existing object upload is not repeated, and final chunk persistence is one transaction. After an uncertain finalization response, inspect the version before retrying; an already-terminal version is not re-finalized. No worker or automatic retry exists. Upload/retry responses return `202` with synchronous processing results.

## Schema and source lineage

The applied migration is `supabase/migrations/202609230002_document_intelligence.sql`. It creates `documents` (stable UUID, unique human code, title, category, optional department, creator), `document_versions` (unique document/version and global SHA-256, dates, safe UUID storage path, format/size, uploader, parsing and review states, submitter/approver/rejector), and `document_chunks` (stable chunk key, order, content hash, heading/section, page/paragraph/table locator, character offsets, parser version). A full-text index supports later lexical retrieval; no vector index or embedding column exists.

Parse states: `UPLOADED → PROCESSING → PARSED | NEEDS_REVIEW | FAILED`, plus `UPLOADED → FAILED` on upload failure. Review states: `DRAFT → SUBMITTED → APPROVED | REJECTED`; approving a new version changes the prior approved version to `SUPERSEDED`. The reusable `current_effective_document_version(document_id,on_date)` query requires an ACTIVE logical document, `APPROVED` and `PARSED` version, effective date reached, and no passed expiry. `APPROVED` alone and newest-created are not synonyms for current-effective. `NEEDS_REVIEW` or `FAILED` cannot be submitted/approved. Uploader or submitter identity cannot review the same version even with dual Training Manager/Reviewer roles; only an Admin with explicit `admin_override=true` and a reason may do so, and the audit includes creator/approver/override evidence.

PDFs are read page-by-page with PyMuPDF. Nonempty text blocks retain one-based page and original block/bounding-box locations; larger-font short blocks are treated as likely headings but remain source content/chunks. Image-only/scanned PDFs yield no chunks and `NEEDS_REVIEW/NO_EXTRACTABLE_TEXT`. Encrypted PDFs become `NEEDS_REVIEW`; OCR is out of scope. DOCX paragraphs retain one-based paragraph references and style; Heading levels form a section path and are preserved as source content. Meaningful table cells retain table/row/cell references. Input text is normalized without following links, scripts, or macros. DOCX ZIP entry count, expanded size, compression ratio, and macro presence are checked before parsing. Malformed files produce controlled `FAILED` parsing and never fabricated extraction.

Chunks are deterministic slices of each source unit, bounded by configurable `DOCUMENT_CHUNK_CHARS` (default 1200) with `DOCUMENT_CHUNK_OVERLAP` (default 150) for long units. They never combine across source locations, retain heading/section and locator metadata, and receive SHA-256 content hashes plus stable keys derived from version, sequence, locator, and text hash. Overlap reduces boundary loss; it is not semantic retrieval or an embedding. No empty chunk is persisted.

## Phase 2 access matrix

| Capability | Admin | Training Manager | Reviewer | Manager | Employee |
|---|---|---|---|---|---|
| Upload; submit parsed draft | Yes | Yes | No | No | No |
| List, detail, version/chunk preview | Yes | Yes | Yes | No | No |
| Approve/reject submitted version | Yes | No | Yes | No | No |
| Private original Storage read | Yes | Yes | Yes | No | No |
| Direct document-table mutation | No (RPC only) | No (RPC only) | No | No | No |

FastAPI enforces those roles. PostgreSQL RLS permits only the three document-management roles to read the three tables; direct table writes are revoked. Authoring/review RPCs are user-scoped, while `finish_document_processing` has `service_role` execute only and verifies the JWT role. The private `company-documents` bucket allows only PDF/DOCX objects up to 15 MB, UUID-derived paths, uploader-owned inserts for reserved versions, and read access for Admin/Training Manager/Reviewer. There are no new user update/delete policies for originals. Client navigation visibility is never authorization. Production hardening still needs malware scanning/quarantine and review of any pre-existing Storage policies.

## Migration and live verification

The migration was reviewed and applied manually by the project owner; do not reapply it as part of this closeout. Keep the gateway/API limit aligned; the configured file limit must not exceed the bucket/database 15 MB ceiling without a deliberate migration. Verify with disposable real role-scoped sessions, never assuming mocked tests prove RLS. The direct-attack live checklist below remains **PENDING**, not passed.

## Hidden-evaluation readiness and limits

No production parser branch depends on a company name, document title, policy heading, or fixture name. An unseen valid PDF/DOCX uses the same validation → Python parsing → chunking path. Document and chunk lists are bounded, offset-paginated; the UI shows range, page, and next/previous controls, including later review chunks. Server-side search, background processing, OCR, malware scanning, and advanced PDF layout/table extraction are not implemented. The application marks unextractable sources for review, and no Phase 2 content becomes approved without Reviewer/Admin action. Detailed live RLS/Storage verification remains pending after manual migration.

Trusted-processing boundary: the uploader cannot call finalization with their JWT. FastAPI hashes/parses/chunks bytes; the repository alone uses the backend-only credential to submit results. On recovery it re-downloads and verifies the reserved checksum/size first. The database trusts the backend service identity; it does not cryptographically verify Python parser behavior. Reviewers must still compare originals and extracted evidence. This credential is powerful and must be held only by FastAPI, rotated/protected operationally, and never copied into browser/Next.js configuration.

## Closeout verification evidence

Automated closeout gates: backend pytest **74 passed** (one upstream TestClient deprecation warning); frontend lint **PASS**; TypeScript check **PASS**; Next.js production build **PASS**. These tests do not establish live RLS or Storage policy behavior.

Project-owner-reported manual live evidence:

- A real PDF was uploaded and parsed by Python into traceable chunks, submitted, independently approved by a Reviewer, reached `APPROVED`, and became current-effective version `v1.0`.
- A real DOCX was uploaded and parsed into **33** traceable chunks. Headings, sections, paragraphs, and a Word table with table/row/cell locators were preserved. Values including "Within 7 days", "Within 3 days", and "within 1 hour of discovery" were preserved. It reached `SUBMITTED`; approval is **not** claimed.
- A Training Manager used the Documents upload/submit workflow; a Reviewer accessed submitted documents and the review workflow. A Reviewer call to the submit endpoint returned HTTP 403. Manager and Employee Documents navigation was hidden; this is a UI observation, **not** proof of direct API, database, or Storage denial.

The listed direct RPC, table-write, Storage, cross-document/version, dual-role self-review, Admin-override audit, and negative current-effective checks were **not reported as executed**. They remain manual live tests, not closeout passes. Production hardening limitations above also remain.

## Post-migration direct-attack live checklist — PENDING

- Anonymous: no document table, RPC, or private Storage access.
- Admin: upload/submit/review, read originals; own review requires explicit override and reason, with audit evidence.
- Training Manager: upload/submit and read; direct finalizer, direct table mutation, and approval/rejection denied.
- Reviewer: read original/chunks, approve another person's submitted version, no upload/submit; dual Reviewer+Training Manager cannot review own uploaded/submitted version.
- Manager and Employee: no Phase 2 table, original, or API access; no direct Storage upload/read.
- Try direct finalizer RPC with an ordinary uploader JWT and fabricated chunks; it must be denied. Try user-scoped direct table insert/update/delete; denied.
- Try Storage insertion for an unreserved path, another uploader's path, and another document/version path; denied. Attempt Storage update/delete of an approved original; denied. Check for pre-existing permissive Storage policies.
- Duplicate SHA-256 and duplicate `(document_id,version_label)` reservations fail. Cross-version chunk insertion by user fails. An unparsed/`NEEDS_REVIEW`/`FAILED` version cannot submit or approve.
- Confirm only one approved version per document; check current-effective lookup before and after effective/expiry dates and supersession.

Evidence classes: application tests exercise Python/API behavior; static SQL review inspects permission and guard statements; the direct RLS/Storage checks above remain **LIVE TEST REQUIRED** until manually executed.
