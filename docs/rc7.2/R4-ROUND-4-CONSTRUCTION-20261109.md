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
