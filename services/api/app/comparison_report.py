"""GenAI vs Python requirement-level comparison report (SRS Step 46, Deliverable 6).

Pure and read-only: every value comes from the frozen generation snapshot (Python
ground truth), the persisted plan (GenAI result), and the persisted validator
findings/JEV decision. Nothing is recomputed, repaired, or inferred here.
"""

import csv
import io

from .generation_models import GenerationInputSnapshot
from .rrm_rules import canonical_json

COLUMNS = (
    "requirement_code", "requirement_id", "role", "requirement_statement",
    "python_expected_mandatory", "python_expected_priority", "python_expected_stage", "python_expected_sources",
    "genai_modules", "genai_mandatory", "genai_priority", "genai_stage", "genai_sources",
    "match", "coverage_status", "traceability_status", "finding_codes", "validation_status", "explanation",
)
_TRACE_CODES = {"UNSUPPORTED_REQUIREMENT", "SOURCE_SUPPORT_MISSING", "SOURCE_REFERENCE_INVALID"}


def _source(document_version_id, chunk_id, locator) -> str:
    return f"{document_version_id}/{chunk_id}#{locator}"


def _joined(values) -> str:
    return "; ".join(dict.fromkeys(str(value) for value in values))


def comparison_rows(snapshot: GenerationInputSnapshot, content: dict, findings: list[dict],
                    decision_status: str) -> list[dict]:
    stages = {item.stage_definition_id: item.label for item in snapshot.stage_set.items}
    cited: dict[str, list[tuple[dict, str]]] = {}
    for stage in (content.get("plan") or {}).get("stages") or []:
        label = stage.get("label", "")
        for module in stage.get("modules") or []:
            for requirement_id in module.get("requirement_ids") or []:
                cited.setdefault(str(requirement_id), []).append((module, label))
    by_requirement: dict[str, list[dict]] = {}
    for finding in findings:
        by_requirement.setdefault(str(finding.get("requirement_id")), []).append(finding)

    rows = []
    known = set()
    for req in snapshot.requirements:
        key = str(req.revision_id)
        known.add(key)
        modules = cited.get(key, [])
        own = by_requirement.get(key, [])
        codes = sorted({f["code"] for f in own})
        blocking = [code for code in codes if not all(
            f["severity"] == "WARNING" for f in own if f["code"] == code)]
        rows.append({
            "requirement_code": req.code, "requirement_id": key, "role": snapshot.employee.role_code,
            "requirement_statement": req.statement,
            "python_expected_mandatory": req.mandatory, "python_expected_priority": req.priority,
            "python_expected_stage": stages.get(req.stage_definition_id, "Not assigned"),
            "python_expected_sources": _joined(_source(ref.document_version_id, ref.chunk_id, canonical_json(ref.locator))
                                               for ref in req.evidence),
            "genai_modules": _joined(module.get("title", "") for module, _ in modules) or "NOT GENERATED",
            "genai_mandatory": _joined(module.get("mandatory") for module, _ in modules),
            "genai_priority": _joined(module.get("priority") for module, _ in modules),
            "genai_stage": _joined(label for _, label in modules),
            "genai_sources": _joined(_source(ref.get("document_version_id"), ref.get("chunk_id"), ref.get("locator"))
                                     for module, _ in modules for ref in module.get("source_refs") or []),
            "match": "MATCH" if modules and not blocking else "MISMATCH",
            "coverage_status": "MISSING" if "MISSING_MANDATORY_REQUIREMENT" in codes
                               else "COVERED" if modules else "NOT_REQUIRED_NOT_GENERATED",
            "traceability_status": "UNTRACEABLE" if _TRACE_CODES & set(codes)
                                   else "TRACEABLE" if modules else "NOT_GENERATED",
            "finding_codes": _joined(codes), "validation_status": decision_status,
            "explanation": _joined(f["explanation"] for f in own) or ("Structured attributes and sources match."
                                                                       if modules else ""),
        })
    for key, own in by_requirement.items():
        if key in known or key == "None":
            continue
        rows.append({column: "" for column in COLUMNS} | {
            "requirement_id": key, "role": snapshot.employee.role_code,
            "python_expected_mandatory": "NOT IN APPROVED MATRIX",
            "genai_modules": _joined(module.get("title", "") for module, _ in cited.get(key, [])),
            "match": "MISMATCH", "coverage_status": "UNSUPPORTED", "traceability_status": "UNTRACEABLE",
            "finding_codes": _joined(sorted({f["code"] for f in own})), "validation_status": decision_status,
            "explanation": _joined(f["explanation"] for f in own),
        })
    return rows


def _cell(value) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet formula injection guard: generated/source text is data, never a formula.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(rows: list[dict]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(_cell(row.get(column)) for column in COLUMNS)
    return stream.getvalue()
