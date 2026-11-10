# WB-C-W0 六页面／十分区原创产品能力对账与交互验收合同

状态：**W0_DESIGN_PROBE / NOT_W1 / NOT_F_QA**。编写基线：A 组 W0 HEAD `515f6a367bd16d3b83197fa2c89e15d63a83c4fe`；原版只读参照 `naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`（PolyForm Noncommercial 1.0.0）。**未复制原版 HTML、JS、CSS、素材或许可证规避性派生。**所有原始功能记作「原版候选／待人工复核」，不是本仓库已实现。来源锚点由 `WB-A01-ATOMIC-FEATURE-REGISTER.md` 的 50 项记录、原版 README 与中文指南、`public/index.html`、`public/app.js`、`server/routes.js` 抽象；对应源码入口并不等价于按钮真实可用，F 须逐项复核。

## 页面身份与导航

原版**五条主导航 + 从项目卡片进入的第六页面**，而非六条并列主导航：`index.html#rail` 的 `data-view=dashboard/assistant/board/calendar/skills`，`#view-project-detail` 由项目入口打开。一级页面中文名称固定：测试首页、DSH 测试对话、项目看板、日历排期、QA Skill 安装、项目详情。项目详情左侧严格保留十个分区；新增 Mission、代码影响、证据等仅作为子视图。项目业务六阶段固定「需求分析→用例设计→用例评审→执行中→缺陷回归→已发布」，**与 RC7.2 NodeGate 状态机隔离**。

## 原版页面逐个动作、表单、失败态（目标验收，而非现有实现）

| 页面 / 原版锚点 | 必须保留的可观察控件与行为 | 必测失败与并发边界 | 原创组件 / 预期数据提供者 |
|---|---|---|---|
| P01 首页 `index.html#view-dashboard`, `app.js:renderReminders/renderDashboardCases/renderMiniCalendar` | 待办/风险/项目/日程/动态；卡片进入详情，里程碑进入日期，待审批直达门禁；逾期、临期标记；最多 5 个在办卡片不等于项目总数 | 同名项目不可串项目；过期事项不能显示「已完成」；拒绝无权限项目；无来源显示未知 | `HomeOverview`, `ActionQueue`, `ProjectTile`, `AgendaStrip` → B 项目授权 / E 审批摘要 |
| P02 DSH 对话 `#view-assistant`, `loadChat/updateDshChrome/renderDshHistory/openDshCapabilities` | 项目/迭代切换；模型选择、发送/停止、历史恢复、附件、技能与命令、斜杠输入提示、工作目录、辅助策略、项目雷达 | 非插件模式显式不可用；鉴权失败/截断/断流/历史丢失；同项目 Session 绑定、跨项目不得泄漏；绝不能自建模型密钥 | `HostConversationSlot`, `HostModelPicker`, `HostHistory`, `HostCapabilities`, `ProjectRadar` → D 原生宿主 adapter |
| P03 项目看板 `#view-board`, `openNewProject/renderBoard/bindDnD` | 项目/迭代新增及父子关系、名称编号产品负责人范围、删除二次确认；类型筛选、六阶段拖拽、并发刷新/SSE；主体点击进入详情 | 未授权/重复/非法表单、拖拽冲突回退、断网/并发水位恢复；拖入「已发布」不得伪造 N10/Human Gate 或业务发布 | `StageBoard`, `ProjectEditorDialog`, `KanbanMoveGuard` → B Project / E 发布条件 |
| P04 日历 `#view-calendar`, `renderFullCalendar/openScheduleModal` | 年/月/日切换、上一月/下一月、点选日期、日程新增编辑删除、项目选择、里程碑和临期/逾期提醒 | 2 月 29 日、月界、非法业务日期、跨项目提醒、冲突/越权、保存失败回退；不能因 UTC 解析改变业务日 | `BusinessCalendar`, `ScheduleDialog`, `MilestoneMarker` → B Calendar / batch scope |
| P05 QA Skill `#view-skills`, `renderSkills/installSkill` | 目录分类/测试类型六组、关键词搜索、中英文说明来源、官网详情、一键安装、已安装状态 | 无结果、目录未配置、宿主缺失、许可证/版本/离线缺失、安装失败不标成功 | `SkillCatalog`, `SkillDetails`, `SkillInstallGuard` → D Host capability/catalog |
| P06 项目详情 `#view-project-detail`, `openProjectDetail/renderProjectDetailTabs` | 从项目进入/返回、十区导航、资料与成员编辑、文件夹、阶段时间线、DSH 对话入口；顶部**统一投产日期→需求→系统版本→SST** | 刷新/切分区 Scope 不丢；失效关联清理并告警；无数据/无权限、文件目录不可写、旧日期改期仍保留 batch_id | `ProjectDetailShell`, `BatchScopeBar`, `DetailSectionRouter`, `ProjectProfileDialog` → B06 Scope + B Project |

### 项目详情十个分区：操作／表单／异常／组件

| 分区 | 原始能力（输入与动作） | 新增子视图（不取代原分区） | 验收禁错与原创组件 |
|---|---|---|---|
| D01 项目概览 | 项目编号/产品/负责人/成员/摘要/阶段/策略、进度/风险及编辑保存 | 真实批次质量摘要 | `ProjectOverview`、`ProjectProfileForm`；ACL 失败不可局部泄漏、无 R1 = 未知 |
| D02 质量任务 | 任务新增、来源快照/验收标准/风险决定/范围评审、执行配置、预览/运行/取消/重试、证据、故障/回归、质量摘要 | N1–N10、Agent Teams、资源/证据/诊断 | `QualityTaskPanel`, `ExecutionConfigForm`, `EvidenceViewer`；原版部分测试计划版本/评审/预览**仅服务端 API、没有相应完整 UI**；不得补造原版 UI；无 source/adapter 禁运行，重试保留旧 Attempt |
| D03 需求 | 功能/非功能类型、业务风险、验收标准、关联用例、编辑/查询 | BR/SR/TR、系统版本/SST 结构、代码影响 | `RequirementTree`, `RequirementEditor`；同需求多个版本，未拆分=待拆分，缺业务 Oracle 标记未就绪 |
| D04 测试用例 | 类型/优先级/前置/步骤/预期/状态/追踪/风险标签、审核 | L1–L7、测试义务与充分度、数据子页 | `CaseTable`, `CaseEditor`, `TraceMatrix`；无明确预期不可标真 PASS，同用例跨 SST 不重复记 Attempt |
| D05 缺陷 | 环境、严重度、复现步骤、期望/实际、频率、影响、状态修改 | 独立复现、RCA、修复回归 | `DefectForm`, `ReproductionTimeline`；无复现不得关单，原失败永不被回写为通过 |
| D06 里程碑 | 新增/编辑/删除里程碑、日期与状态、日历跳转 | 与投产业务日关联 | `MilestoneEditor`; 逾期/日期冲突提示，跨项目无权 |
| D07 报告 | 测试计划/报告/发布说明草稿、保存、版本审阅 | 批次分母分子和 N10 | `VersionedReportEditor`, `ReportEvidenceMap`；无 Evidence 不得显示「完整报告」 |
| D08 知识 | 知识条目新增/检索、来源/更新时间 | 需求/代码/API/DB/CAT 知识索引 | `KnowledgeSearch`, `KnowledgeEditor`；ACL/来源不可缺，跨项目检索拒绝 |
| D09 会议纪要 | 纪要、决议、行动项、责任人、日期/状态 | 与四元组的合法业务关联 | `MinutesEditor`, `ActionItemList`；未授权决议修改拒绝；改期不得断历史链 |
| D10 门禁 | 需求/策略/用例/报告/发布/结项审批、通过/驳回、理由/人/时间 | R1 NodeGate 只读映射与 Human Gate | `HumanReviewQueue`, `NodeGateTruthPanel`；原 QA WARN ≠ NodeGate PASS；HUMAN_GATE/BLOCKED/STALE 不可强制通过 |

## 全局交互与错误分支（必须覆盖，不能只跑 Happy Path）

`index.html#global-search` 的项目/需求/缺陷搜索、键盘入口；设置、版本信息弹窗与变更记录；中文默认及完整语言模式（当前产品正式要求全部中文）；浅色/深色/系统主题；主导航、项目栏、雷达折叠/拖动边界/双击复位；宽屏/390px 窄屏；项目抽屉与完整详情；项目/迭代父子关系与本地八类工作目录；DSH Host 失联、取消执行、重复提交、旧数据、0 结果、401/403/404/409/422/503。原版 SSE 是**同机多窗口同步**，不代表跨机器协作。所有成功/失败都需 toast 或区域内反馈并保留正式 error_code；禁将按钮点击、HTTP 200、模型计划、DISPATCHED 认作 PASS。

## Scope 设计与调用（B06 才是权威生产实现）

```text
ProjectDetailShell
  BatchScopeProvider(project_id, stable batch_id, release_date, relation_revision)
    BatchScopeBar(投产日期→需求→系统版本→SST)
       └─ useWorkbenchScope() [项目/批次/需求版本SST ID 数组; 版本由 system_version_id 区分]
          └─ ten SectionPanels read the SAME immutable snapshot+query-key
```

- 选择日期：仅 `GET /api/workbench/v1/projects/{project_id}/release-dates` 可发现；解析 `GET .../release-dates/{yyyy-mm-dd}/scope` 返回批次 `batch_id`、`relation_revision`、合法复合关联、`as_of`、授权/来源、空项/UNSPLIT；业务时区批准前不得自行按浏览器 UTC 归算。
- 联动：需求→**关联到该需求的**系统版本→**该需求+该系统版本**的 SST，切换项目/日期强制复位，不作 ID 或名称笛卡尔积；筛选上下文在十个分区只保存一次，查询 key = `principal/project/batch/selected IDs/relation_revision/access_scope_revision/truth_revision`。
- 请求服务端重验主体+Scope，授权优先：403 不泄露存在性，合法主体不存在 404，非法复合关系 422，修订/幂等冲突 409，R1 不可用 503 显示「来源暂不可用」而非零成功。事件端 `GET /api/workbench/v1/events` 必须项目+批次+权限水位绑定；切换清除旧 SSE、过期响应不得覆盖新选择。
- 详情非 R1 领域数据用 B 业务 API；Mission/Attempt/Evidence/NodeGate 通过 E 的 R1 查询，命令走服务端验证的正式控制面。C 不从 UI 发送自报 principal/authorization，不提供 publish/NodeGate 强制 PASS。
- 设计 API 目前均**未实施**。`rc7_admin` 旧 API 不等同新接口。正式 C02 的入口以 WB-B06 实际签收的分页 Scope API 为唯一来源，不依赖静态 mock。

## W0 可行性工件与承诺边界

`tools/dsh_workbench/ui_w0_prototype/` 提供**独立原创、离线静态**的六页面导航/十区切换/业务日选择/关系联动/错误反馈草模；所有数据显著标「演示」，不可进入 RC7.2 运行内核或银行交付。`scope.mjs` 是纯数据规约实验，**不是 ACL、数据库事务、真实 SSE 或复合外键**；交互按钮只报「未接入」，不伪造安装/执行/人审。正式 W1 状态仍 `WB-C01=TODO`、`WB-C02=TODO`，其后 C03/C04/C05 受既有 DAG 约束，C06 须等待 E02 和 C04。

F 独立核销时逐 `feature_id` 记录：上游 SHA+入口、目标源 SHA、动作+输入、项目/日期、真实响应/网络追踪、交互正反向、截图、服务端审计/R1 引用、实际结果、Reviewer、时间。**W0 静态原型的单元测试通过，不代替任何正式产品 QA_PASS。**

## F 组 2026-11-09 FG20 复验整改（50 项同源差异矩阵）
- 固定 `A01@5dc514c` 50 项，35 O/A 候选 + 15 N 新增，与本组 [50 项差异矩阵](./WB-C-W0-50-FEATURE-DELTA.md) 逐 ID/动作/类型对账；F #85 的 **47→50 文档不一致**已在此消除。此前提及的 47 为历史快照，不用于本轮验收。
- 所有正式产品 50 条 `NOT_RUN`；W0 demo 仅页面/十区/Scope/错误提示，C01/C02 还未满足 A/F W0 冻结及 B06 真实 API 依赖。不得由演示截图推导 50 项功能通过。
- F 独立结论 `REVIEWED_WITH_BLOCKERS`、FG19 多组账本冲突、FG18 B SST 约束反例红、FG17 全继承 CI 红均保留；本组正核销 FG20、协调 FG19 的 C 分支冲突，不自行宣布 W0 冻结。


## 2026-11-10 C 组 W0 原创交互深化（不进入 W1）
本轮针对 F 已完成的 75fd2c6 独立复核结论继续施工。F 结论仍为 REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN，故本轮只扩大 W0 原型的可行性覆盖，不启动 C01/C02。

- 统一 Scope 多选：项目详情顶部的需求、系统版本、SST 改为多选。选择集按 project_id + batch_id + requirement_id + system_version_id + sst_id 显式关系过滤，不按显示名/版本标签笛卡尔积；上级收窄后自动清除无效下级；无效多选先整体校验再提交，拒绝时不留下部分状态；query() 返回冻结快照。
- 十区表单可行性：十个分区各自展示其领域字段（项目概览/质量任务/需求/用例/缺陷/里程碑/报告/知识/会议纪要/门禁），所有必填字段有原生浏览器校验；即使字段完整，提交也 fail-closed，显示未连接正式 API、未产生任何业务写入。
- 跨区上下文一致性：每次 Scope 变化更新全部十个分区入口的同一只读快照标识；逐区切换验证同一投产日期/需求/系统版本/SST 选择不丢失。
- 证据范围：这些是原创静态 W0 演示；没有 B06 数据库/API、ACL、分页、SSE、R1、Host、Mission/Attempt/Evidence 持久化，不可记正式功能 QA_PASS。原版 PolyForm Noncommercial 源码仍零复制。
