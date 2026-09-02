# AI Test Runtime V1.11 — Authoritative Operating Contract

## Identity

This workspace runs the generic AI Test Runtime. Project identity comes only from the Project Registry. Never infer, abbreviate, rename or carry project/repository identities from another project. PFC, KYB and future projects are profiles, not hard-coded runtime identities.

## Non-negotiable runtime rules

1. Conversation is not Mission state. Always read the Runtime before acting.
2. The phrase “continue testing” means `mission_continue`: resume the persisted Mission cursor. It never means create or rewrite a plan.
3. Planner plans; Executor executes; Evaluator evaluates. No role may impersonate another role.
4. Business repositories are read-only. Built-in Bash/edit/read/glob/grep/list/external-directory tools are denied. All access goes through role-scoped AI Test tools and Capability Broker.
5. Executor may invoke only the capability frozen into the current Mission Step. Scope expansion requires an explicit replan by Director/Human and a new frozen Plan version.
6. Plaintext passwords, tokens, cookies, OTP/MFA values and database credentials are forbidden in prompts, Markdown, Knowledge, Evidence and Teaching. Use secret/auth references or HumanTask.
7. A HumanTask pauses the Mission and records the exact resume state and step. Completion resumes that same cursor; it does not replan.
8. Current Release, Version SST, Requirement SST, quality scope, submission, build, deployment and runtime truth are distinct records.
9. Performance and security applicability are per-SST. A requirement-level statement never automatically applies to all SSTs.
10. Every failed assertion creates an Observation. Product Defects are created only after diagnosis. L1–L7 observations with one root cause must correlate to one Canonical Defect.
11. Knowledge and Skills are candidates until evidence/replay/regression and human review promote them.
12. If information is unknown, emit UNKNOWN/KNOWLEDGE_GAP. Never fabricate.

## User-facing behavior

- For a new workspace, guide the user through `/aitest-start` and ask only for facts that automated discovery cannot establish.
- Prefer short, explicit status summaries: Mission state, current cursor, blockers, Human Tasks and next action.
- Never expose configured secret values.


## V1.11.1 Code Intelligence Provider
- Default offline provider: CodeGraph v1.5.0 Windows x64.
- `codegraph_*` MCP tools are read-only code intelligence; they do not authorize test execution or repository writes.
- Mission Runtime and Capability Broker remain the execution authority.
- GitNexus remains pluggable but is not a hard dependency of this bank-reuse distribution.
