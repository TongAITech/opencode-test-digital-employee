# V1.9.4 historical capability → V1.13.0 recovery

Historical raw bytes were read from the provided Downloads paths. Both surviving V1.6 archives and the V1.9.4 base/hardening/harness/freshness/quality bundles are inventoried with hashes in `docs/reviews/rec3-final/HISTORICAL_RAW_SOURCE_REGISTRY.json`. Installation semantics and conflicting whole-file patch semantics were reconstructed from raw scripts. Legacy runtime is an oracle only; architecture v7 and R1 authority are preserved.

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
| API | RESTORED | Multi-step httpx business chain/extraction/schema/path/range/expression/state/idempotency assertions, real generated pytest resolving the same R1 case, bounded per-step G4 Evidence |
| UI | RESTORED | Scripted and interactive StandardCase actions, navigation/forms/frame/popup/network/screenshot, G4 cursor/lease/admission and approved-origin routes |
| Knowledge | UPGRADED | R3.E1 indexed, versioned task views; explicit scope/revision/freshness/ranking/dedup/budget; human review plus G4 proof; no second truth |
| Teaching replay | RESTORED | Execution-bound human trace → semantic locator candidate → approved generated script actual replay → governed asset; G6 HOLD |
| Unit | RESTORED | pytest plus hash-bound approved native runner argv/cwd; Maven/Gradle/JUnit/npm may use the same native binding |
| Performance | RESTORED | Local reused pinned k6, bounded approved load, error/SLO checks and Evidence |
| Security baseline | RESTORED | Governed one-request passive API header inspection, clearly not a full ZAP scan |
| ZAP full scan | OPEN_BANK_BINDING | ZAP and Java payload bundled; engine smoke is separate from approved bank scan policy and execution binding |
| CodeGraph | REPLACED | Frozen codegraph-ai/CodeGraph 0.20.1 graph-only; historical same-name 1.5.0 payload rejected as different provider |
| Git / ripgrep | PRESERVED | Git exact diff authority; local ripgrep enrichment; no invented actual coverage |
| CAT / DB / Manual | OPEN_BANK_BINDING | Existing governed G4 capability/HumanGate paths; bank adapters and credentials remain external |
| G5 defect flow | PRESERVED | Canonical investigated Observations→defects; no automatic defect from one error |
| INSTALL → daily START | UPGRADED | Offline INSTALL.sh to two arbitrary user-selected roots; workspace-template materialized directly; no service or auth during install; explicit installation identity and protected existing data |
| OpenCode starts with auth pending | UPGRADED | Normal conversation path starts real server and Control Loop before model readiness; installed entry verifies integrity |
| Host OpenCode | REPLACED | PATH-resolved external host, capability probing, no exact version gate, no provider/auth copy or XDG override |
| Natural-language mission entry | QUALIFIED_WITH_EXPLICIT_FIXTURE_BOUNDARY | Actual OpenCode user turn/tool path and distinct Planner/Worker Sessions; scripted semantic planner is not real-model proof |
| >=10MB context stress | QUALIFIED_WITH_EXPLICIT_FIXTURE_BOUNDARY | Bounded evidence reader, two supervisor rotations, same lineage, task completion; synthetic transport is not bank evidence |
| Entry/status/package truth | UPGRADED | Recovery product1.13.0, canonical G1-G5 CLOSED/FROZEN, G6 HOLD; Windows and bank validation reported separately |
| Legacy aitest.db as product truth | INTENTIONALLY_NOT_RESTORED | Existing migration/reference code is not the recovery product entry |
| G6 automatic learning/promotion | INTENTIONALLY_NOT_RESTORED | HOLD; teaching observation does not grant promotion authority |

Actual executed scenarios and failures are in MACHINE_VALIDATION_RESULT.json.
Payload existence is not a test PASS; unconfigured bank connections stay explicit.

Actual OpenCode 1.18.3 user/tool messages and background Control Loop rotations are exercised with a synthetic model protocol and a >=10MB evidence source. The combined test requires two real successor Sessions, preserved lineage, completion, Control Loop restart and export replay. This proves runtime transport and bounded-context behavior; AI semantic planning and BLOAN bank results remain separate unproven gates. Authenticated UI assertions can reuse the exact approved CDP browser after G4 returns its lease to AI.
