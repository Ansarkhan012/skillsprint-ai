"""Phase 3A.2 API boundary tests; database RPC integrity remains a live check."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models import AppRole, Principal, Profile
from app.rrm_repository import RRMRepository, get_rrm_repository
from app import security
from app import rrm_service


ROLE_ID = str(uuid4())
MATRIX_ID = str(uuid4())
CHUNK_ID = str(uuid4())
VERSION_ID = str(uuid4())
DOCUMENT_ID = str(uuid4())
CONFIG_ID = str(uuid4())


class FakeRepo:
    def __init__(self):
        self.calls = []
        self.stale = False
        self.self_review = False

    async def rows(self, token, table, params):
        self.calls.append(("rows", token, table, params))
        today = datetime.now(timezone.utc).date().isoformat()
        if table == "document_chunks":
            return [{"id": CHUNK_ID, "document_version_id": VERSION_ID, "content": "Complete training within 7 days",
                     "text_hash": sha256(b"Complete training within 7 days").hexdigest()}]
        if table == "document_versions":
            return [{"id": VERSION_ID, "document_id": DOCUMENT_ID, "version_label": "v1.0", "parse_status": "PARSED",
                     "review_status": "APPROVED", "effective_date": today, "expiry_date": None}]
        if table == "documents":
            return [{"id": DOCUMENT_ID, "document_code": "DOC_001", "title": "Policy", "status": "ACTIVE"}]
        if table == "requirements":
            return [{"id": str(uuid4()), "statement": "Training", "requirement_code": "REQ_01"}]
        if table == "role_requirement_matrices":
            return [{"id": MATRIX_ID, "role_id": ROLE_ID, "revision": 1, "status": "APPROVED", "current_edit": 1,
                     "lock_version": 2, "created_by": str(uuid4()), "submitted_by": str(uuid4()), "decided_by": str(uuid4()),
                     "decided_at": "2026-09-24T00:00:00Z", "admin_override": False, "decision_reason": None,
                     "snapshot_hash": "a" * 64}]
        if table in ("role_requirements", "requirement_dependencies", "rrm_issues", "rrm_issue_resolutions", "requirement_sources", "requirement_applicability"):
            return []
        return []

    async def rpc(self, token, name, payload):
        self.calls.append(("rpc", token, name, payload))
        if name == "current_effective_document_version":
            return [{"id": str(uuid4()) if self.stale else VERSION_ID}]
        if name == "get_rrm_ground_truth":
            if self.stale:
                raise HTTPException(409, "RRM_STALE_SNAPSHOT")
            return {"snapshot_hash": "a" * 64, "snapshot": {"entries": [1]}}
        if name == "edit_rrm_matrix":
            if self.stale:
                raise HTTPException(409, "RRM_EDIT_CONFLICT")
            return 3
        if name == "transition_rrm_matrix":
            if self.self_review:
                raise HTTPException(403, "RRM_SELF_REVIEW_FORBIDDEN")
            return payload["p_action"] + "TED" if payload["p_action"] == "SUBMIT" else "APPROVED"
        return str(uuid4())


def principal(role: AppRole) -> Principal:
    identity = uuid4()
    return Principal(user_id=identity, token="opaque-test-token", profile=Profile(
        id=identity, auth_user_id=identity, display_name="Test", status="ACTIVE", roles=frozenset({role})))


@pytest.fixture
def client():
    repo = FakeRepo()
    app.dependency_overrides[get_rrm_repository] = lambda: repo
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.ADMIN)
    with TestClient(app) as http:
        yield http, repo
    app.dependency_overrides.clear()


def candidate():
    return {"code": "REQ_01", "statement": "Complete training", "requirement_type": "MUST_COMPLETE",
            "category": "SECURITY", "mandatory": True, "chunk_ids": [CHUNK_ID], "scopes": [{"role_id": ROLE_ID}],
            "timing": {"state": "NOT_SPECIFIED"}}


def test_ambiguous_timing_blocks_readiness_even_after_issue_resolution(monkeypatch):
    requirement_id = str(uuid4())
    issue_id = str(uuid4())

    class MatrixRepo:
        async def rows(self, _token, table, _params):
            if table == "role_requirement_matrices":
                return [{"id": MATRIX_ID, "current_edit": 2, "status": "DRAFT"}]
            if table == "role_requirements":
                return [{"requirement_id": requirement_id, "sequence": 0}]
            if table == "rrm_issues":
                return [{"id": issue_id, "kind": "AMBIGUITY", "requirement_id": requirement_id}]
            if table == "rrm_issue_resolutions":
                return [{"issue_id": issue_id, "edit_no": 2}]
            return []

    async def details(_repo, _token, _ids):
        return {requirement_id: {"timing": {"state": "AMBIGUOUS", "original_text": "Within 7 days"}, "evidence": []}}

    monkeypatch.setattr(rrm_service, "requirement_details", details)
    result = asyncio.run(rrm_service.matrix_detail(MatrixRepo(), "opaque-test-token", uuid4()))
    assert result["issues"][0]["blocking"] is False
    assert result["readiness"]["blocking_codes"] == ["RRM_TIMING_MANUAL_REVIEW"]


@pytest.mark.parametrize("role,expected", [(AppRole.ADMIN, 201), (AppRole.TRAINING_MANAGER, 201),
                                           (AppRole.REVIEWER, 201), (AppRole.MANAGER, 403), (AppRole.EMPLOYEE, 403)])
def test_ambiguity_issue_creation_uses_user_jwt_and_existing_rbac(client, role, expected):
    http, repo = client
    app.dependency_overrides[security.current_principal] = lambda: principal(role)
    response = http.post(f"/api/v1/matrices/{MATRIX_ID}/issues", json={
        "expected_version": 13, "kind": "AMBIGUITY", "requirement_id": str(uuid4()),
        "detail": 'The source states "Within 7 days" without specifying the triggering event.',
    })
    assert response.status_code == expected
    calls = [call for call in repo.calls if call[0] == "rpc" and call[2] == "raise_rrm_issue"]
    assert (len(calls) == 1) == (expected == 201)
    if calls:
        assert calls[0][1] == "opaque-test-token"


@pytest.mark.parametrize("role,expected", [(AppRole.ADMIN, 201), (AppRole.TRAINING_MANAGER, 201),
                                          (AppRole.REVIEWER, 403), (AppRole.MANAGER, 403), (AppRole.EMPLOYEE, 403)])
def test_candidate_creation_rbac_and_user_jwt(client, role, expected):
    http, repo = client
    app.dependency_overrides[security.current_principal] = lambda: principal(role)
    response = http.post("/api/v1/requirements", json=candidate())
    assert response.status_code == expected
    calls = [item for item in repo.calls if item[0] == "rpc" and item[2] == "create_requirement_candidate"]
    assert (len(calls) == 1) == (expected == 201)
    if calls:
        assert calls[0][1] == "opaque-test-token"
        assert calls[0][3]["p_data"]["origin"] == "MANUAL"


def test_candidate_rejects_stale_source_without_rpc(client):
    http, repo = client
    repo.stale = True
    assert http.post("/api/v1/requirements", json=candidate()).status_code == 422
    assert not any(call[0] == "rpc" and call[2] == "create_requirement_candidate" for call in repo.calls)


def test_candidate_type_mandatory_mismatch_rejected(client):
    http, repo = client
    payload = candidate() | {"mandatory": False}
    assert http.post("/api/v1/requirements", json=payload).status_code == 422
    assert not repo.calls


def test_list_pagination_and_filters(client):
    http, repo = client
    response = http.get("/api/v1/requirements?offset=2&limit=5&origin=MANUAL&mandatory=true&search=training")
    assert response.status_code == 200
    params = next(call[3] for call in repo.calls if call[2] == "requirements")
    assert params["offset"] == "2" and params["limit"] == "6"
    assert params["origin"] == "eq.MANUAL" and params["mandatory"] == "eq.true"
    assert http.get("/api/v1/requirements?limit=101").status_code == 422


def test_matrix_create_edit_and_stale_edit(client):
    http, repo = client
    assert http.post(f"/api/v1/roles/{ROLE_ID}/matrices", json={"config_id": CONFIG_ID}).status_code == 201
    payload = {"expected_version": 2, "entries": [{"requirement_id": str(uuid4()), "sequence": 0}],
               "dependencies": [], "reason": "Source review completed"}
    assert http.patch(f"/api/v1/matrices/{MATRIX_ID}", json=payload).json()["lock_version"] == 3
    repo.stale = True
    response = http.patch(f"/api/v1/matrices/{MATRIX_ID}", json=payload)
    assert response.status_code == 409 and response.json()["code"] == "RRM_EDIT_CONFLICT"


def test_submit_reviewer_denied_and_independent_review_rpc(client):
    http, repo = client
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.TRAINING_MANAGER)
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/submit", json={"expected_version": 1}).status_code == 200
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/approve", json={"expected_version": 2}).status_code == 403
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.REVIEWER)
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/approve", json={"expected_version": 2}).status_code == 200
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/reject", json={"expected_version": 2, "reason": "   "}).status_code == 422
    rpc = [call for call in repo.calls if call[0] == "rpc" and call[2] == "transition_rrm_matrix"]
    assert [call[3]["p_action"] for call in rpc] == ["SUBMIT", "APPROVE"]


def test_admin_override_reason_and_membership(client):
    http, repo = client
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.REVIEWER)
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/approve", json={"expected_version": 2, "admin_override": True, "reason": "Emergency"}).status_code == 403
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.ADMIN)
    assert http.post(f"/api/v1/matrices/{MATRIX_ID}/approve", json={"expected_version": 2, "admin_override": True}).status_code == 403
    assert not any(call[0] == "rpc" and call[2] == "transition_rrm_matrix" for call in repo.calls)


def test_contributor_self_review_denial_from_authoritative_rpc(client):
    http, repo = client
    repo.self_review = True
    app.dependency_overrides[security.current_principal] = lambda: principal(AppRole.REVIEWER)
    result = http.post(f"/api/v1/matrices/{MATRIX_ID}/approve", json={"expected_version": 2})
    assert result.status_code == 403
    assert result.json()["code"] == "RRM_SELF_REVIEW_FORBIDDEN"


def test_ground_truth_success_and_stale_error(client):
    http, repo = client
    success = http.get(f"/api/v1/roles/{ROLE_ID}/ground-truth").json()
    assert success["snapshot_hash"] == "a" * 64
    assert success["approval"]["decided_at"] == "2026-09-24T00:00:00Z"
    repo.stale = True
    result = http.get(f"/api/v1/roles/{ROLE_ID}/ground-truth")
    assert result.status_code == 409 and result.json()["code"] == "RRM_STALE_SNAPSHOT"


def test_unauthenticated_and_inactive_fail_closed(client):
    http, _ = client
    app.dependency_overrides.pop(security.current_principal)
    assert http.get("/api/v1/requirements").status_code == 401
    app.dependency_overrides[security.current_principal] = lambda: (_ for _ in ()).throw(HTTPException(403, "PROFILE_INACTIVE_OR_MISSING"))
    assert http.get("/api/v1/requirements").status_code == 403


def test_rpc_errors_are_sanitized():
    import httpx
    request = httpx.Request("POST", "https://example.test/rpc")
    response = httpx.Response(400, json={"code": "22023", "message": "RRM_DOWNGRADE_EVIDENCE_MISMATCH"}, request=request)
    with pytest.raises(HTTPException) as exc:
        RRMRepository.check(response)
    assert exc.value.detail == "RRM_DOWNGRADE_EVIDENCE_MISMATCH"
    response = httpx.Response(500, json={"code": "XX000", "message": "internal secret data"}, request=request)
    with pytest.raises(HTTPException) as exc:
        RRMRepository.check(response)
    assert exc.value.detail == "RRM_SERVICE_UNAVAILABLE"


def test_ambiguous_timing_sql_error_remains_an_independent_422():
    import httpx
    request = httpx.Request("POST", "https://example.test/rpc/transition_rrm_matrix")
    response = httpx.Response(400, json={"code": "22023", "message": "RRM_TIMING_MANUAL_REVIEW"}, request=request)
    with pytest.raises(HTTPException) as exc:
        RRMRepository.check(response)
    assert exc.value.status_code == 422
    assert exc.value.detail == "RRM_TIMING_MANUAL_REVIEW"
