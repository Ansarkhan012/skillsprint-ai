import csv
import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import security
from app.comparison_report import COLUMNS, comparison_rows, to_csv
from app.main import app
from app.validation_repository import get_validation_repository
from test_generation_api import actor
from test_validation import check, fixture, module, PLAN
from test_validation_api import Store


def rows_for(plan, frozen):
    evidence, decision = check(plan, frozen)
    findings = [item.model_dump(mode="json") for item in evidence.findings]
    return comparison_rows(frozen, plan, findings, decision.status)


def test_verified_plan_matches_every_requirement_with_sources():
    frozen, plan = fixture()
    rows = rows_for(plan, frozen)
    assert len(rows) == 6
    assert {(r["match"], r["coverage_status"], r["traceability_status"], r["validation_status"]) for r in rows} == {
        ("MATCH", "COVERED", "TRACEABLE", "VERIFIED")}
    first = next(r for r in rows if r["requirement_id"] == str(frozen.requirements[0].revision_id))
    assert first["python_expected_sources"] == first["genai_sources"]
    assert first["python_expected_stage"] == first["genai_stage"]


def test_missing_and_unsupported_requirements_are_reported_as_mismatches():
    frozen, plan = fixture()
    for stage in plan["plan"]["stages"]:
        stage["modules"] = [m for m in stage["modules"] if m["module_id"] != str(UUID(int=605))]
    module(plan, 0)["requirement_ids"].append(str(UUID(int=79999)))
    rows = {r["requirement_id"]: r for r in rows_for(plan, frozen)}
    missing = rows[str(frozen.requirements[5].revision_id)]
    assert (missing["match"], missing["coverage_status"], missing["genai_modules"]) == ("MISMATCH", "MISSING", "NOT GENERATED")
    unknown = rows[str(UUID(int=79999))]
    assert (unknown["python_expected_mandatory"], unknown["coverage_status"]) == ("NOT IN APPROVED MATRIX", "UNSUPPORTED")
    assert "UNSUPPORTED_REQUIREMENT" in unknown["finding_codes"]


def test_csv_has_stable_columns_and_neutralises_formulas():
    frozen, plan = fixture()
    module(plan, 0)["title"] = "=HYPERLINK(\"http://evil\")"
    parsed = list(csv.reader(io.StringIO(to_csv(rows_for(plan, frozen)))))
    assert tuple(parsed[0]) == COLUMNS and len(parsed) == 7
    assert any(cell.startswith("'=HYPERLINK") for row in parsed for cell in row)


@pytest.fixture
def client():
    store = Store()
    frozen, _ = fixture()

    async def read(token, validation_id=None, plan_id=None):
        return {"id": str(validation_id), "generated_plan_id": str(PLAN), "findings": [],
                "decision": {"status": "VERIFIED"}}
    store.read = read
    app.dependency_overrides[security.current_principal] = lambda: actor()
    app.dependency_overrides[get_validation_repository] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_comparison_csv_endpoint_downloads_excel_compatible_csv(client):
    response = client.get(f"/api/v1/validation-runs/{UUID(int=700)}/comparison.csv",
                          headers={"Authorization": "Bearer opaque-test-token"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text[0] == chr(0xFEFF) and text[1:].startswith(",".join(COLUMNS))
    assert text.count("\r\n") == 7
