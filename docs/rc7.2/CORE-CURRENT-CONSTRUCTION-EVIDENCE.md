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
