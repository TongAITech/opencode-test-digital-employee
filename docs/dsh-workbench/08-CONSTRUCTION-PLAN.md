# DSH 工作台 — 施工总账与依赖计划
状态：W0-IN_PROGRESS / F_INITIAL_REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN；状态必须随 GitHub 新 HEAD 重验
首次基线 RC7.2 work/rc7.2 @ 3de74c2bf3a0f3a555ccd979edd2832f26c9963a
本次分支 work/dsh-wb-w0（文档施工独立分支，等待 PR 评审）

## 六组施工责任
A 总集成 work/dsh-wb-integration：设计冻结、PR 集成、依赖与合同；不可包揽全组业务编码。
B 业务模型 work/dsh-wb-domain：数据及关联、合法过滤、迁移。
C 界面 work/dsh-wb-ui：六页面/十个分区/中文交互。
D 宿主 work/dsh-wb-host：DSH 原生插件、模型、会话、技能与断线恢复。
E 运行 work/dsh-wb-runtime：RC7.2 R1、Mission、Agent Teams、BSK/Replay 适配。
F 独立验收 work/dsh-wb-qa：契约测试、真实证据与离线交付核验。
六个是工程施工会话，不是 DSH 运行队员。

## 调度规则
以工单而非聊天回合作为施工单位；每单必须有编号、owner、路径、输入、正反向测试、退出条件、PR、CI、source_sha、证据和 next_action。
状态 TODO→IN_PROGRESS→CODE_COMPLETE→CI_PASS→QA_PASS→MERGED→CLOSED；阻断记录 BLOCKED+reason，不能伪关闭。
B/C/D/E 并行但不得越权改他组文件；A 维护接口变更单及依赖。F 独立验收。
每单局部测试，轮次末进行一次集成回归；仅候选交付点构建完整 Windows ZIP。
每个新会话第一步重新读取分支 HEAD、最近 commits、同 HEAD CI、08/09/10 账本及对应合同；接管下一个 ready 工单，不读旧会话凑状态。

## W0 — 设计冻结与前置调查
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-A00 | A | 本目录合同首次提交、建立 W0 PR | 无 | CODE_COMPLETE / PR_VERIFIED / F_PENDING（不关闭） |
| WB-A01 | A | 原版能力范围对账并冻结功能清单 | WB-A00 | CODE_COMPLETE_CANDIDATE / F_PENDING（未冻结） |
| WB-A02 | A | 许可证/商业授权与源码复用方式确认 | WB-A00 | BLOCKED_LICENSE（仍需权利人书面授权或独立实现） |
| WB-A03 | A | API/事件/数据迁移合同跨组评审 | WB-A00 | IN_PROGRESS（契约+负向测试，跨组未签） |
| WB-F00 | F | W0 初审及新 HEAD 独立复验 | WB-A01,A03 | F_INITIAL_REVIEWED_WITH_BLOCKERS；FG11/12 CONTRACT_CI_PASS；最终复验待完成 |

## W1 — 最小真实业务纵向链路
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-B01 | B | 投产日期与唯一性/变更历史 | A03 | TODO |
| WB-B02 | B | 系统/系统版本规范对象 | A03 | TODO |
| WB-B03 | B | 批次-需求/批次-版本关系 | B01,B02 | TODO |
| WB-B04 | B | 需求-版本多对多合法关系 | B03 | TODO |
| WB-B05 | B | 需求-版本-SST 关联及错误阻断 | B04 | TODO |
| WB-B06 | B | 跨分区 Scope 关联查询与分页 | B05 | TODO |
| WB-C01 | C | 六页面/十分区不缺失的导航骨架 | A01 | TODO |
| WB-C02 | C | 项目详情投产日期/需求/版本/SST 联动 | B06,C01 | TODO |
| WB-D01 | D | DSH 宿主版本/面板真实兼容性探测 | A00 | TODO |
| WB-E01 | E | RC7.2 R1 只读 Scope 与 Evidence 适配 | B06 | TODO |
| WB-F01 | F | 真实日期、跨版本、多 SST 纵向核验 | C02,D01,E01 | TODO |

## W2 — 保留原能力与资产增强
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-C03 | C | 首页/看板/日历/技能页面完整对账 | C01 | TODO |
| WB-C04 | C | 十分区信息与资产表单完整对账 | C01 | TODO |
| WB-C05 | C | 中文/主题/搜索/响应式/可访问性 | C03,C04 | TODO |
| WB-B07 | B | 用例/义务/缺陷/报告追踪规范化 | B05 | TODO |
| WB-B08 | B | 历史数据兼容和可逆迁移 | B07 | TODO |
| WB-D02 | D | DSH 原生模型/Skills/Commands/附件 | D01 | TODO |
| WB-D03 | D | 项目会话+批次 Mission 绑定与恢复 | D02,B01 | TODO |
| WB-F02 | F | 原版能力矩阵逐项回归与反例核销 | C05,B08,D03 | TODO |

## W3 — 自主测试闭环
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-E02 | E | Mission 查询、N1–N10 可视状态 | E01 | TODO |
| WB-E03 | E | 带幂等键和权限门禁的正式控制 API | E02 | TODO |
| WB-E04 | E | ETU/WorkItem/Attempt 实时执行监控 | E03 | TODO |
| WB-E05 | E | Agent Teams/租约/并发上限探测和恢复 | E04,D03 | TODO |
| WB-E06 | E | Evidence/缺陷回归/N10 收敛事实映射 | E04,B07 | TODO |
| WB-C06 | C | 质量任务内自主编排/诊断/证据子视图 | E02,C04 | TODO |
| WB-F03 | F | 一次真实批次闭环/假 PASS 反例/重启接管 | E05,E06,C06 | TODO |

## W4 — 可选执行增强与最终交付
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-E07 | E | ZSeven QA 可选 Replay 及 BSK 互斥 | E05 | TODO |
| WB-D04 | D | Windows Git Bash 免安装依赖和诊断 | D03 | TODO |
| WB-F04 | F | 离线安装/重启/恢复/证据与 SHA 验收 | F03,D04 | TODO |
| WB-A04 | A | 最终集成、版本对账、RC8 契约移交 | F04 | TODO |

## W0 实际进度
- 合同：11 份已提交在 work/dsh-wb-w0；草稿 PR #84 已开启，目标 work/rc7.2。
- 实际工单总数：35；WB-A00 代码/文档提交完成，但不代表 W0 签收，F 审查和授权门禁仍未关闭。
- fd9e60e 同 HEAD 28/28 checks 成功及 W0 32/32 已经核实；3fc09ca 的 W0 定向 CI 38/38 成功，后续 HEAD 必须另查。只认可对应源 SHA 的结果，不能写产品 QA_PASS。

## 当前唯一合理下一步
A 吸收 F 初审完成 A01 原子功能登记、A03 跨组签收合同、A02 原创许可路线；B/D/E 审查后签收接口字段，F 复核整改新 HEAD。未获批准的依赖任务不能进入正式 W1，C 可调查/原创设计，不得复制受限源码。

## 2026-11-09 A 组现场 GitHub 审计/施工证据
WB-A00：PR #84 OPEN DRAFT、base=work/rc7.2、head=work/dsh-wb-w0、11 文档原始 HEAD 12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8 存在；F 已通过 PR #84 评论及 PR #85 完成初审（因同一 GitHub 账号无法向自己的 PR 提交 GitHub 正式 REQUEST_CHANGES Review）。只能核销提交产物，不能 CLOSED。
WB-A01：01 文件新增源 upstream commit fc5a054a48973d004580a3cc1de60da3f701150b 与 27 项页面/分区/交互候选，需 F 逐条验收。实际新 UI 未实施。
WB-A02：原创许可证/manifest/哈希门禁与契约测试提交 4046029591b0b324e6a33028629dc22034d511d0，代码通知路径修复 82c18fdd93867e7d27107f665e124c5edcae8b2c。无商业授权；源代码溯源仍需 F/法务审阅，正式 Windows 包流水线尚未接入该门禁。
WB-A03：06 增量接口设计、身份/幂等/流式事件/迁移反例，B/D/E/F 未签收，实际 /api/workbench/v1 不存在。
运行命令：python -m unittest discover -s tests -p 'test_dsh_workbench_w0.py' -v。首轮同 HEAD run 42582069489 执行 32 tests，30 OK、1 FAIL、1 ERROR；许可证通知路径比较方向反、01 缺原版源码 SHA 两项已定位并修订。只有新 HEAD CI 成功才能写 CI_PASS。
所有功能仍不得宣称 field PASS；WB-B01/C01/E01 等依赖未满足工单不能作为正式 W1 启动，D01 只可做调查。F 对新 HEAD 再审、B/D/E 合同签收及合规路线确认前不 W0 冻结，不合入 work/rc7.2，也不重复打包全量 ZIP。

## 2026-11-09 A 组施工收口增量（最新事实覆盖历史 TODO）
- F 初审 PR #85：https://github.com/TongAITech/opencode-test-digital-employee/pull/85；F 针对 A HEAD fd9e60e 发布了 [独立复核评论](https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6736506135)。结论 WB-F00=F_INITIAL_REVIEWED_WITH_BLOCKERS / W0_NOT_ACCEPTED。FG11、FG12 在契约 CI 层核销；FG01–10、FG13–14 仍按 F 分类 OPEN/NOT_RUN/BLOCKED。
- 旧 HEAD fd9e60e：同 SHA **28/28 GitHub Checks SUCCESS**、两次 W0 定向 **32/32**；本轮代码加固 3fc09ca：W0 定向 CI **38/38 SUCCESS**（https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42595773766/job/129087916062）。此处仅为指定 SHA 已验证历史；本次新文档 HEAD 仍需同 SHA check-runs。
- WB-A01 新增 WB-A01-ATOMIC-FEATURE-REGISTER.md，覆盖六页十区逐原子正反向验收定义、来源/动作/证据模板；全为 TARGET_NOT_IMPLEMENTED / NOT_RUN，F 设计完整性待复核。
- WB-A02 新增 WB-A02-LICENSE-BOUNDARY.md，明确可审计原创实现 + SBOM/许可证/人工审批，不复制 naodeng PolyForm Noncommercial 源码；保持 BLOCKED_LICENSE，staging gate 尚未接正式打包。
- WB-A03 新增 WB-A03-CROSS-GROUP-SIGNOFF.md，02/06 同步迁移、复合外键、授权优先级、命令幂等、batch SSE、R1 NodeGate 真值表；**B/D/E/F 尚未签署**，真实 API/DB/SSE 未实现。
- 测试增加项目+批次事件隔离、命令 scope 拒绝和 staging 非规范路径/符号链接拒绝；只是 W0 Oracle 单测，不能代替真实 R1/SUT。
- 本次提交后：再次查询同 HEAD CI、请 B/D/E 留合同签署或异议、请 F 复查最新 HEAD；未经独立接受 W0 不冻结、不合并、不构建银行 ZIP。
