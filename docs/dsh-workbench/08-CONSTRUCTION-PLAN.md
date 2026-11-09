# DSH 工作台 — 施工总账与依赖计划
状态：W0-IN_PROGRESS；只在 GitHub 当前 HEAD/PR/CI/Evidence 核实后更新，不以聊天记忆为准
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
| WB-F00 | F | W0 设计审查、补反例与独立签收 | WB-A01,A03 | TODO |

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
- 当前同 HEAD CI 状态尚未验证为通过；严禁写 CI_PASS。

## 当前唯一合理下一步
A 完成 WB-A00 的 PR 创建并交由 F 审阅合同；A/B/C/D/E 不能在合同未冻结前把未批准的业务接口当成既有事实。B 的 WB-B01 至少等 API/领域约束明确后再开始，C 可以先调查原始 UI 功能但不得复制未授权代码。

## 2026-11-09 A 组现场 GitHub 审计/施工证据
WB-A00：PR #84 OPEN DRAFT、base=work/rc7.2、head=work/dsh-wb-w0、11 文档原始 HEAD 12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8 存在；F 尚无 Review。只能核销提交产物，不能 CLOSED。
WB-A01：01 文件新增源 upstream commit fc5a054a48973d004580a3cc1de60da3f701150b 与 27 项页面/分区/交互候选，需 F 逐条验收。实际新 UI 未实施。
WB-A02：原创许可证/manifest/哈希门禁与契约测试提交 4046029591b0b324e6a33028629dc22034d511d0，代码通知路径修复 82c18fdd93867e7d27107f665e124c5edcae8b2c。无商业授权；源代码溯源仍需 F/法务审阅，正式 Windows 包流水线尚未接入该门禁。
WB-A03：06 增量接口设计、身份/幂等/流式事件/迁移反例，B/D/E/F 未签收，实际 /api/workbench/v1 不存在。
运行命令：python -m unittest discover -s tests -p 'test_dsh_workbench_w0.py' -v。首轮同 HEAD run 42582069489 执行 32 tests，30 OK、1 FAIL、1 ERROR；许可证通知路径比较方向反、01 缺原版源码 SHA 两项已定位并修订。只有新 HEAD CI 成功才能写 CI_PASS。
所有功能仍不得宣称 field PASS；WB-B01/C01/E01 等依赖未满足任务不能启动，D01 只可做调查。F 独立审查与授权门禁前不 W0 冻结，不合入 work/rc7.2，也不重复打包全量 ZIP。
