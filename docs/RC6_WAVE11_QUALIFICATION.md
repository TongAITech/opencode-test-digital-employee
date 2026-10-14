# RC6 Wave 11 Qualification — Empirical L1-L7 Execution Coverage Closure

## Objective
Close the gap between “test design looks sufficient” and “real execution actually covered the required changed/risky behavior”. Wave 11 never uses Case count or model-reported percentages as execution coverage truth.

## Layer-specific empirical coverage contracts
- L1: changed method / line / branch from JaCoCo; mutation from PIT when policy marks it applicable
- L2: DB object / SQL path / transaction / state transition from database evidence
- L3: route / method / schema / auth / business rule / error path from API runtime evidence
- L4: page / control / UI state / network / frontend branch from BrowserSkill or Playwright evidence
- L5: journey node / state transition / system hop / consistency assertion from E2E orchestrator evidence
- L6: workload / latency SLO / throughput SLO / error-rate SLO / resource envelope from k6 evidence
- L7: attack surface / authn / authz / input validation / security control / security error path from ZAP evidence

These are capability IDs rather than exact tool-version pins.

## Runtime invariants qualified
- every empirical coverage subject is explicit and has layer, dimension, risk, required flag, expected runtime refs and source refs
- only an integrity-verified real `ExecutionRecord` may produce coverage evidence
- coverage observation is bound to exact TargetIdentity, attempt, tc_id, Case version and layer
- cross-layer observations are forbidden
- coverage tool must be permitted for that professional layer/dimension, authorized by the worker lease and READY for the exact worker+target
- every observation requires a real tool-call ref and evidence ref
- runtime computes `covered` from expected refs vs actually observed refs; caller cannot self-declare coverage
- model/caller `coverage=1.0` style metrics are ignored
- missing/partial evidence creates an explicit gap; CRITICAL/HIGH gaps are separately surfaced
- applicable required subjects with no execution evidence cannot PASS
- optional capabilities such as mutation may be reported as optional gaps when policy marks them non-required; they are never silently counted as covered
- evidence from another TargetIdentity cannot close current-target gaps
- gaps with an existing frozen Case route to `DELTA_EXECUTION`; gaps with no Case route to the same layer `DELTA_DESIGN`
- re-evaluation after delta evidence must close the actual subject before sufficiency can PASS

## Required RED reproductions
1. caller claims 100% with no observations -> NOT_SUFFICIENT
2. partial runtime refs -> explicit empirical gap
3. cross-layer evidence -> reject
4. wrong tool for dimension -> reject
5. BLOCKED/non-integrity attempt -> cannot create coverage
6. evidence from another TargetIdentity -> does not close gap
7. high/critical uncovered subject -> closure blocked
8. optional mutation gap -> visible but non-blocking only when policy explicitly marks optional
9. existing-case gap -> DELTA_EXECUTION; no-case gap -> DELTA_DESIGN
10. delta evidence -> re-evaluation closes gap
11. all seven layers use professional evidence and can close independently

## Qualification command
`python -m unittest discover -s tests -v`

## Freeze rule
Wave 11 may be frozen only when implementation, these RED reproductions, and the Wave 11 GitHub Actions run are green on the same implementation commit.
