# RC7.2 第一轮 P0 — 正式 Gate 与 DSH AgentTeams Host 接线

状态：SOURCE_CONSTRUCTION / TARGETED_CI_PENDING / BANK_FIELD_NOT_VERIFIED
源分支：work/rc7.2-p0-stage-20261107；合入 PR #76 前禁止打包。

## 核心原则

旧 RC6/RC7 的 mission_gate_commit 不能将任何非空 evidence_ref 转换成 RC7.2 认可的 SCRIPT_READY Gate。正式生产者是 NativeScriptReadyGateProducer：

- N1–N5 都有当前有效的 Native Delivery/NodeGate；
- N6 的整个冻结 Case 分母有当前真实 N6 ExecutableContracts，非单个 happy path；
- 逐 Case 调用只读 N7 ExecutionAdmission 检验现有数据、源码、Case 版本、签名来源、环境；
- N6 原有独立评审 NodeGate 严格为 PASS；
- 经当前 Host Captain 所属 R1 Lease 身份再次核验后，签发源/批次/版本/分母绑定的 HMAC admission；
- R1 重建重验签和当前输入；失败 HOLD，不产生 execution_attempt 和 bank_final。

发布中的 Native ReleaseBatchDriver 在完整搬运包达到 N7 前自动调用该 producer，而不是要求用户在旧 Mission 上手工调用 Gate。

## 现场命令

现有状态只读：
    python -m rc7_release.rc72_mission_cli script-ready-status --ledger <R1.jsonl> --source-commit <40SHA> --release-batch <批次> --release-id <release>

完整搬运包的原生命令，附加可信 DSH Host：
    python -m rc7_release.rc72_mission_cli run --ledger <R1.jsonl> --source-commit <40SHA> --release-batch <批次> --release-id <release> --package-root <包根> --evidence-root <证据根> --mission-config <bank-capabilities.json> --captain-observer-module <行内受控模块> --dsh-host-url http://127.0.0.1:4096

如需要单独触发正式 N6：
    python -m rc7_release.rc72_mission_cli admit-script-ready <上面的共同参数>

注意 Q7 的 ReleaseBatch/admission 和银行物理搬运验证仍须在本命令前完成；本接口不创建任意业务资料、不绕过 N1–N5，也不替代 Q3–Q9。

## 可信 AgentTeams 观测模块要求

受信任的行内模块必须实现以下名称的 Python 函数：

    create_captain_observation_provider(truth, release_id, source_commit, release_batch_id)

并且**必须返回** rc7_release.rc72_dsh_agentteams_factory.CaptainProviderWiring 类型，成员包括：

- proof：从**行内真实 AgentTeams 控制平面**获取并签名的 SignedAgentTeamsCaptain；
- membership_authority：AgentTeams 单独的 HMAC 验签器；
- host_authority：与上者独立的 Host 控制器 HMAC 验签器；
- role_profiles：各 L1–L7 EXECUTE/Review 所需的严格允许角色；
- approved_capabilities：审核后的最小工具能力集合。

此模块不得让模型文字/JSON 配置/聊天 Session 自动提供 HMAC 签名或任意 Team ID。原生 LocalDshAgentTeamsHost 实际通过 DSH 本机 REST GET /session/{id} 与 GET /session/status 检查会话存在、ID/状态匹配，拒绝非环回地址、重定向、过大响应、错误签名、过期观测、外来 Captain、角色升级。

当前银行 DSH AgentTeams 插件是否对外提供这类签名成员身份信息**尚未现场验证**。如果不可提供，工具必须 HOLD，禁止伪造。这属于明确的行内 Host 接入依赖，而不是可以通过 CI 冒充已闭环的事实。

## P1-5 / P1-6 端到端

- Case→ETU→WorkItem→Contract→Admission 唯一且全分母；
- 准备和执行前校验，独立 Reviewer 复查，N8 恢复旧证据也必须复查；
- Attempt 只能归属于同一 Case/WorkItem/Contract 和真实签名工具回执；
- 审查输出必须来自签名的原始 Reviewer 输入文件所在的原始进程目录，内容 SHA256 可复查，不能被同摘要其他路径替换；
- 旧失败 Attempt 继续保留原证据和状态，新回归必须新 Attempt，拒绝假 PASS；
- 启动和重进均不能重复业务 HTTP/Browser 操作，N10 只接受已通过独立 Gate 的完整投产批。

## 流水线

中途只跑 RC7.2 P0 Staging Fast Check（Python3.8 编译与 P0 定向测试）。其他 PR 与完整构件包**不更新、不构建**。GAP-01/GAP-02/P1-5/P1-6 生产代码、全部对应负例/冷恢复、同 HEAD 定向回归均通过后，才冻结最终 SHA、推进 PR #76、统一跨平台全量验证、最后运行手动 Windows Q2/Portable 一次打包。BANK_FINAL 始终由真实行内证据决定。
