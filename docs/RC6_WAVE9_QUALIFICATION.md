# RC6 Wave 9 Qualification — L1-L7 Real Execution

## Objective
Close field gaps where generated Cases were treated as executed without a verified real action, actual result, assertion, and current evidence.

## Runtime invariants qualified
- seven independent execution profiles exist: `L1_EXECUTE` ... `L7_EXECUTE`
- execution requires an exact PREPARED attempt bound to the same FROZEN Case version and TargetIdentity
- execution worker role/layer/phase and lease scope are runtime-enforced
- every layer has required real tools; binary discovery alone is insufficient because Tool Capability admission must be READY for the exact worker and target
- each required tool must produce a real tool-call ref and evidence ref during the attempt
- actual result is mandatory before any PASS is possible
- oracle assertion is evaluated separately from the real action and must have assertion/evidence refs
- final PASS is computed by the runtime; model/caller self-reported PASS is ignored
- `BLOCKED`, `SKIPPED`, and `NOT_RUN` remain non-PASS states
- oracle assertion failure remains FAIL with valid execution integrity; it is not rewritten to PASS
- mixed-layer Cases such as `L2|L3` are rejected
- execution receives copies of the frozen Case and PreparedAttempt; canonical Case/binding cannot be mutated by the execution callback
- execution roles have no Case-design artifact permission

## Canonical default execution profiles
- L1: Maven + JUnit (`CODE_UNIT`)
- L2: database runtime (`DB_COMPONENT`)
- L3: API runtime (`API_SERVICE`)
- L4: BrowserSkill (`UI_BROWSER`)
- L5: E2E orchestrator (`CROSS_SYSTEM_E2E`)
- L6: k6 (`PERFORMANCE`)
- L7: ZAP (`SECURITY`)

These are capability IDs, not exact tool version pins. Bank Reality / Tool Capability Broker binds them to callable bank tools.

## Qualification command
`python -m unittest discover -s tests -v`

## Required RED reproductions
1. wrong execution role -> reject
2. mixed layer -> reject
3. Case version mismatch -> reject
4. tool not READY -> block before action
5. missing required real tool call -> FAIL integrity
6. no actual result -> cannot PASS
7. BLOCKED/SKIPPED/NOT_RUN -> cannot PASS
8. failed deterministic oracle -> FAIL, not green retry
9. worker mutation attempt -> canonical Case/PreparedAttempt unchanged
10. all L1-L7 profiles with real tool evidence + actual + assertion -> PASS

## Freeze rule
Wave 9 may be frozen only when repository code, this qualification, and GitHub Actions are all green on the same implementation commit.
