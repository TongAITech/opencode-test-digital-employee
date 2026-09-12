# Worker Session authority independent raw-source review

**Current decision: TYPED-AUTHORITY LOCAL COMPONENT REVIEW PASS; INITIAL THREE P1 CLOSED.** Current implementation is a work in progress. Findings are ordinary implementation/compatibility issues that can be repaired within existing CC-01 typed-root architecture; no request for user architectural approval is warranted. No product source or Git was changed by reviewer.

## P1: new default Mission extension violates unchanged golden contract

The new mission_session_authority extension is globally applicable to Mission streams. Even Missions which never use Session authority gain its empty state/hash/projection contribution. The already adopted `docs/reviews/v4/ARCHITECTURE_AND_COMPONENT_CONTRACT_DECISION.md` CC-01 amendment explicitly preserves baseline Mission initialization, serialization, projection/verification and golden composed hashes.

Independent existing frozen test failed: test_v4_typed_roots.TypedRoots.test_frozen_mission_bytes_results_fingerprints_hashes, 1 test, 0.213s. Full unchanged expected/current captures are in worker-authority-golden-diff.json; changed top-level fields are commands, results, repeated_results, replay and verification. Thus merely preserving core Session event bytes is insufficient.

Reviewer corrects prior same-Mission default-extension advice in WORKER_HOST_ADMISSION_IMPLEMENTATION_REVIEW.md: that advice did not account for this concrete baseline-applicability contract. The simplest conforming path is to put authority into a dedicated CC-01 typed root, with exact governed Mission/Task/Attempt links, shared coordinator and durable phase recovery. Do not update the golden to hide a semantic change. A same-stream alternative would need an explicitly compatible applicability/serialization mechanism, rather than adding empty state to every old Mission.

## P1: old owner composition does not fence new Mission events

Existing durable_core/subjects.py scans unknown root/event ownership only for streams whose seq-1 event differs from mission.created. Consequently removing the new Mission authority owner still allows assert_writable_compatible. The new component test independently failed precisely here. Changing a manifest version does not repair it. Modifying a new runtime's global guard cannot retroactively protect older composition code.

A typed authority root uses the existing unknown-root guard and also avoids the preceding golden failure. A compatibility-only marker root before Mission events would close downgrade admission but not the default-Mission-hash issue. If implementing such a marker, its role must be explicit and it cannot become a second Mission truth. Prefer the full typed authority owner when that removes both problems without core schema changes. Continue to distinguish old-owner composition testing from running an actual historical binary.

## P1: Planner rotation successor enters Worker lineage branch

lineage() handles only provision.phase == PLANNING as a planner lane. Existing rotate_planning_session creates PLANNING_ROTATION with task_id=None. Independent actual G2.1 rotation on temporary R1 and a Host protocol fixture returned MISSION_AUTHORITY_ACTIVE_TASK_REQUIRED before dispatch. Evidence: worker-authority-planner-rotation.json. Validate both permitted planner phases using planner goal/revision/logical/rotation lineage; do not require a Worker Attempt or rewrite frozen Session attributes. Implementer is already repairing this finding.

## Other evidence and limits

Independently ran first available nine component tests: 7 passed, 2 failed, 6.871s. Failures: old-owner guard above, and unknown-send test expected an exception while the product returned a bounded result. The latter needs an outcome/effect oracle instead of requiring a particular exception style; do not infer that missing exception alone proves blind resend.

Cross-realm recovery exploratory execution reached SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN in dispatch/progress before reaching realm recovery. Evidence worker-authority-realm-recovery.json is retained but does not establish the correctness of realm recovery. A read-only current() foreign-realm denial alone is not proof that trusted background recovery can provision a fresh successor after endpoint change. Realm-aware token REQUEST-before-create and pre-POST lease checks are positive source changes; recoverability still requires a fresh-Host test.

The pre-POST interception is correctly placed at dispatch_context before the underlying transport call, rather than after super() returns. Current Worker joins use latest Attempt, current Task/Plan revision and immutable R2.5 root logical anchor; present contradictory attributes reject without inventing successor attributes. Model entry compares actual tool message/agent/input and copied payload identifiers under the coordination lock. These are supported source properties, not complete qualification.

Remaining explicit scope exclusions are honored: knowledge/recovery/context/HumanGate/C2 all-role integration is not declared complete by this review. The C1 control and General file/R1 component seals remain separate. TASK_DIFFICULTY=HARD; REASONING_RECOMMENDATION=HIGH.

## Typed-root implementation recheck

The revised implementation owns all authority events in a dedicated MISSION_SESSION_AUTHORITY typed root. Its immutable identity includes the exact Mission SubjectRef and workspace; no Mission authority state is injected into old Mission composition. Runtime owner methods resolve the actual Mission/Provision/Task/Attempt under the existing shared coordination lock before issuing a grant. Model admission replays both owners and compares current lineage; the separate root does not create a new Task or scheduling authority. Live and replay enforce the root schema/owner, while external cross-root validity is checked by the trusted issuing adapter and again at use. Root metadata-only workaround was removed.

Independent current component suite: **13 tests / OK / 11.514s**. Original frozen Mission golden: **1 test / OK / 0.189s**, unchanged fixture. The suite includes omitted-owner rejection, projection validation, full rebuild with no additional Mission, REQUEST-before-Host-create, pre-POST first actual product-tool protocol check, current Worker/Planner rotation and predecessor denial, grant-before-send crash recovery, no lease extension, unknown-send no blind retry, copied/wrong caller rejection, and admission held across a competing rotation. These are actual temporary R1/transport fixtures, not real-model or Windows evidence.

The three initial P1 findings are closed: typed-root registration preserves old Mission hashes; omitted typed owner is now visible to the existing compatibility guard; PLANNING_ROTATION uses a separate planning_lineage lane with no fabricated Worker Attempt. Worker successors retain original R2.5 root logical anchors. No new demonstrated P0/P1 was found in this bounded source/recheck window.

G5 tool name `aitest_diagnosis` matches its TypeScript export and agent permission. Registry DIAGNOSIS and DEFECT_HUNTER are distinct capabilities despite the same Host agent name. An independent plain-DIAGNOSIS G5 attempt is denied (worker-authority-diagnosis-route.json); source g5/service.py already requires DEFECT_HUNTER, so this is not a newly discovered authority bypass or justification to expand capability. Generic `aitest_worker` remains separately eligible for real non-Planner routes. Route-context messaging and explicit positive/negative coverage should prevent an ordinary DIAGNOSIS task from being mistaken for formal G5 authority.

Qualification remains intentionally narrow: cross-realm current() is fail-closed; automated fresh-Host recovery is C2 OPEN and the earlier SESSION_ROUTER_AGENT_OVERRIDE_FORBIDDEN exploratory result is not a recovery PASS. Knowledge/recovery/context/HumanGate and all-role C2 entry completion remain OPEN. Lease expiry may conservatively block; this recheck does not claim autonomous expiry rotation. Real Host and Windows integration must be separately evidenced. Earlier full-C1/General/control seals are not broadened by this component result.
