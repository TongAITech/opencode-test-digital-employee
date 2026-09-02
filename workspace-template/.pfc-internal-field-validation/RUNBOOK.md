# Field Validation Runbook

## FV-0 — Environment Doctor

From `workspace-template`, run `field-validation\FV.cmd fv-0 --output ai-test\evidence\field-validation\FV-0.json`.

The Doctor checks package-local runtime structure, configuration, Git/OpenCode/browser binding shape, and the absence of bundled secrets. It does not log in, navigate a bank system, or claim field readiness.

## FV-1 — Project Reality Initialization

Copy `field-validation\bindings\bank-binding.template.json` to a controlled local binding file and populate only through the bank-approved environment/reference mechanism. Run `field-validation\FV.cmd fv-1 --input <binding-file>`. The report is a configuration summary; configured external bindings remain subject to human and environment proof.

## FV-2 — Requirement / Coverage / Standard Case Reality

After the canonical R3 sources are identified, prepare a receipt from `FV-2_INPUT.template.json`. Run `field-validation\FV.cmd fv-2 --input <receipt>`. The tool checks receipt shape only. Coverage, Standard Test Case, Oracle and evidence sufficiency remain owned by their frozen R3 authorities.

## FV-3 — Real Execution Reality

After R2 execution and R1 evidence exist in the target environment, prepare a receipt from `FV-3_INPUT.template.json`. Run `field-validation\FV.cmd fv-3 --input <receipt>`. The tool does not execute a Mission, browser action, API call, database query or adapter.

## FV-4 — Defect / Continuous Quality Reality

After findings and lifecycle evidence exist, prepare a receipt from `FV-4_INPUT.template.json`. Run `field-validation\FV.cmd fv-4 --input <receipt>`. Do not convert a synthetic or engineering-only result into a bank field-validation claim.

All reports must retain exact upstream references, scope, digest, provenance and the evidence class. `WINDOWS_EXECUTION_PROOF=REQUIRED` remains true until the independent Windows audit is completed.
