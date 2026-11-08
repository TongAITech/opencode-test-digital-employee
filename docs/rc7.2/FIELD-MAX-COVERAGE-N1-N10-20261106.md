# RC7.2 行内最大化真实能力验收计划（2026-11-06）

> 状态：FIELD_AUDIT_PROTOCOL / NOT_FIELD_VERIFIED / BANK_FINAL=NO。仅为现场执行协议，不是已实现或已验收声明。
>
> 主线基准：`work/rc7.2` @ `d4981d3a925e71fe876bfbe42b813b9e077bf725`。实际运行以搬运包 `SOURCE_COMMIT`、当前 R1 和工具真实 Schema 为准；若不同先记录版本差异，勿假设匹配。
>
> 目标场景：`BLOAN-PF1.3.0 / STB915-7723`（以行内 Starlink/TMS 真值为准）。根：ReleaseBatch -> Requirement -> SST -> TestObligation -> L1-L7 -> Case -> ETU -> WorkItem -> Attempt -> Evidence。

## A. 为什么不能只看 DSH Team

新 DSH 会话不会自动成为 RC7.2 原生 Mission。即使 `agent_teams_create` 创建了 team.json / DAG，也只证明 DSH 成员分工。须分别验证：
1. DSH tool Schema + Team 实际创建、成员数、任务状态、消息/重试；
2. 原生 `mission_id` / `rc72_release_batch` / 10 `rc72_mission_node` / `rc72_node_delivery` / `rc72_node_gate` / `rc72_node_transition`；
3. canonical WorkItem / Attempt / WorkerSession、Captain fencing、Capability/Browser/Data/Model Lease；
4. 真实 Tool/Skill result、R1 evidence、NodeGate、N8 语义回边、冷恢复。

若 2-4 缺失，一律记 `DSH_TEAM_ONLY_PARTIAL`，禁止宣称 RC7.2 自主闭环。

## B. 双轨验收：阻断也要最大覆盖

- **轨道 A：正式串联验收**：只从已验证安装包的正式入口、真实 Q7 Admission 和既有 Mission 启动/恢复。每节点仅在上游 Gate PASS、权限/环境可用时进入；失败保留原 Mission/Attempt/R1，不能跳 Gate、不能补假记录。
- **轨道 B：独立能力探测**：当 A 被任何上游节点阻断，仍逐项验证 N1-N10 对应的底层服务/工具可用性、输入 Schema、只读调用和负面拒绝。把结果标记为 `CAPABILITY_ONLY` / `BLOCKED`，绝不当作该 Mission 的 Node PASS。
- **轨道 C：恢复/稳定性**：配额 429、模型超时、DSH session 丢失、Worker 重启、BrowserLease 冲突、缺证据、错误 Schema、权限拒绝，均只在真实允许的无副作用或明确授权边界下验证。
- N1-N10 的 MissionNode 与 DSH member/task 完全不同；辅助 TMS 回填任务不得注册为 N11/N12 MissionNode。

## C. Agent Teams 编排门槛

1. 先列出当前工具真实 `tools/list` / DSH AgentTeams Schema；必要时检查插件是否已注册。未发现 `agent_teams_create`/任务工具则记录 `TEAM_TOOL_UNAVAILABLE`，不凭模型自行打印「团队已创建」。
2. 若可用，创建 **1 个 Captain + 不超过 4 个 Worker 的小 Team**，按需角色分配、每次最多 **2 个模型密集型 Worker**；同一个 100 次/10 分钟额度窗口建议以 60 次/10 分钟为初始软限制（非提供方真实配额），保留恢复余量，按实测再调。Team 身份从真实工具结果读取，不可编造。
3. Captain 只调度/审阅；分析/代码/用例、执行/工具、独立评审至少分开；失败后可复用角色但按 WorkItem/Attempt 启动新 session。若宿主不支持，记录 `WORKER_RUNTIME_NOT_INTEGRATED`。
4. 429/502/STREAM_CLOSED 当作 `PROVIDER_GAP`；按 Retry-After/退避和实际能力切换，不让多个 Worker 同时连续重试，不重复已提交业务操作。
5. 不以固定 8 人数代替运行时动态编排；Team 任务不代表原生 WorkItem。

## D. N1-N10 逐节点验证矩阵

| 节点 | 独立能力探测（轨道 B，可在主线阻断后做） | 正式验收（轨道 A，要求证据） |
|---|---|---|
| N1 现实环境 | 包身份、真实部署/路由、模型/配额、TDSQL、CAT、CodeGraph、Libra、BSK、4A Skill、AgentTeams、资源；分类环境 GAP | N1 WorkItem / Attempt + 真实资源探测证据 + NodeDelivery / NodeGate |
| N2 需求 | Starlink/TMS 真实 ReleaseBatch/Requirement/SST，BR/SR/TR、边界/负面/权限/状态；充分度评审 | TestObligation 追溯、N2 Delivery、独立 Gate；不缺资料假 PASS |
| N3 代码分析 | 部署 commit 与 Feature/release 对齐；CodeGraph 实际结构查询、接口路由与 DB/DTO/行为映射，必须有真实 evidence_refs | CodeSlice/Requirement/SST 影响关系及独立代码分析 Gate |
| N4 用例 | 依据 Obligation 拆解正反例、异常、边界、幂等、权限、状态转移、L1-L7；每例前置/步骤/Oracle/证据要求；质量/充分度反例 | Case 谱系 100% 齐全，Gate 不通过则回 N4 |
| N5 测试数据 | TDSQL 查询权限、现存数据发现、占用、构造方案、人工审批边界、准备/核验/回收流程；缺能力要明确 | DataRef、DataLease、独立验收及 N5 Gate；未知业务副作用不得重复执行 |
| N6 可执行就绪 | L1 harness、API 合法路由与部署、UI/BSK、L6/L7 工具、可执行 Oracle、脚本/签名与资源计划；不编造接口 | ExecutableContract 引用非 STALE N4/N5 和 N1，N6 Gate |
| N7 真实执行 | 各 L1-L7 路由逐层能力探测；从正式 Case 运行工具/Skill；HTTP/DB/CAT/截图/断言分离，验证失败和跳过的真实原因 | 每 ETU 新 Attempt，真实调用、断言与 Evidence 写 R1，禁止假 PASS |
| N8 诊断恢复 | 用已存在的真实失败或安全受控负例验证 ENVIRONMENT/PROVIDER/CAPABILITY/ANALYSIS/TEST_DESIGN/TEST_DATA/PRODUCT 缺口分类 | 原 Attempt 不变，签名差量/回边 N1/N3/N4/N5/N6/N9，受控 fresh Attempt，禁止无授权重放 |
| N9 专业缺陷 | 独立差异调查、复现资格、CAT/DB/日志证据、RCA 与修复后独立回归；若无真实缺陷就验证拒绝路径 | 产品缺陷有可复现证据+专业 Gate；未完成回归绝不 CLOSED |
| N10 投产收敛 | 检查要求/用例/层级/执行/缺陷/Libra 增量覆盖率/未解决 GAP /证据分母；验证 coverage-only 不得 PASS | 完整 ReleaseBatch 的正式 N10 Gate，能解释未收敛原因，不虚构 BANK_FINAL |

## E. 横向必测专项

- AgentTeams create / assign / reassign / close / restart，Captain handoff 与跨 session 恢复；
- DSH 工具真实 Schema、额外字段拒绝、缺 `assignee`、Captain 被错误赋工作、maxMembers 限制；
- 429（100 次/10 分钟，现场观测）与 502/STREAM_CLOSED；限速、checkpoint、模型切换、新 Attempt；
- `GATE_STAGE_MISMATCH`、`AUTH_ARTIFACT_NOT_R1_RECORDABLE`、`evidence_refs` 必填及正确上游修复；
- BSK_AUTO_START=0 / daemon 状态、BSK 0.4.1 能力兼容、浏览器写租约冲突、4A 真实登录；
- N1-N10 状态和 R1 数量按时间变化（不可只以团队窗口文字输出推断）；
- 干净解压/离线 Git Bash 启动、SOURCE_COMMIT、MCP 原生入口、R1 路径一致性。

## F. 现场问题台账（每个问题独立保存，不允许覆盖旧失败）

每个问题必须记录：
```json
{
  "issue_id": "FIELD-YYYYMMDD-序号",
  "source_commit": "<SOURCE_COMMIT>",
  "release_batch_id": "<真实值或 UNKNOWN>",
  "mission_id": "<真实值或 NOT_CREATED>",
  "node": "N1..N10 / CROSS_CUTTING",
  "layer": "L1..L7 / NA",
  "tool_name": "<真实工具名称>",
  "input_schema_version": "<真实版本或 UNKNOWN>",
  "workitem_id": "<真实值或 UNKNOWN>",
  "attempt_id": "<真实值或 UNKNOWN>",
  "error_code": "<原始>",
  "observed": "<实际结果>",
  "expected": "<验收要求>",
  "classification": "HOST_WIRING/PROVIDER/ENVIRONMENT/CAPABILITY/SCHEMA/STATE/GATE/EVIDENCE/PRODUCT/UNKNOWN",
  "evidence_refs": [],
  "r1_refs": [],
  "reproducible": "YES/NO/UNKNOWN",
  "severity": "P0/P1/P2",
  "status": "OPEN",
  "proposed_owner": "A/B/C/D/E/UNASSIGNED",
  "next_fix": "<工程修复点>",
  "retest_criterion": "<可核验条件>"
}
```

一次任务每个 N 节点至少有一行矩阵结果；若未测写原因，不得悄悄删节点：
- `CANONICAL_PASS`：NodeDelivery/NodeGate/R1/Worker/Attempt 均有真实引用；
- `CAPABILITY_ONLY`：真实能力探测，但非该 Mission 的正式 PASS；
- `BLOCKED_UPSTREAM` / `BLOCKED_ENVIRONMENT` / `BLOCKED_PROVIDER` / `BLOCKED_HOST`；
- `FAILED` / `NOT_EXECUTED` / `UNKNOWN`。

## G. 每轮交付物

1. `field-rc72-inventory.json`：SOURCE_COMMIT、包运行入口、DSH 模型插件/工具 Schema、Team/Mission/R1/租约状态；
2. `field-rc72-node-matrix.csv`：N1-N10 全部 10 行；轨道 A 与 B 独立列；有无 R1 真证据；
3. `field-rc72-issues.jsonl`：每个失败不可变记录，去重靠根因+场景+SHA，保留复测历史；
4. `field-rc72-summary.md`：完成/阻断/未执行真实数目、L1-L7 状态、是否可继续、下一轮修复优先级；
5. 原始日志/工具回执/截图路径。不要在日志保存 4A 密码、Cookie、Token 或银行敏感明文。

## H. 必须阻断的行为

严禁：根据用户提示词虚构通过状态、手写 R1 PASS、用旧 session 内容替代 Evidence、越 Gate 强制执行 N7、产生未知副作用后直接重试、将模型 429 当作产品 BUG、在未经批准环境进行安全/性能破坏性测试、为了 92% 覆盖率生成不溯源用例、以 DSH 团队 DAG 当作自主 Mission 完成。

本计划不负责修复已存在的产品缺口；工程侧优先追踪 Issue #18（Host/C07），验收报告必须与代码 PR/同 HEAD CI/行内 Field 实证交叉核对。
