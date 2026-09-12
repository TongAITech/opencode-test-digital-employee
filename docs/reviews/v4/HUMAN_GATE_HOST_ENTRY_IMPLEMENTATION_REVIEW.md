# HumanGate actual Host entry: bounded implementation review

**Decision: PROCEED_WITH_LOCAL_CC05_EFFECT_DELTA.** Ordinary owner/recovery work within current architecture; no need to re-run Phase 0 or ask user approval. This document is source-based implementation advice, not validation PASS.

## Minimum safe entry and selection

Add the HumanGate path before generic resolve_subject chooses a unique Mission. The current interaction_admission flow would reject two relevant Missions before discovering that only one contains a compatible Gate. Use the actual Host UserTurn's complete unquoted clause and existing negation/conditional/quoted-content checks. Accept only a completion phrase as REQUEST_TO_VERIFY_COMPLETION. A model-provided gate_id, outcome, actor, completion proof, or decision_id does not confer authority.

Build an explicit authorized Mission set from R1 ownership/scope context; if an exact literal scope/Mission was supplied, restrict first. Enumerate each Mission's compatible EXTERNAL_ACTION PENDING gates with existing takeover mode/status rules, then select zero/one/many Gates globally across that authorized set. Zero returns no pending Gate without creating Mission. Multiple yields clarification with bounded Gate/Task identities. One resolves its exact Mission/Gate/Task/root Attempt/takeover/browser identity. Do not scan unrelated workspace Missions as an implicit grant. Current receipt candidates link actual Host Session IDs; Primary successor continuity must use durable logical/authorized context rather than assume every old Mission is contextual to a new physical Session.

For replay, inspect the immutable operation receipt before current selection: once an operation bound Gate A, Gate B must never be selected because A closed, disappeared, changed state or became inaccessible. The same rule applies when the user repeats the tool call after a crash. A new human turn may make a new request, but must serialize against any still-pending effect for that Gate/context.

## Durable owner path

1. Atomically CLAIM the interaction operation with a dedicated Gate-intent event, following existing control-intent compatibility practice. Persist exact subject/scope, Gate ID, deterministic decision ID derived from operation identity, takeover fact/digest, browser session/context epoch/digest, root Attempt and verification intent. The original Host source digest remains bound. No new Mission or fake Task.
2. Queue/recover this request without keeping the Primary tool call open across browser verification. Use the same Mission effect/control coordination; respect pause/stop and current Gate/Attempt/context before a new side effect. Fixed Gate identity is independent of whichever Mission happens to be uniquely selectable later.
3. Perform fresh same-context browser verification through the existing supervisor. A failed check remains WAITING_HUMAN/verification-not-complete, not authorization success. Persist the exact verification evidence reference/hash/time and handback intent before changing external ownership. Deterministic refusals must not leave an unrecoverable interaction fence forever.
4. Reconcile ownership and the R2.6 decision for that exact Gate and decision identity. Complete the G4 lease/takeover/reconciliation facts from canonical decision/evidence when possible. Never send the user completion phrase as proof to R2.6.
5. If UI continuation exists, hand it to a separate durable continuation/effect receipt before executing it. Report the distinction between Gate verified/handed back and subsequent test execution. Only then complete the interaction summary from durable references, or retain a precise recoverable pending phase.

## Concrete current source hazards

`g4/service_r2_4.resolve_human_gate_user_turn` chooses a Gate only within one Mission and builds its default decision digest from Mission/Gate/text. It is not an immutable actual-user-turn claim; repeated identical text cannot substitute for the new operation identity. Use its completion-intent and compatibility semantics, but do not repeatedly call its selection loop on recovery.

`g4/service_base.complete_human_takeover` writes pending verification and AI_RECLAIMING facts, transfers HUMAN→AI, records R2.6 decision, then writes AI_CONTROLLED/RESUME_SAFE/RESUME_COMPLETED facts. A process death after handback but before decision bypasses the Exception compensation path. A death after decision but before final G4 facts leaves a non-PENDING Gate, so a plain retry fails G4_HUMAN_GATE_NOT_PENDING. The Exception path can also compensate back to HUMAN after an uncertain decision outcome; recovery must first inspect the durable decision rather than assume an exception means it did not commit.

`g4/service.py:32-41` immediately calls execute_capability when the returned cursor contains ui_journey_resume. That is a separate SUT effect after handback; wrapping the whole method in an interaction receipt does not make it replay-safe. A crash after the effect but before its evidence/interaction receipt can duplicate a click/submission if the whole complete path is retried.

## Required CC05 local safety cut

Split the owner-level completion/reconciliation from automatic continuation. Keep existing frozen R2.6 contract and original services available internally, but route explicit and AUTO resume through the same new durable Gate/context effect owner. Suppress the unreceipted direct auto-continuation path for this integrated flow; merely suppressing it for explicit input while background AUTO can run it leaves the same duplicate-effect window.

For handback intent with no decision: inspect exact current browser context and lease owner. If still HUMAN, rerun fresh verification before a governed transfer. If already AI, require exact context and revalidated canonical evidence to finish the same decision without another handback. Unknown/replaced context cannot be adopted or automatically compensated as if it were the original one.

For committed exact R2.6 decision: recover subsequent G4 facts/receipt without calling the PENDING-only resolver, re-deciding another Gate, or transferring the browser back merely because a return value was lost. If external lease/context contradicts the committed state, retain explicit reconciliation-required fencing. Completion history may be recovered after original UserTurn expiry; expiry cannot erase a committed effect. Starting a new expired verification/effect is a different authority decision.

Continuation identity must include exact Gate/decision, Mission/root Attempt/cursor checkpoint, current Attempt, case/version and operation identity. Claim before physical call; after a lost result use actual provider/evidence reconciliation where supported. An UNKNOWN non-idempotent effect remains fenced and never retries automatically without proof. Only confirmed no-effect failure may be safely retried. This is a bounded CC05 delta required by the new route, not a claim to finish every executor effect family now.

## Small isolation matrix before component seal

Actual unquoted done versus quoted/negated/example text; zero Gates; two Missions with one compatible Gate; two compatible Gates; explicit literal scope; unauthorized Mission exclusion; stale copied ToolContext; two simultaneous explicit/AUTO requests for one Gate. Crash after claim, verification, handback intent, actual HUMAN→AI, decision commit, final G4 facts, continuation claim, actual continuation, and interaction complete. Clear original Host messages before background recovery. Assert exact Gate identity, original decision identity, same browser epoch, no new Mission, no extra handback or physical continuation and durable UNKNOWN fencing. Include pause arriving during verification/continuation and stale Attempt after rotation.

Use actual R1 and browser-adapter boundary fault injection for local tests, with an honest mock/synthetic label. Real Playwright/Host smoke and Windows integration must separately validate transport behavior. No fixture may be reported as bank PASS. TASK_DIFFICULTY=HARD; REASONING_RECOMMENDATION=HIGH.
