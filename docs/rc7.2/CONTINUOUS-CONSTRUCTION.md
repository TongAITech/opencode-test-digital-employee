# RC7.2 持续施工与最终搬运交付

## Native worker process environment and launch admission — 2026-11-03

The shared DSH launcher now delegates process-environment projection to its
concrete authority before emitting WORKER_STARTED or launching a child. Legacy
RC6/RC7 authority retains its previous environment behavior. RC7.2 authority
requires the current exact signed identity/lease/worker/scope, rejects revoked,
expired or not-yet-issued grants, and supplies a private home/profile keyed by
worker, session, lease and scope. Native workers do not inherit the Captain's
ambient environment or DSH home; explicit scoped provider configuration remains
available to the worker.

Explicit control credentials, external home/profile paths, interactive-control
mode, broader/duplicate tool projections and mismatching caller projections are
rejected before a process or WORKER_STARTED record. Protected environment keys
are canonicalized to prevent case-insensitive Windows aliases from bypassing the
checks. Tool order may differ when exact membership is unchanged. Every native
worker receives LEASE_BOUND_WORKER mode; absent downstream MCP configuration
cannot fall back to Field interactive authority.

A real child-process canary changed from parent-marker/profile visibility to
neither being visible. Tests exercise eight professional roles, distinct grants,
explicit provider configuration, startup TTL/revocation/scope rejection and
Windows-style aliases. Initial native N1→N5/launch regression passed 57 tests;
inherited RC7 regression passed 492 tests with 1 existing skip and 7 collection
warnings. Final caller-projection/environment/native-N5/N1-N2 checks passed 53
in 21.70s. An earlier launch-fence revision completed the original full 28-Case
product chain in 615.43s; final grant/profile/caller hardening is covered by the
targeted tests and still requires exact committed-source whole-chain/platform
qualification. The unchanged file budget is 900 seconds.

This is environment/profile projection and launch-time authority admission, not
an OS filesystem sandbox or proof of all tool-call authorization. Native per-role
DSH profile/provider materialization, complete MCP task projection and actual
call-time gates remain C07/C08 work. N1 already owns a canonical rc7_task; its
WorkerAssignment scope is mission-node://..., which the inherited task resolver
does not map to that task. Reuse the real workitem/assignment lineage when wiring
that bridge; do not create placeholder Tasks or permit interactive fallback.
The broader frozen design, N9/N10/controller and complete transport remain OPEN.

## Worker-owned authenticated HTTP execution — 2026-11-03

`WorkerHTTPAuthAssetProvider` now reads one bank-host export bound to the exact
Preparation/Release/source/Mission/WorkItem/Attempt/worker/contract. Frozen N4
transport may select `WORKER_HEADER`; the selected approved N1 auth Fact must
supply the exact principal, full role set, non-device-bound asset reference and
same-origin identity probe. The original Case role remains authoritative.

The parent performs real authenticated identity HTTP before business I/O and
requires the actual account and complete role set to match N1. Extra privileged
roles are rejected. Only the parent uses Authorization; the child gets the fixed
native operation capability, with no secret argument or credential environment.
Signed observation binds the original asset via domain-separated HMAC, actual
identity response hash, original scope, frozen auth specification and time window.
Historical review needs no old secret file and never restores live permission.

Fresh live-dispatch/source/authority/resource/asset checks surround the effect.
A signed identity observation is journaled before business dispatch, followed by
another permission check. Rotation/expiry during business retains signed UNKNOWN,
actual captured response and custody without automatic replay/cleanup. Authentication
failures retain bounded runtime reason codes, not server bodies or header values.
Missing providers fail preflight rather than silently switching to anonymous.

Evidence: `worker-http-auth-final-integrated.log` 52 passed in 152.68s across auth,
anonymous native HTTP, formal Runner, conclusive failures, pipeline and N4 handoff.
`worker-http-auth-discrepancy.log` additionally passed a real authenticated business
discrepancy through separate independent N8/reviewer processes to N9 intake only;
no PRODUCT_DEFECT or N7 PASS was invented. Renewal/heartbeat/full repair-retry/obligation regressions for this new source
passed 38 tests in 145.54s (`worker-http-auth-recovery-qualification.log`). The
complete original 28-Case product regression passed in 645.41s under its unchanged
900-second limit (`worker-http-auth-product.log`) on runtime source `f318f945`.
No Case, original Attempt evidence or obligation denominator was removed.

This concrete provider supports bank-exported, non-device-bound Authorization
headers with same-origin identity probing. Actual bank AuthKeeper/4A automatic
export/lifecycle wiring, device-bound Browser/Cookie/mTLS/other identity providers,
authenticated preparation/cleanup provider composition and all-role DSH fences
remain construction work. It does not establish bank Field qualification or close
all of C07/C09. See [the exact host contract](NATIVE-HTTP-AUTH-ASSET-CONTRACT.md).
N9 professional qualification/RCA/fix/regression, N10/controller and complete
physical transport delivery remain OPEN; overall goal stays ACTIVE / NO_DELIVERY.

## Full 28-Case native product-chain qualification

Exact runtime source `f3ac2da4e11a6a4f16bde335a12ce74eca004309` passed the
complete original 28-Case N1→N7 product flow in 622.11s under the unchanged
900-second file budget (`native-http-plan-economy-product.log`). The test includes
actual parent-owned HTTP/process execution, cleanup and released resources,
independent N7 acceptance, primary/secondary obligation proof from the same
original Attempts, and no-write driver replay. The final-source failure/repair/
retry/pipeline/obligation regression also passed 28 tests in 129.07s
(`native-http-plan-economy-recovery-final.log`). N9 remains READY: this does not
claim N9/N10, Mission convergence, Field or final transport completion.

Two earlier whole-chain runs remain recorded as TIMEOUT/FAIL at 900 seconds:
the pre-replay-optimization source (`native-http-full-product.log`) and
`e9b70d2` before fresh admission input reuse (`native-http-final-source-product.log`).
The qualified improvement retains the original Case denominator and acceptance
rules. For parent `f3ac2da`, construction and Linux engineering qualification are
terminal SUCCESS while Windows engineering is still running; Q2 clean-unpack
is terminal SUCCESS, which does not establish a complete package.

## Actual parent-owned HTTP execution and replay economy — 2026-11-03

The N7 formal API Runner now uses `RC72_NATIVE_API_HTTP_V1`: an ephemeral local
capability invokes the parent-owned transport with the original approved N6
endpoint, method and JSON input. The child cannot supply replacement request
arguments. Before the effect, the parent refreshes R1 under the shared ledger
lock, checks the live dispatcher, exact contract, worker authority and resource
custody, and persists a signed intent. It checks authority again after the
response. Revocation or interruption retains UNKNOWN/IN_FLIGHT custody; no
business replay or automatic cleanup is authorized. A duplicate request in the
same live invocation returns the authenticated observation without another I/O.

The parent captures real response bytes outside the declared child output root.
Signed formal receipts bind those bytes, the frozen N4 response mapping and both
temporal authorization snapshots. Child-reported tool names or invented result
values cannot establish API execution. Independent discrepancy review rehashes
and maps the actual native response before recomputing the frozen Oracles.
An API result labeled as DB/CAT or another independent tool Oracle remains HOLD
until that native provider supplies its own evidence.

At this earlier checkpoint the transport supported anonymous HTTP(S), JSON
input and frozen response projection. The newer Worker-auth section above adds
an explicit scoped Authorization provider; unsupported bank authentication modes
still do not fall back to anonymous execution. Host credential providers, DB/CAT/Browser tool gates and all-role DSH
enforcement remain OPEN under C07/C09. This gate does not establish general OS
process isolation; such isolation is not added here as a new frozen-design
delivery requirement. This is construction evidence, not bank Field qualification.

Validation recorded so far: `native-http-integrated-final.log` 49 passed;
`native-http-oracle-provenance-final.log` 1 passed;
`native-http-replay-economy-final.log` 34 passed. Current-source affected-service regression: `native-http-final-affected.log`
24 passed. Recovery regression found 76 passes and three obsolete expectations;
strict native evidence-gap requalification passed all 20 evidence tests, and
renewal-denied/process-timeout requalification passed both fault tests while
retaining blocked Attempts and custody. The complete product-chain qualification is recorded in the latest section
above; no final-source platform claim is made. Parent source `36f7d05` has
terminal Windows/Linux platform, construction and clean-unpack CI success.

Ledger replay still validates every native/legacy event and rebuilds from the
complete journal on each locked decision. It avoids a second normalization and
an unused returned snapshot. A 1,974-event, 3,353,609-byte real construction R1
prefix produced identical current state AND all version histories; observed
rebuild time was 0.420s before and 0.346s after. This narrow local measurement does
not establish whole-release scalability or close C10.

Next: complete the recovery/product regressions, qualify exact committed source
on Windows/Linux, and continue authenticated native providers, N9 professional
qualification/fix/regression, N10/controller completion and the complete RC7.1
transport inventory. C01–C12 reconciliation remains authoritative. Overall
status stays ACTIVE / NO_DELIVERY; there is no complete portable package yet.

### Fresh admission input reuse within one plan decision

A full 28-Case run on the earlier double-normalization source reached the
unchanged 900-second limit before completion (`native-http-full-product.log`).
It is a failed qualification, not a PASS. The subsequent replay-only source
also timed out; the additional admission reuse below then passed the complete
chain, as recorded above. The time budget and Case denominator are unchanged.

A further measured duplication was removed: plan validation used to perform the
same complete admission check twice per Case, first to authenticate the receipt
and then to obtain its reconstructed input. The internal decision now returns
both results from the same full check. Each new plan decision still reconstructs
all original Cases, sources, Gates, runtime/data bindings and digests; it does not
cache across decisions or trust caller-supplied readiness. The returned batch and
contract are checked against the exact plan item before use.

On an unchanged real 28-Case R1 copy, both paths returned identical plans without
journal writes. Admission checks decreased from 56 to 28, and the measured plan
validation decreased from 2.393s to 1.216s. `native-http-admission-economy.log`
passed all 28 admission/planning/native-HTTP tests. This is a local decision cost
reduction; full-chain completion remains mandatory before final qualification.

## Frozen-contract business discrepancy → independent N8 → N9 intake — 2026-11-03

The concrete N7 pipeline now handles an actual successful approved Runner whose
frozen business Oracle fails. `ConclusiveAssertionFailureEvidence` uses native
historical source/identity/dispatch checks, all approved precondition/data checks,
formal process/target proof, signed cleanup and released resources, and every
required evidence file. It captures an immutable HMAC-signed proof as canonical
Evidence, retaining the full original plan denominator and failed Case/Attempt.
The ordinary positive N7 review and finalizer still require all Oracles PASS.

The typed same-preparation N8 evidence service admits that proof; separate actual
diagnostic/reviewer processes reread captured bytes and independently recompute
all deterministic Oracle operators. A reviewed discrepancy routes only
`VALID_TEST_FAILURE` to the actual N9 Gap/back-edge. It does not establish product
causality or create a Defect, turn the failed Attempt/N7 into PASS, shrink pending
Cases, or automatically replay business actions. Missing evidence holds before
acceptance; forged product-defect output is rejected by the second process.
General unexplained failures without this proof remain UNKNOWN as before.

Cold continuation reuses original dispatch/cleanup/diagnosis receipts. Partial
capture/proof canonical writes resume from identical signed bytes, repairing only
the exact missing base Evidence pointer after authenticating the existing proof.
Already stored diagnosis/review results complete acceptance without another
process or restoring business authority. Process failure/absent tool observation
now holds before automatic cleanup and records the actual blocked Attempt;
unknown external effects retain original resources for diagnosis.

Evidence: `conclusive-failure-integrated-final.log` 100 passed in 328.73s covering
N7 review/finalization/cleanup, N8 existing/retry/member reuse, pipeline and native
obligation audit. Final targeted `conclusive-failure-qualification-final.log`
9 passed in 30.63s covers real HTTP, cold R1 restart, absent files, forged/rehashed
signature, changed capture bytes, independently rejected product-defect claims,
and interruptions after capture, failure proof or actual diagnosis fsync.

Historical limit at this checkpoint: the approved Script/Runner trace alone
was insufficient native tool attestation. The newer parent-owned HTTP section
above supersedes that API-only boundary; other tool/provider gates remain C07
work required before final delivery. Local tests perform actual HTTP/process I/O,
but are not bank DSH/physical-tool Field qualification. N9 professional defect
qualification/RCA/fix/regression, other semantic C03 repair classes, upstream N8
repair execution in the controller, actual N9/N10 driver/factory and complete
RC7.1-equivalent transport remain OPEN. Overall goal remains ACTIVE / NO_DELIVERY.


## Native accepted execution → full obligation evidence rollup — 2026-11-03

`AcceptedObligationExecutionProof` refreshes R1 under the shared ledger lock and
requires the actual accepted current N7 Delivery. New read-only finalization
`audit` rechecks signed independent process bytes, full bundle/source/cleanup
proof, Gate and Delivery scope, canonical review Evidence, original completed
bindings, actual PASS Attempts, independently accepted WorkItems and matching
output artifacts, and closed executor/reviewer identities. It cannot resume or
repair partial finalization, dispatch tools, restore leases or write acceptance.

The rollup maps every approved primary and secondary coverage_links obligation
to its unchanged original Case SHA, actual Attempt and current-plan ETU. Whole
Case/ETU denominators and exact canonical obligation lineage are checked; blocked,
stale, revision/split/merged ETUs do not pass. No copied Case/ETU, repeated business
call or manually promoted VERIFIED flag substitutes for accepted evidence.

`ReleaseConvergenceAggregator(execution_proof=...)` optionally consumes this
concrete same-R1/same-release native service before publishing any observation.
The existing legacy path remains compatible. Actual HTTP/pytest tests prove
primary/secondary sharing, unchanged execution count and read-only audit, while
changed process bytes, evaluator identity, canonical obligation lineage and
blocked ETU reject. The fixture deliberately retains required L1..L7 policy:
accepted L3 evidence does not turn missing levels or Mission convergence PASS.

Local verification: 16 passed in 37.42s across the native proof, inherited N10
convergence/coverage terminal and N7 pipeline tests; additional blocked-ETU proof
1 passed in 6.41s. Upstream N6 merge validation 2 passed in 76.54s. The full
28-Case product integration now also asserts whole primary/secondary obligation
rollup; its new exact-source CI is pending, not claimed by the earlier N7 run.

C05 remains ACTIVE: full incremental coverage/Gap closure, multi-version release
convergence and the production N9/N10 driver route remain open. C03/C04 conclusive
failure/defect handling, C07 all-role tool fences, product factory, Journey/economy,
final same-source qualification and COMPLETE RC7.1-equivalent package remain open.


## Native formal N7 product route — 2026-11-03

N7PipelineService connects the actual planning/preparation, signed dispatch,
FormalN7RunnerAdapter child processes, environment cleanup/verification,
immutable evidence capture and independent-process finalizer. Existing returned
calls/cleanup proofs resume without restoring released business leases. Unknown
external effects remain held without replay or cleanup. Review-pending and PASS
resume the original active Delivery/bundle, whose full native proof is audited.
A genuine accepted N7→N9 FORWARD edge skips dormant N8 scheduling; it never
changes N8 into PASS. Local engineering tests include real HTTP/process I/O;
initial approvals remain fixtures, not bank Field or production DSH proof.
C08 remains incomplete: N8 repair/N9/N10, production factory/run command and
broader semantic repair. Complete RC7.1-equivalent transport remains C12 OPEN.


ExecutionPreparationService now checks the current identity/contract/task and
all business resources under the same OS-held ledger decision lock through
worker authority restoration. This removes the intervening projection refresh
race and repeated per-resource full replays. Signed existing process suspension
still denies a cold controller before lock acquisition and is checked again
inside. Heartbeat lock contention retains the bounded existing retry semantics.
This is a narrow C06 correctness/performance improvement; legacy writers,
unknown-effect/orphan adjudication and all-role tool fences remain open.



Validation for this checkpoint (local engineering, not Field):
- Full N1..N7 product composition: 28 original approved Cases, real HTTP and
  formal child processes, cleanup, independent acceptance and read-only replay;
  1 passed in 789.79s under the explicit 900s whole-chain budget. Existing
  contract-file budgets remain 180s; path normalization supports Windows.
- Atomic preparation/process/renewal/expiry/resource exclusion and N7 pipeline:
  56 passed in 126.49s. Includes actual external lock contention at authority
  restoration, cold cleanup/review continuation, unknown effect no replay and
  actual malformed independent reviewer process held without looping.
- Windows candidate transport regression: 19 passed in 201.69s across files.
  Prior exact 95be2cc Windows CI failed five files with WinError 206: large
  fixture candidates were argv payloads. The protocol process now reads the
  complete content-addressed candidate file, preserving native review content.
  Actual production DSH's large-prompt transport still needs its supported host
  protocol verified; fixture transport is not evidence of that host capability.
- Previous N1/N4/N5 regression 21 passed in 63.82s; budget runner 4 passed.
- Logs are release-driver-n7-full-final.log, release-driver-n7-atomic-authorization-final.log
  and release-driver-windows-candidate-transport.log in ../evidence.
- Prior 95be2cc Linux platform baseline passed; Windows failed as above. New
  exact-source Windows/Linux qualification is required. No final package exists.

## Native N6 product route and canonical multi-obligation Cases — 2026-11-03

The product driver now automatically uses N6PipelineService and the existing
CanonicalExecutableService, not caller-supplied ExecutableContracts. Every
approved Case is checked for reviewed execution materialization before compile
writes; all missing Case IDs are returned with owning N4. Typed readiness
violations retain their actual canonical Case scope. Native request/schema
facts are routed to N3 at this Case boundary, never to N1 (which explicitly
cannot own them); inherited standalone compiler behavior remains compatible.

Composition exposed canonical mapping incorrectly requiring every obligation
to be a Case's primary owner. CanonicalDesignService now also recognizes the
approved coverage_links, checking Requirement/SST/layer lineage and rejecting
orphan links. It preserves all obligations, original Case identity, primary
ownership and source hashes. It never duplicates Cases or drops secondary
obligations to make N6 pass. N7/N10 must still consume the full semantic coverage
relationship; final convergence of secondary obligations remains C05 work.

N6 PASS/review-pending recovery re-audits the original approved sources and
reuses immutable contracts; no data occupancy or Case execution result is
created. Missing execution materialization remains HOLD rather than guessing.
Engineering protocol evidence and limits are in RELEASEBATCH-PRODUCT-DRIVER.md.
C08 remains incomplete: N7..N10, semantic repair routing, production factory/run
command, C07 all-role fences and final RC7.1-equivalent package remain open.


## Native N5 product route and owned WorkItem closure — 2026-11-03

The ReleaseBatch product driver now connects concrete N5PipelineService:
canonical whole-Case inventory, deterministic reuse/discovery planning, native
discovery assignment and DSH output, immediate raw anchoring/promotion, a fresh
independent verifier, native resource/binding finalization and whole N5 Gate.
Dispatched plans keep their original denominator while work is in progress;
only after all results are finalized may verified reuse plans be recomputed.
Cold continuation handles mixed finalized/pending work and partial replanning.

N5WorkItemFinalizer re-audits actual native verifier output before closing each
owned discovery task through canonical Evaluation. Negative results create
explicit TEST_DATA_GAP repair work owned by TEST_DATA with test_data capability;
the inherited TEST_DATA_DEFECT -> SCRIPT_READINESS policy remains unchanged.
N5OwnedWorkItemGateService rejects verified bindings that hide unfinished owned
tasks, independently binds Evaluations to native verifier results, and rechecks
producer/verifier raw bytes and promoted candidate hash. This is data-work
acceptance, never Case execution PASS, DataLease authority, Field or BANK_FINAL.

The driver now resumes REVIEW_PENDING through actual registered N1..N5 Gate
services, rather than returning NODE_NOT_READY after a durable Delivery write.
Unsupported nodes remain HOLD. Production N6..N10, semantic repair execution,
worker factory/run command, C07 all-role live tool fences and full portable
package remain open. General interruption inside inherited Evaluation/Gap/task
journal writes remains C06 work; tested recovery points are listed separately.


## Native N4 product route and parent-scoped acceptance — 2026-11-03

The ReleaseBatch driver now connects N4PipelineService: the exact canonical
Requirement x SST set -> native assignment -> DSH design -> immediate raw
anchor -> candidate promotion -> independent design review -> formal N4 Gate.
Cold assignment/review boundaries resume without repeating the designer.

Composition uncovered a real acceptance gap: legacy N4 obligation schema could
not carry its parent source mapping. The additive source_refs contract preserves
exact KIND:source_id:parent_artifact_id identities. N4ParentScopedDesignEvaluator
requires every mandatory parent source in a required same-kind obligation;
equal symbol IDs in different repositories cannot collapse the denominator.
It composes actual independent review with inherited deterministic Oracle and
SufficiencyV2 depth/interaction guards, retaining the native RC7.2 Case contract.
N4ParentScopedDeliveryGateService independently recomputes these checks before
writing a Delivery or opening N5, including when older review rows say PASS.

Actual DSH independent design review also required the inherited reviewer role
in RC72AuthorityRuntime; only its exact review-candidate/analysis-gap permissions
were added, never canonical Case, obligation, Evaluation or Gate write rights.
N4/driver regression and recovery evidence is recorded in
RELEASEBATCH-PRODUCT-DRIVER.md. Protocol children are engineering adapters, not
bank DSH/physical-tool Field proof. C08 remains incomplete: N5..N10, repair/retry,
worker factory/run command and C07 all-role live fences remain open. No final
RC7.1-equivalent portable package has been built or delivered.


## Native N3 product routing — 2026-11-03

The ReleaseBatch product driver now uses concrete N3PipelineService for the
application discovery -> anchored candidate -> independent source mapping
review -> every discovered code target -> independent Code evaluator -> whole
N3 Gate chain. Native Git/CodeGraph requirements and mandatory impact dimensions
remain authoritative. Unresolved discovery is a HOLD before promotion/code;
negative code sufficiency never opens N4. Source and code promotion interruption
resumes from canonical bytes without repeating discovery or analysis. Completed
N3 replays the native Gate without rolling downstream state back.

N1/N2/N3 product and recovery chain: 15 passed / 10.93 s. See
RELEASEBATCH-PRODUCT-DRIVER.md. Engineering child protocols do not qualify actual
bank DSH/Git/CodeGraph tool bodies. C08 remains ACTIVE, incomplete: N4..N10,
repair/retry routing, production factory/run command and all-role C07 fences
still open. Final RC7.1-equivalent portable package has not been built/delivered.


## ReleaseBatch product route foundation — 2026-11-03

C08 is now ACTIVE: the concrete ReleaseBatchDriver connects actual N1 strict
completion to the whole N2 Requirement fanout, governed candidate promotion,
independent DSH review and formal NodeGate. No caller-provided PASS callback or
driver completion record exists. Read-only `rc7_release.rc72_mission_cli status`
reads existing R1 without worker configuration. Cross-process batch ownership,
cold source audits, interrupted promotion-to-review continuation and unchanged
required denominator are exercised. Native regression: 37 passed / 5.60 s.

This composition uncovered and fixed N1 replay requiring N2 to stay READY:
advanced downstream states now require the original canonical forward lineage
and are not reset. See RELEASEBATCH-PRODUCT-DRIVER.md for actual route and limits.
N3..N10, repair/retry routing, production worker configuration/run command and
all-role call-time tool fences remain open. This is not a complete C08 product,
Field qualification or final package. The overall goal remains ACTIVE.


## Whole-repair resource custody — 2026-11-03

Existing-DataRef repair admission now takes the same OS ledger lock as data
reservations and native tool calls. Its durable request owns exact-resource
custody while preparation and independent verification are in progress, across
process/controller restarts and the gap between returned tool calls. Another
repair cannot concurrently claim that resource. Native tool calls reject a
conflicting unfinished repair, and normal reservations cannot bypass it.

A negative independent result (`REPAIR_REQUIRED`) retains custody. A later
repair may restore the exact resource; ordinary reservations reopen only when
that repair is independently VERIFIED, the exact binding revision points to its
anchor and contains its actual verification evidence, and its block is cleared.
A failed terminal row by itself never makes the resource available.

Validation: actual MCP preparation/verifier, independent cold-controller
reservation, negative verification then a fresh exact-binding repair and
successful verification: `native-repair-lifecycle-retry.log`, 2 passed (13.99 s).
Native repair integration: `native-repair-lifecycle.log`, 36 passed (127.98 s).
Custody/fencing and cross-process reservation checks:
`native-repair-lifecycle-cold.log`, 16 passed (40.88 s). Unknown-effect disposition,
all journal writers and general orphan recovery still require C06 construction;
this is not full design or delivery qualification.


## Native N5 call-time authority — 2026-11-03

C07 now has an actual MCP-to-parent execution bridge for existing-DataRef
preparation and independent verification. Each physical handler is admitted at
call time against the signed assignment, exact tool and arguments, current task
owner, unrecalled lease and deadline. Child workers receive a scoped ephemeral
capability and isolated environment, never the parent signing key. Native mode
cannot fall back to the legacy field handler. A reported tool call or positive
output without matching signed physical observations cannot produce a handoff.

Signed call records distinguish IN_FLIGHT, RETURNED and UNKNOWN. A transport
retry of the same returned request does not repeat effects; an unknown effect
cannot replay or reopen its former invocation. In-flight/unknown calls and data
reservations share the ledger gate and preserve conflicting resource custody
across missions. Historical evidence verifies scope and observations without
restoring an old live capability.

Validation: `native-call-gate-integrated.log`: 54 passed (129.04 s), covering the
actual MCP subprocess entry, native repair finalizers and inherited DSH/MCP
contracts. The protocol worker is an engineering adapter, not real DSH-host or
bank Field qualification. Additional custody/process checks: `native-call-gate-custody.log`, 14 passed
(29.50 s), including a different mission denied during IN_FLIGHT and after
UNKNOWN plus controller closure.

C07 remains incomplete: other node roles, non-MCP tools, physical specialists,
provider/captain/session takeover and the unified production driver still need
implementation/qualification. Generic unknown-effect disposition and full N5
lifecycle reservations remain C06 work. C03/C04/C05/C08/C09/C10/C11/C12 remain
open as tracked below; this component does not authorize final delivery.


更新：2026-11-03。起点：8563f984f714e589048106c2a115ceddac6478c5。
状态：ACTIVE / DESIGN_INCOMPLETE。用户已授权完成全部设计落地后制作开箱即用搬运包。

## 目标与完成条件

依据冻结设计 00..05、07、08、09，逐项完成代码、产品入口、实际运行链路、
契约测试、继承回归及同源工程平台验证，再制作并验证最终搬运包。
用户已明确：最终现场验收由用户搬包进行内后执行，本轮不等待现场环境接入。
不以测试数量、单个节点、工程示例或旧包代替设计完成。设计 09 的任务完成优先
规则继续有效：不能为节省模型调用删减必测范围，也不能把 UNKNOWN 用量伪称实测。

持续目标在当前任务中保持 ACTIVE；每个施工段完成后选取下一未完成项继续，
无需用户重复发送“继续”。提交、推送、测试通过仅是检查点，不结束总体目标。
只在确实需要外部资料或用户决策、且不能继续任何独立施工时记录阻塞。
不得将缺失的银行环境、真实审核或现场证据替换为 fixture PASS。

最终完成必须同时满足：
- 全部 Phase 0..10 / GAP-01..08 / CT-01..26 有对应实现及验证证据；
- ReleaseBatch 产品入口可驱动 N1..N10，失败、修复、重试及接管均使用 R1；
- Q0/Q1/Q2 和可在仓库执行的 Q4 资格满足条件；Q3..Q9 现场部分提供
  可执行验收入口与证据导出流程，状态如实保留 PENDING/HOLD，不伪称 PASS；
- 最终源提交的回归与 Windows/Linux 工程资格通过；目标 Linux 留给行内实机验收；
- 最终包校验和、载荷清单、离线依赖、双平台启动、干净目录解压启动、
  配置引导、诊断和恢复说明全部核验，包内身份与源提交一致；
- 输出最终包、校验和、操作说明和验收记录。未经证明不标记 BANK_FINAL。
- 搬运包必须达到 RC7.1 同等级完整载荷：不是源码包、增量补丁或测试压缩包；
  对照继承 package 构建器逐项核对 Python/离线依赖、DSH/工具/插件、浏览器/CodeGraph、
  工作区模板、配置引导、双平台入口、运行诊断和验收材料。
  具体继承载荷见 COMPLETE-TRANSPORT-BASELINE.md（含 Node、Java/Maven 离线仓库、
  OCR/CV、Allure/k6/ZAP、BSK CLI/扩展及最终封装链，不能只用工程包构建器）。

## 当前对齐

已定位的实际工程链路：规范 N1..N6 源/Gate 接纳、持久规划、严格签名 Worker、
实际本地 N7 运行/证据/补偿/独立进程审查/最终化；实际窄范围数据失败 N8
诊断与独立复核、N5 回边、独立补偿权限及修复边界；原 DataRef 原生复验与
Gate 版本机制；复用 DataRef 独立物理修复/复验和新 Gate/修复接纳；影响集冻结、
局部中断恢复及新 Attempt 关联约束。

已有证据不能覆盖：真实银行端到端任务、全部 N8 分类、
N9/N10 产品消费者、全局并发/孤儿恢复、Journey/经济策略的所有产品调用点。
详细历史证据见 CURRENT-CHECKPOINT 和 DESIGN-CONSTRUCTION-RECONCILIATION。
旧搬运包保持隔离，不进入本次交付。

## 按依赖推进的工作队列

| 编号 | 施工范围 | 完成证据 | 当前状态 |
|---|---|---|---|
| C01 | N5 复用数据缺少 discovery candidate 时的独立修复 assignment、原 DataRef 复验、新 Gate | 实际 N8 边界进入；独立 verifier/原始证据；旧证明不复用；失败不放行 | CODE_COMPLETE_CI_PENDING：145 项跨节点通过；最终源码冷启动等 69 项通过 |
| C02 | 修复影响后 N6 重编译；新规划保留原 WorkItem/ETU/Case、继承 parent Attempt | 实际修复→重编译→新签名 Attempt→执行；原失败历史不变；完整分母 | CODE_COMPLETE_CI_PENDING：238 项跨节点通过；最终源码 8 项恢复/篡改/完整执行通过 |
| C03 | N8 其余语义分类与 N1/N2/N3/N4/N6 修复回边、受控重试/UNKNOWN | 独立证据审查；版本失效和新 Attempt；非产品故障不生成缺陷 | ACTIVE：本地可执行文件实际缺失→独立能力缺口诊断；通用探测失败保持 UNKNOWN；其余回边待施工 |
| C04 | N9 缺陷/有效失败接纳、RCA/回归与 N7 完整分母审查 | 真实动作/结果证据关联；缺陷生命周期和验收分支；非叙述定案 | OPEN |
| C05 | N10 全 ReleaseBatch 消费者与 coverage 反馈闭环 | 全 Requirement/SST/Obligation/L1..L7、高风险/缺陷/gap/证据/STALE 分母；结构化未收敛理由 | OPEN |
| C06 | 全局 Data/Browser 写排他、过期/续约、孤儿 claim/session、初始 N8 多事件恢复 | 多进程争用、崩溃恢复、不能重复业务 I/O、旧权限不复活 | ACTIVE：原生进程自动心跳/全租约续约、过期 custody、签名补偿；已执行成员签名排空、未影响复用及受影响新 Attempt 贯通整体验收；原生混合多成员、已执行/待重跑成员双轮修复及整体验收已验证；通用孤儿、其他故障补偿及调用 fencing 待完成 |
| C07 | 同任务 Provider/Captain/会话接管；STRICT Capability amendment/delegation | 实际启动器/任务入口；丢会话不丢工作；权限不扩大、不继承 Captain 凭证 | ACTIVE：原生 N8→Broker 决定/冷恢复/撤销；N5 准备与独立验证已接实际 MCP 调用时拦截，其他角色/非 MCP/接管仍待落地 |
| C08 | 统一产品入口/推进器/状态查询接上全部原生节点服务 | 真实产品命令/接口从 ReleaseBatch 驱动 N1..N10；重启从 R1 接续；无测试专用快捷开关 | ACTIVE：N1→N2→N3→N4→N5→N6 已接通，缺失执行信息按用例和所属节点阻断；N7..N10 和生产运行入口待落地 |
| C09 | Journey 教学→编译→回放→基准→人工批准→正式 L4/L5；真实 Browser 所有权 | 正式资产和完整业务谱系；独立浏览器租约及批准范围核验 | OPEN/AUDIT |
| C10 | 模型经济 A..H 与真实生产/审查/修复启动点集成 | 实测或 UNKNOWN 用量、上海时窗、软预算、浪费硬门、最小上下文/重试增量、逐成员 batch 证据、Q7 双结果 | OPEN/AUDIT |
| C11 | 全设计/CT/GAP 审核与同源 Windows/Linux 工程验证 | 当前源的逐项证据表；否定用例；CI 不能替代现场 | OPEN |
| C12 | 最终离线搬运包与 Q3..Q9 行内验收工具 | 双平台离线干净启动、校验和、行内实机/BSK/审核/真实任务/故障演练入口与证据导出；现场结果由用户搬包后获取 | OPEN / 无现场接入依赖 |

C06/C07 的基础组件可在不破坏上述依赖顺序的前提下插入修复；发现新缺口即加入
队列，不通过降低设计、缩减分母或修改测试期待来消除未完成项。

## 每段施工规程

先核对当前源和相关设计/原生接口，完成一个真实可调用路径及必要负面/恢复验证。
按影响范围运行检查；大状态机/跨节点变更运行全量，最终资格使用最终同源提交。
避免无理由重跑已通过检查；修改发生在全量运行中时，明确记录并补齐最终源码影响链路。

更新实现证据、缺口和下一项，提交并推送当前分支；检查远端同源结果；继续队列。
最终包装阶段单独冻结源身份，剔除中间证据/缓存/凭证，使用包内运行时与离线依赖。
干净解压后执行产品入口而非只做 import/编译。只有本轮工程与搬运交付完成条件全部达成才结束持续目标。

现场边界：用户 2026-11-03 明确“你做好搬运包，我搬进行内验收”。
据此，现场真实执行不阻塞本轮工程/包装目标；冻结 Q3..Q9 的真实证据规则保持不变。


## C02 衔接约束

只消费已接受的新 N5 修复 Gate、每个失败 DataRef 的新独立原始证明与已应用影响集。
从当前批准的 N4 数据重新核对旧义务/规划语义，不能仅把 STALE 改回 READY。
在治理记录中保留原规划、不可变拆分快照、完整 Case 分母、原 ETU/WorkItem 身份
及原失败 Attempt；新 N6/接纳收据必须来自真实重编译和当前源/Gate。

数据修复且规划语义不变时，以受治理、可审计的重规划记录关联新输入与原拆分身份；
普通规划的源/分母/快照校验不能因此放宽。Case、工具、角色、数据语义或分母变化
需要相应上游修复，不得接受任意调用者映射。准备阶段创建新 Worker/Session/Attempt，
使用现有 generation 和 parent Attempt 机制，再登记不可变恢复关联。

证明必须包括真实本地业务运行、全部 Case 的独立证据审查、原失败历史保留和中断恢复；
不能只造一个替换 binding。并发已完成成员的复用/排空由 C06 的明确策略处理，
不得通过减少 Case 分母或重复未知业务 I/O 来绕过。
