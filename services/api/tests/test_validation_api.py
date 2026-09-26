"""API tests use deterministic in-memory repositories only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import security, validation_service
from app.main import app
from app.models import AppRole
from app.generation_context import input_hash
from app.generation_models import PreflightResult
from app.rrm_rules import snapshot_hash
from app.validation_repository import ValidationRepository, get_validation_repository
from test_generation_api import actor
from test_validation import fixture, RUN, PLAN


class Store:
    def __init__(self):
        self.frozen,self.content=fixture()
        self.plan={"id":str(PLAN),"run_id":str(RUN),"status":"UNVERIFIED",
            "schema_version":"onboarding-plan/1.0.0","content":self.content,"content_hash":snapshot_hash(self.content)}
        self.run={"id":str(RUN),"employee_id":str(self.frozen.employee.employee_id),"employee_profile_id":None,
            "created_by":str(actor().profile.id),"status":"UNVERIFIED","completed_at":"2026-09-26T00:00:00Z",
            "input_snapshot":self.frozen.model_dump(mode="json"),"input_hash":input_hash(self.frozen),
            "projection_hash":"a"*64,"template_hash":"b"*64,"prompt_version":"test-fixture/1",
            "provider":"groq","model":"openai/gpt-oss-20b","schema_version":"onboarding-plan/1.0.0"}
        self.results=[]
        self.saved=None
        self.reviewed=[]

    async def load_plan(self,token,plan_id):
        if plan_id!=PLAN: raise HTTPException(404,"VALIDATION_PLAN_NOT_FOUND")
        assert token=="opaque-test-token"
        return self.plan,self.run

    async def persist(self,actor_id,plan_id,result):
        self.results.append(result)
        replay=self.saved is not None
        self.saved=self.saved or result
        return {"validation_run_id":str(UUID(int=700)),"idempotent_replay":replay,"decision":self.saved["decision"]["status"]}

    async def read(self,token,**kwargs):
        return {"validation_run_id":str(UUID(int=700))}

    async def review(self,token,validation_id,request):
        self.reviewed.append(request)
        return {"action":request.action}


@pytest.fixture
def setup(monkeypatch):
    store=Store()
    app.dependency_overrides[security.current_principal]=lambda:actor()
    app.dependency_overrides[get_validation_repository]=lambda:store
    async def current(*args):
        return PreflightResult(status="READY",snapshot=store.frozen,input_hash=input_hash(store.frozen))
    monkeypatch.setattr(validation_service,"preflight",current)
    with TestClient(app) as client: yield client,store
    app.dependency_overrides.clear()


def test_valid_request_replay_ignores_client_findings(setup):
    client,store=setup
    first=client.post(f"/api/v1/generated-plans/{PLAN}/validate",json={"decision":"VERIFIED","findings":[]})
    second=client.post(f"/api/v1/generated-plans/{PLAN}/validate")
    assert first.status_code==second.status_code==200
    assert first.json()["decision"]=="VERIFIED"
    assert second.json()["idempotent_replay"] is True
    assert store.saved["evidence"]["mandatory_total"]==6
    assert store.plan["status"]=="UNVERIFIED" and store.run["status"]=="UNVERIFIED"


@pytest.mark.parametrize("role",[AppRole.EMPLOYEE,AppRole.MANAGER,AppRole.REVIEWER])
def test_validation_requires_author_role(setup,role):
    client,store=setup
    app.dependency_overrides[security.current_principal]=lambda:actor(role)
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==403
    assert not store.results


def test_missing_auth_denied(setup):
    client,_=setup
    del app.dependency_overrides[security.current_principal]
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==401


@pytest.mark.parametrize("field,value",[("status","FAILED"),("completed_at",None),("input_hash","0"*64),
    ("projection_hash",None),("template_hash",None)])
def test_failed_or_invalid_generation_never_validates(setup,field,value):
    client,store=setup; store.run[field]=value
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==409
    assert not store.results


def test_no_plan_for_failed_run(setup):
    client,store=setup
    assert client.post("/api/v1/generated-plans/1a78da8c-a34a-4799-84ee-5257d6be4f1c/validate").status_code==404
    assert not store.results


def test_tampered_plan_hash_rejected(setup):
    client,store=setup; store.plan["content_hash"]="0"*64
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==409


def test_tm_cannot_validate_another_authors_plan(setup):
    client,store=setup
    app.dependency_overrides[security.current_principal]=lambda:actor(AppRole.TRAINING_MANAGER)
    store.run["created_by"]=str(UUID(int=999))
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==403


def test_inactive_profile_fails_closed(setup):
    client,store=setup; user=actor(); user.profile.status="INACTIVE"
    app.dependency_overrides[security.current_principal]=lambda:user
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==403


def test_employee_cannot_review(setup):
    client,store=setup
    app.dependency_overrides[security.current_principal]=lambda:actor(AppRole.EMPLOYEE)
    assert client.post(f"/api/v1/validation-runs/{UUID(int=700)}/review",
        json={"action":"APPROVE","reason":"reviewed"}).status_code==403
    assert not store.reviewed


def test_override_reason_required_and_extra_fields_forbidden(setup):
    client,store=setup
    for body in ({"action":"OVERRIDE"},{"action":"OVERRIDE","reason":"   "},
                 {"action":"OVERRIDE","reason":"reviewed","decision":"VERIFIED"}):
        assert client.post(f"/api/v1/validation-runs/{UUID(int=700)}/review",json=body).status_code==422
    assert not store.reviewed


def test_reviewer_override_denied_and_admin_reason_forwarded(setup):
    client,store=setup
    app.dependency_overrides[security.current_principal]=lambda:actor(AppRole.REVIEWER)
    url=f"/api/v1/validation-runs/{UUID(int=700)}/review"
    payload={"action":"OVERRIDE","reason":"Explicit human exception"}
    assert client.post(url,json=payload).status_code==403
    assert not store.reviewed
    app.dependency_overrides[security.current_principal]=lambda:actor(AppRole.ADMIN)
    assert client.post(url,json=payload).status_code==200
    assert store.reviewed[0].reason==payload["reason"]


def test_ground_truth_outage_is_not_a_verification(setup,monkeypatch):
    client,store=setup
    async def unavailable(*args): return PreflightResult(status="BLOCKED",blocker_codes=("GROUND_TRUTH_UNAVAILABLE",))
    monkeypatch.setattr(validation_service,"preflight",unavailable)
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").status_code==503
    assert not store.results


def test_stale_source_persists_manual_review(setup,monkeypatch):
    client,store=setup
    async def stale(*args): return PreflightResult(status="BLOCKED",blocker_codes=("STALE_SOURCE",))
    monkeypatch.setattr(validation_service,"preflight",stale)
    assert client.post(f"/api/v1/generated-plans/{PLAN}/validate").json()["decision"]=="MANUAL_REVIEW"


def test_trusted_rpc_uses_separate_key_and_review_uses_caller_jwt():
    from app.rrm_repository import RRMRepository
    from app.validation_models import ReviewRequest
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={"ok":True})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repo=ValidationRepository(RRMRepository("https://invalid.local","test-public",client),"test-trusted")
            await repo.persist(UUID(int=1),PLAN,{})
            await repo.review("test-user",UUID(int=700),ReviewRequest(action="OVERRIDE",reason="Documented exception"))
    asyncio.run(scenario())
    assert calls[0].headers["Authorization"]=="Bearer test-trusted"
    assert calls[1].headers["Authorization"]=="Bearer test-user"
    assert calls[0].url.path.endswith("/record_python_validation")
    assert calls[1].url.path.endswith("/review_validated_plan")
