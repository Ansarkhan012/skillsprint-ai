from enum import StrEnum
from uuid import UUID

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class AppRole(StrEnum):
    ADMIN = "ADMIN"
    TRAINING_MANAGER = "TRAINING_MANAGER"
    REVIEWER = "REVIEWER"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"


class Profile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    auth_user_id: UUID
    display_name: str
    status: str
    roles: frozenset[AppRole]


class Principal(BaseModel):
    user_id: UUID
    token: str
    profile: Profile


class HealthResponse(BaseModel):
    status: str
    service: str


class MeResponse(BaseModel):
    id: UUID
    display_name: str
    roles: list[AppRole]


class Department(BaseModel):
    id: UUID
    code: str
    name: str
    parent_id: UUID | None = None
    status: str


class RoleRecord(BaseModel):
    id: UUID
    code: str
    name: str
    department_id: UUID | None = None
    status: str


class Employee(BaseModel):
    id: UUID
    employee_code: str
    profile_id: UUID | None = None
    role_id: UUID
    department_id: UUID
    experience_level: str
    location_code: str | None = None
    joining_date: str
    manager_employee_id: UUID | None = None
    training_status: str


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Z0-9_-]{2,32}$")
    name: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Z0-9_-]{2,32}$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    department_id: UUID | None = None


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_code: str = Field(min_length=1, max_length=40)
    profile_id: UUID | None = None
    role_id: UUID
    department_id: UUID
    experience_level: str = Field(pattern=r"^(BEGINNER|INTERMEDIATE|ADVANCED)$")
    location_code: str | None = None
    joining_date: date
    manager_employee_id: UUID | None = None
