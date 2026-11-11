# F independent fanout regression test review

Candidate [PR #241](https://github.com/TongAITech/opencode-test-digital-employee/pull/241), exact `ec6d35c163926d74ce7d1439fb8de98ae159d89e`. Original complete-run source `16ae40e8a86b5193da0a1f97b3b5f7a5f76204cc`. Date: 2026-11-11.

**FANOUT_GUARD_TEST_REGRESSION_ACCEPTED_EXACT_EC6D35C1.** This is acceptance of the test fixture/coverage repair. It is not a complete-source PASS, production guard change, native DSH/Windows field acceptance, or release qualification. F wrote only this report; no implementation, 08/09/10 or branch merge was performed.

## Original failure actually retained and reproduced

F checked [complete-source run 42893372170](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42893372170) at exact 16ae. Job `abcd-v4-ubuntu-3.11-complete-source-real-chromium` failed with **1 failed, 3110 passed, 4 skipped, 39 warnings**. The four separately listed Ubuntu/Windows × Python 3.8/3.11 native CI jobs succeeded on that run; they are not field evidence and are not transferred to ec6.

In a separate detached worktree at exact 16ae, F ran `python3 -m pytest -q tests/test_rc7_script_fanout_control_gate.py`: **1 failed / 3 passed**, 1.38 seconds. The failed `test_accept_evaluation_invokes_script_fanout_gate_before_persisting_pass` expected SCRIPT_FANOUT_SENTINEL, but received MISSION_SCOPE_TARGET_UNRESOLVED. Its object.__new__ Control with SimpleNamespace scheduler never reached the script fanout hook: the approved production guard correctly rejects that unsupported composition. This is a real failed regression in the old test, not proof that the production fanout gate accepted a bad PASS.

## Coverage is retained and strengthened

The candidate commit changes only this test, its focused workflow and its evidence document. The relevant rc6_runtime and rc7_runtime files are identical between original 16ae and ec6; intervening unrelated changes are not accepted by this report. The candidate does not weaken or bypass the approved guard.

The changed test bootstraps a real TruthRuntime and Mission and registers the same synthetic OUTPUT_PRODUCED SCRIPT_READINESS Task through the default guarded Control composition. It calls the same public `accept_evaluation` with PASS. It does not unwrap the decorator, substitute a scheduler, grant authority or change production code. A sentinel replaces only the fanout check on that test instance, as in the old ordering test. The callback checks the reloaded task's stable ID and OUTPUT_PRODUCED state plus PASS evaluation. Stable identity is appropriate for a real persisted projection that returns a new object rather than the former stub's exact Python object.

Production `accept_evaluation` still invokes `_require_script_fanout_pass_ready` before append_entity(Evaluation) and Task transition. The test's expected sentinel proves that the public path actually reached that gate, so an early guard rejection cannot masquerade as a successful ordering assertion. After the sentinel, the test requires unchanged R1 bytes, absent Evaluation and unchanged OUTPUT_PRODUCED Task. These are stronger business-side-effect oracles than the old sentinel alone. Three direct fanout behavior tests remain unchanged, covering incomplete barrier, missing receipt binding and the repair-task exemption. Synthetic preexisting Task output and the ordering sentinel do not prove a real SCRIPT_READINESS execution or actual fanout PASS.

## Exact candidate verification

- F local `python3 -m pytest -q tests/test_rc7_script_fanout_control_gate.py tests/test_rc7_unadmitted_scope_hold.py`: **106/106**, 3.15 seconds; fanout4 + local HOLD102, no skips.
- F local pytest of all affected files enumerated by the focused workflow: **174/174**, 4.58 seconds, no skips. This set overlaps the 106 and is not an additional independent denominator.
- F inspected [focused CI 42953971185](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42953971185). Both checkout and `git rev-parse HEAD` show exact ec6d35c163926d74ce7d1439fb8de98ae159d89e. Actual **Python 3.8.18: 174 passed**, 5.64 seconds; actual **Python 3.11.18: 174 passed**, 2.61 seconds. The test file is now included in the path trigger and the pytest list.

No remaining P0/P1 in this narrow test change. A still needs complete-source and applicable native regression on its resulting exact integrated source; this report does not transfer the old 3110 passes or four skips, certify field/Windows installation, or alter the local guard's existing residual boundaries.
