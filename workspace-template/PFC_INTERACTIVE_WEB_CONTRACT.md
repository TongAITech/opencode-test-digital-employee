# PFC Autonomous + OpenCode Web Interactive Contract

## Required usage model

This Ready Package has two clients over one PFC workspace:

- `./START-PFC-FIELD-VALIDATION.sh` is the autonomous client. It checks the OpenCode Runtime Gate, starts or attaches OpenCode Web, restores the durable PFC context, and resumes only the persisted Mission cursor.
- OpenCode Web is the interactive client. Product Owner and Tester may ask natural-language questions or request an explicit action. The Web client uses `pfc_truth` for reads and `pfc_command` for canonical commands.

Conversation is not Project Truth. Requirement, Coverage, StandardTestCase, Mission, Execution, Evidence and Defect state must be read from the pinned V3 durable SQLite runtime or written through its existing lifecycle APIs.

## Interaction boundary

Before answering a state question, the Director reads `pfc_truth`. Before changing state, it routes the request through `pfc_command`. A natural-language request never creates a temporary script, runs an untracked action, or leaves the result only in the conversation.

The supported interaction intents are:

- `show`: read the current canonical PFC truth.
- `select_requirement`: set an explicit durable active Requirement scope; it does not silently replace the Project or create a second workspace.
- `continue`: resume the persisted Mission cursor; it never creates a new plan.
- `hold`: checkpoint the current durable context and keep execution stopped.
- `review_reject`: record a Product Owner case-rework request through the case lifecycle once the Runtime Gate permits it.
- `execute_approved` and `rerun_failed`: remain blocked until the existing Runtime Gate, case review, execution authorization and real bank preconditions pass. A blocked request creates no ExecutionAttempt.
- `cat`, `database_status`, `defect_assessment`: read existing canonical evidence and report UNKNOWN when the required evidence is absent.

## Scope and continuity

Requirement IDs are explicit business scope, not chat memory. The same workspace is able to hold `BLOAN-PF1.0.0` with `STBB19-234`, `STBB19-240`, `STBB19-242`, and future versions/requirements as they are registered in Project Truth. Switching scope must be explicit and durable.

OpenCode session rotation, compaction, restart, Web closure and machine restart do not delete PFC truth. START checkpoints and reconnects the interactive worker using the durable Mission context. STOP checkpoints the Mission, closes the worker-session lease and stops only the package-owned Web process; it does not delete Project, Mission, Requirement, Coverage, Cases or Evidence.

## Safety boundary

Built-in file, shell, web and external-directory tools remain denied. Do not expose session IDs, provider refs, credentials, tokens, cookies, OTP/MFA values or internal command names to the user. Do not treat `opencode --version` as AI Runtime readiness. The current quarantined `Coverage 39 / Selected 33 / 3 StandardTestCases / FV-2` remains `NOT_VERIFIED / QUARANTINED`.
