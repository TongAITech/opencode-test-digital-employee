# RC7.2 第四轮施工台账 — R4-07 32 人 Agent Teams（2026-11-09）

基线：`work/rc7.2` @ `3de74c2bf3a0f3a555ccd979edd2832f26c9963a`。
施工分支：`work/rc7.2-r4-capacity32`。关联 Issue #82。
本台账是第四轮首批施工，**不代表第四轮其他任务已实现**。

## 任务矩阵
| 任务 | 范围 | 当前状态 |
| --- | --- | --- |
| R4-01 | C07 正式 Mission Host/真实 Agent Teams Captain | 未核销，依赖行内真实 Host |
| R4-02 | N8 产品自主修复回边 | 待最新 HEAD 复核 / 现场验收 |
| R4-03 | N9 独立因果、复现、修复回归 | 待专业链现场验收 |
| R4-04 | N10 覆盖率新执行/新测量收敛 | 待产品全链路核销 |
| R4-05 | SCRIPT_READY gate / 429 / 502 / 冷启动与接管 | 待产品及行内验收 |
| R4-06 | C12 已批准 DSH 主程序、一次 ZIP、独立解压 | C12_PHYSICAL_HOLD |
| **R4-07** | **32 个逻辑成员、独立受控活跃执行数** | **本分支首批源码施工** |

## R4-07 首批真实工程变更
- 仓库正式离线包必需插件为 `@nanmicoder/dsh-agent-teams`，其 `maxMembers` 现有默认值为 8。提出**32** 配置预览，但不擅自覆盖行内受保护的 DSH profile。
- `TeamCapacityPolicy(team_member_capacity=32,max_active_workers=4)` 将成员数与真实任务派发容量拆开。
- 真实 Captain-fenced R1 调度的 `dispatch_etu` 在同一账本锁内读取所有活跃 `rc72_worker_session`，容量耗尽时拒绝新分配且不写新 Worker/Attempt；崩溃遗留未核销的 ACTIVE Session 仍占用容量，不允许无依据地释放。
- 兼容 `dsh-team` 的 `maxTeammates` 但绝不混写到 Nanmi；官方 `@deepseek-ai/dsh-agent-team` 拒绝无效的 `maxMembers`，容量由其下层 subagent runtime 管理。
- 配置形状检查和单一真实插件版本检查不等于插件现场成员已经存在；不得把源码单测解释为行内 32 成员创建成功。

## 后续实际施工与验收
1. 增加现场 DSH 配置/版本可信观测及隔离 profile 中的 8→9 拒绝、32 成员创建、33 人拒绝实验；
2. 调度回收与队列状态、真实成员身份关联、模型 429/502 限额与资源保护、跨进程队列公平性；
3. 保留冻结 05 的 R1 签名、独立审查、Session/Lease/Browser/Data 权限与冷恢复约束；
4. 执行 Windows Python 3.8/3.11、Linux 同源 CI；Field 使用真实 DSH、Agent Teams、模型与 R1 记录；构建大型 ZIP 只在代码批次完成且 C12 来源获批后执行。

不允许自动从配置文本伪造 Team 成员，不允许仅凭 DSH 配置读取宣布 32 个实际 Session 已建立。

当前：`R4_SOURCE_PARTIAL` / `R4_07_FIELD_PENDING` / `C12_PHYSICAL_HOLD` / `BANK_FINAL=NO`。

## R4-07 第二施工批次 — 2026-11-09，32 人真正进入隔离运行配置
- DSH 的 `cordis.patch.yml` 覆盖是整个插件配置替换，而非键级合并。禁止在通用 `--patch` 中仅声明 `maxMembers: 32` 覆盖整个插件配置。
- 增加 `rc7_release.rc72_team_profile_capacity`：只有 DSH 原生安全 clone 建立且严格验证来源 marker/base digest、插件真实 manifest、单条显式 `agent-teams` YAML 行后，才在**隔离 clone**中保留其他字段、只新增/替换 `maxMembers: 32`。
- 启动路径：`packaging/rc7.2/AITEST.sh` 设置 R4-07 开关；继承 `packaging/rc7/AITEST.sh` 在 clone 后、生成 DSH patch 前应用改造；不在安装前调 `npm`，不修改银行受保护的 `web` profile。
- 支持无 `config` / 已有 `config` / 已有数字键 / 幂等重启，拒绝缺失/重复插件行、非数值/脚本成员数、未核准插件来源、来源漂移、符号链接。
- 返回 `SOURCE_CONFIG_APPLIED_NOT_RUNTIME_VERIFIED`，**不宣称 DSH 运行进程确实加载了该字段**。真实 DSH `--dump-config`、32 真实成员创建、33 人阻断、DSH 会话/团队身份绑定以及行内 429/502、真实 R1 在下一 Field Gate 中独立验收。
- 本批次不修改固定冻结的 R1 Captain/TaskLease/Browser/Data/认证权限语义；不触发 GB ZIP。

## R4-07 第三施工批次：Ready WorkItem 的有界队列派发
- CaptainFencedWorkItemScheduler 新增 `dispatch_ready_batch`，只接受冻结 N7 WorkItem/ETU/role/canonical_refs 显式清单；沿 canonical `TaskScheduler.ready_tasks` 排序逐个调用原有 `dispatch_etu`，没有任何弱化的临时 Worker 快捷通道。
- 同一 R1 ledger 锁保护每个真实 TaskLease，活跃容量满时返回仍为 READY 的排队 WorkItem，下一次 Mission tick 可重新挑选；不释放未知副作用 Worker、不伪造模型工具调用；非容量错误绝不转换为排队成功。
- 新增顺序、容量 1/2、重复提交、畸形数据、剩余 READY 与 R1 不变的反例测试；实际 DSH 模型自动唤醒/32 实体 Session 仍需行内证明。

## R4-07 安全审计补充
插件 ID 不能单独证明插件身份。32 成员容量应用前严格核验 YAML 同行组内的 `name: '@nanmicoder/dsh-agent-teams'` 与 clone package.json；同 ID 冒名插件拒绝，保留原配置与银行受保护 profile。

## R4-07 关键阻断修复：正式 N7 全分母在并发=1 时不可死锁
- 原 `dispatch_etu` 将所有 ACTIVE WorkerSession 算作并发；正式 `N7Pipeline.complete` 要等所有 Case 执行、清理且独立审查后才关 Session。大于 4 Case 时会在第 5 个排队且永远无法执行最终 review，这是源码审计发现的 R4_P0_GATE。
- 新增正式 `ExecutionEvidenceReviewService` 类型化只读受控绑定：必须拥有同 R1/release 的 N7 Review，由它对每个 N7 WorkItem 复核实际 ToolDispatch RETURNED、签名 CLEANUP 与 VERIFY 回执、冻结 Oracle、R1 Evidence 和所有资源实际 RELEASED 后，才把仍 ACTIVE 的历史执行 Session 视为**占用 roster、但不再占用执行并发槽**。不关闭 Session、不回收未知副作用、不生成 PASS。
- 所有未开始、失败、UNKNOWN、证据缺失、不完整清理、审查签名不合格的 Session 继续占用执行容量。原始完整 N7 最终 review/NodeGate/Case 分母不变。
- 新增正式本地 HTTP N7 端到端独立回归：多 Case + 并发 1，所有真实业务调用一次、资源清理、独立 Gate PASS、冷/热重复运行不会重复调用。**CI 与银行 Field 未过前不得核销。**

## R4-07 启动可用性拒绝退化
- 严守 RC7 原有“克隆配置后 DSH 本体必须能启动，不得让可选插件恢复/安装阻断 UI”合同。32 人配置检查返回 HOLD 时保留 `state/rc72-team-capacity.json`，以醒目非 PASS 提示继续 DSH UI 启动；不静默称其已扩容，不做前置 npm/plugin 安装。
- 正式 Mission 仍以独立真实 DSH AgentTeams proof 与 R1 Captain 绑定为前提；`HOLD` 是现场未获资格而非 32 人已达标。代码和脚本专项验收单列。

## R4 最新同源 CI 失败与修复（2026-11-09）
- SHA `70115c8a0c68` 共 46 项 Check，30 失败/14 成功/2 skipped，5 类独立 CI 日志抽查指向共同回归 `CAPTAIN_SCHEDULER_N7_REVIEW_REBIND_FORBIDDEN`（N7 pipeline 重建时非必要拒绝新 reviewer 对象，连带 C07/C09/C04/ABCD 等）。
- 修复：`CaptainFencedWorkItemScheduler.bind_n7_cleanup_review` 只允许同一 R1、同一原生签名 authority、同一 source commit、同一工具白名单的第二个 N7 Pipeline 进行只读重入；始终保留最初绑定的审核服务，不允许真正替换审核权威。新 Pipeline 的 Captain/TaskLease 权限依旧由 `_prepare_governed_item` 验证，过期/外来 Captain 不被放行。
- 回归：新增同源重复构造无 R1 写入、不同签名 authority/变更 source 严拒、原有外来 Captain 禁止执行测试。**本修复须新的同 SHA CI 验证成功才能算工程修复完成。**

## R4-07 修复：ReleaseBatch WorkItem 数量与 32 名成员池彻底解耦

- 移除 `dispatch_ready_batch` 对入参 WorkItem 数量的 `len > team_member_capacity` 错误拒绝：一个投产批次可以拥有超过 32 个有效 ETU/WorkItem；32 是插件成员数，初始 4 是活跃任务并发数，**都不是批次待执行案例数量**。
- 对 33 个真实入账 R1 READY WorkItem 增加调度回归：只允许 4 个 signed admission / WorkerSession，剩余 29 条保持 READY；重复调用不得二次派工或改变 R1；测试不声称 33 名真实 DSH Agent 已创建。


## R4-07 第四施工切片：只读现场成员名册观测工具（source qualified candidate）

- 正式代码 `rc7_release.rc72_team_roster_observation`；行内通过 `python -m rc7_release.rc72_team_roster_observation --team-state-file <workspace>/.agent-teams/<team-id>/team.json --team-id <team-id> --dsh-url http://127.0.0.1:4096 --output state/rc72-team-roster-observation.json` 收集本地插件现存 Team JSON 的 SHA256、非 removed 名册计数、已创建子会话计数、Captain 真实 loopback `/session/<id>` / `/session/status`。此工具**不调用模型、不新增成员、不改变 R1**。
- 原生 NanmiCoder 插件 `src/state.ts` 以 `<workspace>/<stateDir>/<teamId>/team.json` 存团队；`stateDir` 默认 `.agent-teams`、可自定义，所以必须从真实运行配置传入 team-state-file，不得猜路径。成员 `status=idle/working/removed`；`id=''` 表示仍未创建子会话，不允许当作缺陷。
- 仅 `ROSTER_SNAPSHOT_AND_LIVE_CAPTAIN_OBSERVED`，输出 `field_verified=false/bank_final=false`：磁盘快照+本地 DSH session 不是原生插件 HMAC membership proof，也不是第33人的真实添加拒绝；后续仍要求受控 DSH AgentTeams 第33人拒绝结果、正式 N7 R1 Session/Lease、真实模型和 E 独立现场验证。不可把测试合成的 32 members 误报为现场。
- 四平台 read-only 正反例测试独立 CI，不构建 ZIP。


## R4-05 增量施工：共享模型请求额度文件损坏不得重置为零（2026-11-09）

- 本次源码审计发现真实缺口：`rc7_runtime/model_resilience.py` 的持久化滑动窗口在 JSON 截断、非字典、无效时间戳等情况下静默返回 `timestamps=[]`；不同进程的残余模型请求历史被清空，存在超额请求风险。此缺口与 429/502 背压及跨进程安全恢复有关。
- 独立分支 `work/rc7.2-r4-model-governor-failclosed-20261109`，以 `work/rc7.2@58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d` 为起点。
- 真实修复：只允许首次无状态文件从空窗口启动；已经存在但损坏/非本 schema/含 NaN、负数、布尔或非数值时间戳/符号链接的限流状态必须抛出 `MODEL_RATE_GOVERNOR_STATE_UNVERIFIED`，不得覆盖文件或启动新的模型请求；保留原有正向额度统计、合法恢复和 R1 启动门禁。
- 测试：在 `tests/test_rc7_1_model_resilience.py` 新增损坏状态不覆写/解锁及真实 launcher 在模型 IO 前阻断的负例；已有 429/502、工具副作用未知不得重复派发及额度窗口回归必须继续通过。
- 专项 CI：`.github/workflows/rc7.2-r4-governor-failclosed.yml`，Windows/Linux × Python 3.8/3.11，No ZIP。**同 HEAD CI 运行与审查前状态为 SOURCE_SUBMITTED / CI_PENDING；尚未核销 R4-05 整项。**
- 上述仅修复 R4-05 的一个工程子缺陷；SCRIPT_READY、真实银行 429/502、冷启动跨会话/跨进程补位和全产品 Q8 仍需专属证据；`R4-05_FIELD_PENDING`、`C12_PHYSICAL_HOLD`、`BANK_FINAL=NO`。

## R4-05 批次化施工：SCRIPT_READY 原子签发与 CI 去重（2026-11-09）

- 源码审查发现：原 `NativeScriptReadyGateProducer.issue` 先核验 Captain，再在无 R1 账本锁的区间完成签名与 `append_atomic`。真实 Captain 换届可在两者之间发生，使旧代 Captain 仍写入一份刚签发的历史 SCRIPT_READY。下游 inspect 会拒绝旧代，但 R1 写入本身违反原子资格边界。
- 修复：将最后一次当前 Captain owner/generation 核验、完整 N6/Case/Contract 事实再次核验、签名及唯一 R1 append 保持在同一 OS ledger lock。拒绝变更的冻结事实和过期 Captain；旧签名历史、独立 Reviewer、N7 Case 分母均不放宽；冷重入已有测试保持无重复写入。
- 新增定向拒绝证据：两次 N6 读取不一致时不产生 SCRIPT_READY/Attempt/R1 变更；真实签发的 R1 append 期间，其他 Captain 相关 ledger 操作无法重入；同状态重复 issue 不再次写入。
- 新增无 ZIP 的 Windows/Linux Python3.8/3.11 `r4-script-ready-lock` 定向工作流。保留 ABCD v3/v4 同 SHA **完整**产品回归，不删减任何 Case；仅将两条大工作流的 PR 并发组改为 PR 标识并在新 HEAD 到来时自动取消同 PR 的旧 SHA，避免将已过期回归当作交付资格。正式候选 SHA 仍需完整独立 QA；branch/manual 运行不自动取消。
- 本批次为 **R4_05_SOURCE_SUBMITTED / SAME_HEAD_CI_PENDING**，不是银行 Field 证明，未核销 429/502/cold takeover 所有现场路径；R4-01～04、R4-06/07 继续按其真实 DoD 保持 OPEN，`BANK_FINAL=NO`。


## R4-02 批次集成：N8 冷恢复缺失/篡改原生 Delivery 不得重新写入 R1

- 发现现有 ExecutionDiagnosisService._accept 在独立诊断 Receipt 已持久化、原生 N8 Delivery 缺失的情况下会尝试重建 NodeDelivery，并可能在随后原始 EvidenceRefs 校验失败前先写入 R1 Node/Event。
- 修复：必须在任何 Evidence、Node 状态、NodeGate、分类和修复回边写入前验证原生 Delivery 唯一，且 Mission/Node/Worker/Contract/原始 Evidence 谱系一致；Receipt 不是新 Delivery 的执行授权。
- 新增真实 N7 失败和独立 N8 进程诊断后的两个 cold replay 反例：缺失 Delivery、篡改 evidence_refs，必须拒绝且 R1 文件逐字节不变、原始 Attempt BLOCKED、零 HTTP 再执行。保留既有 N8 正向重入及修复测试。
- 集成此变更与 PR #86、#87、#88 的所有原代码和台账记录，以同一候选 SHA 跑四平台定向/完整继承 CI。无银行真实 Host/AgentTeams/4A/Libra、独立 QA、C12 主程序及离线包证据前不能核销整个第四轮。FIELD_PENDING / C12_PHYSICAL_HOLD / BANK_FINAL=NO。

## R4-05 / Q3–Q6 现场签章准入补强（2026-11-10）

- 发现源码安全问题：原 FieldQualificationService._is_trusted_for_gate 仅验证 provider:// 或 human:// URI 字符串和 ReleaseBatch 关联。任意 R1 写入者可凭借这些可伪造字段提交 Q3–Q6 FIELD PASS，甚至原有测试未使用真实签章。此情况不符合 Field Evidence 真伪门禁。
- 修复为 Gate-specific 银行 Host 信任根（trusted_gate_authorities）。对 R1 Evidence 实施 HMAC-SHA256 精确绑定：Gate、Batch、source_commit、platform_family、platform_release、architecture、python_version、Evidence ID/Kind、source/content reference、content hash、subject_refs 与 artifact_version；少签、错签、跨批/跨平台重放、无可信 Host 时必须 HOLD。Q6 保留独立 human:// 和 CASE_HUMAN_GATE_APPROVAL 类型，并要求银行审批侧受信签章。
- 明确安全边界：源码单测内的 signing key 只是隔离测试夹具，不能替代行内信任根、真实审批、4A 或物理 Evidence 真实性。银行 Host 必须在确认原始 Provider/人审/被签文件后才签发，且密钥不能注入 Agent Prompt/Worker 或随包分发。
- 增加 4 平台（Windows/Linux × Python3.8/3.11）独立专项 CI；不重复构建 ZIP。此轮仅更新 Q3–Q6 的安全准入，不宣称 R4-01～07 Field、C12 或 Bank Final 通过。

当前：FIELD_APPROVAL_SIGNATURE_HARDENING_PR / FIELD_VERIFIED=false / C12_PHYSICAL_HOLD / BANK_FINAL=NO.

## R4-01 / C07 DSH AgentTeams provider 自签名门禁加固（2026-11-10）

- 源码审计发现：configured_agentteams_host_bindings 允许 provider_module 按调用方字符串动态导入，且 CaptainProviderWiring 可以同时返回其自行构造的 membership_authority 和 host_authority。若不要求独立银行 Host 提前锁定信任根，provider 的自签名可能被当作真实 AgentTeams Captain。
- 增加 BankCaptainTrustRoots：调用方必须由银行可信 Host 预先注入受批准 provider_module 名称及彼此独立的 membership/host authority；在导入模块前拒绝 provider 名称不匹配、缺少受信根及共享密钥。provider 返回的 authority 必须是预先注入的同一对象，不能自签自验。LocalDshAgentTeamsHost 继续检查真实 loopback DSH session/status、HMAC、准确 R1 Batch 和 Captain 身份。
- 新增独立负例：缺少受信根或未批准模块不得 import，独立对象共用同一签名 key 必须拒绝，provider 自带的任意双 key 不得创建 Captain，签名缺失即使 trust root 正确仍不写 R1。
- 这只能证明受控 Host 源码的准入条件，不代表银行真实 module 文件身份、私有信任根、DSH 进程及 32/33 人 Field 已实测。provider 的真实来源、供应链校验、银行密钥保管及行内单点签章均依旧属于现场准入。不能将模拟测试密钥直接复制到交付包。
- 目标：Windows/Linux Python3.8/3.11 定向回归，仅一次源码工程批次验收，不构建 ZIP，FIELD_VERIFIED=false / BANK_FINAL=NO。

### C07 CLI 接线约束与继承回归
- `rc7_release.rc72_mission_cli.main` 新增仅供受信银行 Host 进程使用的 keyword-only `bank_trust_roots` 注入入口。普通 CLI 参数、配置 JSON 或模型 Prompt 均无法提供或制造签章密钥；未批准银行控制端嵌入时，`--captain-observer-module` 显式 fail-closed，而不是退回 legacy 无 Captain 执行。
- 原 `tests/test_rc72_configured_mission.py` 的真实 loopback DSH Captain 正向测试升级为显式 BankCaptainTrustRoots 注入，不删除原真实会话/R1 Gate 断言；四平台 C07 工作流增加旧 Mission CLI 与 Host 继承合同测试。
- 此接线能力仍不是银行 Host 授权的实际取得：行内应由受控进程 provision/sign，绝不能把 test-key 加入安装包。`R4_01_SOURCE_VERIFIED_PENDING_CI / FIELD_HOLD / BANK_FINAL=NO`。

### PR #99 完整 Chromium 继承回归失败分析与修复
- 两个完整 Chromium 继承 job 均执行 `2938 passed, 4 skipped`，仅有 2 个失败，定位在 `tests/test_rc72_q7_admission.py` 的 Q7 正向准入 fixture：测试仍使用原先无签章 `provider://` / `human://` 字符串模拟 Q3–Q6 PASS，触发新安全门禁后正确 HOLD。该失败不是通过放松生产校验解决。
- 已修正 Q7 admission 测试夹具：每个 Gate 使用隔离的测试 Host authority，先对 Gate/Batch/source SHA/平台/Evidence 全字段签章，再调用 FieldQualificationService；保留 Q7 对 `field_verified=false` / `bank_final=false` 的原有断言。无签章与伪造场景的拒绝测试仍保留。
- 修复 commit `3b167018415f3a9e651e8d3e1538fb025ba38f0a`，触发 PR #99 同 HEAD 新 CI；在同 HEAD 全部回归通过前不合并。测试 key 仅用于测试，不能代表真实银行 Host 授权。

## R4-07 路径安全补强：容量配置工具不能通过路径重定向触碰银行配置（2026-11-10）
- 新增源码审计缺口：`apply_cloned_profile_capacity` 直接调用时只检查 base/target 最末级是否 symlink，未拒绝 `DSH_HOME/profiles` symlink 及 clone 下 `node_modules/@nanmicoder/dsh-agent-teams` 中间目录 symlink；可能把插件身份读取重定向到 clone 外部路径。
- 原 CLI `--output` 直接 `write_text`，若目标指向 `~/.dsh/profiles/web/cordis.patch.yml` 或指向它的 symlink，会把 JSON 报告写入银行受保护配置，违背只改隔离 clone 的合同。
- 修复分支 `work/rc7.2-r4-capacity-path-hardening-20261110`：拒绝 profiles root/base/target/package/config 路径上的任一 symlink；在修改 clone 前解析并拒绝任何 DSH profile 内的报告目标；报告采用同目录临时文件 + flush/fsync + atomic replace，并在替换前重新校验。
- 新增 4 个反例：profiles root symlink、node_modules 祖先 symlink、报告直接指向 web profile、报告 symlink 指向 web profile；必须在任何 profile/config 写入前 HOLD/拒绝。现有克隆配置正向、原配置保留、幂等与 Windows/Linux Python3.8/3.11 四平台合同继续保留。
- 本修复只证明路径/文件写入隔离，不证明 DSH 运行进程已加载 32 成员配置，更不证明 32 名真实 Agent/第 33 名拒绝。`SOURCE_PENDING_CI / FIELD_PENDING / BANK_FINAL=NO`。

## 第四轮 CI 新模式：草稿 PR 专项先行，Ready PR 才执行完整 ABCD（2026-11-10）
- 用户要求减少“每个小修复都跑 40–60 分钟完整 Chromium/继承回归”的浪费。v3/v4 原 workflow 对所有 `pull_request` 无条件启动 4 平台完整工程 + 2 套 Chromium/全继承测试。
- 已调整 v3/v4：Draft PR 只执行对应专项合同工作流（如 R4-07 capacity32、C07 trust、Q3–Q6 signature）；ABCD 工程矩阵与完整 Chromium/RC7+RC7.2 继承套件仅在 PR Ready for Review 时执行。`ready_for_review` 事件已加入，转 Ready 会自动触发；Ready PR 后续每次 synchronize 仍执行完整回归。push 与 workflow_dispatch 行为不变。
- 本 PR #105 保持 Draft，因此新 HEAD 只应执行 R4-07 四平台专项，不重复启动完整产品回归；原已启动的本 PR 旧 SHA 完整作业由 PR 并发策略取消。PR #99 当前非 Draft，已承担本轮一次完整产品回归，不再为同一代码批次额外复制完整回归。
- 此策略不删除任何测试、不缩减测试集合；仅把全量回归放到集成检查点，专项测试仍在每个 Draft PR 上运行。

## R4-05 批次新增：银行模型请求配额的内核锁和冷恢复（2026-11-10）

- 旧共享限流器以 O_EXCL 文件创建/删除充当锁，且错误地在 lockfile mtime 超过 30 秒时无条件 unlink；另一个活跃进程若临时超过 30 秒仍可能持有该窗口，第三个进程却可获得新锁并触发模型额度双重计量。
- 本批将其改为平台原生独占锁：Windows `msvcrt.locking`、Linux `fcntl.flock`；锁文件长期存在，不再以年龄删除。进程崩溃时 OS 自动释放锁，守护者重新获取锁并基于原 `shared-window.json` 继续额度计算，不清空存量；用 monotonic deadline 避免模拟钟/时钟回拨造成无期限等待。异常、非法符号链接和重入保持 fail-closed。
- 增加真实本地文件锁反例：活跃锁的 mtime 被人为设为一小时前，第二实例仍必须超时拒绝；旧版遗留的僵尸 PID 文件在无 OS 锁时可恢复且 **保留全部历史计数**；子进程锁定后调用 `os._exit(0)`，冷重启必须可安全重新加锁。保留损坏窗口模型 IO 前拒绝、429/502 已启动 Worker 不盲重放与旧 R1 Attempt 不重启等测试。
- 非工作日/工作日额度仍以既有银行明确模型窗口合同为准。本次不将源码锁恢复当作真实银行额度/502/会话现场 PASS。

## R4-02 批次新增：N8 先验证既有 Gate/Delivery 代数再写证据（2026-11-10）

- 在既有“诊断 Receipt 不得补造原生 Delivery”基础上进一步发现：如果冷恢复已有 Node Gate 被篡改或 `Node.active_delivery_version` 与原生 Delivery 不一致，`_accept` 先执行 `_ensure(rc7_evidence)`，再修改 Node 或检查 Gate；在中断重入时可能先造成 R1 副作用，之后才拒绝。
- 现先验证原生 Delivery 谱系、已激活 Delivery generation/ref、已有 Gate 的 reviewer 身份/签名所绑定 Evidence 分母，全部通过后才允许 `_ensure`、NodeGate、分类和 N5 回边；新增 forged Gate 与失配 active version 的真实 N7→N8 独立进程冷重入负例，断言零 Evidence IO、原 BLOCKED Attempt、原始 R1 字节不变、业务 HTTP 零重放。
- 保留之前“已有 Process Receipt/原生 Delivery 丢失、Evidence 伪造、R1 Gate 伪造、UNKNOWN 拒绝分类”的全部正反例，禁止通过改写原失败或缩减 Case/ETU/Attempt 分母达成 PASS。

## R4-01～R4-07 一次批次化集成与资格策略（2026-11-10）

- 集中基线 `work/rc7.2@87f956f1388f58beabf7116c937fd6fda5fae2ca`，从 PR #99 导入 Q3–Q6 真签章验收与 Q7 正向签章夹具，从 PR #100 导入 C07 银行预批准 provider + 独立 Host/Captain 根和正式 CLI 接线，从 PR #105 导入 32 人隔离 profile 完整路径及报告保护及 ABCD-v3/v4 的 Draft/Ready CI 门禁。
- 以上所有修复、N8 预校验和模型额度 OS 锁均先真实提交到**同一独立施工分支**，本阶段不会给每个修复构建完整离线 ZIP 或各跑一套全量 Chromium。
- 待代码齐备后一次性创建 Ready 候选 PR：Windows/Linux Python 3.8/3.11 专项合同 + v3/v4 完整继承（含真实 Chromium/CDP/DOM/业务 Oracle）同 HEAD 验证；最终确认无失败并经独立 E 组审查后才能合入主线。该批次以前的源 PR 绿灯不能自动代替此候选 SHA。
- 工程源码边界：`32 logical members` 不等于真实行内 DSH 32 个成员创建和第 33 人真实拒绝；受信 Host 的测试签名不等于银行认可的 Provider、4A 人审和原生 Team/Captain 签名；内核锁与冷恢复单测不等于现场 429/502/Libra/N9/N10 全业务闭环。
- R4-06/C12 仍需获得分发授权的真实 DSH 主程序、独立 SHA256、正式 Windows 搬运包与 clean-unpack/目标 Linux/行内 Q3–Q9 验证。**缺此来源不得编造 dsh.exe、不得构建并宣称最终 ZIP。** `FIELD_VERIFIED=false`，`C12_PHYSICAL_HOLD`，`BANK_FINAL=NO`。

## R4-05 源码审计：模型配额临时文件路径重定向 P0（2026-11-10）

- 在 PR #113 最初集成源 `d35eea4ad69334a24d6166a5f388552258bba503` 复核 `PersistentSlidingWindowGovernor._save`，发现旧代码使用可预测路径 `shared-window.tmp` 并直接 `Path.write_text`。若该路径已是符号链接，数据会先覆盖其所指文件，然后才调用 `os.replace`；隔离临时目录已重现“保护文件内容被覆写、结果状态成为符号链接”的负例。
- 本次最小修复不修改模型额度窗口、R1、Worker 或原字段语义：采用同目录系统随机 `NamedTemporaryFile(delete=False)` 原子创建，写入后 flush/fsync，再替换正式账本；异常清理残留临时文件，正式账本若为符号链接仍拒绝。旧固定临时路径永不再被写入。
- `tests/test_rc7_1_model_resilience.py` 增加两项对抗回归：旧固定 `.tmp` 已是 symlink 指向受保护文件时，模型额度持久化不改变外部文件且不生成符号链接正式账本；旧固定 `.tmp` 是普通崩溃残留文件时，不覆盖该文件，限额仍正确持续计数。符号链接不可创建的 Windows runner 合法 skip 该专用符号链接反例，另有普通残留测试跨四平台必跑。
- 将源码、测试和本台账先提交于独立暂存分支，然后**只在一次合并检查点**推进 PR #113 候选 HEAD；旧 `d35eea4` 的所有测试成功不继承为新 HEAD 成功。新的完整 ABCD-v3/v4 和专项只跑新最终源，不为每条文件编辑重复触发大型 CI。
- 状态：`R4_05_ATOMIC_TEMP_HARDENING_SUBMITTED / SAME_HEAD_CI_REQUIRED / E_INDEPENDENT_REVIEW_REQUIRED / FIELD_VERIFIED=false / C12_PHYSICAL_HOLD / BANK_FINAL=NO`。无需且不得因此构建 ZIP。

## 第四轮统一集成：同 SHA CI 与独立 E 组 Review 实质门禁（2026-11-10）

在 PR #113 源码 `f63e72f366569c155028d038260a7d02a90a6505` 上，16/16 GitHub PR 工作流全部 `completed/success`、四平台+ABCD-v3/v4 真实 Chromium 均成功。但 Github API 报告 `reviews=[]`；`mergeable=true` 不能代替独立 E 组签收。故不合并、不得称 R4_FIELD/BANK_FINAL。

新增 `rc7_release/rc72_r4_merge_gate.py`（仅工程合入准入、无业务执行、无模型调用）和对抗测试、No-ZIP 四平台工作流：
- 从只读 GitHub PR / Actions / Reviews API 抓取事实，检查目标 `work/rc7.2`、精确 40 位 HEAD、非 Draft、16 项列名固定的必需工作流均为同 SHA `pull_request/completed/success`，缺失、跳过、失败、排队、旧 SHA、重复同名相互矛盾均拒绝。
- 独立审批仅接受 GitHub API 的真实 `APPROVED` review，审批人须由**仓库管理员维护的** `RC72_E_REVIEWER_LOGINS` 变量授权，且**不得等于 PR 作者**、不得是 Bot、Review 所绑定 `commit_id` 必须等于当前 HEAD；撤回/驳回更新后的审批不接受。若无独立 E 组账号、未配置授权名单或无有效 Review，保持 `HOLD`，不得自己伪造 E 组签收。
- 新增四平台 Python3.8/3.11 负例：16 项全绿但无审批、错 SHA、错分支、缺/跳过/失败/正在运行的 CI、非授权/原 PR 作者/Bot/过期/撤销审批、分页不完整，均不能返回工程可合入状态。
- `.github/workflows/rc7.2-r4-e-merge-admission.yml` 为 R4 候选自动运行上述门禁；`pull_request_review` 的提交或撤销会触发重新评估。若仓库未来将该检查设为 required，它才成为 GitHub 服务器强制保护；**不能因为存在 Workflow 便宣称分支保护已配置**。
- 通过门禁仅表示 `SOURCE_MERGE_ADMISSIBLE`；输出仍强制 `field_verified=false / bank_final=false`。C12 approved DSH main / 银行真实 32 roster + 33rd 拒绝 / Q3–Q9 / 4A / BSK / 真实 N8-N9-N10 仍 HOLD。不得借此绕开 Issue #79 或制造虚假 ZIP。

施工采取独立支线先做源码和定向 CI，再**一次性**将本批集成到 PR #113，不在每个文件提交后触发两轮大 Chromium。现阶段 `R4_E_REVIEW_GATE_SOURCE_SUBMITTED / QA_SOURCE_PENDING / E_INDEPENDENT_REVIEW_PENDING / C12_PHYSICAL_HOLD / BANK_FINAL=NO`。

## 第四轮独立准入门禁再次加固 — PR 所属身份不可借同 SHA 混用（2026-11-10）

- 最新统一候选 `work/rc7.2-r4-consolidated-1to5-20261110@1e7195383506f2a53e9361fc8db7a739e5363653` 的 **18 项**同 HEAD 工作流核验：原 16 项工程回归 + 4 平台 merge-gate 源码专项共 **17 SUCCESS**；独立 E 准入门禁 1 FAIL，按设计拒绝不存在 E Review 的合并，不是生产功能的假 FAIL。E 组仍未正式 Review，未合入 `work/rc7.2`。
- 源码准入审计补充：只按 `head_sha` 搜索 Actions 仍有跨 PR 借用相同 commit 的风险。现在必需工作流同时关联 GitHub REST 的原生 `pull_requests[].number` 到 **当前候选 PR**，如有 `head_branch` 还必须一致；候选 PR 编号和源分支不可缺失/错配，严拒 `pull_requests=[]` 等无法证明来源的记录。新增对抗测试覆盖跨 PR 同 SHA、无原生关联、错源分支、错编号及缺少源分支。不能从 PR 文案或 agent 输出代替 GitHub API 证明。
- GitHub 的 `pull_request_review` 自动事件对 workflow 是否存在于**默认分支**有额外平台触发条件；当前仅在 RC7.2 候选源码存在，不得声称独立 Review 提交后必会自动重新评估。实际审批后可由有权限人员在当前 HEAD 的失败 Admission 工作流点 **Re-run failed jobs**，使读取实时 Github Review API 的门禁再评估；管理员应审查/配置默认分支触发策略与 RC7.2 目标分支 required check，未经确认不得报自动化审查链完全闭环。
- 此修复先在隔离施工分支，完成 Python3.8/3.11 × Windows/Linux 四平台定向 CI 后才纳入 #113。纳入即产生新 HEAD，原先 17 项 PASS 只作历史证据；新的完整 ABCD 全量源资格需重新核销。
- 合入资格仍由**真实独立 E 组身份/签名 Review**及所有必要 CI 决定；不得由 A 自我代签，不能为了变绿将审查门禁改为 SKIP。现场 Q3–Q9、DSH Agent Teams 32+第33人阻断、C12 已批准可分发 DSH 主程序及独立 SHA256 均仍 HOLD。BANK_FINAL=NO。
