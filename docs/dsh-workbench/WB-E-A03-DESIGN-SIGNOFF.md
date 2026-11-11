# WB-A03 — E 组运行内核与控制面 W0 DESIGN_SIGNOFF

签署日期：2026-11-09；角色：E（RC7.2 runtime / R1 / Agent Teams / Evidence / NodeGate）；结论：**E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS**。
**仅签署 W0 设计语义和拒绝规则，不签署 W1–W4 实现、真实运行或 F 独立 QA。** 反对任何将下面的纯内存 oracle 标记为 API、R1、SSE、真实回放或缺陷 QA_PASS 的做法。

## 1. 可复核源锚点（不能借用旧 HEAD 作为当前版本）

- 待签 W0 文件基线：`work/dsh-wb-w0@5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`，PR [#84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84) OPEN/DRAFT；签署范围为 `02`、`04`、`05`、`06`、`07`、`WB-A03-CROSS-GROUP-SIGNOFF`、`08/09/10`，以及 `docs/rc7.2/01–05`、`10-DESIGN-IMPLEMENTATION-CLOSURE-CONTRACT`、`NATIVE-N10-CONTROL-CONTRACT`。
- F 独立缺口：PR [#85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85)，包括 FG04/05/06/10/13/16，F 仍为 REVIEWED_WITH_BLOCKERS。E 组不代签 F。
- E 审核的实际文件 blob SHA：`rc7_admin/server.py@4cd89462a43fa55fab7c19880d53006f555f7887`、`product_server.py@8e8fc4c90ced920b49026ffe37c5981f75eee990`、`projection.py@db456fc1eb653bb7cf2642a54e028ecbd23f9d5c`；`rc6_runtime/truth.py@4c7ba52bbc4c61f53b379934215d0fdc6b6162a4`、`rc7_runtime/truth_overlay.py@a039db505b64fcb37d420023cc7e9f20fc35ac35`、`rc7_runtime/rc72_domain.py@6e7b0d1e00aeaf6ccc65a645e199344948974d2a`、`rc7_runtime/rc72_linkage.py@27c1ef1f19ff6ec3312397791dd310b0e7c9f12b`、`rc7_runtime/models.py@fef66a5f2696f02c49801aa8490c26e39e8cdbf2`、`rc7_admin/derived.py@eecd5b070e6f3f63e8703c9003f277d1316a66cd`。
- 上述 blob SHA 为该次源码审计身份，不代表实际生产环境/行内部署版本。**E 施工分支的最终 HEAD、PR 及同 HEAD CI 必须以提交完成后的 GitHub API 查询为准**，不能预填。

## 2. 旧 rc7_admin 的真实端点与缺口

| 类别 | 真实路径/源码 | E 结论 |
|---|---|---|
| GET 基础 | `/api/health`、`/api/meta`，server.py:36–59 | 存在，但不能作为宿主 SSO/项目权限证明 |
| GET Mission | `/api/missions/{id}/overview`、`/api/missions/{id}/detail` | 存在，R1 投影，不是跨日期的 B06 关联图 |
| GET 资源 | `/api/{missions,tasks,gaps,evidence,defects,evaluations,artifacts,requirements,code-impacts,test-cases,executions,reports}` 及单 ID；`/api/test-obligations`、`/api/scripts`、`/api/defects/{id}/detail` | 存在，旧版 `_contains` 模糊检索和 page/page_size；没有项目+批次真实复合 join/ACL |
| GET 产品扩展 | `/api/requirement-hierarchy`，product_server.py:22–37 | 存在，不等于批次→需求→系统版本→SST |
| POST | `/api/test-cases`，`/api/test-cases/{id}/revisions`，`/api/test-cases/{id}/quarantine` | 存在且会写 R1；**不能成为 UI 任意写 R1 的控制命令代理** |
| 新工作台 GET | `/api/workbench/v1/projects/*`、`/missions/*/graph`、`/workitems`、`/attempts/*/evidence`、`/capabilities` | **未发现实现**；待 B06/E01–E06 |
| 新工作台 POST | `/api/workbench/v1/missions/{id}/commands` | **未发现实现**；待 E03 正式控制面 |
| SSE | `/api/workbench/v1/events` | **未发现实现**；待持久批次水位、回放、鉴权与断线补放 |
| 鉴权 | 现有 `server.py` 和 `product_server.py` 的 `do_GET/do_POST` | 没有可复用的可信宿主 principal/项目角色 ACL。旧端口 127.0.0.1 默认绑定不是安全隔离依据 |

`TruthRuntime` 通过 `append_atomic` 写原子事件、从 JSONL 重建投影。**现有 R1 事件序号不直接等于按 project+batch 授权的 SSE 流 revision**，也无跨进程幂等命令日志。旧后管读 API 只能用作来源追溯，不能带着旧权限模型直接开放为正式工作台控制接口。

## 3. E 正式签署的目标设计协议（仅字段/失败语义/可实现性）

| 合同面 | E 设计签署 | 必须延迟到实现期核验 |
|---|---|---|
| 身份/Scope | Host/D 服务端提供不可由 body 覆盖的 principal；先鉴权 project，然后用真实 mission→batch→project 关系确定拥有者。未授权优先 403、不泄露对象存在；有权但 ID 不存在 404；非法关联 422 | D01/D03 获取可信主体；B06 复合真实 join + 关联修订；E01 的 HTTP 403/404/422 实测 |
| R1 只读 | E 只读映射稳定 `project_id,batch_id,release_date,mission_id,requirement_id,system_version_id,sst_id,etu_id,workitem_id,attempt_id,evidence_id`。返回 `truth_revision,as_of,source_refs,relation_revision,access_scope_revision,warnings,gap_indicators`；R1 不可用 503/UI UNKNOWN | B06 正式批次身份、RC7.2 历史兼容关联；E01 同 R1 快照/证据与分页复算，不写影子 truth |
| N1–N10/NodeGate | 沿用 `MissionNodeState`（NOT_STARTED/READY/RUNNING/REVIEW_PENDING/PASS/NEEDS_REVISION/BLOCKED/HUMAN_GATE/STALE）与 `NodeGateDecision`（PASS/NEEDS_REVISION/BLOCKED/HUMAN_GATE）；NodeDelivery、独立 reviewer、fresh session、revision/back-edge 持续可追溯 | E02/E06 在真实 R1 验证 NodeGate/Delivery/version/stale/human；质量卡片 WARN 绝不等于 PASS |
| 命令/幂等 | body 仅 `command_id,idempotency_key,expected_state_revision,scope_ref,action,reason`；动作暂限 pause/resume/retry_failed/request_human_gate；拒绝 principal/authorization 字段、publish/任意 NodeGate PASS。持久键 = (principal_id,project_id,mission_id,idempotency_key)；同 payload 重试返回原 command_ref，不同 payload 409。重复请求的身份/Scope 校验优先，幂等查询应在状态版本冲突前防止误重试 | E03 服务端持久原子事务、签名/合法状态机、Worker 和资源租约、Human Gate、冲突无副作用、冷重启正确返回 |
| SSE 批次隔离 | 事件强制 `event_id,project_id,batch_id,type,revision,truth_revision,source_ref,timestamp`（带时区）及可选 mission_id；订阅/cursor 绑定 (principal,project,batch,access_scope_revision)，批次有序 stream revision 和 R1 truth revision 独立。快照原子水位 → 无缝补放 → 实时订阅；gap、同 ID 变内容、权限/批次变更 fail closed | E04 可恢复持久事件存储、订阅服务、断链期间数据不丢、反向串批拒绝、断线及权限降级验证；内存测试不能替代 |
| ETU/WorkItem/Attempt | `WorkItemAttemptBinding` 以 task/attempt 正式 ID 连接 ETU，处于 RUNNING/EVIDENCE_READY/COMPLETED 必须有 worker/session/task_lease_ref；UNRESOLVED lineage 不可猜 node；重试新 Attempt 不覆盖历史失败，不确定副作用 HOLD | E04/E05 真实 signed lease 和执行 I/O 证据，Agent Teams 配置 32/宿主并行/模型配额分层验证 |
| Evidence/缺陷/人审 | `Evidence.content_hash` 目前可选，**非空 hash 也不代表已验证**；回读 content_ref 内容后重新计算 `sha256:` hash，来源/Attempt/ETU/缺陷必须通过结构化 trace refs。缺失、失效、伪造、不可获取→UNKNOWN/HOLD。NodeGate PASS+N10 CONVERGED+独立 Evidence 验证+明确的人审批准，也只具有“可发起受控发布请求”资格 | E06/B07 真实 hash/checksum、可靠 Evidence 与 Defect/Regression 链，旧 Attempt 保留，人工签署防篡改；禁止伪 PASS/伪缺陷/回归 |
| 浏览器互斥 | BSK 与可选 ZSeven Replay 必须同一个资源管理器的排他 BrowserLease；UNKNOWN side-effect 保持 HOLD，不能直接重试或双 owner 竞争。ZSeven MIT 仍保留 LICENSE；Node>=24.11、驱动/离线依赖另验 | E05 通过后考虑 E07，可选项不阻塞 W4 正式必需链路 |

### E 组未解决的“实现约束”，不作为 W0 设计签署依赖

- **E-HOLD-01/B06**：ReleaseBatch 旧类是 `release_batch_id,mission_id,name,planned_release_time,version_ids,requirement_ids`，未内建项目+业务日期+系统版本+SST 复合关系；不可默认业务时区。B 负责真实关系与迁移来源，E01 不得绕过 B06 采用 fuzzy 搜索凑 Scope。
- **E-HOLD-02/D 身份**：旧 HTTP 无可靠会话主体；不能以客户端传来的主体验证权限，不能复用旧后管 HTTP handler 承诺安全。未完成可信 SSO/host adapter，所有新命令 fail closed。
- **E-HOLD-03/R1 控制**：旧 `dispatch_post` 只写 test-cases，R1 append 不是命令权限/幂等控制器；E03 需新增正式控制面而非原 UI 直接调用 `append_atomic`。
- **E-HOLD-04/Evidence**：`validate_rc7_evidence` 只要求 kind/source_ref/content_ref 和 subject_refs，没有强制 hash、原始字节校验与 attempt provenance；`AdminDerivedViews._verified_json` 已有严格 `file://` + `sha256:` 校验可参考，但只针对特定 JSON artifact，不等于全 Evidence 可信。
- **E-HOLD-05/事件**：R1 append-only seq 是存储级序号，缺跨实例持久 SSE per-batch offset/重放协议；需要快照水位与 ACL 隔离实测。
- **E-HOLD-06/人审**：现有 NodeGate 的 reviewer_worker_id/reviewer_session_id 不是正式银行发布人审批事件；必须独立关联 Human Gate 的批准主体、时间、修订、签署与投产权限。

## 4. W0 可执行契约反例与明确分层

- 原创参考 oracle：`tools/dsh_workbench/e_contract_oracle.py`，只在内存中模拟授权拒绝、命令幂等、SSE 批次水位、Evidence hash 与门禁投影；没有服务端 API、数据库、SSE 流、R1 持久写入、真实 Worker/browser 执行。
- 测试：`tests/test_dsh_workbench_e_contract.py`。
- 命令：`python -m unittest discover -s tests -p 'test_dsh_workbench_e_contract.py' -v`。
- 正向：合法 project+mission+batch、相同负载幂等重放、连续事件补放、真实字节哈希匹配、完整 Gate+N10+人审+证据前提只显示 ELIGIBLE_TO_REQUEST_ONLY、具有 lease/trace 的只读关联演示。
- 反例：跨项目在资源存在性查询前 403、跨批次 422、伪 principal/authorization、publish/NodeGate override、修订/同键不同内容冲突、SSE 跨批次/过期权限/水位缺口/同 ID 变内容/无时区、hash 空值/篡改、NodeGate BLOCKED/NEEDS_REVISION/HUMAN_GATE/STALE/UNKNOWN、缺陷缺 trace 或未验证证据。测试夹具没有真执行证明，不标 QA_PASS。
- 对 F 提交的验收请求：复核本签署对旧端点与 R1 真相的锚点，检查测试在同 E HEAD 实际运行，保留 FG04/05/10/13 待 W1+ 真证据，并复验 FG16 W4 门禁传递依赖。W0 仍由 A/F 判断是否 DESIGN_FROZEN。

## 5. E 组工单决策

| WorkItem | 当前 E 决策 |
|---|---|
| WB-A03/E | **DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS**（以 PR #84 与本 E 分支源码/测试为凭） |
| WB-E01 | **BLOCKED_DEPENDENCY_B06**；只允许只读映射和契约夹具，不允许 `IMPLEMENTATION_QA_PASS` |
| WB-E02–E06 | **NOT_STARTED / 依赖未满足**，不得假造控制命令或 execution PASS |
| WB-E07 | **OPTIONAL_NOT_ADMITTED**；E05、BSK/Replay BrowserLease、MIT 通知、Node>=24.11 与离线驱动门禁未通过 |
| F 独立验收 | **PENDING**；不代签 F，不宣布 W0 冻结 |

E 设计签署不覆盖 B/D 的独立 DESIGN_SIGNOFF、F 的独立复验，也不能解除 A02 的 PolyForm Noncommercial 商业许可阻断。未获适用商业授权时不复制 naodeng 原受限源码进入银行交付。

## 6. F 组独立审查后 E 组第二轮实际施工（2026-11-09）

**F 原始意见**：`docs/dsh-workbench/qa/WB-F00-ABCDE-INDEPENDENT-REVIEW-20261109.md`（F PR #85）：E 设计源 `bee612b2dd94a6040404db4b9a4a5fd816e136dd` 的 19/19 合同 CI 已核实，状态仅 DESIGN_SIGNOFF_SUBMITTED_WITH_HOLDS；FG17 A 全量 CDP 失败、FG18 B 来源 SST 身份负例红、FG19 E 与 B 的共享合同/08–10 冲突，W0 NOT_FROZEN，E01 BLOCKED_B06。

**新增只读协议适配原型**：`tools/dsh_workbench/e_readonly_scope_prototype.py`，源码/测试提交 `7cfa92b`、`0fa08a5`、`2eb94ee`、`c69b7cb`。无新增 /api/workbench/v1 route、服务端 ACL、持久 R1 命令、SSE 或浏览器执行。原型只在外部可信 B06 scope 已授权后读取既有 `AdminProjection.mission_overview`；不调用 `dispatch_post`、`append_atomic`。若 Mission 缺显式 `project_id`/`batch_id`，拒绝用旧 `release_id` 猜批次；缺已验证需求-版本/SST source link 拒绝；同原始 SST ID 跨系统版本保持不同复合身份；UNSPLIT 不能补假 SST。没有真实内容字节验证的 Evidence 一律 UNVERIFIED，任何 Attempt/NodeGate/发布一律 UNKNOWN/HOLD。

**正反向测试与真正源码路径**：`tests/test_dsh_workbench_e_readonly_scope.py` 与 `test_dsh_workbench_e_contract.py`。增加真实 `rc7_admin.AdminApplication` 和实际 `TruthRuntime` 的临时文件测试：向**隔离临时测试 R1**创建 synthetic Mission，用旧 mission read projection 验证缺 batch/project 显式关系时拒绝并且 **R1 event-stream bytes 不变化**；真 `dispatch_get`/`dispatch_post` 对拟议 workbench route 返回 UNKNOWN_RESOURCE/UNKNOWN_COMMAND。测试里的 synthetic Mission 是合同 fixture，绝不作为真实银行 Evidence/Attempt/PASS。两类 E 单测统一 CI `dsh-wb-e-contract.yml`，命令 `python -m unittest discover -s tests -p 'test_dsh_workbench_e_*.py' -v`。

**已核查历史同源 CI**：E 施工历史 HEAD `1fe27e70a64b54a5c011e3627b52301438e72e90` 的 [job #129230844848](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42637900557/job/129230844848) 实际 `Ran 38 tests ... OK`（19 A03 + 19 pre-B06 夹具）。后追加 2 个真实旧 Admin/R1 拒绝测试，必须以**最终 E HEAD** 新 CI 重验，不能继承历史绿灯。

**FG19 消除 E 侧并发文件冲突**：E 已创建 `WB-E-A03-LEDGER-MERGE-HANDOFF.md` 完整保存原 E 行/08–10 增量，并将本 E 分支内的四份共享 `WB-A03-CROSS-GROUP-SIGNOFF.md`、`08`、`09`、`10` 恢复 A W0 原始 blob SHA；E PR #91 的变更保持自身原创新文件。A 在合并 B/C/D/E 后必须按交接原文更新统一 08–10/签署表、提交同 HEAD 的综合 CI；F 重新运行 ABCDE premerge 才能正式核销 FG19。不能删账本信息，也不能覆盖 B 的 `source_verified_requirement_version`/`source_verified_link` 或 D 可信主体协议。

**当前 E 任务门槛**：WB-A03/E = DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS；WB-E01 = PRE_B06_READONLY_PROTOTYPE_ONLY / IMPLEMENTATION_QA_BLOCKED_B06；E02–E06 NOT_STARTED；E07 OPTIONAL_NOT_ADMITTED；F 独立 PRODUCT_QA 未通过，A02 BLOCKED_LICENSE，W0 NOT_FROZEN，不打包。

## 7. A 组已完成第一轮 ABCDE W0 单源候选集成后的 E 增量边界

重新核对 A `work/dsh-wb-w0@1956b549206002a5566f076ca41d76b1dc9208fa`：第一轮 E 签署/Oracle、B/C/D 合同和 `08/09/10` 已进入 A 的候选树；本 E 分支只保留**第二轮**只读映射预适配代码、测试、CI 更新和本文件增量，不再倒退/覆盖 A 的综合账本。A 对 F 的 FG18 来源键、FG19 单源集成及 FG17 CDP 的修正仍须独立 F 对**新同 HEAD**重新审核，不能借本 E 的预适配宣称 W0 FROZEN。

第二轮的可复核历史独立证据：E `8401ab85cefb2876ce4451252d3d9a6e7d14704c` 的 [GitHub job #129231742936](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42638157232/job/129231742936) 实际 `Ran 40 tests ... OK`，含真实旧 RC7 Admin/R1 synthetic fixture 2 例；这只是 W0 E 局部合同 CI。重建在 A 新 HEAD 上的 E 分支**必须重新取同源 CI**，旧成功只作历史来源证据。正式 E01 的真实 B06/HTTP/Host/R1 映射依然受 W0 设计和 B06 实施门禁阻断。

E 第二轮成果应由 A 在集成时把 `PRE_B06_READONLY_PROTOTYPE_ONLY`、合同用例数量、新 source_sha、F 独立审查情况累积更新到共享 `08/09/10`；本 E 组不重写 A 的已集成总账，防 FG19 再次发生。

## 8. 2026-11-10 E01 consumer protocol alignment after F independent review

F's completed independent recheck of A W0 source `75fd2c64159db863cfd1319d41a887785b556d40` is recorded in PR #94 and A PR #84 comments. Its outcome is `REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN`: FG17 was observed flaky (one real Chromium failure followed by passing repetitions; root cause unresolved), FG21 reported PR #84 dirty against `work/rc7.2`, and A02 remains `BLOCKED_LICENSE`. This is a completed review with blockers, not W0 acceptance or product QA.

A subsequently advanced W0 to `7067d19742c1954bc5b940f11fe00aa6db24065a` with an exact SPA text wait and a Python 3.8 FG17 five-trial gate. That is an A follow-up source change; **F has not yet independently re-reviewed this new HEAD**. E does not inherit F acceptance from 75fd to 7067.

**B06 source inspection at the reviewed 75fd HEAD:** `rc7_admin/server.py` blob `4cd89462a43fa55fab7c19880d53006f555f7887`, `rc7_admin/product_server.py` `8e8fc4c90ced920b49026ffe37c5981f75eee990`, `rc7_admin/projection.py` `db456fc1eb653bb7cf2642a54e028ecbd23f9d5c`, and `rc7_runtime/rc72_linkage.py` `27c1ef1f19ff6ec3312397791dd310b0e7c9f12b`. The reviewed tree contained no PostgreSQL B06 migration/service or `/api/workbench/v1` route. B06 remains a design contract, not an available E01 implementation dependency.

**E consumer-side correction:** B06 is a project+batch/filters/pagination scope service, not a Mission allow-list. E invokes a B06 port bound by DSH Host middleware to the authenticated request context, with project and batch only; the E adapter does not accept a raw principal argument. Mission membership is checked separately against explicit R1 Mission `project_id`+`batch_id`; missing legacy fields remain HOLD and `release_id` is never interpreted as batch_id. B06 source refs must cover each verified relation link. Empty relation sets are rejected; partial/missing pagination metadata cannot be represented as a complete Scope.

New E-owned protocol note: `WB-E01-B06-CONSUMER-PROTOCOL.md`. E readonly-scope tests now contain 27 cases; with 19 E A03 design-oracle tests the exact E workflow ran 46 tests on HEAD `86d2516f02aa523021ac76c5c258c0e51f8c44cb` (two independent same-HEAD jobs #129311426006 and #129311468840). These remain pre-B06 protocol/fixture tests, not `IMPLEMENTATION_QA_PASS`.

**B review requested:** confirm the unique `source_refs` list and exact `next_page_cursor` payload shape before freezing B06. This PR does not change B's signed SQL schema or shared 08/09/10 ledgers.

**Status remains:** E A03 design accepted with implementation holds; E01 `BLOCKED_DEPENDENCY_B06`; E02–E06 `NOT_STARTED`; E07 `OPTIONAL_NOT_ADMITTED`; no HTTP/API/DB/SSE/command/NodeGate/Agent Teams production integration; no ZIP.

## 9. B06 consumer protocol signed by B; multipage E readonly pre-adapter (2026-11-10)

B [PR #95](https://github.com/TongAITech/opencode-test-digital-employee/pull/95) expressly confirmed on E [PR #96](https://github.com/TongAITech/opencode-test-digital-employee/pull/96) the exact consumer shape: each B06 page has a distinct/unique source_refs list covering verified BRV + SPLIT BRVS links; request = page_size/page_cursor; mandatory top-level next_page_cursor (null final), no second pagination envelope; B06 authenticates project+batch from Host-bound request context, does not own Mission membership or R1 truth_revision. E must check explicit R1 project_id/batch_id after B06 and must consume **all pages before declaring Scope complete**.

E added `tools/dsh_workbench/e_b06_page_consumer.py` with bounded, revision-stable B06 page gathering and read-only R1 admission only after all pages pass. Cross-page duplicate relation, UNSPLIT/SPLIT contradiction, date/relation/access version drift, cursor cycle, missing next cursor, too many rows and max-page exhaustion reject before R1 lookup. Full Scope `source_refs` merge preserves B06 provenance, and R1 source_ref is appended without being mistaken for a B06 verified link. No assumption of executed Attempt or valid Evidence is added.

Tests `tests/test_dsh_workbench_e_pages.py` are synthetic B06 page port and isolated R1 read projection fixtures, **not** real B06 PostgreSQL, real Host signed request context, R1 event stream qualification, or W1 IMPLEMENTATION_QA. Existing E01 `BLOCKED_DEPENDENCY_B06`; E02-E06 `NOT_STARTED`; E07 `OPTIONAL_NOT_ADMITTED`.

Latest F independent audit [PR #101](https://github.com/TongAITech/opencode-test-digital-employee/pull/101) against A W0 `b385e042c4543f5d918d61bff5e01be1d88afba7` remained `REVIEWED_WITH_BLOCKERS/W0_NOT_FROZEN` after FG22 CI negative policy failure. A subsequently committed `5bba94c213e2d54a83f8aa360b0f3d71ea8d26a1` to fix FG22; **that new HEAD requires F independent recheck**. FG17 targeted real Chromium and FG21 Git merge conflict received narrower positive review, not field QA. A02 `BLOCKED_LICENSE` remains.

This E own-design/signoff addition intentionally does not edit A-owned `08/09/10` shared ledgers. A must integrate and record its own source-sha and F signoff separately.

## 10. F #106 latest W0 review and E source-revision cross-page hardening

F PR [#106](https://github.com/TongAITech/opencode-test-digital-employee/pull/106) independently tested the precise A W0 integrated source `a3555b187eb35d27a2d712313dd8ea7daa28915f`: 206/206 W0 Python, 30/30 C Node, FG18 1/1, FG16 2/2, CI admission 21/21, and real Chromium prototype PASS. F accepted `C_W0_PROTOTYPE_REVIEW_PASS`, `FG23_CLOSED`, and `FG20_DESIGN_RECONCILIATION_PASS`. **F did not sign W0 global freeze, E01 product QA, commercial license or bank field deployment.**

After E #102 was integrated into that source, E added a new cross-page source revision fence to `e_b06_page_consumer.py`: the same requirement-version BRV parent must preserve its verified `source_link_ref + source_revision` across multiple SST rows/pages; conflicting provenance rejects before R1. The source key is scoped by requirement **and** system_version, so legitimate SST raw-ID reuse across different versions is not blocked. New E negative and positive tests prove rejection and no R1 read. Real B06 PostgreSQL/DSH Host verification remains a dependency; this is E pre-B06 protocol hardening only.

E owns this isolated change; A owns 08/09/10 integrated ledger updates. W0 `NOT_FROZEN`; A02 `BLOCKED_LICENSE`; E01 `BLOCKED_DEPENDENCY_B06`; E02–E06 `NOT_STARTED`; E07 `OPTIONAL_NOT_ADMITTED`; no ZIP/mainline deployment.

## 11. F #111 P1 remediation — R1 scope-first read before related details

F PR #111 independently reviewed E #107 at exact HEAD `917f597d11daa1ae0bfc0caa07066bd45ad64ffa`. It accepted `E107_SOURCE_DRIFT_GUARD_PASS` but issued `E01_SECURITY_ADMISSION_BLOCKED`: the E adapter called old `mission_overview(mission_id)`, which loaded Tasks/Executions/Evidence before the caller compared Mission project/batch membership.

E remediation is implemented on the follow-up source:
- New required port `mission_overview_scoped(project_id, batch_id, mission_id)`; no unscoped fallback.
- `AdminProjection` performs a minimal Mission identity lookup first, verifies exact explicit project+batch binding, then and only then queries Tasks/Executions/Evidence. Missing or mismatched bindings return the same `R1_MISSION_SCOPE_UNRESOLVED` result. It returns only the required identity tuple.
- Both E adapters share `read_scoped_r1_mission_overview`. Tests cover cross-project, cross-batch, missing binding, old unsafe-only projection, and actual inherited RC7 AdminProjection; all rejection cases assert zero related-detail queries.
- Legacy Mission model currently lacks project/batch bindings, so actual old Missions correctly fail closed. No release_id inference is added.

This closes the identified **pre-read ordering defect in the prototype contract**, pending F review of the new exact source. It does not implement Host principal ACL, production B06/PostgreSQL, a canonical Mission migration, or E01 production QA. E01 remains blocked until those dependencies and same-HEAD field/API tests exist.
