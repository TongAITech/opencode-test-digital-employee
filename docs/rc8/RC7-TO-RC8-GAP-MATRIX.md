# RC7 -> RC8 Gap Matrix

This matrix converts RC7 field/reality findings into RC8 construction obligations. IDs below are RC8 carry-forward IDs; they do not replace historical RC7 evidence IDs.

Status lifecycle: OPEN -> IMPLEMENTED -> TESTED -> REALITY_VERIFIED -> CLOSED.

| ID | Sev | RC7 finding / risk | RC8 closure mechanism | Planned slice | Status |
|---|---|---|---|---|---|
| R7R8-G001 | P0 | Cross-node closed loop was not visibly/reliably demonstrated end-to-end | Central Mission Graph + Gap Router + invalidation + loop product view | W5 | OPEN |
| R7R8-G002 | P0 | Full-flow execution did not clearly explain what business risks/verification points were actually tested | Test semantic model + case attempt/assertion/evidence trace + report/workbench | W3/W8 | OPEN |
| R7R8-G003 | P0 | High-value route/auth analysis could disappear with a lost DSH session and quality could regress on re-analysis | Durable versioned runtime knowledge + evidence-backed promotion | W4/W6 | OPEN |
| R7R8-G004 | P0 | Session loss/history corruption could lose execution context or force manual reconstruction | Durable TestRun/WorkItem/checkpoint independent of session | W1/W3 | OPEN |
| R7R8-G005 | P0 | Director/orchestrator could perform work instead of reliably dispatching real workers | Authority boundary: control plane plans/routes/evaluates; worker/tool produces execution facts | W0/W2 | OPEN |
| R7R8-G006 | P0 | Tool/plugin installed/registered did not prove model visibility or real executable capability | Capability qualification chain and node registry | W1/W2 | OPEN |
| R7R8-G007 | P0 | PASS/EXECUTED risked being asserted without sufficiently typed real evidence | Evidence Contract + assertion binding + producer authority gate | W0/W3 | OPEN |
| R7R8-G008 | P0 | Planned/future activity could be confused with runtime truth | R1 executed-event contract; plans live outside executed event stream | W0/W3 | OPEN |
| R7R8-G009 | P1 | Browser daemon/basic functionality existed but DSH->Browser->real business->evidence chain was incomplete | Browser adapter contract + business-flow recorder + evidence binding | W2/W4 | OPEN |
| R7R8-G010 | P1 | API route guessing and repeated 404 exploration remained possible | Browser network discovery -> verified route knowledge -> task-scoped reuse | W4/W6 | OPEN |
| R7R8-G011 | P1 | 4A login capability could regress to historical cookie/manual-login behavior | Auth runtime skill + capability gate + fresh-login policy for required tasks | W2/W6 | OPEN |
| R7R8-G012 | P1 | CodeGraph could exist but not be obligatorily used for relevant Java changes, or stale graph evidence could be reused | Java-change policy + snapshot binding + graph_evidence + freshness gate | W2 | OPEN |
| R7R8-G013 | P1 | Test design could be one-pass and case count could masquerade as sufficiency | Independent sufficiency evaluator + Gap loop + empirical execution feedback to design | W5 | OPEN |
| R7R8-G014 | P1 | Requirement/code analysis could execute once without proving sufficiency or looping on gaps | Independent evaluation + Gap repair + re-evaluation and downstream invalidation | W5 | OPEN |
| R7R8-G015 | P1 | Test data/precondition construction was incomplete and could block real execution | Data requirement extraction + find/build/validate/lease/reclaim workflow | W5/W7 | OPEN |
| R7R8-G016 | P1 | L1 Maven/JUnit harness/environment behavior could be inconsistent despite configured paths | Preserve proven RC7 harness; node preflight executes minimal real JUnit and stores evidence | W2/W9 | OPEN |
| R7R8-G017 | P1 | L2 database/data execution had significant blocking risk | DB capability gate + data builder + typed BLOCKED reason/evidence | W2/W5 | OPEN |
| R7R8-G018 | P1 | L4 UI execution had partial/awaiting-worker/false-execution risk | Browser worker reality proof + step/action/network/screenshot evidence | W2/W4 | OPEN |
| R7R8-G019 | P1 | L6 was closer to baseline capability than fully verified business performance testing | Separate BASELINE from PERFORMANCE_VERIFIED capability/status | W2/W8 | OPEN |
| R7R8-G020 | P1 | L7 remained partial rather than fully qualified | Independent L7 capability qualification and honest partial status | W2/W8 | OPEN |
| R7R8-G021 | P1 | Failure diagnosis/retry/defect chain was not consistently closed | Failure classifier -> gap/defect route -> RCA -> fix verification -> regression | W5 | OPEN |
| R7R8-G022 | P1 | Backend product views were CRUD-like and insufficient to understand runtime testing | Product contract-first redesign; test task/requirement/report sample pages first | W8 | OPEN |
| R7R8-G023 | P1 | Version/requirement/BR-SR-TR/code/case/execution data could be missing or unsynchronized in admin UI | Central domain model + projection/read models directly linked to TestRun/R1 | W0/W8 | OPEN |
| R7R8-G024 | P1 | Repeated analysis could overwrite/lose better prior outputs | Snapshot/version lineage for code analysis, knowledge, flow and execution attempts | W4/W6/W8 | OPEN |
| R7R8-G025 | P2 | Context/session growth caused slowdowns or DSH loading-history hangs | Task-scoped context resolver + durable state + session rotation/re-attach | W3/W6 | OPEN |
| R7R8-G026 | P2 | Multi-agent/plugin registrations were visible while actual calls could be unavailable | Node/skill/capability conformance with runtime execution evidence | W1/W2/W6 | OPEN |
| R7R8-G027 | P2 | Startup scripts/process termination/restart behavior was fragile | Unified Node Agent shell lifecycle + diagnostics + recovery | W1/W9 | OPEN |
| R7R8-G028 | P2 | Admin/report evidence navigation did not consistently show complete step/assertion/actual mapping | Unified evidence viewer + attempt detail + report trace | W3/W8 | OPEN |
| R7R8-G029 | P2 | Knowledge/flow/API facts were not team-shared across testers/nodes | Center knowledge + artifact sync + skill distribution | W6/W7 | OPEN |
| R7R8-G030 | P2 | Packaging success could differ from bank-environment install/start reality | Continuous Center/Node packages + clean-machine + bank smoke + restart/upgrade gates | W9/W10 | OPEN |

## Closure rule

A carry-forward gap closes only when:
1. the RC8 implementation exists;
2. automated tests pass;
3. required real runtime evidence exists;
4. the product projection (where applicable) correctly exposes the fact;
5. regression does not weaken the inherited RC7 capability.

No gap is closed by design text, code existence, mock-only success or worker self-report.