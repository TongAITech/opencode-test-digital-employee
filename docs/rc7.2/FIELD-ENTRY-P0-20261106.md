# 2026-11-06 RC7.2 field-entry P0: native Host routing guard

Source base: `work/rc7.2` @ `d4981d3a925e71fe876bfbe42b813b9e077bf725`.

## Field evidence (bank Windows / DSH)

- DSH AgentTeams 8-member / 12-task prompt-DAG started; tasks were not canonical RC7.2 WorkItems.
- `MISSION_NOT_FOUND`, empty R1 event stream, no ReleaseBatch/MissionNode/NodeGate/Worker/BrowserLease/ModelAssignment.
- DSH-generated MCP entry from `rc7_release.dsh` routes to `rc7_release.mcp_server_authorized`, not a native RC7.2 Mission Host.
- AgentTeams reassignment after STREAM_CLOSED is not signed RC7.2 Attempt recovery.

## Current atomic change

- `rc7_release.rc72_field_wiring_gate` inspects the actual generated DSH patch and exact package `SOURCE_COMMIT`. It **never writes to R1** and never claims FIELD_VERIFIED/BANK_FINAL.
- RC7.2 launcher exports `PFC_RC72_REQUIRE_NATIVE_HOST=1`; RC7 shared launcher checks the gate *after* generating the patch and *before* starting DSH. RC7-alone launches and Q2 launch-plan engineering probes are unaffected.
- Known RC7-only generated MCP patch now stops RC7.2 Field startup with a dedicated `RC72_FIELD_START_BLOCKED` error and a diagnostic JSON under `state/rc72-field-wiring-gate.json`.
- This is **not a positive native-host acceptance**. Even a patch declaring `pfc_aitest_rc72` and `rc7_release.mcp_server_rc72_authorized` only yields `NATIVE_ROUTE_PRESENT_NOT_FIELD_VERIFIED`; signing, source, Q7 admissions, all-role DSH invocation, R1 and browser ownership still need independent runtime evidence.

## Required remaining engineering

1. Connect actual DSH host identity (Captain/Team/Session, signed R1 scope/fencing) to `MissionCaptainBinding` and `create_mission_driver`. Never infer Captain identity from model prompts or editable team.json.
2. Build `rc7_release.mcp_server_rc72_authorized` (or a frozen-contract-equivalent explicitly approved native host entry) and update generated DSH MCP patch. Host control is trusted and distinct from STRICT worker tool calls.
3. Run exact Q7-admitted ReleaseBatch Mission through N1-N10 real state machine, WorkItem/Attempt, resources, N8/N9/N10, BSK, and evidence.
4. Add a **positive** clean-package Host + R1 integration test and cold-resume/negative authorization tests. This static routing guard alone does not close C07.
5. Rebuild the Windows offline payload only after all engineering gates pass. Independent bank Q3–Q9 remain unverified.

Status: `FIELD_BLOCKED`, `C07_OPEN`, `BANK_FINAL=NO`. No release ZIP authorized by this change.
