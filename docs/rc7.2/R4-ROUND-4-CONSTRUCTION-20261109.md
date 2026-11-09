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
