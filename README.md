# SkillSprint AI

Phase 1 foundation: Next.js web app, FastAPI/Python API, and Supabase PostgreSQL/Auth/RLS infrastructure. Supabase is the selected implementation, not an explicit SRS requirement. Later RRM, GenAI, and onboarding features remain in the architecture documents.

Phase 2 document intelligence is locked after project-owner closeout. Its migration has been applied to the live project. See [Phase 2 implementation and verification notes](docs/PHASE2_DOCUMENT_INTELLIGENCE.md); detailed direct RLS/Storage attack checks remain pending.

## Prerequisites

- Node.js 20 or later and npm
- Python 3.12
- Supabase project with Auth and PostgreSQL
- Phase 2 backend parser dependencies from `services/api/requirements.txt` (PyMuPDF, python-docx, python-multipart)

## Configuration

Copy `.env.example` to a private root `.env` for the API. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `WEB_ORIGIN`, and other server values as needed. The `NEXT_PUBLIC_*` values are the public Supabase URL and anon key only. Put `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and `API_BASE_URL` in `apps/web/.env.local` for Next.js. Never put `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, or `GEMINI_API_KEY` into a `NEXT_PUBLIC_` variable.

Apply `supabase/migrations/202609230001_foundation.sql` through your Supabase migration workflow. This migration creates no user or sample business records. Create an Auth user through Supabase, then insert its matching `profiles` row and an `ADMIN` membership from a trusted SQL editor. Do not use public signup for administrator bootstrap. The migration contains no credentials.

## Run locally

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r services\api\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services\api --reload
```

In another terminal:

```powershell
cd apps\web
npm install
npm run dev
```

Open `http://localhost:3000/login`. The API health endpoint is `http://127.0.0.1:8000/api/v1/health`. Protected API endpoints require a valid Supabase access token and an active profile with an assigned application role.

## Phase 1 permissions

| Role | Profile | Directory read | Create department | Create role/employee | Admin check |
|---|---|---|---|---|---|
| Admin | Own | Yes | Yes | Yes | Yes |
| Training Manager | Own | Yes | No | Yes | No |
| Reviewer | Own | Yes | No | No | No |
| Manager | Own | Departments/roles; own team employees | No | No | No |
| Employee | Own | No directory access | No | No | No |

The API enforces server-side RBAC before each operation. Supabase RLS provides database-level protection for rows and writes. Client navigation visibility is not authorization. A missing, inactive, or roleless profile is denied. Initial Admin bootstrap is a trusted SQL operation because public self-registration cannot grant roles.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest services\api\tests -q
cd apps\web
npm run lint
npm run typecheck
npm run build
```

## RLS verification in a connected Supabase project

1. Confirm all six Phase 1 public tables have RLS enabled.
2. With an anonymous session, verify reads of profiles, roles, departments, employees, and audit logs return no rows.
3. With an active Employee token, verify only the employee's own profile and membership are readable; department/role directory and audit logs remain denied.
4. With a Manager token, verify only their own employee row and direct reports are visible in `employees`.
5. With a Training Manager token, verify role and employee access works but profile-role assignment and audit-log reads are denied.
6. With a Reviewer token, verify read access to directory data and denial of writes.
7. With an Admin token, verify authorized foundation writes create audit events; direct client inserts into `audit_logs` remain denied.
8. Set a profile to `INACTIVE` and confirm API access is denied even while the Supabase session remains valid.

The project owner reports that the migration was applied and all five role logins and dashboards were manually verified. The detailed live row-level RLS checks in `docs/PHASE1_RBAC_RLS_VERIFICATION.md` remain a separate manual verification procedure; login success does not itself prove every RLS policy.

## Phase 2 document intelligence (locked)

The Documents workspace accepts PDF and DOCX originals through FastAPI. Python validates file signatures, hashes actual bytes, extracts source-located text, and chunks it deterministically. The initial upload limit is 15 MB (`MAX_UPLOAD_BYTES`); set it consistently on FastAPI and the Next.js server. Phase 2 processing finalization requires a backend-only `SUPABASE_SERVICE_ROLE_KEY`; authoring and review remain user-JWT scoped. Never place that credential in `NEXT_PUBLIC_*` or the browser. OCR and embeddings are not used. Scanned/unextractable PDFs become `NEEDS_REVIEW`, not invented text. Only Admin/Training Manager can upload or submit; Reviewer/Admin can review, but cannot review their own version without explicit Admin override and a reason. Current-effective ground truth requires an approved, parsed, date-effective version, not merely the latest upload. Supabase is the infrastructure boundary for private Storage and PostgreSQL/RLS; parsing and chunking are portable Python logic.

Do **not** reapply `supabase/migrations/202609230002_document_intelligence.sql` automatically. The project owner applied it manually. Direct live RLS/Storage attack verification remains separately documented and pending. Phase 1's applied migration remains unchanged.
