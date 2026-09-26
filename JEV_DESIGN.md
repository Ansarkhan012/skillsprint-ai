# JEV Deterministic Decision Engine

Status: **Phase 5 foundation implemented: jev/1.0.0; pending migration and human review.** JEV is pure Python and cannot alter evidence. The authoritative table is `services/api/app/jev.py`.

Implemented precedence: CONTRADICTORY (timing/structured contradiction/dependency errors) → UNSUPPORTED (unknown requirements or missing/invalid grounding) → MANUAL_REVIEW (unresolved timing, stale data, applicability, structure or invalid duplication) → INCOMPLETE (missing mandatory coverage). First matching blocking row wins. Only consistent DUPLICATE_REQUIREMENT is an explicitly allowed warning. VERIFIED_WITH_WARNING/VERIFIED require positive structural/current-input invariants, nonzero mandatory count and complete grounded coverage, with no blocker. No scores or AI confidence decide status.

Human disposition stays separate. Approval requires verified JEV and current data; Admin override records reason/actor and retains original JEV. Phase 4 plans stay UNVERIFIED. Regeneration is only a recorded request. The conceptual table below is design history; its retry/reporting/publication features are not additional implementation claims.

## Input and output

Input: immutable validation run, issue list, calculated metrics, source validity, retry count, and rule-set version. Output: `status`, `matched_rule_id`, ordered `reason_codes`, human-readable reasons, evidence/issue IDs, recommended action, and timestamp.

## Ordered decision table

First matching rule wins. A higher row cannot be weakened by a lower row.

| Priority | Evidence predicate | Decision | Action |
|---:|---|---|---|
| 1 | Any unresolved critical contradiction | `CONTRADICTORY` | Lock finalization; human review |
| 2 | Any unsupported mandatory factual item | `UNSUPPORTED` | Lock finalization; human review/remove item |
| 3 | Invalid, missing, expired, obsolete, inaccessible, or ambiguous critical source; validator uncertainty on a critical claim | `MANUAL_REVIEW` | Human source review |
| 4 | Mandatory coverage below 100%; missing mandatory checklist/task/assessment evidence; valid targeted retries remain | `INCOMPLETE` | Targeted regeneration, then revalidate |
| 5 | Mandatory coverage below 100% after retry limit | `INCOMPLETE` | Human review; no further automatic retry |
| 6 | No blocking issue; only non-critical warnings | `VERIFIED_WITH_WARNING` | Allow review/finalization with visible warnings |
| 7 | 100% mandatory coverage, mandatory traceability 100%, valid current sources, no unresolved contradiction/unsupported/blocking issue | `VERIFIED` | Permit final approval/publication |

`VERIFIED` is not inferred from absence of errors alone; all positive invariants must be present. Detailed SRS labels such as `REQUIREMENT_MISSING`, `OUTDATED_SOURCE`, and `SOURCE_SUPPORT_MISSING` are validation issue codes mapped into these six decisions.

## Explainability record

Example:

```json
{
  "status": "INCOMPLETE",
  "matched_rule_id": "JEV-004",
  "rule_set_version": "1.0.0",
  "reason_codes": ["MANDATORY_COVERAGE_BELOW_100"],
  "reasons": ["2 of 12 mandatory requirements are absent (83.33%)."],
  "validation_issue_ids": ["uuid-1", "uuid-2"],
  "action": "TARGETED_REGENERATION",
  "target_requirement_ids": ["REQ-004", "REQ-009"]
}
```

Percentages use stored numerator/denominator and a documented rounding method; decisions compare integers where possible. Every execution stores an input evidence hash so the decision can be reproduced.

## Workflow guards

- A plan revision cannot become final without JEV plus any required human approval.
- Editing or regeneration creates a new revision and invalidates prior finalization for that revision only.
- Reviewer override never rewrites JEV status. It records an authorized workflow disposition, required reason, actor, and linked original decision.
- Critical contradiction or unsupported mandatory content requires review even if coverage is 100%.
- Retry budgets are application configuration and audited; JEV only recommends the next action.

## Tests

Use table-driven unit tests for every row, boundary coverage at 0/99.99/100%, precedence tests with multiple simultaneous issues, determinism/replay tests, invalid-input fail-closed tests, and property tests proving `VERIFIED` cannot occur when a blocking predicate is true.
