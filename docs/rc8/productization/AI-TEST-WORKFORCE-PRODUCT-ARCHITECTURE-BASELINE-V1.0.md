# RC8.0 AI 测试数字员工产品化架构基线 V1.0

> 冻结日期：2026-11-08
> 状态：DESIGN_FROZEN / REVIEW_PENDING / IMPLEMENTATION_NOT_AUTHORIZED_BY_THIS_DOC
> 冻结范围：产品边界、架构原则、RC7.2→RC8 能力迁移策略及验收门禁
> 基线来源：work/rc8 @ ad75969a368cbc1762b1d6bc77cc31cfe49708b3；work/rc7.2 @ d4981d3a925e71fe876bfbe42b813b9e077bf725
> 设计性质：独立产品化冻结候选；不覆盖 docs/rc8/N1-N10-CONSTRUCTION-PLAN.md、既有 RC8 冻结架构、RC7.2 冻结合同或当前施工状态；PR 经审查后才进入 RC8 主线。冻结设计不等于功能完成、工程验收或 BANK_REALITY_VERIFIED。

## 1. 关键决策（冻结）

1. **RC8 是最终唯一自主测试运行架构**：Center 是唯一正式任务状态、资源分配与确定性质量门禁权威；不存在双 Mission 状态机或第二套终态判定系统。
2. **RC7.2 是能力来源，不是并行运行的第二套产品内核**。按能力迁移，而非整分支 merge；优先提取经过验证的工具、技能、适配器、数据/失败恢复算法和合同测试。所有重叠的 N1–N10 调度、NodeGate、R1、状态机以 RC8 为准。
3. **WeKnora 用作知识服务、文档管理、检索和产品前端能力来源**，不得直接接管测试 Mission 生命周期；其自有 Agent/自动化不能将测试状态写成 RC8 PASS。
4. **teibto-browser-qa 是 L4/L5 专业执行器候选，BrowserSkill 是浏览器驱动**。统一 BrowserBroker / BrowserLease；任何时刻同一浏览器资源只允许一个有效写拥有者。无有效断言不得 PASS。
5. **L1–L7 是可插拔专业执行能力**，不能等同于 N1–N10；N1–N10 是任务语义和收敛流程，L1–L7 是测试层级。
6. **现在即可启动低耦合能力对接，但不得提前宣称完成合入或银行正式可用**。核心 N8/N9/N10 机制与生产运行态的融合必须经过 RC8 单节点真实闭环证明和迁移专项验证。
7. **不以“RC7.2 全部修完”作为 RC8 集成的总前置条件；以单项能力准入门禁替代总等待**。仍需保证 RC7.2 独立修复、验证和离线包的施工主线不被破坏。
8. 只允许通过显式证据判定验收，不做主观完成率，不以 CI/Mock/页面展示冒充行内实测。

## 2. 产品目标及功能边界

定位：面向银行金融科技的自主测试数字员工平台；以投产批次 ReleaseBatch 为业务入口，支持自然语言发起、专业测试资产管理、真实执行、失败诊断、缺陷修复回归和投产质量结论。

产品中心：
- AI 测试工作台（创建/暂停/恢复 Mission、观察 Worker、Human Gate）
- 项目/版本/投产批次与需求/SST 中心
- 知识中心（WeKnora 需求、设计、测试规范、历史缺陷）
- 代码影响分析中心（CodeGraph、页面-接口-代码-数据库可核验关系）
- 测试资产中心（TestObligation、TestCase、DataRef、Journey、Review）
- 测试执行中心（N1–N10、AgentTeams、Attempt、Evidence Viewer）
- 缺陷、回归、覆盖率及质量报告中心
- 工具、模型、执行节点、租约、离线包与权限管理中心

统一链路：
ReleaseBatch → Requirement → SST → TestObligation → TestCase → ETU → WorkItem → Attempt → Tool/Skill → Evidence → R1 + PostgreSQL → Director review → Center deterministic gate → N10 convergence。

逻辑运行链：
Mission → MissionNode(N1–N10) → Stage → WorkItem → Attempt → ExecutionNode/dsh-node → dsh-agent-team → Agent → Tool/Skill → Evidence。

明确：MissionNode ≠ ExecutionNode；Role ≠ Session；AgentTeams 只是执行底座，不能替代 Mission 状态机。Director 负责协调审查，不执行领域测试。

## 3. 目标技术架构

- 门户/交互：统一中文工作台，基于 WeKnora 前端能力扩展；RC8 Product API/BFF 仅聚合，不持有第二套任务真相。
- 知识服务：WeKnora 文档解析、检索、引用来源；N2/N3/N4/N8 调用 Knowledge Adapter。模型相关知识处理在银行允许的办公 PC 模型通道进行；不得假设服务端有可用模型/Embedding。
- 控制面：RC8 Center 的调度、SufficiencyGate、GapRouter、CapabilityBroker、ResourceLease、正式缺陷与投产收敛判断；无 AI 依赖。
- 执行面：DSH Director / Agent Teams / Fresh Worker / 专业 Tool Adapter；Worker 的权限最小化并经签名租约授权。
- L1：JUnit + Mockito，候选 EvoSuite / PIT；L2：Spring Boot Test + WireMock，按环境使用 Testcontainers；L3：Karate + Schemathesis，按能力评估 Keploy。
- L4/L5：BrowserSkill + teibto-browser-qa + RC8 Journey Teaching / Replay；不得把 teibto 自带的浏览器检查分类误作 L1–L7。
- L6：JMeter / k6 + Prometheus/Grafana（正式压测需资源审批与负载阈值）；L7：ZAP / Semgrep / Nuclei / Trivy / Dependency-Check（必须授权扫描范围、限制速率和危险动作）。
- 真实资产：R1 事件是运行事实；PostgreSQL 是持久化事实；Redis 只用于协调；证据落对象/文件存储，统一内容摘要、来源和身份连续性。

## 4. RC7.2 → RC8 分批迁移矩阵（冻结）

| 批次 | 可迁移能力 | 前置条件 | 合入定义 |
| --- | --- | --- | --- |
| M0 立即 | 4A、CodeGraph、CAT、TDSQL、Libra、部署/接口路由、BSK 已有 Tool/Skill 的适配封装；WeKnora 检索 Adapter；专业执行框架 Adapter 骨架 | 能力/版本探测、协议合同测试、权限边界；不得直接写正式 PASS | 仅迁入隔离分支、适配器和测试；未验收功能默认关闭 |
| M1 专项修复完成 | C06 资源/Browser 排他、C07 AgentTeams 会话/权限/故障接管、C09 Journey/BSK 正式消费、C10 模型经济 | 对应 C 项当前 HEAD CI、负面/恢复测试和产品入口证据；兼容 RC8 的资源租约和 Agent 角色；行内专属边界保留 FIELD_PENDING | 可在 RC8 按能力开关进行集成验证，不能直接宣称银行可用 |
| M2 核心运行证明后 | C01/C02 N5/N6 修复与重执行机制、C03 N8 语义回边、C04 N9 缺陷复现/回归、C05 N10 收敛、C08 产品入口全链路 | RC8 SINGLE_NODE 生产 claim/lease 驱动冻结 15 个真实 Stage Worker，产生无预置 Attempt/Artifact/R1 证据；迁移专项失败/恢复/幂等测试通过 | 只移植不重复 RC8 已有的核心算法和验证用例；正式状态/门禁由 RC8 Center 唯一拥有 |
| M3 发布准入 | C11 完整设计到代码对账、C12 离线包与 Windows/Linux 资格验证、行内真实工具与任务证据 | RC8 DISTRIBUTED 验证、银行真实 4A/BSK/CodeGraph/CAT/DB/DSH、原有回归、证据身份贯通；未解除 HOLD 前不得宣称正式版 | 正式启用能力、旧实现有序退役并完成发布验收 |

重要区别：
- **代码候选迁入 ≠ 生产功能开启 ≠ 工程验收 ≠ 行内验证通过。**
- M0 可以与 RC7.2 的 P0/P1 修复并行。
- M1 必须按 C 项逐项验证，不等待其他未相关 C 项。
- M2 的核心算法如果 RC8 已具有等价且更严的生产实现，则只导入 RC7.2 测试、证明和缺失的边界，不导入第二套相同服务。
- M3 是正式产品可用条件，而非启动产品开发的条件。

## 5. 合并冲突处理与单一权威

以现有 RC8 语义合同和数据库真相为最高优先级。针对每项 RC7.2 变更必须完成：
1. 建立能力与条款双向对账：来源路径/commit、目标路径、所需数据变更、影响 N 节点、C 项/CT 编号、风险；
2. 标注状态：NOT_IMPLEMENTED / COMPONENT_TESTED / PRODUCT_INTEGRATED / ENGINEERING_VERIFIED / FIELD_PENDING / FIELD_VERIFIED / BLOCKED；
3. 单独 Adapter PR，独立的单测、契约、端到端失败/恢复测试；禁止在一个 PR 中捆绑多项状态机替换；
4. 如果修改 Mission、NodeGate、R1、WorkItem/Attempt、lease 语义，必须先修订正式合同并走架构审查；
5. 不得在 Actor/Worker 层自行裁决最终 PASS，不得仅基于工具退出码或 AI 文本升级任务状态；
6. 失败/重试必须保留原 WorkItem/ETU、历史 Attempt、全部证据和覆盖分母。产品断言失败不得静默重试成绿灯。

## 6. 专业引擎统一执行合同

RC8 定义平台自己的能力接口，不直接依赖任一引擎的文件格式：
- probe / prepare / compile / execute / collect / evaluate / cleanup / recover
- 输入至少含 mission_id、mission_node_id、workitem_id、attempt_id、case_id、test_level、tool_capabilities、preconditions、DataRef、AuthRef、BrowserLease、required_evidence；
- 输出至少含 execution_status、assertion_results、failure_classification、artifact_manifest、evidence_refs、source_hash、tool_version、observed_times、cleanup_outcome；
- L6 必须记录负载模型、阈值、采样区间和环境资源限制；L7 必须记录授权 Scope、模板/规则版本及验证状态，扫描发现不是自动确证的产品 Defect。
- 工具原始日志与证据完整保存，RC8 仅做可信映射，禁止“猜成功”。

## 7. 行内部署与离线交付

- 测试服务器 Docker：RC8 Center、统一门户/API、WeKnora 非模型知识能力、PostgreSQL/R1、Redis、证据存储。
- 办公 PC Windows + Git Bash：DSH / 模型连接 / AgentTeams / Director / BSK / 4A / 需要模型的知识推理。必须支持冷启动、无管理员安装、缺失依赖 fail-fast。
- Windows / 信创 Linux 执行节点：L1–L7 所需的确定性工具；按能力注册调度，无公网安装依赖；统一 shell 启动（Windows 通过 Git Bash）。
- 中央包仓库：版本/OS/CPU/能力清单、SHA 校验、离线依赖、兼容探测、启动自检、升级回滚与日志导出。
- WeKnora 依赖/数据库扩展、Embedding 服务可达性、Java/Maven 离线仓库、BSK/Chromium 离线资源和安全扫描规则/漏洞数据库刷新机制都需要明确资格检查。

## 8. 实施顺序和门禁（不得用日期替代）

P0：RC8 生产驱动 SINGLE_NODE N1–N10 实际完整闭环与证据证明；并行完成 M0 适配层和一个真实 SST 的只读知识链路。
P1：单 SST 的 WeKnora → N2/N3/N4 → L3 Karate + L4 BSK/teibto → Evidence → N8/N9/N10 纵向可核验链路；M1 专项迁移。
P2：版本/投产批次级 L1–L5、Journey Teaching、用例充分度、缺陷复现回归、Libra 反馈；具备恢复和语义回边的真实证明。
P3：L6/L7、分布式、多执行节点、负载/扫描授权与隔离、监控/安全规则离线治理。
P4：完整中文产品体验、同源全量回归、Windows/信创 Linux 冷解压、真实行内验收、版本发布/回滚。

每批至少要有：
- 需求/SST/Obligation/Case → WorkItem/Attempt → Evidence 贯通；
- 真实工具调用和业务断言；负面、异常、故障注入及冷恢复；
- 最新目标 HEAD 对应的测试和 CI，防止旧 HEAD PASS 冒充；
- 等价或改善原 RC8 真相约束，不缩小测试分母；
- 独立验收结论，未达到的字段维持 UNKNOWN / FIELD_PENDING。

## 9. Release Gate 与试点验收

首个试点：PCC 一个真实 SST，至少包括正向可通过、负向可确认、环境/数据故障、产品缺陷复现与回归、一次 Session/Worker 重启接管。不能用模拟数据库/浏览器/工具结果宣称银行通过。

正式版本试点：覆盖该投产批次完整需求/SST/义务分母，按适用性执行 L1–L7；Libra 增量覆盖率可设置 92% 目标，但覆盖率不替代业务 Oracle、设计充分度、缺陷闭环和环境真实性；0/0 不算 100%。

N10 必须分别输出测试充分度、产品质量、投产建议，不因生成报告、Token 经济目标或模型主观结论自动收敛。

## 10. 本次冻结不改变的工程事实

- work/rc7.2 的 C01–C12 仍按 docs/rc7.2/10-DESIGN-IMPLEMENTATION-CLOSURE-CONTRACT.md 验证；此架构文件不宣布任何 C 项完成。
- work/rc8 的 docs/rc8/N1-N10-CONSTRUCTION-PLAN.md 当时仍为 SINGLE_NODE N1–N10 full-loop NOT_PROVEN、DISTRIBUTED NOT_PROVEN、BANK_REALITY_VERIFIED=NO、RELEASE_READY=HOLD；本文件不改变这些状态。
- 本文件冻结的是集成政策与目标架构，工程与行内事实必须每次从最新 Git/HEAD/CI/R1/Evidence 重新判断。
- 产品化基线的实质性更改须独立设计 PR、注明原因/兼容方案/测试影响，不允许在施工中通过聊天口头变更。

## 11. 第一批行动清单

1. 新建产品化能力清单与来源/目标文件映射，按 M0/M1/M2/M3 标注 Gate；
2. 编写 WeKnora Knowledge Adapter 与 teibto/BSK Browser QA Adapter 契约测试，先不触碰 RC8 Mission/R1 核心；
3. 为 L1–L7 建立 probe/execute/collect/evaluate 的最小可用适配协议与失败拒绝测试；
4. RC8 主线继续证明 SINGLE_NODE 15 Stage 的生产驱动闭环；RC7.2 主线独立修复 C01–C12；
5. 先在一个真实 SST 做跨组件纵向验收，验收通过后再以能力 PR逐项纳入 RC8。

**冻结结论：现在进行 M0；M1 逐项修复逐项合入；M2 等 RC8 真实核心闭环与对应 C 项验证；M3 等真实银行验收。绝不等待 RC7.2 100% 才启动，但绝不把未验证核心整包合入。**
