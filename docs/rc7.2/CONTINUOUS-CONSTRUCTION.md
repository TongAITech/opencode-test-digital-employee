# RC7.2 持续施工与最终搬运交付

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
| C08 | 统一产品入口/推进器/状态查询接上全部原生节点服务 | 真实产品命令/接口从 ReleaseBatch 驱动 N1..N10；重启从 R1 接续；无测试专用快捷开关 | ACTIVE：N1→N2→N3→N4→N5 与发现工作项正式验收已接通；N6..N10 和生产运行入口待落地 |
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
