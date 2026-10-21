# RC7 -> RC8 Gap Matrix

Status: ACTIVE
Source: latest RC7 Reality Certification + field validation handoff.

## 1. Frozen RC7 certification summary
- RC7 Reality Certification: `CLOSED`
- Certification meaning: `CORE_CAPABILITIES_PROVEN_WITH_OPEN_REALITY_GAPS`
- `RC8_ENTRY_READY=YES`
- RC7 is **not** `FULLY_AUTONOMOUS_TEST_COMPLETE`
- L1: READY
- L2: READY
- L3: READY
- L4: PARTIAL
- L5: PARTIAL
- L6: BASELINE_ONLY
- L7: PARTIAL
- Completion: `TEST_PARTIALLY_EXECUTED`
- Release: `HOLD`
- Raw gaps: 49
- Canonical gaps after deduplication: 16
- Canonical severity distribution: P0=7, P1=5, P2=3, P3=1
- Human waivers in final certification: 0

Individual severity mapping is not guessed here; it must be copied from the final RC7 capability-cert artifact when available. The canonical names and required RC8 closure mechanisms below are frozen.

## 2. Canonical 16 gaps
| Canonical gap | RC8 closure mechanism | Target wave | Status |
|---|---|---|---|
| CG-TIME-VOCAB | canonical time semantics across plan/runtime/evidence/report; occurrence vs ingestion vs validation timestamps | W0 | OPEN |
| CG-TRUTH-CHAIN | R1 runtime truth -> projection -> report; prohibit plan/model-claim contamination | W0/W3 | OPEN |
| CG-EVIDENCE-REF | typed evidence identities, hash/provenance and Assertion binding | W0/W3 | OPEN |
| CG-PROVENANCE-OWNER | producer/node/worker/tool ownership for every runtime fact/artifact | W0/W1 | OPEN |
| CG-EXEC-KERNEL | preserve RC7 proven execution substrate, real Worker/tool execution, no Director-generated execution truth | W1/W2 | OPEN |
| CG-CODEGRAPH | capability migration + Java-change policy + snapshot/freshness/evidence binding | W2 | OPEN |
| CG-DESIGN-GATE | design sufficiency evaluator, iterative repair and downstream invalidation | W5 | OPEN |
| CG-DATA-LIFECYCLE | test-data discover/build/validate/lease/reuse/release lifecycle | W4/W5 | OPEN |
| CG-ENV-TRUTH | environment/capability reality probes; distinguish installed vs verified | W0/W1/W2 | OPEN |
| CG-COVERAGE | requirement/risk/verification-point coverage and execution feedback to design | W5 | OPEN |
| CG-DEFECT | defect truth, RCA/evidence/regression linkage and real-valid-defect objective | W5/W8 | OPEN |
| CG-WAIVER-HUMAN | explicit governed human gate/waiver semantics; no implicit “human needed” completion | W5 | OPEN |
| CG-COMPLETION-RELEASE | `PLAN_COMPLETE != TEST_SUFFICIENT`; completion/release gate based on runtime truth | W0/W5 | OPEN |
| GAP-ADD-03 | imported from RC7 final certification; exact final description must be copied verbatim from `capability-cert/final` before closure | W0 import | OPEN |
| GAP-ADD-06 | imported from RC7 final certification; exact final description must be copied verbatim from `capability-cert/final` before closure | W0 import | OPEN |
| GAP-ADD-10 | imported from RC7 final certification; exact final description must be copied verbatim from `capability-cert/final` before closure | W0 import | OPEN |

## 3. RC7 field/reality problems that must not disappear in the 16-gap abstraction
These are tracked explicitly even when they map into one or more canonical gaps.

| Field problem | RC8 handling | Status |
|---|---|---|
| Node-local self-loop was not visibly/provably closed | durable evaluator/gap/repair loop + UI attempt history | OPEN |
| Later-stage execution did not reliably route gaps back to the correct prior stage | central Gap Router + Dependency/Invalidation Engine | OPEN |
| Full-flow runs made it hard to understand what was actually tested | test-semantic model + TestRun/report product surfaces | OPEN |
| RC7 product pages were insufficient; user stopped relying on them | RC8 Product Baseline + sample-page gate + page-by-page acceptance | OPEN |
| High-quality API/auth/route analysis was lost with DSH session and later rerun degraded | verified central Knowledge + version/provenance + task-scoped resolver | OPEN |
| Session loss/context inflation/stall could lose work or degrade performance | Session != TestRun; checkpoints + durable state + context budget/rotation | OPEN |
| Director could do work itself instead of dispatching real Worker | execution producer policy + worker/tool provenance gate | OPEN |
| Plugin/tool installation could be mistaken for real capability | Capability Qualification state machine and reality probe | OPEN |
| CodeGraph could exist but not be used when required | capability/policy gate and evidence requirement | OPEN |
| 4A could regress to stale cookie/manual-history behavior | unified auth runtime skill/adapter; fresh auth and re-auth path | OPEN |
| API route guessing/404 behavior | business-flow capture + route knowledge + freshness/revalidation | OPEN |
| Test-data/precondition construction remained weak | data lifecycle and precondition builder | OPEN |
| L4/L5/L7 were partial and L6 baseline-only | layer-specific capability gates; no global green masking | OPEN |
| Evidence could be incomplete or semantically weak | typed Evidence Contract and Assertion binding | OPEN |
| Backend data/product UI could drift from runtime reality | projections must derive from R1/events and durable domain state | OPEN |
| Bank deployment/turnkey behavior could fail despite development success | package/clean-install/smoke/upgrade/restart gates | OPEN |

## 4. Gap closure state machine
Every gap uses:
`OPEN -> IMPLEMENTED -> REALITY_VERIFIED -> CLOSED`

`IMPLEMENTED` is not closure. Each gap must point to code, automated tests, reality evidence, and user-visible product projection where applicable.

## 5. RC8 entry rule
RC8 construction is authorized, but W0 must first close/lock the foundation portions that would otherwise contaminate all later architecture: runtime truth semantics, evidence contract, capability qualification, execution identity/provenance and completion semantics. Other RC7 gaps are closed during migration/loop/product waves rather than by building a second throwaway RC7 repair architecture.
