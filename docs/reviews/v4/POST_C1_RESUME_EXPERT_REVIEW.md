# Post-C1 independent delta review

**DECISION = PROCEED_C1_REMAINING。ARCHITECTURE_CHANGE_REQUIRED = NO。阻断 C1/C2/C3 产品施工的 HARD_DEPENDENCY_FAILURE = NO。** 不需要用户确认；保留已验证组件，立即继续。Windows 进程隔离未证明仅阻止依赖它的危险执行。

Reviewer 直接核对本地 `b0d1aaba8820d7eb3dfd358ada106c96c748bcd2`，worktree clean；远端核对由独立 Implementer 执行，本报告不冒称已联网核对。读取新合同、V4 authorities、C1 原始复评及日志，当前 launcher、Host admission、Interaction owner/receipt、General execution、Scheduler、Control Loop、session_pressure、G4 HumanGate 和工具 schema。未重跑已关闭 General 组件。完整身份见 POST_C1_REVIEW_OBSERVATION.json。

## 1. 当前声明是否有证据

**支持声明的组件范围。** 已提交真实 Host 结果 `docs/reviews/v4/C1_REAL_HOST_COMMITTED_SOURCE_RESULT.json` 为 source 4203ae4：一次用户请求、独立 Worker 实际读写、Mission=0、用户技术命令=0；该实验明确禁用 default plugins，所以不是正常安装产品 L4。

Windows run 34693091510 对 source 781fc387：91 run / 89 pass / 2 POSIX-only skip / 0 failure / 0 error。再次读取 result/log 并核对 SHA256，匹配 `03f296a2d372d88ae44dd02105775356209ccfc8f0df38c6241c25e7eb314840`。两条真实 ReplaceFileW 用例已通过。C1 独立复评中的 false completion、恢复窗口、并发 displaced 丢失、unknown-write 分类、兼容门 findings 均按记录范围修复。该证据只支持 **General scoped file + R1 组件**；进程隔离仍 FAIL/NOT_QUALIFIED，完整 C1 仍 OPEN。

## 2. 遗漏或仍开放的 P0/P1

没有发现需推翻已通过文件组件的新 P0/P1。以下属于当前真实源码缺口，必须继续关闭：

- **P0 caller 当前身份**：hosted_intake.actual_host_user_turn 验证真实消息、parent、内容、时效，但没有当前 logical Director/session/epoch/lease 检查；真实来源不等于仍有效 caller。General 的 job-bound caller fencing 不自动覆盖 Primary 的 start/update/control/Gate。先接当前绑定才能开放新 mutation owner。
- **P0 Director/context**：launcher.py:232 起只要旧 Session GET 成功就 attach，无 poison/retired/epoch 审核。session_pressure 是采样历史/保守估计，不是完整 final-provider admission；工具库目前仍主要为执行后 presentation bound。不得把这些写成 all-role Governor PASS。
- **P1 C1 owners 缺失**：MISSION_QUERY 已有受 scope 解析的只读路径，不能说完全没实现；但 update/Gate 返回 OWNER_ADMISSION_REQUIRED，pause/stop/detach/stop_runtime 没有可执行 owner。Mission start/continue 已消费却未完成的 receipt 仍只 RECONCILE_REQUIRED，不能指望下一用户“继续”修复。
- **P1 liveness**：无进展仍只 DIAGNOSIS_REQUIRED WAIT，未派真实诊断；Plan 完成仍停在 quality assessment WAIT。launcher finally 在 TUI 返回时停 loop/server，与 DETACH 语义冲突。业务 POST/DB/UI 副作用恢复不由 General 文件回执或 prompt 防重发自动覆盖。

普通一致性 finding：工具 schema 允许最多32个 result/artifact refs，而 Runtime 上限16；glob/path 上限也有差异。保持 fail closed，但把同一契约限制和 allowed_values/recommended_action 对齐，避免正常模型反复猜参数。此项不是架构 blocker。

## 3. C1 Remaining 精确顺序

1. **共同 authority seam**：Runtime 拥有的 Primary logical identity→current Session/epoch/lease 持久绑定；真实 ToolContext +真实父 UserTurn +当前 binding 联合准入。检查和 R1 mutation CAS/receipt 消费一致，旧 caller 在事件产生前拒绝。为 C2 successor 留共享接口，不把状态放到 launcher JSON 当 Product Truth。
2. **Query + control**：保留现有 query read path，补 completed/paused/active 与多 Mission 的明确结果，禁止新 Mission。pause/continue/cancel 通过已有 canonical Mission 状态机、当前 expected seq 和唯一 operation receipt；pause/stop 先形成 Runtime fence，再处理已拥有的外部进程，保留在途回执。detach 只结束 UI，stop_runtime 独立停止拥有的 Runtime；不杀用户宿主或丢弃未决副作用。
3. **Update**：以同一 Mission 的 durable update intent 请求 Planner 创建新 PlanRevision，沿用现有 validate/activate 和 Scheduler；不能让 Primary 直接提交随意任务 JSON。绑定基准 revision，保护完成/在途 Task、Attempt、effect identity；迟到旧 Planner/旧 revision 结果拒绝，不能重发已完成业务动作。操作回执在各崩溃点可自动继续。
4. **HumanGate**：在当前授权范围内检索 compatible pending Gate，再执行零/一/多选择；不要先强迫多个 active Mission 选一个而漏掉全范围唯一 pending Gate。用户“已登录/完成/好了”仅发 verification request；gate_id/actor/approved 等模型参数不是 authority。复用现有 G4 resolver 的独立 fresh same-context verification，只有 RESUME_SAFE 才 resolve，并由后台继续原 cursor。现有 resolver 本身不替代新 Host/epoch 入口。
5. **Mixed/coexistence + recovery**：按每个完整 clause 绑定独立 operation/scope。停止 Runtime 的操作先于新 mutation；Mission pause 与独立 General work 的语义分开。Active Mission + chat/query/General/update/Gate，两个 controller、重复 turn、旧 caller、operation claim/bind/dispatch 崩溃都需正反对照。保留 General 组件，主要新增集成 tests/actual execution，随后独立原始源码复评。

以上可以完成 C1 的 routing/control 功能；若危险 terminal 仍待 C4，capability matrix 必须精确表示“文件执行 READY、进程执行未合格”，不通过合并标签提前宣布全 General execution PASS。

## 4. C2/C3/C4 最短正确依赖路径

**C1 authority 基础 → C2 all-role request/context + Director successor → C3 无用户时钟自治/Diagnosis/业务 effect 恢复。C4 自身可独立推进，最终危险 terminal 及依赖它的诊断执行必须等 C4 实证。** 无需因为 C4 阻碍全部 C1–C3。

C2 先建立可机读实际/估计来源明确的 telemetry，工具输入/输出 admission 与真实 final-provider hook；再按角色加载、源分块/引用；利用 C1 binding 实现 compact before/after、失败非LLM successor、R1 checkpoint+epoch fence+pointer+TUI follow。压测 >=10MB、中文/schema/history/静态Skill增长与每重要role两次恢复。旧19K→120K现场数字仍是用户回归输入，不当作本地实测。

C3 复用已有 Scheduler 和 Control Loop，有界 wake 的后继必须实际 diagnosis/repair/replan，区分 busy/quota/Gate/stalled。将业务 progress、failure signature、inflight effect ref 持久化；先保护在途效果，再自动恢复，不能为了 liveness 盲重发 POST/DB/UI。

C4 保留 scratch/v4-appcontainer-diagnostics 和所有失败证据；继续定位子进程链、namespace/ACL/token/env/network，真实 Windows 验证。文件/R1 PASS 不重做，不撤销权限，未证明进程继续 fail closed。C closure 后自动 D/E/F/G。

## 5. 是否需要架构变更

**NO。** 当前缺口可在已批准组件边界内完成：R1 唯一 durable truth；Planner/调度/Router/监督职责保持；Primary logical binding 与 owner 接线不要求恢复 legacy DB、第二工作流数据库或让 General 冒充 Mission。若具体实现出现跨根事务/授权不变量矛盾再提出真实 Gate，不能提前以理论疑虑停工。

## 6. 是否存在 false-green Oracle

本 checkpoint 没有新增“已通过文件组件是假绿”的证据；既有负例和 Windows 日志支撑其窄范围结论。**尚开放能力没有通过证据**：Host tool completed 可能内部 FAILED；bounded WAIT 不是最终自治收敛；native compact API成功不是有效压缩；fresh browser verified 不是用户文字保证；fixture不等银行；91 Windows component tests不是整包或进程隔离。C1 新测试必须断言实际 R1 revision/状态/唯一dispatch/原cursor及未增Mission，不能只检查路由标签或 returned status。

## 7. 必须 Preserve

General typed roots、实际 Host identity/operation receipt、同事务 General intent event/旧event兼容、actual Worker Session、文件安全broker和Windows ReplaceFileW保留/UNKNOWN fencing、read/complete/claim crash recovery、两进程单效果、旧Mission golden及已经通过的正反测试。保留历史失败与修复日志、已固定payload字节和真实Host evidence；只在相关变更影响它们时做回归，不无理由重建或重跑。

## 8. Reasoning

TASK_DIFFICULTY = HARD。REASONING_RECOMMENDATION = HIGH。原因：当前剩余工作集中在 Host/epoch authority、HumanGate、PlanRevision 并发、真正provider admission和Windows隔离；普通布线和测试可按 MEDIUM。未声称切换了产品模型/reasoning设置；无法自动切换也不是停工理由。当前没有需要 ULTRA 的全局不变量冲突。

**下一动作：Implementer 直接实施 C1 共同 caller/current-binding owner，再接 query/control/update/Gate；不等待用户逐步批准。**


### C1 proposed Primary binding component delta

Implementer 在本次短复评中提出 additive `PRIMARY_INTERACTION` typed root，workspace-derived identity、专属 root state、受信 launcher owner 绑定 logical Director/actual Host Session/epoch/lease，模型端只能读及接受当前 caller 检查。**该方案属于 CC-01 已有 R1 typed-root机制上的组件合同增量；没有已知 v7 global invariant 矛盾，允许直接施工。** 需记录 root定义、owner、事件/命令和兼容守卫；core session_id 保持空，Host Session作为root-owned binding subrecord，不创建fakeMission。

实际准入仍须检查 Host workspace/provider身份、当前 epoch/lease；只有受信 launcher/lifecycle owner 能 create/bind/renew，model tool 不能自注册。不能以Session存在推定健康或把此binding扩成General/G4权限。本步只实现ownership/fencing，不得宣称 pressure/自动successor/TUI follow完成；这些仍属C2。保留旧Mission golden和未知root/event写入拒绝用例。路径迁移/安装身份需明确处理，不能因重新解压或路径别名意外复活旧Session权限。
