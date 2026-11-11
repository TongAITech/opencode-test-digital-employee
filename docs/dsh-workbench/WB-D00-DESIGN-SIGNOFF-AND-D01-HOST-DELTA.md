# WB-D00 / WB-A03 — D 组 W0 DESIGN_SIGNOFF 与 WB-D01 只读宿主差异审计

状态：**D_DESIGN_SIGNOFF_ISSUED / A_INTEGRATION_PENDING / FIELD_QA_NOT_RUN / W0_NOT_FROZEN**  
签署日期：2026-11-09；执行者：D 组（宿主/插件/会话）；范围：W0 设计合同，不是 D01–D04 现场实施验收。  
审核输入 W0 source_sha: `515f6a367bd16d3b83197fa2c89e15d63a83c4fe`，PR #84 草稿；F PR #85 @ `5eaaeec695d4d1102e467fd306002328830517e1`，结论 REVIEWED_WITH_BLOCKERS。RC7.2 源基线 @ `58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d`。
设计对象：04-DSH-HOST-INTEGRATION.md、06-API-AND-EVENT-CONTRACT.md、WB-A03-CROSS-GROUP-SIGNOFF.md、02 复合关联、05 R1、08/09/10 以及 F 的 FG06/FG08/FG15/FG16。

## 1. D 组正式 DESIGN_SIGNOFF（有明示适用边界）

**D_DESIGN_SIGNOFF = ACCEPTED_FOR_W0_DESIGN_ONLY**：D 同意以下可实现的宿主边界和拒绝语义，供 A 纳入 A03；不以 W1 真实宿主证据作为 W0 设计先决条件。此签署不替 B/E/F 审批，也不覆盖 F 的 FG16 或 LICENSE 门禁。若 A03/04/06 发生身份、会话或授权语义变更，需 D 在新 SHA 重新签署；本附件合入 W0 前为 A_INTEGRATION_PENDING。

### 已签设计不变量与责任划分

1. **principal / ACL**：权威主体来自已认证 DSH Host 的 server-side identity/permission binding，绝不可从浏览器 JSON、prompt、插件 UI 或用户提供的 principal/roles 字段取得。项目权限先行；project.read 未授权一律 403 且不泄漏项目/批次是否存在；授权后才可判 404/422/409/503。权限变化提升 access_scope_revision 并撤销旧查询游标、SSE、暂存上下文、Worker 准入。D 负责宿主主体映射，B/E 负责资源级复核与服务端最终强制授权。
2. **原生入口与存储权威**：测试工作台通过 DSH 原生面板/插件入口，不创建第二个模型目录、API Key 管理、聊天记录库、Skills/Commands 注册表或对话发送服务。模型与凭据仅宿主持有；工作台只保留原生对象 opaque ref 与业务 Scope 绑定，**NO_DUPLICATE_MODEL_KEYS**。禁止为方便测试把宿主设置或 token/Authorization/Cookie 写入 R1、工作台 DB、URL、SSE、附件索引、日志或工作台浏览器持久层。插件不可用要显式 CAPABILITY_UNAVAILABLE，不用模拟模型回复假成功。
3. **三类会话严格隔离**：PROJECT = 项目级通用会话，无 batch/mission 的执行授权；BATCH_COMMAND = project_id+batch_id+release_date+mission_id 的指挥会话，经 E 正式控制面才能执行受控 Mission 命令；WORKER = 单个 WorkItem/Attempt/lease/role 的短会话，只能使用签名允许的工具，过期或重派后撤销。不可通过重命名、历史对话、子 Agent 文本将 PROJECT 升格为 Captain 或把 WORKER 重用成跨项目主控。
4. **持久绑定与隔离**：原生会话绑定记录至少包含 `project_id, batch_id?, release_date?, mission_id?, host_session_id, context_version, session_kind, principal_ref, access_scope_revision`；WORKER 另有 workitem_id、attempt_id、worker_id、签名租约和过期时刻。服务端对 host_session_id 的每次加载、发消息、附件、模型/技能/命令和恢复都重新校验 principal+project/batch/Mission 归属；切项目/投产日期先丢旧订阅与过期选择，不能混合 ContextEnvelope。旧 Attempt provenance 不跟随 UI 当前筛选变化。
5. **恢复与事实**：对话历史仅用于用户可读重开；Mission、WorkItem、Attempt、Evidence、NodeGate 的唯一事实来源是 **R1**。宿主断线/崩溃后先从 R1 加载 Mission/Attempt/租约/版本，核验签名 Captain 及宿主真实 session，才可选择复用或建立新会话。未知副作用 HOLD；已完成 Attempt 禁止重跑或覆盖旧失败；历史会话缺失不可将新 Mission 作为“恢复”。SUT 的 4A Cookie/登录与 Agent 主体完全分离。
6. **模型、Skills、Commands、附件与取消**：列出能力与版本的 Host adapter 必须使用原生 API，保留原生失败信息并转换成中文状态；模型切换只改变该宿主会话的下一次调用，不能静默篡改已签 Attempt 的 model provenance；Skills/Commands 原生路径按宿主能力确认，不允许工作台执行未签高危命令；附件限 project/batch/mission 权限、大小、内容类型、哈希与脱敏，不把机密字节加入 ContextEnvelope。取消原生一次生成 ≠ Mission pause/stop：后者须走 06 的 E 受控命令、幂等/状态修订/人审门禁；不可从 UI 直接改 R1/NodeGate。
7. **Agent Teams 签名控制**：Captain 仅控制与派工，Worker 按角色、精确 Scope、短租约和工具白名单执行，独立 Reviewer 核查；Host 插件证明与 Host 观测签名用不同密钥，验真实 live session、R1 当前租约/代次和观察时效；禁止普通字符串伪 Captain，断线后不得重复派发已完成 Attempt。既有源 `rc7_release/rc72_dsh_agentteams_host.py` 使用 loopback GET session/id+status、签名 membership 和 Host 观察；`rc7_release/rc72_captain_host_reentry.py` 以 canonical R1 租约恢复。不可将只读 probe 当成拥有签名/执行能力。
8. **32 队员四维证据**：源码 `rc7_runtime/rc72_agentteams_capacity.py` 配置 roster=32、默认 max_active_workers=4，仅是 **ROSTER_32_NOT_CONCURRENCY_32**。必须分开记录配置名册数、真实同一时刻活跃 Worker、资源/Browser lease 持有数、模型并行/额度/时间窗口；现场 DSH 1.18.26 插件身份/version/config 未观测前全部 FIELD_QA_NOT_RUN。
9. **业务 Scope**：投产批次为项目内投产日期，稳定 batch_id 在内部保持不变。一个需求跨多个系统版本/多个 SST；多个需求共享版本不共享 SST。DSH ContextEnvelope 不得用名称/版本标签推导真实关联，必须消费 B 组规范化关联及 E/R1 truth_revision。Scope 权限/关联修订失效则丢弃旧筛选，不准跨批次复用知识/附件/技能执行上下文。

## 2. WB-A03 D 组反例与阻断语义（设计期可验，现场未执行）

| Case | 输入/攻击 | 必须结果 | 阶段 |
| --- | --- | --- | --- |
| D-T01 | 浏览器发送 principal=admin 或 forged roles | 忽略客户端自报；服务端用 Host principal 重新 ACL，非法 403；无副作用 | W0 DESIGN |
| D-T02 | PROJECT session 携带其他 batch/mission，冒充 Captain | 拒绝权限升级；不签 Captain / 不写 R1 | W0 DESIGN |
| D-T03 | 同 project 切 2026-11-12 → 2026-11-19 后重用旧 SSE cursor/attachment | 取消旧流、升权限修订、拒绝旧 cursor/附件；无跨批次泄露 | W0 DESIGN |
| D-T04 | WORKER 使用过期/他人租约、超出工具允许表 | 拒绝执行和续租；无成功 Attempt | W0 DESIGN |
| D-T05 | DSH 会话历史消失而 R1 Mission 仍未完结 | 从 R1 恢复或 HOLD，不能生成新 Mission 假接管 | W0 DESIGN |
| D-T06 | 按钮取消模型调用后 UI 标 Mission PASS | UI 只标生成中断；R1 NodeGate/N10 保持真实状态 | W0 DESIGN |
| D-T07 | 模型密钥提交至工作台配置、日志、ContextEnvelope | 拒绝并阻断存储，保持宿主 single owner | W0 DESIGN |
| D-T08 | 只把 Agent Teams member capacity 从 8 改为 32 | 最多证明源码可配置性；未见真实并发/租约/配额不得给现场 PASS | W0 DESIGN |
| D-T09 | 存在真实 DSH session 但无有效签名 Agent Teams membership | 无 Captain 授权，不允许 R1 派工 | W0 DESIGN |
| D-T10 | 原生 Skill/Command/附件不存在或被 Host 拒绝 | CAPABILITY_UNAVAILABLE/明确拒绝，不回退成工作台复制品或 fake PASS | W0 DESIGN |

## 3. WB-D01 来源核查与行内 1.18.26 差异表

以下“开源/仓库侧”是可追溯的实现事实或合同，“行内”缺 Host/插件版本和真实设备日志，全部保持 UNKNOWN。**未知不是证明两边兼容，也不是证明存在差异。**

| 维度 | 可核对仓库源 | 行内 DSH 1.18.26 | 需要的现场只读证据 |
| --- | --- | --- | --- |
| 会话状态 | rc72_dsh_agentteams_host.py: GET /session/status | UNKNOWN | loopback GET 实际状态结构、会话类型与响应时间 |
| 会话身份 | 同文件: GET /session/{id}，精确 ID 校验 | UNKNOWN | 已授权的实际会话 ID 只在内存中核对，存档不带 ID/token |
| 签名队长 | SignedAgentTeamsCaptain + 独立 Host signer + R1 代次 | UNKNOWN | 插件真实签名证明、权限/代次/失效测试（D/E/F） |
| 原生面板 | 04 提议复用 DSH 原生入口，尚无适配器实装 | UNKNOWN | 注册/激活/卸载方式与日志 |
| 模型与秘钥 | 04 禁止复制存储；尚无新工作台 API | UNKNOWN | 宿主能力列表/schema/权限，密钥绝不采集 |
| Skills/Commands | workspace-template/.opencode/skills 与 commands 路径存在 | UNKNOWN | 宿主版本、目录、启停及未授权拒绝 |
| 附件/历史/取消 | 04/06 设计要求，当前工作台无完整集成入口 | UNKNOWN | 已授权 Host 原生操作正反例，含恢复后状态 |
| 工作区/上下文 | 04/06 设计需绑定 scope 与 revision | UNKNOWN | 真实角色切换/跨项目及日期负向日志 |
| Agent Teams | rc72_agentteams_capacity.py 32 名册、默认活跃 4 | UNKNOWN | roster、peak active、资源峰值、额度四独立观测 |
| Windows Git Bash | packaging/rc7 现有脚本；新工作台未打包 | UNKNOWN | 断网非管理员、路径空格/中文、冷启/重启/卸载 |

### 可重复的只读能力探测

```bash
python tools/dsh_workbench/wb_d_host_probe.py --url http://127.0.0.1:4096
python tools/dsh_workbench/wb_d_host_probe.py --url http://127.0.0.1:4096 --session-id <authorized-session-id>
python -m unittest discover -s tests -p 'test_dsh_workbench_host_d.py' -v
```

探测器仅对 loopback 发最多两个 GET（/session/status 和显式的 /session/{id}），拒绝重定向、非本地 URL、URL 密码、越界 session ID、超长/非 JSON 响应；不读 key、不会 POST/创建或取消会话、不写 DSH 配置/R1。JSON 结果脱敏，不包含原始会话数据。探测返回 SCHEMA_OBSERVED 只代表“实际只读接口形状被观察”，**不是 DSH 1.18.26 兼容成功、已登录、原生功能完成或银行现场 QA**。现场授权、环境保密、技能目录只读盘点另由 D/F 在 W1 进行。

## 4. 设计签署结果、异议与后续门禁

- **DESIGN_SIGNOFF（D 范围）**：上述 1–2 节安全、会话、Scope、R1/Agent Teams 和原生能力责任边界已签署；具体宿主 1.18.26 adapter 方法/凭据模式/权限接口是 **D01 OPEN / IMPLEMENTATION_BLOCKED_UNTIL_OBSERVED**，不得在 W0 写假端点。
- **问题 D-G01 P0**：原生面板/模型/Skills/Commands/附件/历史/取消的 1.18.26 实际接口和权限 schema 未取证；D01 源码基线 + 只读探针只能建立证据入口。
- **问题 D-G02 P0**：Host principal 与 Project ACL 的最终接线/失效传播、原生会话绑定持久化/schema 尚未实现；需 D02/D03 与 B/E 对接及 W1+ 真负向测试。
- **问题 D-G03 P0**：Teams32 只有源容量，不等于实际同时运行/租约/模型额度；交 E05/D03/F03 的真实并发审查。
- **问题 D-G04 P0**：Windows Git Bash 全离线包、重启/恢复/SUT4A 与宿主 session 独立性尚无现场验收；D04/F04 未开始。
- **许可证**：naodeng PolyForm Noncommercial 商业权利仍 BLOCKED_LICENSE；本补充无任何 naodeng 限制源码，绝不移除许可证或绕过 A02。
- **W0 状态**：本 D 组设计签署不等于 A03 所有组签齐、F 接受、W0 冻结；FG16 需 F 基于最新 A HEAD 独立复核。D02/D03/D04 尚不具备启动门槛。
- **原子单元**：WB-D00 DESIGN_SIGNOFF + WB-D01 read-only probe/negative contracts；提交 D 独立 PR 指向 W0；请 A 按 SHA 将签署状态与 D-G01..04 同步至 08/09/10。F 对 W0 修订后的 HEAD 另行审查。

审计字段：task_id=WB-D00/WB-D01；source_sha=515f6a367bd16d3b83197fa2c89e15d63a83c4fe；test_command=见 3 节；result=DESIGN_SIGNOFF / READ_ONLY_PROBE_SOURCE_SUBMITTED / FIELD_QA_NOT_RUN；evidence_ref=本文件、源文件、D 独立 PR 和 CI（取得后回填）；date=2026-11-09；executor=D；known_limitations=未接触银行 1.18.26 环境、真实服务响应、真实并发或模型密钥。
