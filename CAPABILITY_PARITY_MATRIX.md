# V1.9.4 historical capability → V1.12.0 recovery

V1.9.4 is the requested historical behavior oracle. The specific named base
and upgrade ZIPs are not mounted in this desktop environment; this matrix does
not assert their final composite byte identity or claim to have replayed their
upgrade scripts. Actual source is the latest canonical packaging branch plus
the recovery commits. Existing local offline tool bytes are inventoried by hash.

| Capability | Recovery classification | Concrete implementation / boundary |
|---|---|---|
| Mission/Task/Attempt/restart | PRESERVED | Canonical R1 Event Stream and ExecutionResume; no legacy product DB |
| BLOAN context pressure | UPGRADED | External G2.1 supervisor, message/turn/activity/byte/token fallback, checkpoint, abort, async successor ContextPack |
| BR→SR→TR | UPGRADED | Immutable revisioned G3 artifacts with source/parent/Code/API/Page refs; R3.1 relationships and bounded recovery reads |
| Requirement/SST files | RESTORED | DOCX/PDF/TXT/MD/JSON parser, SHA256, revisions, source provenance and R1/G3 persistence |
| Current Release/Starlink exports | RESTORED | Approved, expiring, exact-hash export binding and canonical Current Release facts; launcher and OpenCode tool |
| Live Starlink | OPEN_BANK_BINDING | Bank adapter/authentication required; export READY is not live connection READY |
| Human browser teaching | RESTORED | Human drives, bounded page/element/network/screenshot/response observations, real renderer crash/reload, R1/G3 candidate asset; G6 HOLD |
| 4A Human Takeover | PRESERVED | G4 HumanGate and fresh browser verification; user text only requests verification |
| API | RESTORED | Real httpx runner and pytest, explicit oracle, allowed origin/method, bounded response, G4 Evidence |
| UI | RESTORED | Playwright plus bundled Chromium; explicit selector/text oracle, approved-origin route enforcement |
| Unit | RESTORED | pytest plus hash-bound approved native runner argv/cwd; Maven/Gradle/JUnit/npm may use the same native binding |
| Performance | RESTORED | Local reused pinned k6, bounded approved load, error/SLO checks and Evidence |
| Security baseline | RESTORED | Governed one-request passive API header inspection, clearly not a full ZAP scan |
| ZAP full scan | OPEN_BANK_BINDING | ZAP and Java payload bundled; engine smoke is separate from approved bank scan policy and execution binding |
| CodeGraph | REPLACED | Frozen codegraph-ai/CodeGraph 0.20.1 graph-only; historical same-name 1.5.0 payload rejected as different provider |
| Git / ripgrep | PRESERVED | Git exact diff authority; local ripgrep enrichment; no invented actual coverage |
| CAT / DB / Manual | OPEN_BANK_BINDING | Existing governed G4 capability/HumanGate paths; bank adapters and credentials remain external |
| G5 defect flow | PRESERVED | Canonical investigated Observations→defects; no automatic defect from one error |
| INSTALL → daily START | REPAIRED | Offline INSTALL.sh to /d/PFC/AITest; no service or auth during install; explicit installation identity and protected existing data |
| OpenCode starts with auth pending | REPAIRED | Normal conversation path starts real server and Control Loop before model readiness; installed entry verifies integrity |
| Host provider reuse | PARTIAL_BANK_BINDING | Explicit sanitized binding, local plugin/custom SDK support without /v1 conversion; no credential copy or host config write |
| Natural-language mission entry | QUALIFIED_WITH_EXPLICIT_FIXTURE_BOUNDARY | Actual OpenCode user turn/tool path and distinct Planner/Worker Sessions; scripted semantic planner is not real-model proof |
| >=10MB context stress | QUALIFIED_WITH_EXPLICIT_FIXTURE_BOUNDARY | Bounded evidence reader, two supervisor rotations, same lineage, task completion; synthetic transport is not bank evidence |
| Entry/status/package truth | UPGRADED | Recovery product1.12.0, canonical G1-G5 CLOSED/FROZEN, G6 HOLD; Windows and bank validation reported separately |
| Legacy aitest.db as product truth | INTENTIONALLY_NOT_RESTORED | Existing migration/reference code is not the recovery product entry |
| G6 automatic learning/promotion | INTENTIONALLY_NOT_RESTORED | HOLD; teaching observation does not grant promotion authority |

Actual executed scenarios and failures are in MACHINE_VALIDATION_RESULT.json.
Payload existence is not a test PASS; unconfigured bank connections stay explicit.

Actual OpenCode1.18.3 message API and background Control Loop rotation are exercised with synthetic no-reply content. This proves session/checkpoint/attempt transport, not a bank model or BLOAN business result. Authenticated UI assertions can reuse the exact approved CDP browser after G4 returns its lease to AI.
