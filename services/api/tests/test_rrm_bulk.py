"""RRM bulk-read equivalence, request-count, and caller-JWT regression tests."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.rrm import evidence_chunks
from app.rrm_repository import RRMRepository
from app.rrm_service import eligible_sources, matrix_detail, relation_rows, requirement_detail, resolve_sources
from app.supabase import SupabaseGateway


MATRIX = str(UUID(int=1))
REQ_A, REQ_B = str(UUID(int=2)), str(UUID(int=3))
CHUNKS = [str(UUID(int=index)) for index in range(10, 14)]
VERSION, DOCUMENT = str(UUID(int=20)), str(UUID(int=21))
TOKEN = "opaque-user-jwt"


class BulkRepo:
    def __init__(self):
        self.calls = []
        self.today = datetime.now(timezone.utc).date().isoformat()
        self.current = VERSION
        self.approved = True
        self.visible = set(CHUNKS)
        self.text = "Security Awareness Training"
        self.tables = {
            "role_requirement_matrices": [{"id": MATRIX, "status": "DRAFT", "current_edit": 1}],
            "role_requirements": [{"matrix_id": MATRIX, "edit_no": 1, "requirement_id": REQ_A, "sequence": 0},
                                  {"matrix_id": MATRIX, "edit_no": 1, "requirement_id": REQ_B, "sequence": 1}],
            "requirement_dependencies": [{"matrix_id": MATRIX, "edit_no": 1,
                                          "dependent_id": REQ_B, "prerequisite_id": REQ_A}],
            "rrm_issues": [], "rrm_issue_resolutions": [],
            "requirements": [{"id": REQ_A, "requirement_code": "SECURITY_TRAINING", "revision": 1},
                             {"id": REQ_B, "requirement_code": "OTHER", "revision": 1}],
            "requirement_sources": [{"requirement_id": REQ_A, "chunk_id": chunk} for chunk in CHUNKS[:3]]
                                   + [{"requirement_id": REQ_B, "chunk_id": CHUNKS[3]}],
            "requirement_applicability": [{"requirement_id": REQ_A, "ordinal": 1, "role_id": None},
                                           {"requirement_id": REQ_B, "ordinal": 1, "role_id": None}],
            "document_chunks": [{"id": chunk, "document_version_id": VERSION, "content": self.text,
                                 "text_hash": sha256(self.text.encode()).hexdigest(),
                                 "heading": "Training", "source_location": {"table": 1, "row": index, "cell": 1}}
                                for index, chunk in enumerate(CHUNKS, start=1)],
            "document_versions": [{"id": VERSION, "document_id": DOCUMENT, "version_label": "v1.0",
                                   "parse_status": "PARSED", "review_status": "APPROVED",
                                   "effective_date": self.today, "expiry_date": None}],
            "documents": [{"id": DOCUMENT, "document_code": "TEST-RW-001", "title": "Policy", "status": "ACTIVE"}],
        }

    async def rows(self, token, table, params):
        self.calls.append((token, table, params))
        rows = self.tables[table]
        for key, value in params.items():
            if value.startswith("in.("):
                wanted = set(value[4:-1].split(","))
                rows = [row for row in rows if row.get(key) in wanted]
            elif value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key)) == value[3:]]
        if table == "document_chunks":
            rows = [row for row in rows if row["id"] in self.visible]
        if table == "document_versions" and not self.approved:
            rows = [{**row, "review_status": "SUBMITTED"} for row in rows]
        columns = params["select"].split(",")
        offset = int(params.get("offset", "0"))
        rows = rows[offset:offset + int(params.get("limit", "1000"))]
        return [{column: row[column] for column in columns if column in row} for row in rows]

    async def rpc(self, token, name, payload):
        self.calls.append((token, name, payload))
        assert name == "current_effective_document_version"
        assert payload["p_on_date"] == self.today
        return [{"id": self.current}]


def execute(coro):
    return asyncio.run(coro)


def test_requirement_detail_bulk_preserves_evidence_traceability_and_count():
    repo = BulkRepo()
    result = execute(requirement_detail(repo, TOKEN, UUID(REQ_A)))
    assert result["requirement_code"] == "SECURITY_TRAINING"
    assert [item["chunk"]["id"] for item in result["evidence"]] == CHUNKS[:3]
    assert all(item["current_eligible"] for item in result["evidence"])
    assert result["evidence"][0]["chunk"]["source_location"] == {"table": 1, "row": 1, "cell": 1}
    assert result["scopes"] == [{"ordinal": 1, "role_id": None}]
    assert len(repo.calls) == 7  # requirement, links, scopes, chunks, version, document, current RPC
    assert all(call[0] == TOKEN for call in repo.calls)


def test_matrix_detail_bulk_preserves_entries_dependencies_and_readiness():
    repo = BulkRepo()
    result = execute(matrix_detail(repo, TOKEN, UUID(MATRIX)))
    assert [row["requirement_id"] for row in result["entries"]] == [REQ_A, REQ_B]
    assert result["dependencies"] == [{"dependent_id": REQ_B, "prerequisite_id": REQ_A}]
    assert set(result["requirements"]) == {REQ_A, REQ_B}
    assert len(result["requirements"][REQ_A]["evidence"]) == 3
    assert result["readiness"]["blocking_codes"] == []
    assert len(repo.calls) == 12  # fixed for two entries/four chunks/one document
    assert all(call[0] == TOKEN for call in repo.calls)


def test_matrix_detail_reads_all_dependency_and_issue_pages():
    repo = BulkRepo()
    repo.tables["requirement_dependencies"] = [
        {"matrix_id": MATRIX, "edit_no": 1, "dependent_id": str(UUID(int=1000 + i)),
         "prerequisite_id": REQ_A} for i in range(1101)]
    repo.tables["rrm_issues"] = [
        {"id": str(UUID(int=3000 + i)), "matrix_id": MATRIX} for i in range(102)]
    repo.tables["rrm_issue_resolutions"] = [
        {"issue_id": issue["id"], "matrix_id": MATRIX, "edit_no": 1}
        for issue in repo.tables["rrm_issues"][:-1]]
    result = execute(matrix_detail(repo, TOKEN, UUID(MATRIX)))
    assert len(result["dependencies"]) == 1101
    assert len(result["issues"]) == 102
    assert not any(issue["blocking"] for issue in result["issues"][:-1])
    assert result["issues"][-1]["blocking"]
    assert "RRM_UNRESOLVED_ISSUE" in result["readiness"]["blocking_codes"]
    assert all(call[0] == TOKEN for call in repo.calls)


def test_relation_read_limit_fails_closed_instead_of_returning_partial_data():
    repo = BulkRepo()
    repo.tables["rrm_issues"] = [{"id": str(i)} for i in range(101)]
    with pytest.raises(HTTPException) as exc:
        execute(relation_rows(repo, TOKEN, "rrm_issues", {"select": "id", "order": "id.asc"}, maximum=100))
    assert exc.value.detail == "RRM_MATRIX_DETAIL_LIMIT"


@pytest.mark.parametrize("state", ["outdated", "unapproved", "missing_chunk", "bad_hash",
                                   "future", "expired", "inactive_document", "failed_parse"])
def test_bulk_source_eligibility_fails_closed_without_losing_history(state):
    repo = BulkRepo()
    if state == "outdated":
        repo.current = str(UUID(int=99))
    elif state == "unapproved":
        repo.approved = False
    elif state == "missing_chunk":
        repo.visible.remove(CHUNKS[0])
    elif state == "bad_hash":
        repo.tables["document_chunks"][0]["text_hash"] = "0" * 64
    elif state == "future":
        repo.tables["document_versions"][0]["effective_date"] = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    elif state == "expired":
        repo.tables["document_versions"][0]["expiry_date"] = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    elif state == "inactive_document":
        repo.tables["documents"][0]["status"] = "INACTIVE"
    else:
        repo.tables["document_versions"][0]["parse_status"] = "FAILED"
    resolved = execute(resolve_sources(repo, TOKEN, [CHUNKS[0]]))[CHUNKS[0]]
    assert resolved["current_eligible"] is False
    assert resolved["chunk_id"] == CHUNKS[0]
    if state == "missing_chunk":
        assert resolved["chunk"] is None
    else:
        assert resolved["chunk"]["source_location"] == {"table": 1, "row": 1, "cell": 1}
    with pytest.raises(HTTPException) as exc:
        execute(eligible_sources(repo, TOKEN, [CHUNKS[0]]))
    assert exc.value.status_code == 422


def test_pooled_http_client_keeps_auth_headers_per_user():
    seen = []

    def transport(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json=[])

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            repo = RRMRepository("https://example.test", "public", client)
            gateway = SupabaseGateway("https://example.test", "public", client)
            await repo.rows("user-one", "requirements", {"select": "id"})
            await repo.rows("user-two", "requirements", {"select": "id"})
            await gateway.request("user-three", "profiles", {"select": "id"})
            assert repo.client is gateway.client is client
            assert "authorization" not in client.headers

    execute(check())
    assert [header for _, header in seen] == ["Bearer user-one", "Bearer user-two", "Bearer user-three"]


@pytest.mark.parametrize("failure,expected_type,expected_status,received", [
    ("status", "HTTPStatusError", "503", "True"),
    ("timeout", "ReadTimeout", "None", "False"),
    ("json", "JSONDecodeError", "200", "True"),
])
def test_profile_read_failure_logs_only_safe_diagnostics(caplog, failure, expected_type, expected_status, received):
    def transport(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream detail")
        if failure == "json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(503, json={"message": "private upstream detail"})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            gateway = SupabaseGateway("https://example.test", "public", client)
            with pytest.raises(HTTPException) as exc:
                await gateway.request("private-user-token", "profiles", {"select": "id"})
            assert exc.value.status_code == 503
            assert exc.value.detail == "DATA_SERVICE_UNAVAILABLE"
            assert not client.is_closed

    execute(check())
    diagnostics = [record.message for record in caplog.records if record.name == "skillsprint.supabase"]
    assert len(diagnostics) == 1
    assert "table=profiles" in diagnostics[0]
    assert f"exception_type={expected_type}" in diagnostics[0]
    assert f"upstream_status={expected_status}" in diagnostics[0]
    assert f"response_received={received}" in diagnostics[0]
    assert "client_closed=False" in diagnostics[0]
    assert "private-user-token" not in diagnostics[0]
    assert "private upstream detail" not in diagnostics[0]


def test_same_pool_recovers_after_upstream_read_failure_and_keeps_user_headers_isolated():
    seen = []

    def transport(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(503 if len(seen) == 1 else 200, json=[])

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            gateway = SupabaseGateway("https://example.test", "public", client)
            with pytest.raises(HTTPException):
                await gateway.request("user-one", "profiles", {"select": "id"})
            assert await gateway.request("user-two", "profiles", {"select": "id"}) == []
            assert "authorization" not in client.headers

    execute(check())
    assert seen == ["Bearer user-one", "Bearer user-two"]


def test_application_closes_shared_http_pool():
    with TestClient(app) as client:
        pool = app.state.supabase_http
        assert not pool.is_closed
        assert client.get("/api/v1/health").status_code == 200
    assert pool.is_closed


def test_repeated_lifespans_own_distinct_closed_pools_without_default_authorization():
    previous = None
    for _ in range(3):
        with TestClient(app) as client:
            pool = app.state.supabase_http
            assert pool is not previous
            assert not pool.is_closed
            assert "authorization" not in pool.headers
            assert client.get("/api/v1/health").status_code == 200
        assert pool.is_closed
        asyncio.run(pool.aclose())  # Repeated cleanup remains a no-op.
        assert pool.is_closed
        previous = pool


def test_evidence_chunk_page_has_bounded_request_count():
    from types import SimpleNamespace

    repo = BulkRepo()
    result = execute(evidence_chunks(UUID(VERSION), 0, 50, SimpleNamespace(token=TOKEN), repo))
    assert [row["id"] for row in result["items"]] == CHUNKS
    assert len(repo.calls) == 4  # page chunks reused; versions, documents, one current RPC
    assert all(call[0] == TOKEN for call in repo.calls)
