# WB-F00 F 组独立质量审查记录（非 QA_PASS）

> 审查日期：2026-11-09；执行者：F 组独立验收；状态：**REVIEWED_WITH_BLOCKERS / W0_NOT_ACCEPTED**。
> 不得将本记录解释为 W0 冻结、生产就绪或行内现场通过。

## 1. 固定审查输入和证据链

- 仓库：`TongAITech/opencode-test-digital-employee`
- 分支：`work/dsh-wb-w0`；审查 SHA：`12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8`，GitHub branch API 与 PR #84 head SHA 一致。
- PR：<https://github.com/TongAITech/opencode-test-digital-employee/pull/84>，Draft/Open，base `work/rc7.2` @ `3de74c2bf3a0f3a555ccd979edd2832f26c9963a`；本次 diff 恰好 11 个 `docs/dsh-workbench/00–10` 文件，**没有工作台 UI/API/模型迁移实现差异**。
- 工程合同：在上述 SHA 读取 `docs/dsh-workbench/00`–`10` 全部 11 份文件、`docs/rc7.2/01-AUTONOMOUS-TEST-RUNTIME-DESIGN.md` 与 `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md` 全文。
- 原始产品基线：`naodeng/dsh-qa` tag `v0.7.3` 的 `README.md`、`LICENSE`、`package.json`；可访问的原项目 README 说明四视图前端、QA Skill 安装入口与由项目入口进入的十区详情，不应误将六个业务界面都描述为六条一级导航。
- 可选适配器：`ZSeven-W/dsh-qa` tag `v0.1.0-rc.2` 的 `LICENSE`、`package.json`；声明 MIT，Node >=24.11.0，并有若干独立驱动/适配器依赖，不能从自身 MIT 许可推断全部传递依赖均可交付。
- 现有代码审阅：`rc7_runtime/rc72_domain.py`（ReleaseBatch、N1–N10、NodeGate 等）；`rc7_runtime/rc72_linkage.py`（ETU→WorkItem/Attempt）；`rc7_admin/server.py`、`product_server.py` 和 `projection.py`。这些是原 RC7.2 代码，并非 PR #84 新增的工作台功能。
- 同 HEAD CI：GitHub `GET /repos/TongAITech/opencode-test-digital-employee/commits/12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8/check-runs?per_page=100`：检查时共 26 jobs，13 success、4 failure、9 in_progress。失败至少涉及 ABCD-v4 Windows Python 3.8、ABCD-v3 Ubuntu Python 3.8、N8 multi-round Ubuntu Python 3.8、C04 N9 Ubuntu Python 3.8。抽查三个失败日志显示 `setup-python` 获取 Python 3.8 的 HTTP 504（未到产品测试断言），**是 CI 环境阻断，不应直接记为产品缺陷，也不能记为 CI_PASS**。另有 C07 N9 fence、C10 quota 矩阵成功，仅证明这些既有子项在相应条件下通过。
- 未执行：行内 DSH 1.18.26 宿主 UI/模型/附件/技能/命令实际操作、真实投产批次数据的领域读写、Windows Git Bash 整包冷启动/无网安装、R1 实体链端到端检查；这些保持 NOT_RUN，不得外推。

**证据复核入口**：
1. <https://github.com/TongAITech/opencode-test-digital-employee/pull/84/files>
2. <https://github.com/TongAITech/opencode-test-digital-employee/blob/12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8/rc7_runtime/rc72_domain.py>
3. <https://github.com/TongAITech/opencode-test-digital-employee/blob/12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8/rc7_admin/projection.py>
4. <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42580607213/job/129038129136>
5. <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42580607283/job/129038129957>
6. <https://github.com/naodeng/dsh-qa/blob/v0.7.3/README.md>、<https://github.com/naodeng/dsh-qa/blob/v0.7.3/LICENSE>

## 2. 六大页面 / 项目详情十个分区逐项审查

以下 **CONTRACT_PRESENT** 仅表明合同提及，不表示 UI 已实现或 QA_PASS。

| 原界面 | 合同位置 | 当前结论与必须补充的原版功能细账 |
|---|---|---|
| P01 测试首页 | 00/01 | CONTRACT_PRESENT；待办/项目/日程/动态已列，但原版 Native QA Action Desk、状态分层及卡片到详情交互未做按钮级对账 |
| P02 DSH 测试对话 | 00/01/04 | CONTRACT_PRESENT；模型切换、已有会话、Skills/Commands/附件写在合同；实际 DSH 1.18.26 接管/项目迭代会话隔离未验证 |
| P03 项目看板 | 00/01/03 | CONTRACT_PRESENT；六阶段已全列；项目/迭代双形态、拖拽 SSE 同步、发布门禁及恢复回退无操作证明 |
| P04 日历排期 | 00/01 | CONTRACT_PRESENT；年/月/日切换、日期创建/删除、临期/逾期、跨项目日程等需逐按钮覆盖 |
| P05 QA Skill 安装 | 00/01 | CONTRACT_PRESENT；原版测试类型子分类、测试工作流程/加强版、中英文、目录来源、安装到原生宿主路径和失败恢复需要细账 |
| P06 项目详情 | 00/01/03 | CONTRACT_PRESENT；作为项目入口打开的详情保留 10 区；项目/迭代字段编辑、成员、文件目录、阶段时间线和本地工作目录生成等需对账 |

| 分区 | 目标存在 | 缺少的实际验收证据 |
|---|---|---|
| D01 项目概览 | 是 | 项目字段、成员、阶段时间线、批次来源指标 |
| D02 质量任务 | 是 | 来源快照/摘要、受评审计划/不可变配置、预览令牌、真实执行、取消/重试、证据及回归集 |
| D03 需求 | 是 | 需求/非功能需求/验收标准、BR/SR/TR 与关联筛选的双向交互 |
| D04 测试用例 | 是 | 前置/步骤/预期、评审、状态、追踪、版本历史、可复算义务 |
| D05 缺陷 | 是 | 事实与猜测、故障分析、独立复现、人工确认升级、回归 |
| D06 里程碑 | 是 | 日期/逾期提醒、新增删除、时间线来源 |
| D07 报告 | 是 | 报告版本链、质量计算来源、数据截至及下载 |
| D08 知识 | 是 | 本地知识材料与来源/权限/批次绑定 |
| D09 会议纪要 | 是 | 行动项、审批、需求版本 SST 关系保存/恢复 |
| D10 门禁 | 是 | 需求/策略/用例/报告/发布/结项审批及 WARN 例外约束；不得覆盖 N10/NodeGate 事实 |

原项目与本项目两层门禁不能混淆：原版质量结果 `PASS/WARN/BLOCK` 是产品呈现，本项目正式 RC7.2 `NodeGate` 为 `PASS/NEEDS_REVISION/BLOCKED/HUMAN_GATE`。应明确逐字段映射，而非将 WARN 自动映射 PASS。

## 3. 可复现审查 GAP 与具体修订要求

### WB-FG01（P0，A/C）：原版功能仅粗粒度覆盖，不具备签收证据
- **重现**：打开上述 SHA 的 `01-PAGE-FUNCTION-MATRIX.md`，核对每一行只有 TODO，无按钮/状态/CRUD/异常/数据来源/截图/自动化/验收 SHA；再与上游 README 功能特性逐项比对。PR #84 的 11 个文件均为 docs。
- **预期/观察**：预期原版能力可一一对账；实际保留了六页面十区名称，但漏验 Action Desk、迭代双形态、文件目录、受控执行、审批例外、SSE、UI 主题/宽度及 Skill 细分类。**结论：设计范围候选，不是功能漏实现的独立测试结果。**
- **修订**：A01 补 `original_feature_id → 交互 → API/来源 → 独立实现路径 → 正向/反向 Case → 截图/日志 → 结果` 完整矩阵；C01/C03/C04 实现后 F02 再实际回归。负责人 A/C/F。

### WB-FG02（P0，A/B/E）：投产日期与旧 ReleaseBatch 之间缺少确定性兼容迁移
- **重现**：比较 `02-BUSINESS-DOMAIN-CONTRACT.md` 的 `release_date`、`UNIQUE(project_id,release_date)` 与 `rc7_runtime/rc72_domain.py` `ReleaseBatch(release_batch_id, mission_id, name, planned_release_time, version_ids, requirement_ids...)`。旧模型无明确项目+业务日期唯一键。
- **预期/观察**：页面批次唯一可见身份必须是 `2026-11-12` 等日期，跨项目可同日；现有 R1 事实不能通过简单隐藏 `name` 实现关联无损升级。
- **修订**：定义银行业务时区（建议经业务方确认 `Asia/Shanghai`，不能未经批准自行确定）、`planned_release_time` 到 `release_date` 的规范转换、冲突/空日期处理、同项目同日去重、日期更改审计、历史 Attempt/Evidence 的原始批次引用、幂等前向及可回退迁移；设计正反例与迁移回滚测试。负责人 A/B/E。

### WB-FG03（P0，A/B）：多对多关系表缺复合约束/删除/并发合同
- **重现**：`02` 给出四张 batch 关联表，但没有落地唯一/外键组合、原子写入、租户范围、来源系统身份冲突及批次变更规则；`06` API 也未给完整关联 CRUD 的权威 Schema。
- **预期/观察**：同一需求 R1 可对应 V1/V2/V3 各多 SST；R1/R2 共用 V1，但各 SST 不互认；系统 A 与系统 B 的同名版本不能混同；跨 batch 的组合必须服务端拒绝，不能只有 UI 筛选。
- **修订**：A03/B05 冻结带 `batch_id` 的复合主键/外键、删除策略、事务边界、唯一身份键、permission scope、`SST` 来源 identity 与共享规则；提供 422 回滚无副作用证据；使用独立领域契约测试（见 F 组场景表）。负责人 A/B。

### WB-FG04（P0，A/B/E）：Scope 正反向查询与租户边界没有可执行授权契约
- **重现**：`06` 给出 GET 提议和错误码，但无端点授权矩阵/主体身份/批次校验先后顺序；现有 `rc7_admin/server.py` 只暴露 `/api/*` 既有资源，`projection.py` 的 `_contains()` 是文本包含匹配，不是批次内关联表 join；`_query_params` 没有 `project_id/batch_id/system_version_id`。
- **预期/观察**：跨项目返回 403、跨批次关联返回 422、无效 ID 返回 404，不产生任何 R1 写入；任意合法 filter 集合只能返回真实连边。
- **修订**：A03/B06/E01 定义 principal 来源、授权策略与拒绝优先级、stable batch ID 解析、SQL/领域 join 语义和分页排序游标；提供越权、横向穿越、字符串碰撞/同名版本/跨日期及 Scope 恢复反例。不可直接复用模糊过滤当正式关联。负责人 A/B/E。

### WB-FG05（P0，A/E）：全链路真相映射尚无结构化 ID/修订/证据规则
- **重现**：`05` 定义 ReleaseBatch→Mission→Obligation→ETU→WorkItem→Attempt→Evidence→R1 的目标；`06` 的 `/api/workbench/v1` 全部明确为“待实现”；PR 没有对应实现。旧 Admin 的 `dispatch_post` 目前只接受 `test-cases` 新建/修订/隔离。
- **预期/观察**：必须能从日期→需求→系统版本→SST→代码片段→义务→用例→执行→证据→缺陷/报告双向跳转，R1 决定显示，通过/阻断不可由前端改写。
- **修订**：A03/E01/E03 明确 `trace_link` 版本化 schema、`truth_revision`、来源时间、Evidence hash/验证结论、受控命令授权+幂等+修订冲突及事件断线续订顺序；用同一 R1 快照交叉复算全部计数。负责人 A/E/B。

### WB-FG06（P0，D/E/F）：DSH 原生会话和 Agent Teams 目标无现场证据
- **重现**：PR 无宿主面板/会话代码；`04` 是接口要求，尚无 1.18.26 实测票据。成员 8→32 目标与宿主真实可并行数尚未核对。
- **修订**：D01/D02/D03/E05 提供 DSH 1.18.26 现场版本、OS、操作步骤、截图/宿主日志；既有会话、模型切换、Skill/Commands、附件、取消、断线恢复、项目隔离；分别量化成员配置上限/实际 Worker 同时运行/模型限流及租约冲突。不能建立第二套模型密钥或会话真相。负责人 D/E/F。

### WB-FG07（BLOCKER，A/F）：受限源码许可证门禁未核销
- **重现**：`naodeng/dsh-qa@v0.7.3/package.json` 的 license = `PolyForm-Noncommercial-1.0.0`；`LICENSE` 明确只授予许可用途；PR 正文也确认未获银行商业授权。
- **修订**：保持原许可证和必要声明不删不改；A02 取得适用授权与 SBOM/复制范围核查，或者完全不复制其源码，以独立实现加来源审计交付。ZSeven-W/dsh-qa 虽单独声明 MIT，仍应核对实际文件权属及第三方依赖；Node >=24.11、离线驱动另作准入。负责人 A/F（法律意见由有权人员确认）。

### WB-FG08（P0，D/F）：Windows Git Bash 无网离线完整包尚无可重复运行证明
- **重现**：PR 中没有 Windows 打包/依赖清单/离线安装测试变化；`04` 仅写目标。现有 `packaging/rc7` 脚本存在，不意味着新增工作台可在银行 PC 免安装启动。
- **修订**：D04/F04 以新 Windows Git Bash 干净目录、断网、非管理员账号验证；记录 Node/Python/Chromium/BSK/插件/驱动版本、SHA256、许可证、启动/重启/卸载、工作目录空格/中文路径及数据恢复；任何缺依赖均 BLOCKED 而非跳过。负责人 D/F。

### WB-FG09（P0，A/F）：同 SHA CI 非全绿，不可宣称 QA_PASS
- **重现**：同 SHA 26 checks：13 success / 4 failure / 9 in_progress；典型失败日志 `Version 3.8 was not found in the local cache` 后 `Unexpected HTTP response: 504`。
- **修订**：A 区分 INFRA_SETUP_FAILURE 与产品断言失败；待环境恢复，仅对同一候选 HEAD 重跑失败分支并复核全矩阵；新增工作台自己的领域/接口/宿主测试，不可将 RC7.2 既有部分 green 借作 WB 全部 CI_PASS。负责人 A/F。

### WB-FG10（P0，A/E/F）：N1–N10 状态与原 QA 门禁的映射未完整可复核
- **重现**：`05` 文字列出 N1–N10，但未形成 `N-state + NodeDelivery + NodeGate + human approval + Evidence` 到工作台状态的枚举映射、默认拒绝矩阵和状态恢复顺序；PR 没有相应测试/实现。
- **修订**：A03/E02/E06 定义状态真值表，尤其 `BLOCKED/NEEDS_REVISION/HUMAN_GATE/STALE/INCONCLUSIVE` 不许展示通过；看板“已发布”需 N10 质量收敛与人审双条件；补 R1 断线/重复消息、篡改/失效证据、N8 back-edge 反例。负责人 A/E/F。

## 4. W0 退出条件 / 给 A 组的阻断回复

1. A01 产出基于原版完整功能的原子矩阵，并由 F 检查设计范围是否遗漏；“六页面/十区名字齐”只能视为文档层部分覆盖。
2. A03 取得 B/D/E 的领域、API、事件、鉴权、SST 源身份、R1 映射签收；特别落实 WB-FG02–05、10 的正反向契约。
3. A02 继续 **BLOCKED_LICENSE**，除非持有合法适用授权，禁止复制 naodeng 受限源码到银行交付；独立实现可在许可隔离条件下进行设计/开发。
4. A 修订 08 施工依赖状态、09 GAP 矩阵、10 checkpoint；F 的审查意见不可直接被 A 标作 QA_PASS。
5. 纠正 CI 真相；当前 4 failure + 9 in_progress，无同 SHA 全绿证明；后续实际功能实现须另有工作台的合同测试及现场证据。
6. F 对修订后的 **新 HEAD** 再做独立审核，只有满足 W0 合同签收门槛才能讨论冻结；W1–W4 真实功能的 QA_PASS 留给 F01/F02/F03/F04，不得提前分配。

## 5. 本次 QA 状态台账

| 领域 | 状态 | 说明 |
|---|---|---|
| 11 份设计合同存在 | VERIFIED_DOCUMENTS | GitHub SHA 已验证，非功能 PASS |
| 六页面十区命名覆盖 | DESIGN_PARTIAL | 已有条目，原子能力对账缺证据 |
| 领域关系契约 | DESIGN_PARTIAL | 目标多对多清楚，迁移/约束/安全待补 |
| 工作台 API/UI 运行 | NOT_RUN/NOT_IMPLEMENTED_IN_PR | PR 只改 docs；不替代既有 RC7.2 |
| DSH 宿主与 Agent Teams | NOT_RUN | 行内 1.18.26 未核验 |
| 许可证 | BLOCKED_LICENSE | PolyForm Noncommercial 授权未确认 |
| Windows Git Bash 离线 | NOT_RUN | 本审查无银行现场包 |
| 同 SHA CI | MIXED_INFRA_BLOCKED | 成功、失败、运行中混合，非 CI_PASS |
| WB-F00 | REVIEWED_WITH_BLOCKERS | **不能标记 QA_PASS** |

必填审计元数据：task_id=WB-F00；source_sha=12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8；test_command=GitHub PR/contents/branches/check-runs API、逐文件源代码与 upstream 标签读取、三个失败 job 日志复核；result=REVIEWED_WITH_BLOCKERS；evidence_ref=本文件和上述永久链接；date=2026-11-09；executor=F 组；known_limitations=无现场 Windows/宿主/实际业务数据执行、PR 只有 docs。
