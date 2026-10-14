# RC6 Wave 4 Qualification Contract

Wave 4 closes the field failure where a tool was reported READY merely because a binary or path was discovered, while the assigned worker could not actually call it.

## Runtime invariants

A tool is usable for a worker/target only when all stages are true:

`DISCOVERED -> EXECUTABLE -> REGISTERED -> VISIBLE_TO_WORKER -> PERMISSION_OK -> PROBE_PASS -> TARGET_READY -> READY`

Additional rules:

- Binary/path discovery alone can never produce READY.
- REGISTERED requires executable proof.
- A successful probe requires a real `tool_call_ref` and `evidence_ref`.
- Worker visibility and permission are worker-specific.
- Target readiness is bound to the exact TargetIdentity.
- Admission is fail-closed if any required stage is missing.
- Tool call evidence can only be recorded after admission succeeds.

## Qualification scenarios

1. Discovered+executable CodeGraph remains not READY.
2. Probe success without real call/evidence references is rejected.
3. Full staged CodeGraph capability passes for the exact worker and target.
4. Wrong worker visibility blocks admission.
5. Permission denial blocks admission.
6. Wrong TargetIdentity blocks admission.
7. Missing tool blocks admission at DISCOVERED.
8. All Wave 1-3 tests remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 4 can freeze only after committed source passes GitHub Actions and the run id/head SHA are recorded in `RC6_CONSTRUCTION_STATUS.md`.
