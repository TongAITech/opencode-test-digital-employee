# RC7.1 Autonomous Loop GAP Matrix

Shared Contract: `RC-AUTONOMOUS-TEST-LOOP@1.0.0`

| ID | Contract | Current baseline | Status | Target |
|---|---|---|---|---|
| RC71-AL-001 | Canonical L1-L7 | RC7.1 redefined L5/L6/L7 | FAIL | one CanonicalLayerRegistry |
| RC71-AL-002 | Dynamic CAT policy | historical L3/L5-centric assumptions | FAIL | dispatch/backend-driven CAT policy |
| RC71-AL-003 | N7 coverage closure | execution/retry stronger than coverage loop | FAIL | denominator->gap->delta->remeasure loop |
| RC71-AL-004 | Coverage denominator | no unified versioned L1-L7 denominator | FAIL | CoverageDenominatorSnapshot |
| RC71-AL-005 | Cross-layer reopen | incomplete | FAIL | denominator expansion invalidates stale receipts |
| RC71-AL-006 | DATA recovery routing | some paths -> Script Readiness | FAIL | N5 |
| RC71-AL-007 | PRECONDITION recovery routing | some paths -> Script Readiness | FAIL | N5 |
| RC71-AL-008 | AUTH recovery | stale/session-reuse risk | FAIL | N5 fresh 4A/current auth proof |
| RC71-AL-009 | N8 recovery | direct retry stronger than non-direct orchestration | FAIL | WorkOrder->Owner->Receipt->Successor execution |
| RC71-AL-010 | Failure signature loop | partial | PARTIAL | durable same-signature/no-delta budget |
| RC71-AL-011 | Defect dedup | symbol + expected/actual | PARTIAL | DefectSignature/evidence-backed similarity |
| RC71-AL-012 | Defect severity | default/external HIGH | PARTIAL | policy-derived severity |
| RC71-AL-013 | RCA depth | hypothesis exists | PARTIAL | CAT+CodeGraph+Git+Requirement chain |
| RC71-AL-014 | N10 layer objectives | critical obligation/case centric | FAIL | explicit L1-L7 objective matrix |
| RC71-AL-015 | Sufficiency vs quality | partially separated | PARTIAL | three independent states |
| RC71-AL-016 | Residual risk | durable registry incomplete | FAIL | ResidualRisk entity |
| RC71-AL-017 | Delivery packages | scattered | PARTIAL | shared contracts/schemas |
| RC71-AL-018 | R1 event names | scattered | PARTIAL | canonical event registry |
| RC71-AL-019 | AgentTeams receipts | bootstrap/assignment partly gated | PARTIAL | enforce assignment/member receipts across specialist nodes |
| RC71-AL-020 | Bank Field Reality | not verified | OPEN | field qualification only from real bank evidence |

Controlled Engineering PASS MUST NOT be reported as Bank Field Reality PASS.
