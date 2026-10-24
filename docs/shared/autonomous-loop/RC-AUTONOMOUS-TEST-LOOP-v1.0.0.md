# RC Autonomous Test Loop Contract v1.0.0

- Contract ID: `RC-AUTONOMOUS-TEST-LOOP`
- Version: `1.0.0`
- Design baseline: `RC7.1-N1-N10-FROZEN`
- Accepted RC7.1 starting SHA: `98d7ee59cb3caf760177d7aaa933ee70082a6ff3`
- Reality status: Controlled Engineering PASS; Bank Field Reality NOT_VERIFIED

This file is the normative shared semantic contract for RC7.1 and RC8. Chat history is not normative.

## Runtime truth and authority

R1 Event Stream is the unique Runtime Truth. AgentTeams owns Team/Member/Task ownership, claiming, collaboration and node-local specialist loops. RC7 Runtime owns Mission DAG, leases, side effects, evidence identity, deterministic gates, coverage reconciliation and global acceptance. Director orchestrates and accepts/rejects deliveries but MUST NOT impersonate or execute specialist work.

Forbidden: Team unavailable -> local/director specialist execution; model-authored PASS without deterministic proof; duplicate business side effects from AgentTeams and Runtime; stale evidence as current proof.

## Canonical nodes

- N1 Reality / Environment Recon
- N2 Requirement Analysis
- N3 Code Analysis
- N4 Test Design
- N5 Test Data / Preconditions
- N6 Script Build / Readiness
- N7 Coverage-Driven Autonomous Execution Closure
- N8 Failure Diagnosis / Recovery
- N9 Defect Evidence Closure
- N10 Mission Evidence / Global Convergence

## Canonical node loop

`Input -> Plan -> Execute -> Self Check -> Evidence Check -> Sufficiency -> Gap Detect -> Repair/Re-run/Supplement -> Re-evaluate -> READY_FOR_DIRECTOR_REVIEW -> Director/Runtime Gate -> PASS`

AgentTeams may advance at most to `READY_FOR_DIRECTOR_REVIEW`. Final PASS belongs to Director/Runtime authority. Repair preserves prior evidence and must produce delta. Budget exhaustion escalates; it never converts unfinished work to PASS.

## Canonical node states

`PENDING, TEAM_ASSIGNED, IN_PROGRESS, SELF_REVIEW, GAP_DETECTED, REPAIRING, READY_FOR_DIRECTOR_REVIEW, DIRECTOR_REJECTED, BLOCKED, PASS`

## Canonical test layers

- L1 CODE_UNIT
- L2 DB_COMPONENT
- L3 API_SERVICE
- L4 UI_BROWSER
- L5 CROSS_SYSTEM_E2E
- L6 PERFORMANCE
- L7 SECURITY

`API_CONTRACT` is an L3 testing dimension, not L5. `CAPABILITY_EXECUTION` is Runtime infrastructure, not L6.

## N1

Runtime + recon specialists establish current target/version/revision, tool/runtime capability, AgentTeams bootstrap, auth capability, route discovery and service reality. Configuration alone is not capability proof. Ready only with current probe evidence and explicit blockers.

## N2

Build authoritative source obligation denominator from BR/SR/TR/SST/design sources plus independent reviewer discoveries. Required artifacts include source manifest, obligation index, fact/rule catalog, trace matrix, behavior/state/decision models, constraints, conflicts/gaps and coverage ledger. Mandatory source/trace/evidence coverage is 100%; no unresolved mandatory/critical/high gap; independent review PASS.

## N3

Bind Git revision and CodeGraph snapshot. Account every changed file/symbol, graph seed/frontier and impact dimension. Java changes require CodeGraph. Model-declared tool calls are not proof. Graph closure is semantic; open frontier must be zero. Requirement<->Code reconciliation and current evidence are mandatory.

## N4

Test denominator = source + layer + risk + interaction obligations. A Case must link obligations, executable steps, conditions, deterministic Oracle, evidence requirements and execution contract. N4 designs data requirements; N5 prepares actual data. Mandatory obligations and critical/high depth/interactions must close with independent review.

## N5

Runtime-owned preparation loop: batch planning -> shared resource preparation -> per-case final preparation. Final sequence: `Select -> Verify -> Reserve -> Freshness Check -> Bind -> CASE_PREPARED_ATTEMPT`. One Case execution attempt owns one current PreparedAttempt. Mutable bank data defaults EXCLUSIVE. Historical cookie is forbidden; current 4A auth is required. Stale preparation is invalidated and recreated. DB_CREATE requires Human Gate. Cleanup/release/quarantine is lifecycle truth.

## N6

Translate frozen N4 Case into executable automation. `Frozen Case -> Script declares bindings -> N5 PreparedAttempt supplies values -> N7 Runtime injection`. Every case step maps to action, every Oracle check to assertion/runtime hook, every evidence requirement to collector. Script readiness includes technical and semantic implementation readiness but does not execute business assertion.

## N7

N7 is not Case Execution; N7 is Coverage-Driven Autonomous Execution Closure.

Three nested loops: Case Loop, Layer Coverage Loop, Cross-Layer Convergence Loop. Coverage obligation states: `UNEXECUTED, READY, EXECUTING, COVERED_PASS, COVERED_FAIL, BLOCKED, EXCLUDED_WITH_EVIDENCE`. COVERED_FAIL counts as coverage; Product Quality is separate.

Every layer uses a versioned CoverageDenominatorSnapshot. Denominator shrink requires evidence and approval. Cross-layer discoveries may expand/reopen earlier denominators and invalidate stale 100% receipts.

Layer targets:
- L1 target line coverage 100%; target logic coverage 100% (branch/decision outcomes + business condition true/false outcomes)
- L2 mandatory DB/state/data/transaction obligations 100%
- L3 mandatory API/contract/validation/auth/negative obligations 100%
- L4 mandatory UI/state/validation/role/navigation obligations 100%
- L5 mandatory cross-system E2E journeys/hops/side-effects/final state obligations 100%
- L6 planned performance scenarios executed 100% and thresholds evaluated 100%; threshold failure is Product Quality, not test incompleteness
- L7 security obligations executed 100% and findings disposed 100%; vulnerability is Product Quality, not test incompleteness

## N8

Every non-PASS must converge to evidence-backed root cause ownership and a valid recovery path. Failure classes: SCRIPT, SPEC/DESIGN, ORACLE, DATA, PRECONDITION, AUTH, ROUTE, TOOL, ENVIRONMENT, DEPENDENCY, TRANSIENT, FLAKY, PRODUCT, UNKNOWN. Coverage Gap is not a Failure Class.

Assertion failure is not PRODUCT. PRODUCT requires competing causes excluded from current-attempt Runtime evidence. Recovery across upstream nodes requires RepairWorkOrder + RepairReceipt + successor attempt + real re-execution. Direct retry is limited to proven transient/flaky failure.

Dynamic CAT policy: `REMOTE_BUSINESS_ACTION_DISPATCHED AND FAILURE_MAY_INVOLVE_BACKEND -> CAT REQUIRED`. This applies to L3/L4/L5/L6/L7 whenever the real backend business chain is entered. CAT requirement cannot be downgraded by an agent.

Routing: SCRIPT->N6; SPEC/DESIGN/ORACLE->N4; DATA/PRECONDITION/AUTH->N5; ROUTE source truth->N3 or binding->N6; TOOL/ENV/DEPENDENCY->Runtime/N1; TRANSIENT/FLAKY->N7; PRODUCT->N9; UNKNOWN stays in N8 evidence expansion.

## N9

TEST_FAIL is not a Defect. Entry requires a trusted PRODUCT_DEFECT Gap. Lifecycle: Candidate -> real independent Reproduction -> Qualification -> RCA -> Dedup -> Impact -> Severity -> Review -> Confirm/File -> Fix Verification -> Impact Regression -> Close/Reopen.

Reproduction uses a new PreparedAttempt and attempt ID. A reproduced Oracle FAIL makes reproduction task PASS with reproduced=true and MUST NOT emit another PRODUCT gap. RCA remains an evidence-backed hypothesis until engineering confirmation. Possible duplicate cannot auto-merge. Severity is policy-derived. A fix declaration is not verification. Closure requires real original-case post-fix PASS plus impact regression evidence.

## N10

N10 is Global Truth & Coverage Convergence, not report formatting. It rebuilds N1-N9 deliveries, Case fanout, L1-L7 objective closure, traceability, evidence completeness, execution conclusions, defect disposition and residual risk from R1. N10 detects/routes gaps but does not repair upstream artifacts.

Three independent outputs MUST remain separate:
1. TEST_SUFFICIENCY: have we tested enough against current denominator?
2. PRODUCT_QUALITY: what product state did testing discover?
3. RELEASE_RECOMMENDATION: given sufficiency + quality + risk + policy, should release proceed?

An open/confirmed product defect may coexist with TEST_SUFFICIENT. Final report is downstream of CONVERGED, derives only from R1 projection, cannot change Mission state and must preserve historical FAIL even after a defect is fixed/closed.

## Generic NodeDeliveryPackage

Required: mission_id, run_id, node_id, team_id, assignment_ids, member_ids, input_version, iteration_count, artifacts, evidence_refs, coverage_summary, unresolved_gaps, blocked_items, risk_summary, reviewer_result, sufficiency_result, terminal_status, completion_receipt, r1_refs.

## Gap routing

Reality/environment -> N1/Runtime; requirement denominator/source -> N2; code impact/graph -> N3; scenario/oracle/design -> N4; data/precondition/auth/reservation -> N5; script/binding/fixture/assertion implementation -> N6; coverage execution/transient -> N7; failure ownership/unknown diagnosis -> N8; product defect qualification/disposition -> N9; global convergence gaps -> N10 routes to actual owner.

DATA and PRECONDITION MUST NOT route to Script Readiness. AUTH MUST route to fresh Runtime Preparation. PRODUCT MUST NOT blind retry.

## Hard invariants

R1_IS_RUNTIME_TRUTH; REPORT_IS_NOT_RUNTIME_TRUTH; DIRECTOR_SELF_EXECUTION_FORBIDDEN; NO_LOCAL_EXECUTION_FALLBACK; MODEL_CANNOT_AUTHORITATIVELY_DECLARE_PASS; STALE_EVIDENCE_FORBIDDEN; ITERATION_MUST_PRODUCE_DELTA; AGENT_CANNOT_SELF_APPROVE_NODE; NODE_PASS_REQUIRES_DIRECTOR_ACCEPTANCE; COVERAGE_DENOMINATOR_CANNOT_SHRINK_WITHOUT_EVIDENCE; HISTORICAL_COOKIE_FORBIDDEN; CURRENT_AUTH_REQUIRED; ONE_CASE_ONE_ATTEMPT_ONE_PREPARED_ATTEMPT; ASSERTION_FAILURE_IS_NOT_PRODUCT; UNKNOWN_FAILURE_CANNOT_BE_BLINDLY_RETRIED; CAT_EVIDENCE_MUST_BELONG_TO_CURRENT_ATTEMPT; RETRY_REQUIRES_NEW_ATTEMPT_ID; TEST_FAIL_IS_NOT_DEFECT; FIX_DECLARATION_IS_NOT_FIX_VERIFICATION; TEST_SUFFICIENCY_IS_NOT_PRODUCT_QUALITY; RELEASE_RECOMMENDATION_IS_SEPARATE_FROM_TEST_SUFFICIENCY; MANDATORY_TRACEABILITY_REQUIRES_100_PERCENT; UNKNOWN_EXECUTION_FORBIDS_CONVERGENCE; FINAL_REPORT_REQUIRES_CONVERGED_MISSION; FINAL_REPORT_MUST_PRESERVE_HISTORICAL_FAILURE.
