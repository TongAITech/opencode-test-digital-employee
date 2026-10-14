# RC6 Wave 10 Qualification — CAT Diagnosis / Recovery

## Objective
Turn execution failure handling into a deterministic, evidence-backed recovery state machine. Eliminate free-form retries, retry storms, data swapping to green, and CAT queries without bounded correlation scope.

## Runtime invariants qualified
- every failed attempt remains in an append-only AttemptHistory; retries/repreparation create successor attempts instead of overwriting history
- failure diagnosis requires execution evidence before classification
- dedicated runtime-issued `FAILURE_DIAGNOSTIC` role/lease is required
- CAT is mandatory for L3 and L5 failures and for L1 only when the Case made a remote integration call
- CAT queries are bounded by application + time window + at least one request/trace/business identifier
- CAT capability must be READY for the exact diagnostic worker and TargetIdentity before query
- CAT query must produce a real tool-call ref and evidence ref
- secrets/tokens/passwords are forbidden in CAT correlation scopes and persisted CAT diagnosis signals
- valid preparation + real action + failed product assertion must classify as PRODUCT; relabeling it TRANSIENT/DATA/etc. is rejected
- retry is allowed only for TRANSIENT failures and is bounded by a retry budget
- DATA, PRECONDITION, AUTH, TOOL, ROUTE, ENVIRONMENT, DESIGN and PRODUCT each map to distinct recovery semantics
- PRODUCT is terminal: no retry and no reprepare-to-green
- UNKNOWN diagnoses fail closed

## Deterministic recovery vocabulary
- TRANSIENT -> `RETRY_SAME_STEP` (bounded)
- DATA -> `RESEARCH_OR_REBUILD_DATA`
- PRECONDITION -> `RECONSTRUCT_PRECONDITION`
- AUTH -> `REAUTH`
- TOOL -> `REPAIR_TOOL_BINDING`
- ROUTE -> `RECONCILE_ROUTE_BINDING`
- ENVIRONMENT -> `REQUALIFY_TARGET`
- DESIGN -> `REOPEN_DESIGN`
- PRODUCT -> `PRODUCT_DEFECT`
- UNKNOWN -> `BLOCKED_DIAGNOSIS`

## Required RED reproductions
1. wrong worker role attempts diagnosis -> reject
2. L3/L5 CAT required but CAT not READY -> block before query
3. CAT scope lacks correlation ID -> reject
4. CAT time window too wide -> reject
5. L1 local failure -> CAT not forced; L1 remote integration failure -> CAT forced
6. product assertion failure classified as transient -> reject
7. PRODUCT failure -> terminal defect, no retry/reprepare
8. TRANSIENT retry -> bounded; exhausted budget -> no further retry
9. attempt-history overwrite -> reject
10. semantic failure classes route to distinct recovery actions

## Qualification command
`python -m unittest discover -s tests -v`

## Freeze rule
Wave 10 may be frozen only when implementation, qualification tests and the Wave 10 GitHub Actions run are green on the same implementation commit.
