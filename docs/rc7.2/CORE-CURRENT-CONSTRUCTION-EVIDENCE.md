# RC7.2 Core independent construction/evidence checkpoint (2026-11-04)

## Provenance and admission

- Repository: `TongAITech/opencode-test-digital-employee`.
- Confirmed baseline `work/rc7.2`: `7efb3c8aa62f22629e570e3381727969524bf598`. Do not reuse previous conversation SHAs.
- Core construction branch: `work/rc7.2-core`, original base above; latest code checkpoint before this document: `41c88e8e6eee0fdf779bd36d574ae09edcadc274`.
- Integration PR: https://github.com/TongAITech/opencode-test-digital-employee/pull/10 (DRAFT; no main merge).
- Read and checked frozen design `00`–`05`, `10-DESIGN-IMPLEMENTATION-CLOSURE-CONTRACT`, `CONTINUOUS-CONSTRUCTION`, current source R1-related services and same-HEAD CI.

## Exact design/implementation closure scope

| Responsibility | Frozen design intent | Code path changed | Honest status |
| --- | --- | --- | --- |
| P0 / N7 coverage rerun | Accepted fresh complete N7 with unique Gate, signed Evidence Bundle, full Attempt denominator, cold resume | `rc72_native_coverage_rerun.py` uses canonical Gate -> Delivery -> bundle and independent `finalization.audit` | IMPLEMENTED_CANDIDATE; latest exact-SHA CI pending |
| C08 native product composition | Main product entry, no test-only repair/rerun service | `rc72_mission_factory.py` composes `NativeCoverageRepairService` and `NativeCoverageRerunService` into actual N10, with scope checks | IMPLEMENTED_CANDIDATE; not a complete N1–N10 terminal route |
| C03 / N8 historical audit | Preserve original N8 independent evidence after repair; fail closed on changed lineage | `rc72_native_coverage_diagnosis.py` reconstructs historical facts from original signed N9/Libra/intake, independently audits review process | PARTIAL: coverage path only; general N8 failure classifications/backedges not closed |
| C05 / N10 coverage-history convergence | No fake resolved Gap, verify signed repair boundary, full fresh N7/Libra | `rc72_release_convergence.py`, `rc72_n10_control.py` check repaired original proof and fresh post-repair verification | PARTIAL: independent N10 Delivery/Gate and entire ReleaseBatch terminal convergence still open |
| C04 / N9 professional defect | Business bug identification, reproduction, root cause, fix verification, regression | No complete professional defect implementation in this slice | OPEN; existing deterministic no-defect gate is not completion |

## Actual CI and tests, do not promote a candidate to PASS

- Baseline same-HEAD Construction run `41679951672` and Platform `41679951422` were in progress at inspection; Q2 Windows had already passed. Earlier run `41672056689` had **three failures**: two N7 rereun admission and one ambiguous N10 mapping. These were not called PASS.
- Core targeted `41682810634`, `1f24b1e`: **20 passed, 3 failed**, identified missing `bundle_id` on N7 finalize response, ambiguous-mapping assertion.
- Core targeted `41683489480`, `06591b9`, Python 3.11: **21 passed, 2 failed**, now N7 bundle/authentication reached native convergence; two failures exposed historical N8 incorrectly using *current* Libra intake.
- Current code candidate `41c88e8`: targeted run `41684451977` was queued on inspection; construction for that SHA `41684451966` also queued. **No same-HEAD green verdict** at checkpoint. Report future check results only after confirming exact source HEAD.
- Regression assets updated: `tests/test_rc72_mission_factory.py` composition, provenance ownership, side-effect-free cold reconstruction; `tests/test_rc72_n10_control.py` ambiguous-mapping zero-write, zero extra HTTP/ business I/O, cold reentry; inherited fresh N7 and Libra rerun tests remain intact and unskipped.

## Next acceptance gates

Exact-HEAD Linux Python 3.8/3.11 targeted and full Construction are mandatory; investigate any failures without deleting tests or weakening business assertions. Only after passing and independent QA review is promotion from DRAFT to integration permissible. C03 generic N8, C04 professional N9, C05 full terminal N10, B/C/D dependency PR integration, Windows/target Linux Field and full offline/BANK_FINAL remain OPEN. This checkpoint is engineering-source evidence only; no bank Field truth or package sign-off is implied.


## Continued core construction — 2026-11-04, exact source candidates only

### P0 CI verified failure (no acceptance)
- Baseline `7efb3c8` Construction `41679951672` completed FAIL, both Python 3.8 and 3.11: **3 failed, 1406 passed, 3 skipped** on each. The same three failures were N10 ambiguous-mapping no-R1-side-effect assertion and two post-repair fresh-N7 `KeyError: bundle_id`; inherited RC7 regression passed. Main remains RED / no integration.
- Core initial targeted job `41682810634` (1f24b1e): 20 pass, 3 fail; second `41683489480` (06591b9): Python 3.11 21 pass, 2 fail, exposing historical N8 audit against current Libra epoch.
- Later patches address observed P0 classes by deriving the new Bundle only from an accepted N7 R1 Gate/Delivery, verifying full fresh Attempt denominator and original historical diagnosis with signed N9/Libra/intake and CLOSED repair/fresh-verification proof. No same-HEAD green yet: latest HEAD must be rechecked against CI before claiming repair.

### C05 / C08: replay-safe real N10 and business obligation feedback
- `rc72_release_scope.py` and `rc72_release_convergence.py` add an *opt-in* `replay_safe` mode used by actual `NativeN10ControlService`. Every dimension and original denominator is recomputed from R1 before reusing a semantically identical historical snapshot; changed facts still append a new R1 event. This prevents duplicate, changing snapshot IDs under hot/cold continuation without caching an unverified PASS.
- `rc72_n10_feedback.py` projects only the actual persisted convergence blockers into structured `gap_reason/responsible_node/scope_refs/priority/evidence_refs`. Missing SST and mandatory L1–L7 levels are derived from the frozen Manifest; uncovered code slices use the native Gap's actual Requirement/SST/Obligation lineage. Unknown causality is queued to N8 and is *not* silently claimed to be a product defect.
- Product `N10` response now carries derived `issues` alongside real `blockers`. Source-snapshot mutation must fail closed. New and retained tests require all original seven levels even at 100% measured coverage, precise business feedback and read-only identical cold replay.
- **Still OPEN:** an independently reviewed N10 terminal NodeDelivery/Gate, fully converged genuine mixed L1–L7 ReleaseBatch, in-bank Field evidence, and deployment qualification.

### C04: real N9 discrepancy intake, not a false defect
- `rc72_n9_professional_intake.py` is invoked from the production `N7PipelineService._diagnose_failure` only after `VALID_TEST_FAILURE` passes signed conclusive assertion evidence and independently accepted N8 diagnosis/NodeGate. It binds a **`N9_DISCREPANCY_QUALIFICATION`** Task to original approved N4 Case Artifacts and historical N8 Gap, Case, Attempt, process and review identities; its existing RC7 capability is `defect_analysis`, not an invented `defect_reproduction` permission. This task is **analysis triage only**; it is not evidence of an actual reproduction.
- No business operation is replayed, no `rc7_defect` is created, and `defect_confirmed=False` is explicit. The original negative/failure classification and N9/Gap gate stay open until a separate professional reproduction, RCA and repair regression actually prove resolution. Altered task objective/evidence scope fails closed on recovery.
- Added tests in `tests/test_rc72_conclusive_failure_evidence.py`: original valid discrepancy creates exactly one governed N9 qualification WorkItem; inconclusive Runner failure has none; repeated/cold replay has no new R1/business requests; altered WorkItem refuses acceptance; the legacy RC7 reproduction executor **rejects** this task, while the canonical scheduler can lease it to an existing `defect_analysis` worker.
- **Still OPEN:** actual professional reproduction Agent/runner, independent RCA, defect record acceptance, genuine fix verification and full regression lifecycle.

### Parallel PR integration reconciliation
- Core PR #10 remains DRAFT. Runtime C06/C07 PR #6 changes `rc72_n7_tool_dispatch.py` and Captain execution; Journey C09 PR #11 owns journey-specific files; economy C10 PR #8 owns model economy + CLI; QA PR #9 owns independent contract/release acceptance. These branches have not been merged into `work/rc7.2`.
- Before merge: verify exact updated main+PR SHAs, prerequisite product contracts, current HEAD 3.8/3.11 targeted+full Construction, Windows/Linux source baseline and independent QA; merge without force-push and do not overwrite another team's files. User packaging and Field remain separate C12 gates.

**Latest known construction candidate before this document update:** `a24a90a9ea59d91d6e6994f2588b361d71224ac8`. On inspection its exact targeted/Construction CI `41687719160`/`41687719297` were queued, so **engineering acceptance pending**. Do not infer PASS from the presence of a run.


## Follow-up exact candidate checkpoint — 2026-11-04

- **Confirmed protocol mismatch and repaired:** RC7's existing `DefectReproductionExecutionService.execute_task` only accepts `node='EXECUTION'`, `task_type='DEFECT_REPRODUCTION'`, `capability='test_execution'` and a confirmed `PRODUCT_DEFECT` Gap targeting `DEFECT`. N8 `VALID_TEST_FAILURE` has *not* established that product causality. Therefore the initial candidate's `DEFECT_REPRODUCTION` WorkItem with an unknown `defect_reproduction` capability could not truthfully be claimed as a runnable reproduction. It is replaced by a scheduler-leasable `N9_DISCREPANCY_QUALIFICATION` work item using native `defect_analysis`, preserving original signed R1/captured source. Real reproduction/RCA/fix/regression are explicitly still OPEN.
- **N10 lineage strengthened:** `NativeN10FeedbackService.derive` now checks exact persisted snapshot facts, input manifest/scope IDs, blockers, proven and unproven obligations, coverage observations, creation timestamp; mapped coverage Gap Requirement/SST/Obligation lineage and any candidate IDs must resolve to same-batch canonical obligations. A mismatch is a contract exception, never a cosmetic issue label. Tests inject seven separate snapshot-provenance mutations and one actual mapped Requirement rewrite.
- **CI acceptance state:** source commits are candidates only; early same-baseline full Construction remained FAIL (3 failures). GitHub queued latest-core Python3.8/3.11 targeted/full Construction and Windows/Linux checks; do not claim a new successful run until its head SHA and result have both been retrieved. No main integration or BANK_FINAL authorized.


## N10 terminal reviewer source candidate — 2026-11-04 (UNQUALIFIED)

- `rc72_n10_review_worker.py` performs a separate, credential-free deterministic full-denominator consistency review; it does not execute business tests or accept a user-supplied PASS flag. The native source aggregator must re-audit the original signed N7/N9/Libra/gap/repair R1 before and after this subprocess.
- `rc72_n10_terminal.py` adds a product-callable N10 terminal workflow: current native `CONVERGED` snapshot plus no blockers/unproven obligations → versioned R1 NodeDelivery → fresh independent REVIEW session and assignment → isolated process result recorded with signed receipt and file bytes → canonical R1 review Evidence → Gate-only N10 PASS → reviewer checkpoint/closure. Signed receipt and exact snapshot IDs are checked on hot/cold replay. Review input/output paths are constrained to canonical lifecycle reviewer identities and capture root. Returns `field_verified=false`, `bank_final=false` even after engineering Gate PASS.
- `rc72_n10_control.py` now invokes terminal review **only** for native `CONVERGED`, not merely when Libra coverage is above the target. Non-convergence preserves HOLD; existing tests assert no terminal NodeDelivery, Gate or process receipt when original L1–L7 obligations are missing.
- `tests/test_rc72_n10_terminal.py` adds six negative process invariant checks, six path-confinement cases, and a legacy self-reported `CONVERGED` projection refusal without native accepted-source providers. This does **not** constitute a successful full native bank ReleaseBatch proof.
- **Open acceptance blocker:** there is still no independently verified source test running a genuinely complete mixed mandatory L1–L7 release from physical real N7 through native N10 PASS and full hot/cold/reviewer-crash recovery. The new implementation and tests must pass exact HEAD Python 3.8/3.11, Windows/Linux and independent QA before any design closure. Even then target-bank Q3–Q9 and offline transport remain mandatory; no BANK_FINAL claim.

## Continued N8 product integration and current mainline reconciliation — 2026-11-04

- **Mainline moved:** work/rc7.2 HEAD `4721bb57f6a5de1fdf471000030a7b043ebe71c7`. Three P0 mainline fixes (fresh N7 Gate→Delivery→Bundle, ambiguous mapping no-write) and C09 Journey CDP/teaching/replay source were kept in a two-parent **non-forced main→core only** merge `91fd489935bb3e3813fbe960c16a4c0b0fe9f9dc`. The main branch did not receive Core changes. PR #10 remains DRAFT; Git mergeability is not QA acceptance.
- **QA P0 Issue #7 addressed at source level only:** formal `ReleaseBatchDriver.run` now owns `NativeN8ProductRecoveryService` supplied by the Mission Factory; independently admitted N7 failures enter N8 even if the signed FAILED dispatch preceded canonical Attempt persistence. Actual N8 independent diagnosis classifies full evidence; UNKNOWN remains HOLD/BLOCKED, `VALID_TEST_FAILURE` routes only to professional N9 qualification, and `TEST_DATA_GAP` opens scope-fenced N8 compensation/cleanup with N5 repair HOLD until **real independent N5 verification** exists. No business Attempt is retried without source-approved fresh plan.
- **Retry anti-spin:** after an actual accepted N5 repair, `DataRepairContinuationService.reconcile` must yield a distinct R1 N7 plan with `recovery_id`, original blocked Attempt and READY/RUNNING node. The product driver refuses a forged/reused plan rather than loop forever on `CONTINUE`. Accepted N8 diagnosis remains historically read-only auditable after physically new N7 PASS.
- **Tests added:** `tests/test_rc72_n8_product_recovery.py` proves actual local failure→N8 signed process→scoped compensation, UNKNOWN, tampered transition failure, genuine N5 repair→fresh N7 and historical N8 auditing; `tests/test_rc72_release_driver_n8.py` exercises formal product ReleaseBatch real HTTP N7 failure→N8 and N5 HOLD with cold no business replay. Factory tests reject detached N8 adapters. Both added to Python 3.8/3.11 targeted CI. All are **unqualified until actual same-SHA CI PASS**.
- **Remain OPEN:** automatic N5 independent producer/verifier wiring from native DSH resource authority, generic N8 provider/flaky/capability handling, full N9 RCA/fix/regression, actual full L1–L7 converged N10 positive terminal Gate, current Windows/Linux full CI, independent QA, target-bank Field Q3–Q9 and C12 offline delivery. No BANK_FINAL or design-complete claim.

