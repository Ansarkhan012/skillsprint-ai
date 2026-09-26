import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import register_error_handlers
from .models import AppRole, DepartmentCreate, EmployeeCreate, HealthResponse, MeResponse, Principal, RoleCreate
from .security import current_principal, require_roles
from .supabase import SupabaseGateway, get_gateway
from .documents import router as documents_router
from .rrm import router as rrm_router
from .generation_api import router as generation_router
from .validation_api import router as validation_router
from .upload_limit import UploadRequestLimit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(application: FastAPI):
    # The pool has no default user Authorization header. Every request supplies its own JWT.
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=50, max_keepalive_connections=20)) as client:
        application.state.supabase_http = client
        yield


app = FastAPI(title="SkillSprint AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(UploadRequestLimit)
settings = get_settings()


@app.middleware("http")
async def request_log(request: Request, call_next):
    correlation_id = str(uuid4())
    request.state.correlation_id = correlation_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    logging.getLogger("skillsprint.api").info(
        "request method=%s path=%s status=%d duration_ms=%.1f correlation_id=%s",
        request.method, request.url.path, response.status_code,
        (perf_counter() - started) * 1000, correlation_id,
    )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
register_error_handlers(app)
app.include_router(documents_router)
app.include_router(rrm_router)
app.include_router(generation_router)
app.include_router(validation_router)


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="skillsprint-api")


@app.get("/api/v1/me", response_model=MeResponse)
async def me(principal: Principal = Depends(current_principal)) -> MeResponse:
    return MeResponse(
        id=principal.profile.id,
        display_name=principal.profile.display_name,
        roles=sorted(principal.profile.roles),
    )


@app.get("/api/v1/admin/check")
async def admin_check(
    principal: Principal = Depends(require_roles(AppRole.ADMIN)),
) -> dict[str, bool]:
    return {"authorized": True}


@app.get("/api/v1/departments")
async def departments(
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> list[dict]:
    return await gateway.request(principal.token, "departments", {"select": "id,code,name,parent_id,status", "order": "name.asc,id.asc", "offset": str(offset), "limit": str(limit)})


@app.get("/api/v1/roles")
async def roles(
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> list[dict]:
    return await gateway.request(principal.token, "roles", {"select": "id,code,name,department_id,status", "order": "name.asc,id.asc", "offset": str(offset), "limit": str(limit)})


@app.get("/api/v1/employees")
async def employees(
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> list[dict]:
    return await gateway.request(principal.token, "employees", {"select": "id,employee_code,profile_id,role_id,department_id,experience_level,location_code,joining_date,training_status,manager_employee_id,profiles(display_name)", "order": "employee_code.asc,id.asc", "offset": str(offset), "limit": str(limit)})


@app.get("/api/v1/employees/{employee_id}")
async def employee_detail(employee_id: UUID,
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER, AppRole.REVIEWER, AppRole.MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> dict:
    rows = await gateway.request(principal.token, "employees", {"select": "id,employee_code,profile_id,role_id,department_id,experience_level,location_code,joining_date,training_status,manager_employee_id,profiles(display_name)", "id": f"eq.{employee_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "EMPLOYEE_NOT_FOUND")
    return rows[0]


@app.get("/api/v1/audit-events")
async def audit_events(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    principal: Principal = Depends(require_roles(AppRole.ADMIN)), gateway: SupabaseGateway = Depends(get_gateway),
) -> dict:
    rows = await gateway.request(principal.token, "audit_logs", {"select": "id,actor_profile_id,action,target_type,target_id,occurred_at", "order": "occurred_at.desc,id.desc", "offset": str(offset), "limit": str(limit + 1)})
    return {"items": rows[:limit], "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@app.post("/api/v1/departments", status_code=201)
async def create_department(
    data: DepartmentCreate,
    principal: Principal = Depends(require_roles(AppRole.ADMIN)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> dict:
    return await gateway.create(principal.token, "departments", data.model_dump(mode="json", exclude_none=True))


@app.post("/api/v1/roles", status_code=201)
async def create_role(
    data: RoleCreate,
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> dict:
    return await gateway.create(principal.token, "roles", data.model_dump(mode="json", exclude_none=True))


@app.post("/api/v1/employees", status_code=201)
async def create_employee(
    data: EmployeeCreate,
    principal: Principal = Depends(require_roles(AppRole.ADMIN, AppRole.TRAINING_MANAGER)),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> dict:
    return await gateway.create(principal.token, "employees", data.model_dump(mode="json", exclude_none=True))
