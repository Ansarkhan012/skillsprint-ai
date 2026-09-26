"""Phase 4A read boundary. Every Supabase call uses the requesting user's JWT.

Stage-set tables are a Phase 4C dependency and are deliberately not claimed live.
"""

from datetime import date
from uuid import UUID

from fastapi import HTTPException

from .generation_models import (ApprovedMatrixInput, EmployeeGenerationContext, StageSet, StageSetItem)
from .rrm_models import Entry, PrecedenceConfig, Requirement, Scope, Source, Timing
from .rrm_repository import RRMRepository
from .rrm_service import bulk_rows, eligible_sources


class GenerationRepository:
    def __init__(self, rrm: RRMRepository):
        self.rrm = rrm

    async def employee(self, token: str, employee_id: UUID) -> EmployeeGenerationContext | None:
        rows = await self.rrm.rows(token, "employees", {
            "select": "id,profile_id,role_id,department_id,experience_level,location_code,joining_date",
            "id": f"eq.{employee_id}", "limit": "1",
        })
        if len(rows) != 1:
            return None
        row = rows[0]
        roles = await self.rrm.rows(token, "roles", {
            "select": "id,code,department_id,status", "id": f"eq.{row['role_id']}", "limit": "1",
        })
        departments = await self.rrm.rows(token, "departments", {
            "select": "id,code,status", "id": f"eq.{row['department_id']}", "limit": "1",
        })
        if (len(roles) != 1 or len(departments) != 1 or roles[0]["status"] != "ACTIVE"
                or departments[0]["status"] != "ACTIVE"
                or roles[0]["department_id"] not in (None, row["department_id"])):
            return None
        return EmployeeGenerationContext(
            employee_id=row["id"], profile_id=row["profile_id"], role_id=row["role_id"],
            role_code=roles[0]["code"], department_id=row["department_id"],
            department_code=departments[0]["code"], experience=row["experience_level"],
            location_code=row["location_code"], joining_date=row["joining_date"],
        )

    async def approved_matrix(self, token: str, role_id: UUID) -> ApprovedMatrixInput | None:
        rows = await self.rrm.rows(token, "role_requirement_matrices", {
            "select": "id,role_id,revision,current_edit,lock_version,status,snapshot_hash",
            "role_id": f"eq.{role_id}", "status": "eq.APPROVED", "limit": "2",
        })
        if len(rows) != 1:
            return None
        header = rows[0]
        result = await self.rrm.rpc(token, "get_rrm_ground_truth", {"p_matrix": header["id"]})
        if not isinstance(result, dict) or result.get("matrix_id") != header["id"] or result.get("snapshot_hash") != header["snapshot_hash"]:
            return None
        raw = result["snapshot"]
        if raw.get("matrix_id") != header["id"] or raw.get("role_id") != str(role_id) or raw.get("revision") != header["revision"] or raw.get("edit") != header["current_edit"]:
            return None
        requirements = []
        entries = []
        chunk_ids = []
        pinned_sources = {}
        for item in raw["entries"]:
            data = item["requirement"]
            scopes = tuple(Scope(**{key: scope.get(key) for key in ("role_id", "department_id", "location_code", "experience")})
                           for scope in item["scopes"])
            ids = tuple(UUID(source["chunk"]["id"]) for source in item["sources"])
            chunk_ids.extend(str(value) for value in ids)
            for source in item["sources"]:
                pinned_sources[source["chunk"]["id"]] = source
            requirements.append(Requirement(
                id=data["id"], code=data["requirement_code"], revision=data["revision"],
                predecessor_id=data["predecessor_id"], statement=data["statement"],
                requirement_type=data["requirement_type"], category=data["category"],
                mandatory=data["mandatory"], competency=data["competency"],
                assessment_required=data["assessment_required"], priority=data["priority"],
                timing=Timing.model_validate(data["timing"]), scopes=scopes,
                chunk_ids=ids, origin=data["origin"], author_id=data["created_by"],
            ))
            entries.append(Entry.model_validate({key: item["entry"].get(key) for key in (
                "requirement_id", "sequence", "stage_id", "exception_to", "downgrade_requested",
                "downgrade_justification", "downgrade_evidence")}))
        # Phase 3's RLS-protected resolver also checks the current-effective version.
        resolved = await eligible_sources(self.rrm, token, chunk_ids)
        sources = {}
        for chunk_id, item in resolved.items():
            chunk, version, document = item["chunk"], item["version"], item["document"]
            pinned = pinned_sources[chunk_id]
            if (version["id"] != pinned["version_id"] or document["id"] != pinned["document_id"]
                    or chunk["text_hash"] != pinned["chunk"]["text_hash"]):
                raise HTTPException(409, "RRM_STALE_SNAPSHOT")
            sources[UUID(chunk_id)] = Source(
                chunk_id=chunk_id, version_id=version["id"], document_id=document["id"],
                content=chunk["content"], text_hash=chunk["text_hash"],
                source_location=chunk["source_location"], document_sha256=version["sha256"],
                document_status=document["status"], parse_status=version["parse_status"],
                review_status=version["review_status"], effective_date=date.fromisoformat(version["effective_date"]),
                expiry_date=date.fromisoformat(version["expiry_date"]) if version["expiry_date"] else None,
                current_version_id=version["id"],
            )
        config = raw["config"]
        return ApprovedMatrixInput(
            id=header["id"], role_id=header["role_id"], revision=header["revision"],
            edit=header["current_edit"], lock_version=header["lock_version"], status=header["status"],
            snapshot_hash=header["snapshot_hash"], requirements=tuple(requirements), entries=tuple(entries),
            dependencies=tuple((UUID(value["dependent_id"]), UUID(value["prerequisite_id"]))
                               for value in raw["dependencies"]), sources=sources,
            configuration=PrecedenceConfig(ranks=config["ranks"], document_classes={
                UUID(item["document_id"]): item["authority_class"] for item in config["documents"]}),
            blocking_issues=tuple(item["issue"]["kind"] for item in raw["issues"] if item.get("resolution") is None),
        )

    async def stage_sets(self, token: str) -> tuple[StageSet, ...]:
        """Read the proposed Phase 4C tables; test fixtures supply them until 4C exists."""
        headers = await self.rrm.rows(token, "onboarding_stage_sets", {
            "select": "id,code,version,name,status", "status": "eq.ACTIVE", "limit": "3",
        })
        result = []
        for header in headers:
            links = await self.rrm.rows(token, "onboarding_stage_set_items", {
                "select": "stage_definition_id,sequence", "stage_set_id": f"eq.{header['id']}",
                "order": "sequence.asc", "limit": "101",
            })
            if len(links) > 100:
                raise ValueError("INVALID_STAGE_CONFIGURATION")
            stages = {row["id"]: row for row in await bulk_rows(
                self.rrm, token, "onboarding_stage_definitions", "id",
                [item["stage_definition_id"] for item in links],
                "id,code,revision,label,sequence,start_day,end_day")}
            items = tuple(StageSetItem(
                stage_definition_id=link["stage_definition_id"], code=stages[link["stage_definition_id"]]["code"],
                revision=stages[link["stage_definition_id"]]["revision"],
                label=stages[link["stage_definition_id"]]["label"], sequence=link["sequence"],
                start_day=stages[link["stage_definition_id"]]["start_day"],
                end_day=stages[link["stage_definition_id"]]["end_day"],
            ) for link in links)
            result.append(StageSet(**header, items=items))
        return tuple(result)
