# V4 Resume Expert Checkpoint

**DECISION = PROCEED_WORK_PACKAGE_C。ARCHITECTURE_CHANGE_REQUIRED = NO。HARD_DEPENDENCY_FAILURE blocking C1–C3 = NO。** 这是一次独立断点复评，不重做 Phase 0，不批准当前候选为产品 PASS。C4 未通过时危险执行继续 fail closed；其余授权施工立即继续。

评审对象：`work/v1.13.0-recovery-turnkey-validation`，HEAD `c9f067f5868245e115e486fa14936ac9cb783fb5` 加当前未提交草稿；观察清单见 `review-observation.json`。Reviewer 只写本目录证据，未修改产品或测试。Implementer 负责实时远端核对及保存未推送成果；本报告不假称完成远端核对。版本仍为 **1.14.0 CANDIDATE / NOT_QUALIFIED**。

## A–B：已完成与证据边界

- 已有真实产品代码：`03b0645` 修复 mandatory Oracle 覆盖及冻结 expected 绑定；`799f843` 引入同一 R1 上的 GeneralWork/RuntimeDiagnosis typed roots；`7e516c4` 以真实 Host 父用户消息、完整 clause、scope 和 operation receipts 准入；`c9f067f` 增加 R1 prompt claim/receipt/readback、跨进程调度锁、有界自动 wake/rotate。未提交 entry/agents/install fixture 迁移及 General execution contract/file broker 属于施工草稿，不能丢弃或当完成。
- 本次新跑 interaction admission/receipt **36 tests / OK**。Oracle 原始测试逐一检查 DB/CAT 第一/中间/最后 mandatory failure，保留所有断言，含异常与 absent provider 负例；不是只看最后 status。其 DB/CAT 仍是 synthetic providers。
- 阅读 `progress/run-06-slow/summary.json`：9 个真实 R1 + HTTP Host fixture + OS 子进程情景检查通过；source 为旧 HEAD + dirty，actual_model=NONE。源码 oracle 对 idle 明确要求两次进程启动但一次效果、同 lineage，对 crash/late caller 有不增事件断言。storm oracle 允许有界 WAIT，所以它**不证明自动 Diagnosis 和最终收敛**。
- S2 final-fetch hook、S6 browser-use、Windows confinement、S7 k6/ZAP 属于隔离 spike。`tests/v4/test_general_worker_entry.py` 明确使用模块 spy，**没有 General Worker 实际执行证明**。旧 1.13 package/Windows qualification 不升级为 V4 L3/L4。

## C、G：Product P0 仍 OPEN

| 风险 | 原始源码判断 |
|---|---|
| Director context 超限、重启 attach poisoned Session | **仍可能**。`tools/recovery/launcher.py:232–250` 读取 operational pointer，只要 GET Session 存在便 attach；无 logical Director、epoch、poison/pressure 验证。退出 attach 后 finally 停 loop/server，也尚未实现独立 DETACH。 |
| Primary 被限制后无法完成普通工作 | 权限已 deny-all + 合法工具白名单，委派入口已布线；但 `general_work/execution.py` 缺失，General work 返回技术缺口，worker CLI import 不能成功。不得靠用户命令补洞。 |
| Primary 越权重工作 | Agent 权限缩小是实际正向变化；仍须真实 Host 的禁止工具尝试/伪造 role/旧 Session 负例及合法委派成功对照，不能仅凭 Markdown 宣称 Runtime enforcement 完成。 |
| Mission 依赖“继续” | 常见调度 gap 已修，`progress_once/_wake_once` 能自动唤醒。但无进展最终只返回 `DIAGNOSIS_REQUIRED_NO_PROGRESS`，未派真实 Diagnosis；Plan 完成还停在质量评估 WAIT；pause/stop/update/Gate typed owners 未全部接通。 |
| 重复 dispatch / side effect | Prompt claim + readback 提供窄范围防重发；未结束 Interaction receipt 仍直接 RECONCILE_REQUIRED，无自动补 bind/complete。Prompt 防重发不是 POST/DB/UI exactly-once；独立业务 ledger 未集成到本 HEAD。 |
| Context Governor | `.opencode/lib/model-result.mjs` 只是执行后 bounded presentation，未对真实 Tool args 做 size/depth/count 准入；截断 digest 也不必然存在可恢复 artifact。无产品 final provider hook、全角色 token telemetry、Director successor/TUI follow。 |

其他 D/E/F/G 原合同范围继续保留 OPEN，不能由本 checkpoint 默示缩减。

## 草稿中的可复现问题

`draft-counterexamples.json` 是本次独立最小反例，读取实际未提交模块、只写临时测试目录：

1. **P1 / scoped_files.write 并发覆盖**：第二次 hash/inode 校验之后、`os.replace` 之前插入一次实际人工写入，方法仍返回成功，人工内容被覆盖。原子 rename 不是 compare-and-swap。必须定义并证明并发写者边界（Windows 现有 final file handle 也在 replace 前释放），或安全地输出冲突候选，不能声称 expected hash 保证所有外部 writer。
2. **P1 / execution_contract CALL_CLAIM 身份未闭合**：有效 Host field shape 加任意 `request_spec`、彼此不匹配的 host input digest/request digest 被 reducer 接收。当前仅证明内部合同缺口，因 execution service 缺失，**不是已证明可达外部攻击**。加入 action-specific schema、canonical digest 绑定及 actual Host evidence 校验，live/replay 一致。
3. **P1 / General write scope 不满足完整产品例子**：PREPARE 固定只允许 `notes` 和 job scratch，无法实现批准的普通工作区配置文件修改。可保留保护 Runtime/auth/R1，但需从实际用户操作和可信 policy 派生允许的目标，而非把所有 write intent 都降成 notes。
4. **P1 / 搜索边界与耗时尚未证明**：search 在验证每个文件前以路径 `os.walk`，起始 symlink/junction 可以先遍历 scope 外目录；无文件或 glob 不匹配时 4096 candidate 上限不能约束遍历数量。read 最终 no-follow 能拒绝实际内容，但不等于目录遍历边界或资源预算已满足。采用同样受控目录句柄和 visited-entry/time budget，独立负测。
5. **P1 / lifecycle 与执行完成双入口**：现有 TRANSITION_GENERAL_WORK 的 ACTIVE→COMPLETED 只要求 summary，可绕过 execution COMPLETE 所需成功 receipt。执行启用后应拒绝旧 lifecycle completion shortcut，除非有独立明确受信管理语义。

这些是普通可修复 component findings，不需要改变 v7、另建数据库或重启架构评审。

## D–E：下一施工顺序与 Gate

立即完成 C1：修复上述草稿；实现真实 GeneralExecution owner、实际 Host call 校验、受控文件读写和 R1 receipt/recovery；接实际专用 Worker Session 与已有调度/监督；完成普通工作/诊断正例、跨 root/保护对象/旧 caller 负例。随后独立 raw-source + adversarial review 通过才冻结该 wave。危险 terminal 尚依赖 C4，明确技术 fail closed，不能把所有 C1 阻住。

随后 C2：三层 admission +真实 provider最终请求+按角色技能工具选择；先覆盖已超限 Director / compact 失败 / 非模型 successor / atomic epoch pointer / poisoned restart / TUI follow，再做至少两次恢复和 >=10MB / static inventory scaling stress。C3 补实际 Diagnosis/replan、quota/busy/paused/stop、全进度状态与业务 side-effect intent/receipt/reconcile。C4 按实际最新 Windows 证据接产品 broker，不降低隔离；C 通过后继续 D/E/F/G。

Windows 本地较新 evidence 为 **34509751821 / 4f9aacc**：PowerShell result 已生成；public network 返回 10013，另有独立 WFP AppContainerLoopback BLOCK 关联（不能把 timeout 当拒绝）。总体 qualification 仍 incomplete；portable Python fixture 的 denied=false/winerror=null 必须核实 errno/异常和 sentinel，不能先判断实际逃逸或 PASS；Git Bash/产品整合仍缺证据。原 34508440019 缺 PowerShell result 的失败保留，不能当最新结论。相关 evidence 在 `windows-diagnostics-evidence/run-34509751821/`。

## F：新增 V1.9.4 Context 现场经验

用户叙述的初始约19K、后续68K/80K/100K/120K+、数百KB tool output、未见有效 compact，是正式回归需求输入；**未提供 raw trace，本地未独立测得这些现场数字**。V4 F01/F03/F04/F35/F38/F47 已覆盖根因方向，但新 telemetry 分项和 STATIC_CONTEXT_SCALING_TEST 尚未产品化/实测，不可标覆盖完成。应记录 model limit、static system/agent/skill/tool schema、bootstrap/source/history/tool input/output、reserve/final token、pressure、compact before/after、rotation reason；真实取不到则标 UNKNOWN/estimated+方法，不能以 bytes 冒充 tokens 或 cache read 变化当根因。映射新增合同 T11/T12/T13，并保留它们与旧 V4 同编号不同文本的来源身份。

TASK_DIFFICULTY = HARD。REASONING_RECOMMENDATION = HIGH。ESCALATION_REASON = R1 并发与回执恢复、Host最终发送边界、Windows隔离需要跨层推理；普通布线与测试可用 MEDIUM，当前无全局架构矛盾，不建议全程 ULTRA。不能切换 reasoning 不构成停工理由。
