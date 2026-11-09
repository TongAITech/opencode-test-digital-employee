# WB-A01 六主页面及项目详情十区：原子操作验收登记
状态：A_DESIGN_CANDIDATE；F_RECHECK_REQUIRED；PRODUCT_NOT_IMPLEMENTED；所有实际结果 NOT_RUN。
仅依据公开文档/界面源码抽象行为，未复制 PolyForm Noncommercial 受限代码。原版参考 naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b 的 README、中文用户指南、public/index.html、public/app.js；F 初审见 PR #85。
O=原版候选交互，需要 C/F 复核源码入口；A=原版可能仅服务端 API，禁止宣称原 UI 已有；N=本工作台新增目标。以下是待验收预期，不是已执行的实测结论。

| feature_id | 类别 | 用户动作/触发入口 | 可核验正向结果 | 必测负向/异常 | 数据真相及责任 |
|---|---|---|---|---|---|
| P01-01 | O | 打开首页待办与动态 | 项目与负责人一致 | 无权限项目不泄漏 | Project/ACL C |
| P01-02 | O | 点击在办项目 | 进入对应项目详情 | 同名项目不串页 | Project C |
| P01-03 | O | 点击日程/里程碑 | 日期/项目定位正确 | 临期/过期清楚标识 | Calendar C |
| P01-04 | O | 点击待审批或质量风险 | 关联真审批对象 | 没有审批不能伪造已办 | Review C/E |
| P01-05 | N | 日期筛选质量概览 | N1–N10 来自同个 R1 | 无真相显示 UNKNOWN | R1 E |
| P02-01 | O | 由项目与迭代进入对话 | 保持父子项目及原生会话 | 切项目不能泄露历史 | DSH Host D |
| P02-02 | O | 切模型并提交 | 实际模型响应可追溯 | 截断、限额、失败显式显示 | DSH Host D |
| P02-03 | O | 打开旧会话与历史 | 真实恢复同一会话 | 已丢失不能伪恢复 | DSH Host D |
| P02-04 | O | 附件、Skills、Commands 操作 | 宿主执行反馈一致 | 不支持/缺权限明确拒绝 | DSH Host D |
| P02-05 | N | 绑定项目、批次、Mission 后重启 | 合法 Scope 可恢复 | 失效筛选必须清理告警 | Host/R1 D/E |
| P03-01 | O | 看板新增/编辑项目或迭代 | 类型、父项目、字段保存 | 无权限/重复名称拒绝 | Project C |
| P03-02 | O | 查看六阶段看板及筛选 | 六阶段及计数可复核 | 错误筛选不返回混合卡片 | Project C |
| P03-03 | O | 拖动卡片并跨窗刷新 | 持久化状态和同步一致 | 并发冲突回退 | Project/SSE C |
| P03-04 | N | 将卡片拖到已发布 | 真 N10+人审通过才准 | BLOCKED/HUMAN_GATE 禁发布 | R1 E |
| P04-01 | O | 切换年/月/日 | 日期和事件映射正确 | 跨月、闰日边界不丢 | Calendar C |
| P04-02 | O | 新增/编辑/删除日程 | 项目授权和持久化有效 | 非法日期、冲突、越权拒绝 | Calendar C |
| P04-03 | O | 查看临期与逾期 | 告警时间及来源正确 | 跨项目提醒不得泄露 | Calendar C |
| P04-04 | N | 绑定投产日期、提测和冻结 | 统一日历业务日 | UTC/业务日期不能错一天 | ReleaseBatch B/C |
| P05-01 | O | 分类/搜索 QA Skill | 检索和目录正确 | 无结果和错误态可辨 | Catalog D |
| P05-02 | O | 安装选中 Skill | 宿主真实安装结果 | 不兼容/目录不可写不标成功 | Host D |
| P05-03 | O | 切换中英文说明 | 原文与译文来源明确 | 翻译缺失时可回源 | Catalog D/C |
| P05-04 | N | 离线依赖/版本检查 | 来源/版本/许可/哈希可见 | 缺依赖 BLOCKED | License D/F |
| P06-01 | O | 从项目进入详情 | 十区可导航、定位保留 | 返回或刷新不丢项目 | Project C |
| P06-02 | O | 编辑资料/成员/本地目录 | 保存与回读一致 | 无权限/路径错误有提示 | Project/Host C/D |
| P06-03 | O | 查看阶段时间线 | 来源与进度可追溯 | UI 不得伪造发布 | Project C |
| P06-04 | N | 十区统一选批次-需求-版本-SST | 仅合法四元组 | 同名版本/跨日期连边拒绝 | B/C |
| D01-01 | O | 项目概览字段、成员、风险 | 与项目实体一致 | 不显示无权限字段 | Project C |
| D01-02 | N | 批次质量摘要 | 与同一 R1 快照一致 | 无 R1 不显示零缺陷通过 | R1 E |
| D02-01 | O | 建质量任务/选来源/预览 | 来源及评审记录可查 | 无来源禁运行 | Quality E |
| D02-02 | O | 执行/取消/重试/回归 | 独立 Attempt 和故障证据 | 重试不覆盖旧失败 | Attempt E |
| D02-03 | A | 测试计划版本/评审/预览入口 | 原版仅 API 的场景标缺 UI | 不能把 HTTP 200 算页面实现 | Server-only F |
| D02-04 | N | 展示 N1–N10/Agent Teams | Gate、Worker 与 R1 同源 | DISPATCHED 不得 PASS | R1 E |
| D03-01 | O | 维护功能及非功能要求 | 验收标准和风险可查 | 无业务 Oracle 不算就绪 | Requirement C |
| D03-02 | N | 展开版本和 SST | 批次内关联真实 | 共享版本不共享 SST | B/C |
| D04-01 | O | 编辑用例前置/步骤/预期 | 内容及版本可查 | 缺预期不算 PASS | Case C |
| D04-02 | O | 由需求查看用例追踪 | 稳定 ID 双向链接 | 文本相似度不等于覆盖 | Trace B/C |
| D04-03 | N | L1–L7/义务/充分度视图 | 分母与 Evidence 可复算 | SKIPPED/未装工具不可通过 | R1 E |
| D05-01 | O | 提交缺陷实际/预期/复现 | 证据、影响、严重度真实 | 缺独立复现不得关闭 | Defect C/E |
| D05-02 | N | RCA/回归/核销链 | 原始失败保持不可改 | 不得原位改为 RESOLVED | Defect E |
| D06-01 | O | 编辑里程碑与日历联动 | 时间、状态一致 | 过期/冲突/越权提示 | Milestone C |
| D07-01 | O | 查看测试计划/报告/发布说明 | 版本、评审、来源时间齐 | 无证据不显示完整报告 | Report C |
| D07-02 | N | 批次报告与 N10 | 分子分母可从 R1 重算 | 缺 Evidence 禁结项 | R1 E |
| D08-01 | O | 新增/检索知识资料 | 项目权限和来源保留 | 不可跨项目检索 | Knowledge C |
| D09-01 | O | 会议纪要/决议/行动项 | 状态和责任人可追溯 | 不可越权修改决议 | Meeting C |
| D09-02 | N | 绑定批次与四元组 | 合法关联持久化 | 日期改动不断历史链 | Association B |
| D10-01 | O | 人审需求/用例/报告/发布 | 决议、理由、时间齐 | 驳回/WARN 不等于 PASS | Review E |
| D10-02 | N | NodeGate 及 Human Gate | R1 状态与 UI 一致 | NEEDS_REVISION/BLOCKED 不可 PASS | R1 E |

## 逐项 Evidence 模板与设计/实现边界
每条：feature_id, original_source_ref(文件+SHA+入口), target_source_sha, project_id, batch_id, action, precondition, expected, negative_case, actual, screenshot_ref, network_trace_ref, host_log_ref, R1_evidence_ref, result, reviewer, observed_at。
当前统一 actual=NOT_RUN、screenshot_ref=NONE、target_source_sha=NONE；原版的每个具体按钮还需 C/F 逐条核对其真实入口，缺失时标 ORIGINAL_UI_NOT_PRESENT，不可由 A 的设计候选直接转成已验收功能。
