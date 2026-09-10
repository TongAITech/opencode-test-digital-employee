# AI Test Runtime V1.13.0 — Authoritative Operating Contract

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

- The only primary entry is `aitest-director`. Ordinary chat and explanations create no Mission. Semantic/mixed requests use `aitest_director` action `interact`: the model proposes nine typed intents for runtime-returned complete host clauses, and Runtime independently admits provenance, scope, effects and replay. Only explicit test execution uses `start_test`; empty or ambiguous scope requires one clarification. Never supply raw source envelopes/approval tokens or use old intake aliases. General-work and diagnosis routing require real typed workers and leases; a proposal alone grants no I/O. Users never manually create Sessions, select worker Agents or rotate context.
- Prefer short, explicit status summaries: Mission state, current cursor, blockers, Human Tasks and next action.
- Never expose configured secret values.


## G3 Code / Change Intelligence Providers
- Git is the mandatory and sole authority for exact repository/base/head, changed files and changed lines.
- Structural enrichment is provider-neutral. The selected offline CodeGraph payload is pinned only by repository-root `runtime-lock.json`; the current pin is `codegraph-ai/CodeGraph` v0.20.1, Windows x64, `graph-only`.
- CodeGraph/GitNexus-class providers may add enclosing-symbol, caller/callee, dependency and reference evidence, but they never replace Git Change Truth and never become Actual Coverage authority.
- Runtime binaries, graph indexes and provider caches are derived offline payloads and must not be committed to Git. Missing or invalid providers remain explicit `UNAVAILABLE`/`BLOCKED`; they must never be faked as `AVAILABLE`.
- Language structural providers are fallback/corroboration. Regex is last-resort `PARTIAL`; every relevant changed executable line must be `MAPPED_TO_SYMBOL` or remain an exact `MISSING_SYMBOL_MAPPING` coverage/risk obligation.
- ripgrep is best-effort reference enrichment only. Mission Runtime and Capability Broker remain the execution authority.
- GitNexus is not an active provider in this canonical source baseline; no GitNexus activation path is implied.

## Recovery entry and context precedence

These entry rules govern daily V1.12 operation even where historical contracts describe manual diagnostics or older `/aitest-*` commands. `OPENCODE_PROCESS_READY` is independent of Model/Auth/Mission readiness. Historical command examples are optional diagnostics, never prerequisites for a natural-language Mission. Planner owns semantic Tasks; Scheduler owns readiness; Session Router owns role and Session selection; Control Loop owns observation, checkpoint, rotation and recovery. Large Runtime/Evidence source bodies are forbidden as direct Session input; use bounded tools and references.

## Task knowledge and business execution
Use `aitest_knowledge` candidate for bounded, source-bound Requirement/BR/SR/TR/CodeSymbol/CodeImpact/API/Page/Journey/StandardCase/AutomationAsset/EvidenceSummary/DefectRootCause/HistoricalRegressionSignal assets. Preserve exact project/environment/version scope. Only fresh locally reviewed VERIFIED knowledge is eligible for execution Context; global learning/Skill promotion stays G6 HOLD. Never issue approval on behalf of a human.
API and both UI execution paths resolve the frozen StandardTestCase from R1 and pass through G4. Browser HumanGate observations belong to the current ExecutionAttempt. Complete human actions only after fresh same-context authentication/page/business checks; Runtime resumes the recorded cursor.
