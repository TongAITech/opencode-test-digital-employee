# Mission control independent incremental raw-source review

**Current decision: LOCAL COMPONENT REVIEW PASS — FOUR REPORTED P1 CLOSED.** No Architecture/HARD blocker; continue ordinary implementation without user confirmation. This is the Mission pause/continue/stop component, not full C1, C2 or C3 qualification. Prior General file/R1 and Primary reviews remain preserved.

## P1: stale admitted control and no-effect crash can change newer state

`apply_control` does not bind an admission-time Mission sequence or control generation to the durable receipt. When no APPLIED command exists it reads the latest Mission head and manufactures a new CAS. Consequently an earlier admitted continue can run after a newer pause and resume that Mission. Separately, the already-in-target-state path only creates an interaction completion. A crash before that completion leaves no immutable control decision; later recovery may execute a new transition against changed state.

Independent `mission-control-independent-replay.json` uses real temporary R1 storage with Host protocol fixtures: capture continue while ACTIVE; apply newer pause; interrupt receipt completion of an already-PAUSED pause; execute the old continue (ACTIVE); recover the no-effect pause (a new PAUSE command is emitted). This exercises the trusted apply/recovery seam, not a claim that the current full product lock admits concurrent Director requests. It is relevant before background receipt recovery is connected and before stale-operation safety can be claimed.

Minimum repair: durable expected control generation/target state or equivalent freshness contract, including no-effect decisions. A recovered operation must replay its original durable decision or fail stale, rather than reinterpret the newest Mission state. The already APPLIED command path is the right direction: it verifies target/type/actor/payload and recovers the original command reference and transition sequence.

## P1: control is lost behind a long admitted effect

Both effect and pause use the same coordination lock, whose default wait is five seconds. Claiming the control occurs only after acquiring that lock. An admitted effect lasting longer than this makes pause time out before recording a durable receipt. Once the effect drains, the Mission remains ACTIVE and no background receipt exists to recover.

Independent `mission-control-long-effect.json`: real R1 plus an injected blocking physical-call boundary returned RUNTIME_COORDINATION_BUSY after 5.01 seconds, durable_receipt=null, Mission ACTIVE after releasing the effect. The existing drain test caps its synthetic effect at three seconds, so it cannot detect this failure. Root must preserve the authorized pending pause durably before waiting for a long effect, with coherent fencing/drain/recovery ordering, or provide another evidenced durable mechanism. A larger finite timeout alone does not establish recovery or responsive Primary behavior. Product entry also takes the same outer lock, so repairing only the inner helper is insufficient for actual ingress.

## Positive findings and validation boundaries

Independently ran the current eight Mission-control tests: **8 tests / OK / 2.688s**. The tests establish one Mission across pause/continue/stop, zero direct provider dispatch, query without event creation, duplicate same-operation thread serialization, command-before-receipt recovery without a second pause, immutable changed-request rejection, paused G4 execute/resume denial, short admitted-effect drain, and preserved PAUSED G2.1 Session provisioning. They do not establish process-level dual-controller recovery or long-effect durability. The underlying file lock supports processes by source inspection; this suite only uses threads.

Literal scope control removes only previously validated exact target values, then still requires an explicit control phrase. Subject resolution checks exact normalized scope, preventing simple version-prefix or partial-scope widening. The positive multi-Mission case proves selected PF3.0.0 is paused; strengthen its oracle by checking the unrelated Mission remains ACTIVE and both canonical heads, plus mismatched/ambiguous scope negatives. No concrete scope bypass was reproduced in this pass.

G4 public execute and complete-human-takeover calls now reject non-ACTIVE Missions inside the effect lock; product domain calls with Mission IDs likewise guard mutation. PAUSED/BLOCKED G2.1 provisions are preserved. Background Gate candidates are filtered by active state and final complete takeover rechecks under lock. Actual worker Host ownership checks remain OPEN as declared; model-supplied Session binding fields are not upgraded into trustworthy callers by this patch.

Other explicitly retained work: continue currently commits ACTIVE only; autonomous task wake/progress is C3 OPEN. Background control receipt recovery is not connected. Expired Host input blocks the hosted path even if an applied command merely needs receipt reconciliation; background recovery must distinguish reconstructing an already committed transition from applying a new expired request. Existing candidate lifetime budgets and unresolved-receipt handling must not silently strand control recovery.

The tests correctly label transport/effect fixtures and R1-only transitions. No real Windows, bank, full C1 or L4 PASS is inferred. TASK_DIFFICULTY=HARD; REASONING_RECOMMENDATION=HIGH for the lock/authority/recovery fix.

## Incremental repair recheck

Independently ran updated controls suite: **14 tests / OK / 10.604s**. Original two findings are closed for this component window: claim atomically records a second control-intent event with admission sequence, lifecycle generation, original state and no-effect decision; replaying an old no-op is explicitly historical and cannot issue a new transition, and changed-generation effectful controls complete as REJECTED. Intake and Primary authority mutexes are separated from the physical-effect mutex; long-call pause returns CONTROL_PENDING with durable claim, blocks subsequent G4 effects, and the first control-loop step recovers without another user turn. The updated suite exercises the actual product entry as well as an effect lasting beyond five seconds.

Independent `mission-control-event-compatibility.json` additionally injected interruption before the second control-intent event reducer: claim and intent both rolled back, leaving no receipt. After normal preparation, an older event-owner composition rejected compatibility checking, rebuild and a new Mission write with ROOT_EVENT_UNSUPPORTED, with complete database dump unchanged. This is a composition test, not execution of a historical release binary. No weak manifest-version-only assurance is used.

### New P1: invalid state transition strands a durable control

`mission-control-blocked-pause.json` reproduces an actual BLOCKED Mission receiving an otherwise legitimate pause through hosted_interaction. The frozen core correctly rejects PAUSE_MISSION from BLOCKED, but the new owner leaves BOUND forever. Background recovery repeatedly returns INVALID_STATE_TRANSITION. A later continue is blocked by PRIOR_INTERACTION_RECONCILIATION_REQUIRED, so the user cannot resume through the intended entry. Deterministic no-effect rejection needs a completed REJECTED receipt or another explicit terminal outcome. It must not be treated like an uncertain physical effect. Preserve frozen core transitions.

### New P1: lifetime event-count budget disables every effect

Source `pending_controls` reads all historical control-intent events with LIMIT 4097, then throws if more than 4096 exist, before filtering completed receipts. Because both active_effect and the first control-loop step call it, 4097 completed controls suffice to disable fresh effects and loop progress permanently. This is directly determined by the query and unconditional guard; a 4097-operation workload was not run. Use bounded pending projection candidates with R1 replay verification and fair traversal, keeping history intact. A lifetime total cannot serve as a recoverable work budget.

Both new findings were sent to Implementer immediately. They are ordinary implementation work, not Architecture/HARD blockers. Findings refer to the inspected revision; later repairs require recheck before retaining them as open.

## Final component seal after recovery repairs

**All four reported P1 findings are now closed for this Mission-control increment. No remaining demonstrated P0/P1 was found in this reviewed scope. Continue C1 remaining construction; this seal does not qualify full C1.**

Latest independent suite: **16 tests / OK / 11.542s**. Independent original BLOCKED-pause counterexample rerun (`mission-control-final-recheck.json`) now yields REJECTED/CONTROL_INVALID_FROM_STATE, a COMPLETED receipt, no pending background control, and successful subsequent continue to ACTIVE. The explicit valid-from-state table matches the frozen core handlers.

The pending query now excludes completed streams using canonical completion events before LIMIT, and applies Mission/stopping-action filters before limit for effect fencing. The lifetime 4096 guard is removed. Each returned candidate is still replayed through its root owner. The new bounded-page test establishes that four completed controls cannot conceal a pending control with limit=1; no 4097-operation performance benchmark is claimed.

New G2.1 barriers guard planning, dispatch, activity and progress against pending pause/stop, preserving the same short coordinator/effect admission ordering. PAUSED/BLOCKED provisioning preservation remains. Source review does not infer actual prompt execution or autonomous continued progress from these guards.

Seal scope: local R1 Mission control intake, deterministic replay/rejection, short and long effect-drain protocol, product-entry protocol fixture, pending-work discovery and compatibility. Previously recorded independent control-intent atomicity and old event-owner denial evidence remains applicable. Worker actual Host admission, full Mission update/HumanGate ownership, C2 pressure/successor, C3 autonomous wake/liveness, Windows and bank qualification remain separate OPEN work. A component seal must be rechecked when these source fingerprints change materially.
