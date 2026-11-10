# WB-C-W0 / A01 50 项原子功能差异与交互核对矩阵

**审查源：** A01 `work/dsh-wb-w0@5dc514c50d6ae89dcd0c606cea949dda9e0e53fc` / [WB-A01-ATOMIC-FEATURE-REGISTER.md](./WB-A01-ATOMIC-FEATURE-REGISTER.md)；上游只读参考 `naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`。**分类合计：50 = 35 O/A（其中 A=服务端候选，不能冒称原版 UI） + 15 N。**

这是从 A01 设计登记同步的 **feature_id / 类别 / 触发动作**，不是已复制的原版源码，也不是 50 项目标已经验收。逐项原版函数与 DOM 来源锚点在 A01 原文件；原版实现来源及 PolyForm Noncommercial 许可不得转入银行交付。

**W0 原创静态演示覆盖码（只反映很窄的演示行为）：**
- `NAV_ONLY` 页面入口或项目卡片演示导航；没有真实 ACL/路由服务。
- `STAGE_ONLY` 仅显示六个业务阶段标题和演示卡片；没有完整筛选/拖拽/SSE/持久状态。
- `SCOPE_MULTI_ONLY` W0 原型支持需求/系统版本/SST 多选与合法关系级联；没有 B06 复合真关联、ACL/数据库/分页与 SSE。
- `FORM_DENY_ONLY` 十个分区展示对应领域必填字段并验证输入；提交始终明确拒绝，没有创建/修改/执行/审批 API。
- `DENY_ONLY` 按钮显式拒绝缺宿主/API 情况；不能记成功操作。
- `ERROR_FENCE_ONLY` 只模拟 401/403/404/409/422/503、缺证据人审与迟到响应拒绝；不发真实 HTTP，不判真实 QA。
- `TEXT_HINT_ONLY` 搜索输入显示提示，不查询真实 Skill Catalog。
- `THEME_COLLAPSE_ONLY` 只有深浅主题与侧栏折叠；中英文切换、系统主题与雷达宽度未全实现。
- `NO_INTERACTION` 该原子项尚无可独立复核的演示交互。

以下每条**正式产品实测状态都是 NOT_RUN**。C01/C02 及后续功能全部受 W0 设计冻结、B06 等真实依赖限制；W0 Chromium 9/9 + 三截图仅能证实静态演示对应的窄范围行为。

| feature_id | A01 类别 | A01 动作／触发 | W0 演示重叠码 | 正式产品实测 |
|---|---|---|---|---|
| P01-01 | O | 打开首页待办与动态 | NO_INTERACTION | NOT_RUN |
| P01-02 | O | 点击在办项目 | NAV_ONLY | NOT_RUN |
| P01-03 | O | 点击日程/里程碑 | NO_INTERACTION | NOT_RUN |
| P01-04 | O | 点击待审批或质量风险 | NO_INTERACTION | NOT_RUN |
| P01-05 | N | 日期筛选质量概览 | NO_INTERACTION | NOT_RUN |
| P02-01 | O | 由项目与迭代进入对话 | NAV_ONLY | NOT_RUN |
| P02-02 | O | 切模型并提交 | DENY_ONLY | NOT_RUN |
| P02-03 | O | 打开旧会话与历史 | DENY_ONLY | NOT_RUN |
| P02-04 | O | 附件、Skills、Commands 操作 | NO_INTERACTION | NOT_RUN |
| P02-05 | N | 绑定项目、批次、Mission 后重启 | NO_INTERACTION | NOT_RUN |
| P03-01 | O | 看板新增/编辑项目或迭代 | DENY_ONLY | NOT_RUN |
| P03-02 | O | 查看六阶段看板及筛选 | STAGE_ONLY | NOT_RUN |
| P03-03 | O | 拖动卡片并跨窗刷新 | NO_INTERACTION | NOT_RUN |
| P03-04 | N | 将卡片拖到已发布 | NO_INTERACTION | NOT_RUN |
| P04-01 | O | 切换年/月/日 | NO_INTERACTION | NOT_RUN |
| P04-02 | O | 新增/编辑/删除日程 | DENY_ONLY | NOT_RUN |
| P04-03 | O | 查看临期与逾期 | NO_INTERACTION | NOT_RUN |
| P04-04 | N | 绑定投产日期、提测和冻结 | NO_INTERACTION | NOT_RUN |
| P05-01 | O | 分类/搜索 QA Skill | TEXT_HINT_ONLY | NOT_RUN |
| P05-02 | O | 安装选中 Skill | DENY_ONLY | NOT_RUN |
| P05-03 | O | 切换中英文说明 | NO_INTERACTION | NOT_RUN |
| P05-04 | N | 离线依赖/版本检查 | NO_INTERACTION | NOT_RUN |
| P06-01 | O | 从项目进入详情 | NAV_ONLY | NOT_RUN |
| P06-02 | O | 编辑资料/成员/本地目录 | NO_INTERACTION | NOT_RUN |
| P06-03 | O | 查看阶段时间线 | NO_INTERACTION | NOT_RUN |
| P06-04 | N | 十区统一选批次-需求-版本-SST | SCOPE_MULTI_ONLY | NOT_RUN |
| D01-01 | O | 项目概览字段、成员、风险 | FORM_DENY_ONLY | NOT_RUN |
| D01-02 | N | 批次质量摘要 | FORM_DENY_ONLY | NOT_RUN |
| D02-01 | O | 建质量任务/选来源/预览 | FORM_DENY_ONLY | NOT_RUN |
| D02-02 | O | 执行/取消/重试/回归 | FORM_DENY_ONLY | NOT_RUN |
| D02-03 | A | 测试计划版本/评审/预览入口 | FORM_DENY_ONLY | NOT_RUN |
| D02-04 | N | 展示 N1–N10/Agent Teams | FORM_DENY_ONLY | NOT_RUN |
| D03-01 | O | 维护功能及非功能要求 | FORM_DENY_ONLY | NOT_RUN |
| D03-02 | N | 展开版本和 SST | SCOPE_MULTI_ONLY | NOT_RUN |
| D04-01 | O | 编辑用例前置/步骤/预期 | FORM_DENY_ONLY | NOT_RUN |
| D04-02 | O | 由需求查看用例追踪 | FORM_DENY_ONLY | NOT_RUN |
| D04-03 | N | L1–L7/义务/充分度视图 | FORM_DENY_ONLY | NOT_RUN |
| D05-01 | O | 提交缺陷实际/预期/复现 | FORM_DENY_ONLY | NOT_RUN |
| D05-02 | N | RCA/回归/核销链 | FORM_DENY_ONLY | NOT_RUN |
| D06-01 | O | 编辑里程碑与日历联动 | FORM_DENY_ONLY | NOT_RUN |
| D07-01 | O | 查看测试计划/报告/发布说明 | FORM_DENY_ONLY | NOT_RUN |
| D07-02 | N | 批次报告与 N10 | FORM_DENY_ONLY | NOT_RUN |
| D08-01 | O | 新增/检索知识资料 | FORM_DENY_ONLY | NOT_RUN |
| D09-01 | O | 会议纪要/决议/行动项 | FORM_DENY_ONLY | NOT_RUN |
| D09-02 | N | 绑定批次与四元组 | FORM_DENY_ONLY | NOT_RUN |
| D10-01 | O | 人审需求/用例/报告/发布 | FORM_DENY_ONLY | NOT_RUN |
| D10-02 | N | NodeGate 及 Human Gate | FORM_DENY_ONLY | NOT_RUN |
| X01-01 | O | 切换中文/英文、浅/深/系统主题，调整导航或项目雷达宽度 | THEME_COLLAPSE_ONLY | NOT_RUN |
| X02-01 | O | 新建项目/迭代及父子关联 | NO_INTERACTION | NOT_RUN |
| X03-01 | N | 离线失联、Host 缺失、R1 无 Evidence、重复请求与错误 Scope | ERROR_FENCE_ONLY | NOT_RUN |

## 独立验收与未完成清单

- **有演示重叠的原子项不等于实现。** 50/50 对账、50/50 `NOT_RUN` 正式功能实测，不能将 9 个 Node 单测、页面/分区或截图数相加作为功能完成度。
- **完整操作与失败分支尚无生产证据：** P01 首页待办/通知；P02 模型/历史/附件/停止；P03 项目表单、拖拽持久化和审查发布；P04 日历增删改与闰日；P05 Skill 安装和离线许可；P06 项目资料、成员与真实 Scope；D01–D10 十区表单/API/R1 Evidence/人审；X01–X03 真实设置/项目创建/失联重放场景。
- **FG20 对账修复约束：** `tests/test_dsh_workbench_c_feature_reconciliation.mjs` 每次从 A01 源登记逐项核对 50 个 ID、O/A/N 分类、动作与 `NOT_RUN`，并做删项、错类别、假 PASS 的负例；上游新增条目必须显式重新对账，不能静默忽略。
- **FG19 并行账本冲突：** B/C 各自追加 08/09/10 尾部造成独立合并冲突；C 保留原有事实和新证据，同时将本组专属段落移到 A 账本较前的 C 区块，让 B/D/E 原有记录不被覆盖；须由 A/F 在真实 B→C→D→E merge probe 和新同源 SHA 核实，不能以文件 diff 清洁直接宣布 FG19 整体关闭。
- 当前 F #85：`REVIEWED_WITH_BLOCKERS`、`W0_NOT_FROZEN`；FG16 静态发布 DAG 已接受，FG17/18/19 仍开放，FG20 本组 CODE_FIX 需 F 重审；PolyForm Noncommercial `BLOCKED_LICENSE`，无银行 ZIP。
