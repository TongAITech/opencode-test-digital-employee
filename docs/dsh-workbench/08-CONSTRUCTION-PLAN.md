# DSH 工作台 — 施工总账与依赖计划
状态：W0_DESIGN_FROZEN_AT_A73ED52D / W1_COMPONENTS_INTEGRATED / PRODUCT_AND_FIELD_QA_PENDING；状态必须随 GitHub 新 HEAD 重验
首次基线 RC7.2 work/rc7.2 @ 3de74c2bf3a0f3a555ccd979edd2832f26c9963a
本次分支 work/dsh-wb-w0（文档施工独立分支，等待 PR 评审）


## 当前权威状态（2026-11-11）

- 当前代码集成检查点：`73cdb971541e0fec951cbe48bb6c9988010f2262`（PR #84）；本账更新会产生新文档HEAD，实际继续前重新核对远端与同SHA checks。
- W0设计冻结源`a73ed52d`及F #121保持历史结论。已正向合入RC7.2新基线`edaf9290`，未修改主线。精确`7586a80c`的ABCD-v4完整源码/Chromium及四组Ubuntu/Windows原生资格共五job全部SUCCESS（run42847197247）；F联合报告#173。该结论不转签d31或现场Windows离线安装。
- 本轮d31本地回归：真实PostgreSQL222/222、真实PG→浏览器6/6、目录键盘/撤权3/3、Node43/43；轻量561项中269执行通过、292明确跳过。A复跑F测试不构成新独立F签署；目录修复独立F源16fe658d、报告777b8bd7（#178）已集成。
- d31远端同SHA：W0 run42859333314、真实浏览器run42859326708均SUCCESS；本次新台账HEAD另核检查，不转签旧SHA。
- 六类草稿表单、B07七kind与E02读取为组件集成；旧legacy API隔离P1、目录键盘/撤权P2已按独立报告修复。完整项目编辑、看板业务状态、正式R1资产映射及生产纵向链仍未完成；日历年月日已有PR #182组件候选，尚未独立验收/集成，不能把只读目录当项目管理全功能。
- 本轮F独立接受HTTP补丁源`47950777`（#183报告904493cf，13项实际验证）与日历源`1492a572`（#187报告3ac4d157，独立公历oracle/真实PG反例）。两组件已正向合入9642f5b2，新联合HEAD回归进行中；不得把组件接受转成整个产品QA通过。
- V2及V3早期设计P1均保留历史；V3新04ca9716由B #192、D #194及F #196接受纯组件施工，V3文档与报告已集成。仅准入纯codec/DTO/K/HOLD，正式008/锁定快照/Host/writer/typed模型仍需具体增量门禁，未修改R1正式模型。
- C06只读任务事实界面源f1b6b24e已由F #193独立接受并集成，新增三路一致快照与批次范围约束，不提供执行/审批命令；正式Mission生产绑定与E03控制API仍未实现。完整项目编辑/看板/日程提醒、B08、E04–E06及产品纵向资格未完成。
- 纯codec8618676e经F #201独立接受、直接HEAD真实Python3.8/3.11通过，已集成；旧#197/#200失败保留。PG完整来源只读预览026ddff9经F #202仅在已批准project-only schema范围接受并集成，未知/漂移RLS未资格，不能作为最终admission。
- 02ae2d80本轮完整实库Python594/594（0跳过）、Node117/117、真实PG浏览器8/8通过，详见WB-A-INTEGRATION-02AE2D80-20261111.md。正式Host/生产创建/全部产品仍未验，不将自动化回归等同交付完成。
- 紧凑绑定纯模块设计3266cb2d经B206/D207/F208签署；实现968430ed经F210独立接受，已集成。73cdb971上两纯模块20/20局部回归通过；正式models/overlay/control/reader/writer仍未接入，结构成功不授创建/执行或来源权威。
- 下一步并行推进：E防丢失HOLD设计#212待B/D/F审，B只读Schema/RLS资格快照实现中，D项目/批次看板候选#211待A/B/E字段冻结；这些均不借真实Host未可达停止可独立施工部分。
- 调度纠正：本轮重新启动F/B/D并实际完成测试，工具均正常；旧子任务usage报错不能被当成当前持续不可用或存在独立F额度的证明。今后按本次真实调用结果调度，不以旧errored状态停止全部施工。
- 现场统一FIELD_NEEDS_BANK_TRANSFER（用户确认行外无法访问）；真实DSH/SSO、Windows离线、实际并发/资源恢复、F01–F04与LICENSE_RELEASE_APPROVED未通过。RELEASE=NOT_APPROVED；#84保持Draft，不生成最终交付ZIP。

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
| WB-A00 | A | 本目录合同首次提交、建立 W0 PR | 无 | DESIGN_ACCEPTED / PR_VERIFIED（F #121；非产品完成） |
| WB-A01 | A | 原版能力范围对账并冻结功能清单 | WB-A00 | DESIGN_SIGNED（F #121；50项完整产品仍待F02） |
| WB-A02 | A | 许可证/商业授权与源码复用方式确认 | WB-A00 | BLOCKED_LICENSE（仍需权利人书面授权或独立实现） |
| WB-A03 | A | W0 DESIGN_SIGNOFF：字段/状态机/负向合同、跨组可实现性评审（不得要求 W1 实库证据） | WB-A00 | CONTRACT_SIGNED（B/D/E与F #121；后续增量独立审查） |
| WB-F00 | F | W0 独立 DESIGN_REVIEW（不是 W1 产品 QA） | WB-A01_DESIGN_SIGNED, WB-A03_CONTRACT_SIGNED | DESIGN_ACCEPTED_AT_A73ED52D（F #121） |

## W1 — 最小真实业务纵向链路
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-B01 | B | 投产日期与唯一性/变更历史，真实数据库 IMPLEMENTATION_QA | A03_CONTRACT_SIGNED, W0_DESIGN_FROZEN | COMPONENT_QA_ACCEPTED / MERGED（F #128） |
| WB-B02 | B | 系统/系统版本规范对象，真实数据库 IMPLEMENTATION_QA | A03_CONTRACT_SIGNED, W0_DESIGN_FROZEN | COMPONENT_QA_ACCEPTED / MERGED（F #128） |
| WB-B03 | B | 批次-需求/批次-版本关系 | B01,B02 | COMPONENT_QA_ACCEPTED / MERGED（F #130） |
| WB-B04 | B | 需求-版本多对多合法关系 | B03 | COMPONENT_QA_ACCEPTED / MERGED（F #130） |
| WB-B05 | B | 需求-版本-SST 关联及错误阻断 | B04 | COMPONENT_QA_ACCEPTED / MERGED（F #135） |
| WB-B06 | B | 跨分区 Scope 关联查询与分页 | B05 | COMPONENT_QA_ACCEPTED / MERGED（F #138；真实Host未验） |
| WB-C01 | C | 六页面/十分区不缺失的导航骨架，真实 UI IMPLEMENTATION_QA | A01_DESIGN_SIGNED, W0_DESIGN_FROZEN | NAVIGATION_COMPONENT_ACCEPTED / MERGED（F #128） |
| WB-C02 | C | 项目详情投产日期/需求/版本/SST 联动 | B06,C01 | SCOPE_UI_COMPONENT_ACCEPTED / MERGED（F #141；非整体资格） |
| WB-D01 | D | DSH 宿主版本/面板真实兼容性探测 | A00 | COMPONENT_TESTED / FIELD_NEEDS_BANK_TRANSFER（用户确认行外不可达） |
| WB-E01 | E | RC7.2 R1 只读 Scope 与 Evidence 适配 | B06 | READONLY_COMPONENT_ACCEPTED / MERGED（F #142） |
| WB-F01 | F | 真实日期、跨版本、多 SST 纵向核验，独立 INTEGRATION_QA | C02_IMPLEMENTATION_QA, D01_IMPLEMENTATION_QA, E01_IMPLEMENTATION_QA | BLOCKED_FIELD_AND_FULL_IMPLEMENTATION（未签整体通过） |

## W2 — 保留原能力与资产增强
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-C03 | C | 首页/看板/日历/技能页面完整对账 | C01 | MILESTONE_SLICE_ACCEPTED / CALENDAR_YMD_COMPONENT_ACCEPTED / OTHER_PAGE_FEATURES_PENDING |
| WB-C04 | C | 十分区信息与资产表单完整对账 | C01 | MILESTONE_AND_SIX_DRAFT_FORMS_COMPONENT_ACCEPTED / OTHER_SECTIONS_PENDING |
| WB-C05 | C | 中文/主题/搜索/响应式/可访问性 | C03,C04 | TODO |
| WB-B07 | B | 用例/义务/缺陷/报告追踪规范化 | B05 | SEVEN_KIND_COMPONENTS_ACCEPTED / R1_REFERENCE_VERIFICATION_PENDING |
| WB-B08 | B | 历史数据兼容和可逆迁移 | B07 | TODO |
| WB-D02 | D | DSH 原生模型/Skills/Commands/附件 | D01 | BLOCKED_D01_HOST_INTERFACE |
| WB-D03 | D | 项目会话+批次 Mission 绑定与恢复 | D02,B01 | BLOCKED_D02_HOST_INTERFACE |
| WB-F02 | F | 原版能力矩阵逐项回归与反例核销 | C05,B08,D03 | TODO |

## W3 — 自主测试闭环
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-E02 | E | Mission 查询、N1–N10 可视状态 | E01 | READONLY_COMPONENT_ACCEPTED / MERGED（F #154） |
| WB-E03 | E | 带幂等键和权限门禁的正式控制 API | E02 | BLOCKED_FORMAL_CONTROL_API（提案 #155；无伪accepted） |
| WB-E04 | E | ETU/WorkItem/Attempt 实时执行监控 | E03 | TODO |
| WB-E05 | E | Agent Teams/租约/并发上限探测和恢复 | E04,D03 | TODO |
| WB-E06 | E | Evidence/缺陷回归/N10 收敛事实映射 | E04,B07 | TODO |
| WB-C06 | C | 质量任务内自主编排/诊断/证据子视图 | E02,C04 | READONLY_FACTS_COMPONENT_ACCEPTED / AUTONOMOUS_COMMANDS_PENDING |
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

## 2026-11-09 WB-FG15 依赖环纠正：设计/实现/现场三级不能混淆
- 新审查证据：F 组 [PR #85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85) `WB-F00-HEAD-DELTA-6EDB9FB.md`，针对 A HEAD 6edb9fb7 复核 **28/28 GitHub Checks、W0 39/39**，提出 **WB-FG15 P0**：A03 W0 签署依赖 W1 真 DB/API/宿主运行，W1 B01 又依赖 A03 的闭环。
- 本次 A 将 A03 的 B/D/E/F 签署定义为 `DESIGN_SIGNOFF`（字段/关系/状态/ACL/反例/可实现性和签署 SHA）；F 只验 W0 设计/依赖安全。**不要求 W1 实际实现来签 W0**。
- W1 工单仍在 W0 设计签收及 F 独立设计接受后按 DAG 启动。B/C/D/E 的真实代码/数据库/API/DSH Host 和 F 实测分别受 `IMPLEMENTATION_QA_PASS`、`INTEGRATION_QA_PASS` 约束，绝不提前 PASS。
- W4 银行商业打包仍需 **独立的 LICENSE_RELEASE_APPROVED + FIELD_QA_PASS**；A02 BLOCKED_LICENSE 的阻断不因 W0 设计冻结而放松。受限源码始终不得进入银行交付。
- 机器验证：`docs/dsh-workbench/W0-W1-GATE-MANIFEST.json` + `tools/dsh_workbench/w0_dependency_gate.py` + `tests/test_dsh_workbench_gate_dag.py`，必须证明无环、拒绝 W0 依赖 W1 实现、拒绝缺许可/现场 Gate 的发布。最新提交 CI 验证前仍标记 CI_PENDING。

## 2026-11-09 WB-FG16 P0 — F 组发现发布依赖遗漏，A 已修改代码图与负向验收
- F 最新复验 A HEAD `4349ee63015c390e4b6c092e1ba048560be2e292`：28/28 CI、48/48 W0 专项；**FG15 DESIGN_FIX_ACCEPTED**。新增 **FG16**：旧发布 DAG 仅有 F04+LICENSE，F04 仅有 F01，缺 W2 F02 原版六页十区回归、W3 F03 自主闭环、W4 D04 Windows 资格。来源：F PR #85 / `WB-F00-HEAD-DELTA-4349EE6.md` 及 PR #84 复验评论。
- 已将 `W0-W1-GATE-MANIFEST.json` 增量拓展到 W2 的 C03/C04/C05、B07/B08、D02/D03、F02，W3 的 E02/E03/E04/E05/E06、C06、F03，以及 W4 的 D04、F04、A04、最终 bank release，逐工单对应上述原始 08 冻结依赖。
- 新的 F04_FIELD_QA 必须有 F03_AUTONOMOUS_QA + D04_OFFLINE_QUALIFICATION，最终 BANK_RELEASE 还要 F02_FUNCTIONAL_QA、A04_FINAL_INTEGRATION 以及商业 LICENSE；不可用 W1 集成 QA 或静态 oracle 假代真实验收。
- `w0_dependency_gate.py` 校验 release **所有跨阶段必需祖先闭包**、缺节点、缺直连关键依赖与 W0/W1 设计循环；`test_dsh_workbench_gate_dag.py` 新增移除或绕过 F02/F03/D04 的对抗测试。可选 E07 QA Replay 非最终商业发布前置。
- 本轮仅静态代码整改，不是 F02/F03/D04/F04 实际证据；**FG16=CODE_FIX_SUBMITTED / F_RECHECK_PENDING**，A02 继续 BLOCKED_LICENSE，B/D/E DESIGN_SIGNOFF 继续 PENDING，W0 NOT_FROZEN，未合并不打 ZIP。

## 2026-11-09 W0 A 组续工：FG16 及 A01 上游源码锚点
- F PR #85 最新对 A HEAD `4349ee63015c390e4b6c092e1ba048560be2e292` 复验，**FG15 DESIGN_FIX_ACCEPTED**，新增 **FG16 P0** 指机器发布依赖图缺 F02/F03/D04；证据 https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6739906960。
- A 已提交 `16740b71b08728bfa3a7952408cbc7085e3481d4`（38 个 Gate 节点、W2/W3/W4 发布闭包校验、负向反例）、`80efa1bfa585fe29a5939c889d5b5a08e4f742ed`（区分 F02 冗余直接边和真正绕过路径）；`515f6a367bd16d3b83197fa2c89e15d63a83c4fe` 将原版源码 SHA fc5a054a48973d004580a3cc1de60da3f701150b 的逐函数/DOM 参考行号纳入 A01 原子登记。上述 HEAD 的 W0 专项一次 CI 原始日志已核实 **58/58 OK**，最终新 HEAD 全矩阵需另外查询。
- 本次继续补齐 X01/X02/X03 交互与失联/无证据等场景；设计登记更新为 **50 个原子项，35 个上游源码入口候选，15 个新增目标（无原版入口）**。上游代码存在性锚点不等于目标实现、按钮级动态核验或版权许可。
- **FG16 状态 CODE_FIX_SUBMITTED / F_RECHECK_PENDING**；B/D/E DESIGN_SIGNOFF PENDING；A02 BLOCKED_LICENSE；W0 NOT_FROZEN，不能进入未批准的 W1 实施和银行 ZIP 打包。


## B 组 WB-A03 正式 DESIGN_SIGNOFF 提交（2026-11-09）
- source_sha=80efa1bfa585fe29a5939c889d5b5a08e4f742ed；独立分支 work/dsh-wb-domain；签署内容：WB-B-A03-DESIGN-SIGNOFF.md、02/06 增量及 SQLite 设计约束反例 tests/test_dsh_workbench_b_a03_design.py。B_DESIGN_SIGNOFF_SUBMITTED，W1_IMPLEMENTATION_QA_NOT_RUN，F QA 未执行。
- 需 A 合并 B PR、D/E 分别签 W0、F 独立接受并明示 W0_DESIGN_FROZEN 后，B01/B02 才成为 READY；B03 依赖 B01+B02，B04→B05→B06 后提供 C/E Scope API；B07→B08 仍待 W2 依赖。禁止在 W0 不满足时自报 W1 验收或构建 ZIP。

- B-A03 RED→FIX 设计回归：8 个 SQLite SQL witness 初轮 7 OK/1 FAIL，证实 BRV 应强制需求—版本 source_verified_requirement_version FK；已在 d0a38886048bd2183ef364295e6204eb6a742257 修复设计测试，待新同 HEAD CI 结果。**不是 W1 数据库执行。** B01–B08 仍待 W0 冻结依赖。

### B 组同 SHA 契约 CI 结果（仅设计）
- B PR #89；source commit 7b916e295d8f8461a8134ed2da9583ecb897022a；[GitHub Actions job 129171616901](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42620657398/job/129171616901)：SQLite B 设计 witness **8/8 OK**，合并 W0/B 契约回归 **66/66 OK**。仅设计/CI_PASS，禁止记 W1 IMPLEMENTATION_QA_PASS；下一 ready 仍是 A/F 冻结 W0 后 B01+B02。


## C 组 W0 原创探针进度（2026-11-09，待 A/F 审核合并）
- 施工分支 `work/dsh-wb-ui` 由 `work/dsh-wb-w0@515f6a367bd1` 创建，C 的 `WB-C-W0-ORIGINAL-UI-AUDIT.md` 已形成六主页面/十区、表单/动作/错误态/搜索/主题/导航/原创组件/API 接口的候选对账；演示代码 `tools/dsh_workbench/ui_w0_prototype/` 与 `tests/test_dsh_workbench_ui_w0.mjs` 隔离于正式产品。
- 本地 Node 单测 9/9 PASS，语法检查 PASS；浏览器导航被 `ERR_BLOCKED_BY_ADMINISTRATOR` 阻断，**无真实截图，浏览器 QA NOT_RUN**，详见 `WB-C-W0-TEST-EVIDENCE.md`。独立 CI 工作流配置为同 HEAD Node/Playwright 浏览器探针、截图上传；是否真正通过以该 SHA job 为准。
- **WB-C01=TODO、WB-C02=TODO、C03/C04/C05/C06=TODO**；本轮是 W0 可行性探针，不满足 A01/F W0 设计冻结，不进入 W1，也不将纯函数 Demo 等同真实 B06 复合关系/ACL API。
- 源码采取独立创作路径；原版 `naodeng/dsh-qa` PolyForm Noncommercial 受限文件零复制，A02 `BLOCKED_LICENSE` 不变。请 A/F 以该分支真实 PR/同 SHA CI 审核后在正式总账记录，不由 C 代签 W0。

## C 组 W0 独立 CI 真实探针结果（后续增量）
- 源 SHA `465d1006e1b0f8d9ce537436d46912e527d9d096` 同 SHA GitHub job [129176561107](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622094284/job/129176561107)：9 项 Node 单测 PASS、真实 Chromium 原创页面交互 PASS，3 个带 SHA256 的截图实际上传至 artifact 13675694071。旧本地浏览器策略阻断和 Ubuntu26.04 不兼容历史保留；改用 Ubuntu24.04 实际通过。
- **状态仅 W0_PROTOTYPE_CI_PASS，非 W1_IMPLEMENTATION_QA_PASS**；C01/C02 未启动、B06 和 A/F W0 设计门槛未解锁。单次 PR 探针 CI 避免 push+PR 同 SHA 触发两次，不构建 Windows 离线包。



### C 组 W0 来源响应栅栏与负向验收（2026-11-10）
- **FG23 C侧整改已提交**：F #104 在 A+B+C 合并树真实复现 `C_BROWSER_RERUN_ON_LEDGER`。C 只从 `.github/workflows/dsh-wb-c-w0-ui.yml` 的 `pull_request.paths` 移除 `08-CONSTRUCTION-PLAN.md`、`09-GAP-MATRIX.md`、`10-RELEASE-CHECKPOINT.md`；保留原型代码/单测/审查资产路径、`workflow_dispatch`、非 Draft 与真实 Chromium。源 `7fa4d0c516168cde22d6d071170d449dc0ed8b77` 同 SHA [C CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42733902992) 已 30/30 Node、Chromium、B→C 30/30 与 E 合同成功；F 需重新运行 A+B+C 183 项合约，未由 C 自行宣布 FG23 CLOSED。
- 同源实测：C #97 HEAD 15d37ec22e758922cab513a2d403be9211eddaf8；[W0 Chromium job 129545127122](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127122) 实际 30/30 Node PASS + 真浏览器交互 PASS + 3 PNG；[B→C job 129545127428](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127428) 30/30 PASS；[E 合同 job 129545126959](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943656/job/129545126959) SUCCESS。只核销 W0 源反例探针，不证明 W1/F02。
- artifact [13723922528](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/artifacts/13723922528)，scope PNG sha256 6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae；历史 6249f1a 测试漏跑事实保留。
- F 对本 follow-up 最新 UI 和真实截图仍独立审核待办；W0_NOT_FROZEN / A02_BLOCKED_LICENSE / C01_C02_W1_NOT_STARTED / NO_BANK_ZIP。
- C PR #97 已重基在 A 200a96ac 的统一 W0 源树；A 的 B/E/F 账本原样保留，C 仅提交原创 source_fence.mjs 和十项反例。
- 模拟 401/403/404/409/422/503、200 缺证据或人工审批、STALE/UNKNOWN R1；按项目/稳定批次/选中复合关联/修订/epoch 丢弃迟到响应。
- 第一轮 6249f1a 同 SHA CI 仅 20/20 Node + 原型真 Chromium PASS（截图 artifact 13723128464），漏跑新十项。CI 已修复成 30 项正反例与真实当前 C branch 合并探针，新 HEAD 结果须核对。
- 状态 W0_ORIGINAL_PROTOTYPE / C01-C02_W1_NOT_STARTED；F #101 最近判 W0_NOT_FROZEN、FG22 为 A CI blocker；A02 BLOCKED_LICENSE。正式 B06/R1/Host/F02 未运行。

## 2026-11-09 E 组 A03 设计签署增量（施工分支提议，待 A/F 审查合并）
- 工单 WB-A03/E：`E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS`；签署文档 `WB-E-A03-DESIGN-SIGNOFF.md` 固定审核 W0 源 SHA `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`。该状态只接受 W0 R1 只读/权限优先/命令幂等/NodeGate、人审、SSE+水位/证据哈希设计，不要求 W1 真运行以规避 FG15 环依赖。
- 工单 WB-E01：仍 `BLOCKED_DEPENDENCY_B06`，E 仅可提交来源审查、只读映射设计与 W0 协议反例；没有真实 B06 跨 Scope join、身份授权，不得 QA_PASS。WB-E02–E06 保持受依赖约束；E07 仍 OPTIONAL_NOT_ADMITTED。
- 代码/用例：`tools/dsh_workbench/e_contract_oracle.py` + `tests/test_dsh_workbench_e_contract.py`，运行 `python -m unittest discover -s tests -p 'test_dsh_workbench_e_contract.py' -v`；它们只验证内存设计 oracle，不是 HTTP/DB/R1/SSE/执行证明。E 分支最新 SHA/同 HEAD CI 由 GitHub 检查后记入 PR，绝不预填绿灯。
- R1/NodeGate/缺陷完整性、人审、真实签名租约、证据哈希、断线补放由 E01–E06/独立 F 继续实测；A02 BLOCKED_LICENSE / W0 NOT_FROZEN / 不构建银行 ZIP。

## A 组 2026-11-09 ABCDE 联合候选构建（需同 HEAD F 独立复核）
- 固定来源：A `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`、B PR #89 `704c86aaf9b2c5a9b9b4088648ccd0c50204f2f8`、C PR #92 `e9094bf5267ebc840ffae6bf3e8a707380ecaf7f`、D PR #90 `f0b7faeb22f9bf03d2487061a8f81a2776a5213d`、E PR #91 `bee612b2dd94a6040404db4b9a4a5fd816e136dd`。本次使用多父 Git merge commit，逐字节保留各组**独立新增文件**，02/06 取 B 合同追加段，08/09/10 合并 B/C/E 非冲突追加段，A03 融合 B/D/E 正式 W0 设计签收行；F PR #85 原反例另纳入候选回归，不可冒用 F 正式签署。
- FG17 P0：A 全矩阵源 `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc` Chromium/CDP smoke 2907 PASS/1 FAIL/4 SKIP；失败为未在 recorder response artifact 找到 POST /api/save status=200，暂不判定 W0 代码根因。失败日志 https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42620015620/job/129169423859，须修复/验证后方可称最终全 CI PASS。
- FG18 P0：B 设计 witness 原 sst UNIQUE(project_id,source_system,source_key) 禁止同 raw SST key 在不同版本复用；A 候选改为 UNIQUE(project_id,version_id,source_system,source_key)，加同版本冲突、跨版本真实可共存反例，F 原 `test_dsh_workbench_b_sst_identity_f.py` 随候选树运行，B 需正式确认变更语义。
- FG19 P0：F 的原 pinned B→C→D→E 合并由于 08/09/10、A03 冲突而失败，见 job #129218849736。现在 A 提供单个五父提交 SHA，F 需验证父 SHA 与最终合同文本、所有历史证据/失效前置仍存在、同 HEAD 合同+浏览器测试通过。
- FG20 P1：C 原版原子候选数由旧 47 统一为 A 最新 50（35 个 O/A 上游源码入口候选、15 个 N 新增），保留尚未実际执行的 50 个原子用户动作状态 NOT_RUN。
- 仍有 W0 门槛：A01 原版按钮与 C demo 差异逐项独立审核、B FG18 复签、D/E 当前合同签收范围差异确认、F 对集成 SHA 接受、A02 BLOCKED_LICENSE。**W0_DESIGN_FROZEN=NO；W1 B01/C01/E01 实际产品代码无验收，RC7.2 主线不合并、不构建银行 ZIP。**


## 2026-11-09 B 组执行 F WB-FG18 整改（追加而非覆盖历史）
- task=WB-A03-B-FG18；状态=CODE_SUBMITTED / NEW_HEAD_CI_PENDING / F_INDEPENDENT_RECHECK_REQUIRED。F 原始 FAIL：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336677；旧 B 704c86a SQLite 10/10、合同 68/68 绿不覆盖该反例。
- 修改 tests/test_dsh_workbench_b_a03_design.py 的 SST 唯一身份域，增加 source_trace 和四组负向/正向证据；修订 WB-B-A03-DESIGN-SIGNOFF、02、06 合同；完整源码以 B PR #89 最新 HEAD 为准。
- B01/B02 仍依赖 A03_CONTRACT_SIGNED + W0_DESIGN_FROZEN；F 最新 ABCDE 审查为 REVIEWED_WITH_BLOCKERS，FG17/19/20 仍 OPEN，A02 BLOCKED_LICENSE。不能提前解锁 W1、不能打 ZIP。

- WB-FG18 CODE_FIXED_DESIGN_CI_PASS（历史修复 SHA eb48d161bd5c7caa29733fccfabc44654a376dd6）：B 14/14、W0+B 72/72、原 F pinned-SHA 测试 1/1；run 42637588144 job 129229772001。F 审查意见仍待，W0 NOT_FROZEN；当前提交只是追加已经成功的可审计记录。

## 第二轮 B/C/D/E 精确源 SHA 统一验收候选（F 独立复核必需）
- B PR #89 `98bac426a35063a306f4eaa4b43c80cf0a0a1745`：FG18 由 B 组自行修复，SQLite 约束新增全项目内部 sst_id UNIQUE、同系统版本来源键 UNIQUE，另设 `sst_source_trace` 保留 namespace/revision/source_ref；F 原始同 raw SST ID 跨版本反例需在当前联合树重跑。B 仍为 DESIGN_SIGNOFF，仅 W0。
- C PR #92 `4394f7fef7f19035220ea2398af9ff9f19a4b865`：新增 50 个 feature_id 差异表、15 项 Node 测试、原始证据与 B→C 隔离 Git 合并成功；这不是全功能 F02。
- D PR #90 `a332e6c575cac9d2b6ef0b2038615b276dcfa602`：13/13 基线合同、宿主 allowlisted manifest 检测、真实 loopback GET 负向，近期 D 同 SHA 30/30 局部 CI；不是行内 DSH1.18.26 FIELD PASS。
- E PR #91 `8401ab85cefb2876ce4451252d3d9a6e7d14704c`：新增旧 Admin R1 的只读合成/拒绝测试、B06 source-verified 合法关系 DTO 原型；无 /api/workbench/v1、SQL、SSE 或执行。E 新共享合同改为独立 `WB-E-A03-LEDGER-MERGE-HANDOFF.md`，A 上次已保留 E 原 08/09/10 增量。
- 上述改动需要 **统一合并树同 HEAD CI 和 F 独立复核**。FG17 CDP 定向测试仍须真实通过，不可通过 W0 轻量 CI 代替完整 CI。W0 NOT_FROZEN；BLOCKED_LICENSE；不推送运行主线、不出银行 ZIP。


## C follow-up PR #97（原始 W0 对账证据保留；旧 FG 状态由下文 A 最新段覆盖）
### C 组 2026-11-10 W0 原创交互深化（不启动 W1）
- F #94 已对 A 75fd2c64159db863cfd1319d41a887785b556d40 完成独立复验：C 50 项/15 Node 与 156 W0 合同为设计期通过；FG17 FLAKY_OBSERVED / ROOT_CAUSE_PENDING、FG21 work/rc7.2 merge dirty；W0_NOT_FROZEN、A02 BLOCKED_LICENSE。不得把“F 审查完成”写成“F 接受/冻结”。
- C follow-up work/dsh-wb-ui-followup 仅做 W0 允许的原创原型深化：需求/系统版本/SST 多选关系过滤、不可变 Scope 快照、十区领域表单必填校验及 fail-closed 提交、逐区共享上下文浏览器验证。
- 新增 5 项 Scope 单测（累计 14 项）和 Playwright 逐区表单/多选/无结果搜索测试；最新 HEAD `d4863bab1cc65ed78b5c3d7edbf8e6e242c7b6a8` 的 [W0 job 129318183234](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183234) 20/20 Node + Chromium 逐区表单/多选/截图 PASS，artifact 13693719815；[B→C merge job 129318183968](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183968) 15/15 PASS。仅 W0 原型证据，C01/C02 不标 W1 完成，不连接旧 API 或 mock B06。

## 2026-11-10 A 组：F #101 独立审查与 B/C/E follow-up 统一集成

- 审查源：F PR #101 审查 A @ `b385e042c4543f5d918d61bff5e01be1d88afba7`，报告 [PR #84 审核意见](https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6754968337)，为 `REVIEWED_WITH_BLOCKERS`；不得以 F 已审查推导 W0 已冻结。
- FG17：A 已改为 Playwright 精确业务文本等待、保留 POST/CDP/R1/PNG；F 对 b385e04 真 Py3.8/1.48 与 Py3.11/1.62 各 31/31，同一 Py3.8 环境连续 5 次教学动作通过。为 `TARGETED_REAL_BROWSER_RECHECK_PASS`，不是全量 L2/银行现场 QA。
- FG21：A 多父合并 RC7.2 主线 `87f956f1388f58beabf7116c937fd6fda5fae2ca`，GitHub PR #84 从 dirty→mergeable=true；`mergeable_state=unstable` 仅是检查未通过，**不准合并**。R4 32 是逻辑 roster 容量，active worker 默认 4；F R4 Python 100/100 设计/源码定向通过，现场 32 队员/活跃并发及 Windows 免安装均 NOT_RUN。
- FG22：F 独立 164 项 W0 合同 1 FAIL，A b385e04 159 项 1 FAIL：Q1 错误码测试仍期待旧 `Q1_FG17_NEGATIVE_CHECK_REMOVED`。A 后续 `5bba94c213e2d54a83f8aa360b0f3d71ea8d26a1` 修正该负向期望并加入双条件反例；**后续 A 同 SHA CI/F 重新审查之前不得登记 PASS**。
- B PR #95 @ `67c4fc592f290710d6242aef2d4144000e7d82fd` 交付 B_DESIGN_SIGNOFF_RECONFIRMED、B01/B02 额外 SQLite 身份与日期审计见证、B06 source_refs + 顶层 next_page_cursor、宿主可信 principal；原 B 23/23、FG18 F 反例 1/1、shared 165/165 仅属于 B 来源 SHA。
- E PR #96 @ `c70ad0da92c5a4899a72d3096fad5e46fded74d5` 交付 B06→R1 只读消费、安全主体不得由 E 自报、Mission 显式 batch/project 对账和缺来源 fail-closed 设计/测试；原 E 47/47 合同绿灯仅属于 E 来源 SHA，E01 实现仍 BLOCKED_B06。
- C PR #97 @ `78837f45d01acc9fdddc4daffa9e575804c542dd` 交付 W0 原创原型多选 Scope 与十区表单；早期 C 源 `d4863bab` 的 20/20 Node + 真实 Chromium/3 PNG 通过；不是正式六页十区 F02。
- A 将 B/C/E 增量保留原来源、合入统一源码树；共享 08/09/10 **只追加设计证据**，不删除原 F 红灯；C 浏览器 CI 保持禁止仅因三账本改动而重跑，旧完整 RC7.2 V4/Q1 仍作为非 Draft/正式门禁。
- B01/B02、C01/C02、E01 真实 PostgreSQL/HTTP/R1/DSH Host 正式实现、F02/F03/D04/F04、32 人现场、商业授权均未通过：**W0_NOT_FROZEN / W1–W4_NOT_RUN / A02_BLOCKED_LICENSE / PR #84 DRAFT / NO_BANK_ZIP**。


## A 组 2026-11-10 B/C/E 最新源码一致性集成（待新 HEAD/F 核销）
- F 独立 PR #104 在 A `200a96ac` + B #95 + C #97 的临时合并树发现 **FG23：C Browser PR paths 误将 08/09/10 三本账作为重跑条件**。F 原始 183/1 FAIL job https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/job/129552134247 保留；C PR #97 `b2a64df65661880808510d0486f6aefc70ca23df` 已删除三条高成本路径，同源 C 30/30 Node/Chromium/3 PNG SUCCESS https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42734198368 。仅 C 层修复，**联合 F 正式复验仍需新 HEAD**。
- B PR #95 `50bd16d9e2c321eb5eaa21e96f663e89ae377b34` 补 `authoritative_link` 对 `sst_source_trace` 复合来源 FK 与空白来源/跨版本 raw SST ID 冒用反例；B 同源 26/26 SQL + 原 F FG18 + shared 183/183 PASS，https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729370403/job/129543167902 。这仍是 W0 SQLite 设计见证，不是实库 PostgreSQL。
- E PR #102 `26b2deaf5485193133e418da81982291c8056d64` 补 B06 全分页 consumer，检查 page_cursor→next_page_cursor、全页来源并集、稳定的 project/batch/revisions、游标循环与授权拒绝后不读取 R1；Py3.8/3.11 各 68/68 PASS，https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729623656/job/129544043597 。B06 真 HTTP/DB 及 E01 IMPLEMENTATION_QA 仍 NOT_RUN。
- C 源 `source_fence.mjs` + 10 条 SourceReadFence Node 负向用于拒绝跨项目/批次/epoch/修订异步响应、401/403/404/409/422/503、R1 STALE、缺 Evidence/人审假 PASS；A 继承 #103 的 W0 必跑约束及新 L1/Node 校验。**源模拟预览，不能伪称正式 Host/API/R1。**
- B/C/E 通过真实多父 Git 集成到 A `work/dsh-wb-w0`，保留 C/F/B/D/E 的原始证据与错误历史；三本账为追加更正，不删除旧结论。P0 FG21 Git 源冲突已解决；FG22 源 A200 180/180 PASS；FG23 新集成 HEAD CI 与 F 独立核验后才能关闭。
- **门禁：W0_NOT_FROZEN / A02_BLOCKED_LICENSE / A_PR84_DRAFT / W1-W4_PRODUCT_QA_NOT_RUN / R4_ROSTER32_ACTIVE4_DEFAULT / NO_BANK_ZIP**。不把 L0 demo 绿灯当独立 F acceptance；未经商业许可不得复制受限 naodeng/dsh-qa 代码。


### A 组 ABCDE 同源真实验收检查点 `db1026fd`（2026-11-10）
- 多父来源：A `200a96ac` + B #95 `50bd16d9` + C #97 `b2a64df6` + E #102 `26b2deaf` + A #103 `d082e71f`，全部作为真实 Git parents，D 历史源由 A 首父继承；含 RC7.2 R4 合入的第一父祖先。
- 同源 Actions [run #42735465054 / job #129563488731](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42735465054/job/129563488731) ：**206/206 Python unittest + 30/30 Node + CI_ADMISSION_POLICY_PASS（13 workflows）**；FG23 `C_BROWSER_RERUN_ON_LEDGER` 负向代码在该源保留且通过。针对 F 原旧 A+B+C 183/1 FAIL，只判 **A_UNIFIED_L0_RECHECK_PASS / F_INDEPENDENT_RECHECK_PENDING**。
- 工程经济：C 原型 browser workflow 删除 PR paths 08/09/10；A Draft 保持 V3/V4/Q1/N5/Field 长矩阵 skip，L1 非 Draft/人工 pinned SHA 执行，真实 Browser 从未因 L0 PASS 代签。PR 累计差异同步仍可能触发旧 C Workflow，新候选需 F 与 release-review 验证实际工作流调度。
- FG21 source mergeable=true、最新主线 `87f956f` 已纳入祖先；F #104 评审的是更旧源 `200a96a`，**不是 `db1026fd` 的独立签署**。B/E/C 真 PostgreSQL、DSH Host/R1/Agent Teams32/Windows field 仍 NOT_RUN；A02 BLOCKED_LICENSE、W0 NOT_FROZEN，严禁 W1 正式施工越依赖，银行 ZIP 禁止。


## 2026-11-10 A01 中英文范围裁决与 F #106 增量核销
- F [PR #106](https://github.com/TongAITech/opencode-test-digital-employee/pull/106) 已对 A 源 `a3555b187eb35d27a2d712313dd8ea7daa28915f` **独立复验**：W0 206/206 Python、C 30/30 Node、FG16 2/2、FG18 1/1、21/21 CI admission 负向、真实 Chromium/三截图目视。F 关闭 `FG23_CLOSED`，签 `FG20_DESIGN_RECONCILIATION_PASS` 与 `C_W0_PROTOTYPE_REVIEW_PASS`，**没有签 W0 总冻结**；原 FG23 183/1 FAIL 仍保留。
- F 明确指出 A01 `P05-03` Skill 双语说明、`X01-01` 全站语言/主题在 W0 中文演示均 NOT_RUN；不能把 `THEME_COLLAPSE_ONLY` / `NO_INTERACTION` 误判成双语完成。**A 决策 `KEEP_ZH_EN_W1_REQUIRED`**：中文 `zh-CN` 默认，英文 `en-US` 正式保留为 W1 C/D 开发和 F02 按钮级验收，不静默裁剪原 50 功能。
- 本轮新增 [A01 双语设计合同](WB-A01-BILINGUAL-SCOPE.md)、[机器可读 12 项 W1 负例](WB-A01-LOCALE-SCOPE.json)、[静态门禁](../../tools/dsh_workbench/a01_locale_scope.py) 和 unittest。设计状态为 `A_SCOPE_RECORDED_F_DESIGN_REVIEW_PENDING`，不是 W1 UI QA；F 可独立核验英语+技能缺译回退、日期/ID 不漂移、权限/NodeGate/Human Gate 不伪 PASS、主题偏好用户隔离、许可不绕过。
- 同源码提交 `fc2619d6f4ef36afe50b594a3a4630057c1ae884` 的 [W0 run #42743331421](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42743331421) **Python 218/218 + Node 30/30 + CI policy13 PASS**；这是 A 的范围静态测试，不继承为 F 对新 HEAD 的签署。
- A02 PolyForm Noncommercial `BLOCKED_LICENSE`、W0 `NOT_FROZEN`、W1–W4 真实 API/Host/Postgres/R1/Windows/Evidence/50 功能依赖照旧；PR #84 Draft，不合入 RC7.2/不构建银行 ZIP。

## 2026-11-10 A01 原版中英文入口真实来源反例补强（F #106 后）
- 主线 A 已先行施工规范单源 `WB-A01-LOCALE-SCOPE.json` + `a01_locale_scope.py` + W1 12 项设计验收合同。并行旧 PR #109 产生第二套设计合同，A 为避免双标准已将其 **CLOSED_NOT_MERGED**；现只在 A 官方 `KEEP_ZH_EN_W1_REQUIRED` 合同上增量施工。
- P05-03 与 X01-01 的先前原版来源锚点不完整：X01-01 指向主题函数不能证明英语/中文切换；新证据固定 upstream `fc5a054` `public/i18n.js#L700-L722`、`public/app.js#L2048-L2094` 及 P05-03 语言选择 handler。仅保存来源链接、能力描述、原版许可证元数据，禁止复制受限 JS/词典。
- 追加机器合同 `upstream_readonly_provenance`，在原 `a01_locale_scope.py` 增加准确 SHA、法律标识、未复制、语言按钮和词典来源强制校验；新增 5 项独立负向测试：主题入口冒充语言、失去来源 SHA、MIT 误标、复制源码、删除语言/Skill handler 锚点。仍以 **同源 GitHub CI 实测**核销，不以本条自报成功。
- F #106 在 A@a3555b1 已独立接受 `C_W0_PROTOTYPE_REVIEW_PASS/FG23_CLOSED`，并真实 206 Python/30 Node/FG16/18/Chromium；A 后续 W0 b4bea 已记录双语设计，但 F **尚未对本新增源码来源门禁签署**。W0_NOT_FROZEN、A02 BLOCKED_LICENSE、W1-W4 NOT_RUN、NO_BANK_ZIP。

## 2026-11-10 A01 原版语言来源负向门禁已集成的准确工程证据
- 重复 A01 设计 PR #109 因 A 主线已先行建立同一双语合同，**CLOSED_NOT_MERGED**，未造成两套标准。只保留 A canonical `WB-A01-LOCALE-SCOPE.json`；精简 PR [#110](https://github.com/TongAITech/opencode-test-digital-employee/pull/110) 已 **MERGED_TO_W0_DESIGN_BRANCH**，合并 HEAD `afcda9a5737e181a1d1d5e08f926943664c594d5`。
- 在相同合并源码 HEAD，[W0 fast CI #42744769517/job #129594118685](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42744769517/job/129594118685) 实测 Python **225/225**、C Node **30/30**、A01 locale gate **PASS**、CI policy **13 workflows PASS**。原 PR #110 精确修复源 `e3d87d6e032a6733ef887cb9856841445a8c9a9b` 的 [CI #42744623650](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42744623650) 同样 225/30 PASS，并保留原型 Chromium PASS。
- 新增的并非英语产品界面，而是 `i18n.js`/设置页实语言入口和 PolyForm Noncommercial 来源的**负向可验证证据**；A01 50 原子目标与 W1 12 个双语验收案均未标已执行。F #106 的审查只针对旧 A@a355/C 原型，本次合并后的 A01 增量需 F 独立复核，未签全球 W0 冻结。
- 仍 `W0_NOT_FROZEN / A02_BLOCKED_LICENSE / B06_E01_C01_D_HOST_FIELD_QA_NOT_RUN / PR84_DRAFT / NO_RC72_MERGE / NO_BANK_ZIP`。

## 2026-11-10 A 组 F #111 W0 Round-1 独立结果 / B108 + E107 P1 候选集成

- F [#111](https://github.com/TongAITech/opencode-test-digital-employee/pull/111) 对精确 A `f870ad5efb7f3eda669703291900ce49e0a1d36f` 独立运行 W0 **225/225 Python、30/30 Node、A01 locale provenance/CI admission PASS** 与真实 Chromium/三截图；对 B108 精确源跑 30 定向+210 W0，对旧 E107 `917f597` 跑 73 E+211 W0；A+B108+旧 E107 的无远端 overlay 234/234 Python、30/30 Node PASS。F 结论：`ROUND1_W0_CONTRACTS_PASS_WITH_E_P1_HOLD`，W0_NOT_FROZEN，不能把临时 overlay 当正式 A。
- B [#108](https://github.com/TongAITech/opencode-test-digital-employee/pull/108) `b801c25bbec361e6a791c561d5a7dd0ec9440aaf` 获 F `B108_W0_DESIGN_WITNESS_PASS`，SPLIT/UNSPLIT 必须由 verified BRV/BRVS 关系投影推导（不可相信可写 split_state）；source trace、verified requirement-version/source link 不允许无审计覆盖 UPDATE/DELETE。B 的 SQL/SQLite trigger 仅设计见证，不可直接照搬为正式 PostgreSQL supersession/撤销方案。
- F 对旧 E107 `917f597` 指出 **P1：`mission_overview(mission_id)` 先读取 tasks/executions/evidence 后才验证 Mission 的 project/batch Scope**。旧失败记录保留为安全设计缺口，不得以 HTTP 未暴露而无视。
- E [#107](https://github.com/TongAITech/opencode-test-digital-employee/pull/107) 最新 `a04933fbe7b651c10b589b90cade5da65bdd8b81` 提交源码修复：两 R1 入口只调用 `mission_overview_scoped(project_id,batch_id,mission_id)`，不 fallback；继承 `AdminProjection` 先 query `rc7_mission` 唯一身份、显式 project/batch 匹配，之后才 query tasks/executions/evidence；跨项目、跨批次、无 canonical binding 时拒绝且关联明细查询次数 0。E 同源 W0 **239/239 Python+30 Node**，[job 129618982111](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42752449330/job/129618982111)；Python3.8/3.11 各 **82/82**，[job 129618962172](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42752443232/job/129618962172)。**这是 E 工程修复候选、未获得 F 对新 SHA 的独立 P1 关闭签署。**
- A 本轮以 `f870ad5` 为首父，保留 B #108、E #107 精确来源为真实 Git 父提交，并在唯一 08/09/10、A03 增补同源证据。必须对最终 A HEAD 重新验 Python/Node/CI 门禁；F 须独立验证 P1 `zero related reads before auth`、B split/source 与历史 FG18、R1 source fence、F00 设计签署范围。旧 F #111 对旧 E 的 P1 红灯不得覆盖掉。
- F 同时指出 00/02/03/04/05/07 文件头的“W0 候选冻结”容易与唯一状态 `W0_NOT_FROZEN` 矛盾，已按统一 `W0_DESIGN_IN_PROGRESS` 修订并增加机器反例。
- 执行门槛：`W0_NOT_FROZEN / E107_P1_F_INDEPENDENT_RECHECK_PENDING / A02_BLOCKED_LICENSE / B01_B02_C01_C02_E01_REAL_QA_NOT_RUN / R1_HOST_FIELD_NOT_RUN / PR84_DRAFT / NO_BANK_ZIP`。

## 2026-11-10 A 新增：同 HEAD Check Runs 证据校验器（W0 合同施工，不是 QA 签署）
- 施工输入 PR #84 @ f6aa541a7c82b74bcd1937754637d8341111fb70，target work/rc7.2 @ 87f956f1388f58beabf7116c937fd6fda5fae2ca；GitHub 精确源 15 个 checks=1 success(w0-contracts)/14 skipped。Draft 触发跳过是策略，不等于 L1/L2 全绿。
- A 在 tools/dsh_workbench/w0_checkrun_evidence.py 建立完全离线的同 SHA check-runs JSON 核验；tests/test_dsh_workbench_w0_checkrun_evidence.py 提供负向证据，拒绝旧 SHA、required 被跳过/取消/失败/未完成、缺失/同名重复、分页不完整。W0 workflow 通过 test_dsh_workbench*.py 自动收集；本提交在合并后必须以新 HEAD GitHub CI 核实，不能沿用 f6aa541a 的成功。
- 状态：WB-A00_CONTRACT_EVIDENCE_HARDENING_SUBMITTED / SAME_HEAD_CI_PENDING / F_RECHECK_REQUIRED。仅证明选择的 check 成功，永远不会签发 product_qa_pass、F approval 或 license_release；正式 L1/L2 仍要在非 Draft/人工 pin 下完整执行。
- 当前门禁严格维持 W0_NOT_FROZEN、PR84_DRAFT、WB-A02_BLOCKED_LICENSE、50/50_PRODUCT_NOT_RUN、E107_P1_F_RECHECK_PENDING、NO_RC72_MERGE、NO_BANK_ZIP。


## 2026-11-10 总控接管：精确源与 PostgreSQL 增量审查
- 远端 PR #84 接管源 `5c1a5f4e10ed9f79bb523516d340ff21f58c72f0`；RC7.2 `87f956f1388f58beabf7116c937fd6fda5fae2ca`，未修改运行主线。
- 该源 check-runs：w0-contracts SUCCESS，14 SKIPPED；跳过不是产品 PASS。F #112 仅审查 f6aa541，不转移到本源。
- F 独立复验 PR #114，报告提交 `58297959c401106c6f6f5f6221c8f91841c1a5c7`：本地 Python260/260、Node30/30、隔离 F scope-first9/9；未执行 PostgreSQL/Windows/浏览器；未签发 F00。
- PostgreSQL 正式业务库增量合同正在独立分支施工；B/D/E 技术评审 PR #115 为 REVIEW_IN_PROGRESS，不能当作原组签署。增量必须绑定实际 SHA 再审，不继承历史签署。
- BLOCKED：PostgreSQL 增量 B/E/D 审查及最新设计 HEAD 的 F00 接受；W0_NOT_FROZEN。W1 产品实现不得借本轮合同测试宣称完成。
- A02_BLOCKED_LICENSE / 50_PRODUCT_NOT_RUN / FIELD_QA_NOT_RUN / NO_RC72_MERGE / NO_BANK_ZIP。


### PostgreSQL 增量工单评审证据
- PR #116 合同源 `2343e0ff9f08f306da52b38428d7640b3409d526` 已写入02/06；真实本地 Python 合同260/260；同源 GitHub w0-contracts SUCCESS，run 42773079476/job129685163960。不是 PostgreSQL 产品验收。
- PR #115 独立技术审查更新 `1e777123`：B/D/E职责视角 ACCEPTED_FOR_DESIGN，无新增 W0 P0/P1；不冒充历史团队新签署，F 最新联合设计源接受仍待。
- PR #114/#115/#116 均为独立分支审查材料，尚未集成冻结；下一步核对并集成合同及报告，再对精确集成 HEAD 回归/F复验。W0_NOT_FROZEN，真实 PostgreSQL/Host/Windows/现场 NOT_RUN。


## 当前权威检查点：W0_DESIGN_FROZEN（2026-11-10）
- 冻结设计源：a73ed52d88425d5e60cbe07467a0ab5cbed5f708；F PR #121 / 2506b189 正式 WB-F00_DESIGN_ACCEPTED，无剩余 W0 设计 P0/P1。
- B #119/371f43f0、D #118/9e4f6c98、E #120/278a5a58 分别正式签署；00–07/A03/locale/DAG自14534d61字节未变。WB-A01_DESIGN_SIGNED / WB-A03_CONTRACT_SIGNED / WB-W0_DESIGN_FROZEN，仅设计门禁。
- 冻结源同SHA W0 CI SUCCESS：run42776373441/job129695699938；F独立263 Python/30 Node/9安全反例/33 D组件通过。14 SKIPPED不算PASS。后续账本HEAD不继承这些测试数字。
- WB-D01 COMPONENT_TESTED，现场探测GET_UNAVAILABLE，BLOCKED_FIELD；不是IMPLEMENTATION_QA_PASS。
- 下一就绪工单：B01/B02真实PostgreSQL、C01六页十区双语骨架；各组独立worktree/PR。B06未完成，C02/E01仍BLOCKED_DEPENDENCY_B06。A唯一维护08/09/10。
- 真实PostgreSQL实例准备中；50产品功能、Host/Windows/现场QA未完成。A02_BLOCKED_LICENSE / NO_RC72_MAINLINE_MERGE / NO_BANK_ZIP。W0冻结绝非最终交付。


## W1 首轮真实实现验收（2026-11-10）
- WB-C01 PR #122 原源98292caf：Node3/3、Chromium1/1自测通过但F #123/ac5774a6独立发现P1无尾斜杠入口空白、P2键盘重绘丢焦点。保留真实红灯；修复源c699965f46276db30fcf1e11b4aa5e834b5dfcbd已补双入口/焦点反例，F复验中，未记QA_PASS。
- WB-B01/B02 PR #124 源617636424877f24a582d1c55e374553131c3d85a：真实PG本地12/12自测，远端同SHA w0-contracts PASS但postgres-identity FAIL（run42781440846/job129712176958）。状态CODE_COMPLETE/CI_BLOCKED，B正修复，F独立验收中；本地绿不能覆盖远端红。
- W0冻结源a73ed52d的设计签署保持；本轮实现尚未通过集成门禁，不能转移旧设计PASS。B06未实施，C02/E01 BLOCKED_DEPENDENCY_B06；D01 BLOCKED_FIELD；50功能/F01-F04/Windows/现场/许可证发布门禁未完成。
- 下一步：核销两组真实失败→F精确源接受→A唯一集成→同HEAD回归；不合RC7.2，不出银行ZIP。


## W1 B01/B02+C01 联合集成回归检查点（2026-11-10）
- 精确联合源cf11501866d7538167463f2c9e9c2951b67f57e0，真实父源B175efda6、C785c5a3c及F128/0ec59f7b独立复验报告已集成。F接受B01/B02数据库组件与C01导航骨架组件，不代表整个C01实施资格、50功能或F01/F02/现场通过。
- 原C路由/焦点缺陷已F复验关闭；B原外层BEGIN身份残留P1经真实PG反例关闭。旧CI认证与浏览器依赖失败保留，未删除反例。
- 本联合HEAD真实本地PG13/13、Node C01 3/3、Chromium1/1通过；通用合同276发现/263执行/13无DSN明确跳过，单独PG结果不得与skip混计。
- 同源远端：postgres-identity SUCCESS run42784572619/job129722479349；w0-contracts SUCCESS run42784572885/job129722480157；手动正式浏览器 SUCCESS run42784606902，headSha精确cf115018。不是历史源PASS转移。
- B01/B02 COMPONENT_QA_ACCEPTED / MERGED；C01 NAVIGATION_COMPONENT_ACCEPTED / MERGED。B03/B04依赖已满足启动真实关联施工，B05/B06顺序依赖；C02/E01仍BLOCKED_B06。C03/C04需业务资产HTTP合同/API，先补接口评审，禁止占位数据冒充实现。
- D01 BLOCKED_FIELD；真实DSH1.18.26、Windows/离线/实际AgentTeams并发/恢复、F01-F04、A02许可证发布门禁仍未满足。NO_RC72_MAINLINE_MERGE / NO_BANK_ZIP。


## B03/B04 与 Scope 准备组件集成（2026-11-10）
- B03/B04源c94a045da61683347999ed32619db7796766c07e获F130/6359121d独立组件接受：真实PG45/45、F攻击回归20/20，旧缺驱动导入红灯保留并修复。
- A联合源6dc36e2fd92919a469003d97662f5c72ace02b19真实PG45/45，远端PG SUCCESS run42789747684/job129739856195、W0 SUCCESS run42789747479/job129739851635。B03/B04 COMPONENT_QA_ACCEPTED/MERGED，B05已启动，B06尚未实施。
- C准备组件源46006d31由F132发现共享可变Scope引用P1；修复65f7d139109ff0080a910cd9441ac5f02bb0ceaa获F133/483f2026复验关闭，仅客户端状态机准备组件接受。当前A集成422d9433ea1b3438978a94b334b39c89389cc7fa，Node24+F负例1共25通过，远端新联合检查仍须同源核验。
- Scope组件未接UI或不存在的B06；C02/E01保持BLOCKED_DEPENDENCY_B06，不能宣称服务端权限或十区真联动已验收。后续B05接受→B06真实HTTP/DB→C02/E01纵向接入。
- 50项完整产品、真实DSH/Windows/离线/AgentTeams现场、F01-F04及许可证发布门禁仍未满足；不合RC7.2、不出银行ZIP。


## B05 正式组件验收与 B06 启动（2026-11-10）
- B05精确c8972dbdbd136f7da03061ee0463a47d68de6cb9获F135/a5343617独立接受，真实PG68/68、F新增攻击2/2；SST版本限定来源/内部身份唯一/BRVS可信连边/权限审计恢复组件通过，非完整产品验收。
- A联合111bc4806bb39f7bb44d857610d3b17878b23eac真实PG68/68通过；同源远端PG SUCCESS run42795365470/job129759080212，W0 SUCCESS run42795365782/job129759085711。B05 COMPONENT_QA_ACCEPTED/MERGED。
- B06正式启动真实PG Scope HTTP/授权/完整分页/签名游标/修订权限失效；尚未验收。C02与E01仍依赖B06验收，准备组件不能视为真实纵向链路完成。
- DSH现场/Windows离线/正式命令/AgentTeams真实并发及恢复/F01-F04/许可发布门禁继续未满足，不合RC7.2、不出银行ZIP。


## B06 组件集成与 C02/E01 准入（2026-11-10）
- B06精确f144f1a1492d457f0121dd77e23fdd8c474e4268获F138/20aa0068独立组件接受，真实PG/HTTP100/100、F新增攻击2/2；同源PG SUCCESS42796663148/job129763472502、W0 SUCCESS42796663127/job129763472380。
- A联合e901b2d8bda2e53f12a3c90028deeb54071f6741本地真实PG/HTTP100/100通过并推送，远端联合检查须另核；B06 COMPONENT_QA_ACCEPTED/MERGED，仅PG/HTTP Scope组件，不代表真实DSH认证或W1整体通过。
- C02正式日期/需求/版本/SST十区Scope联动与E01 R1只读适配已按组件依赖准入，隔离worktree/PR施工中。Host provider缺失默认503；测试provider明确fixture，不可替真实宿主现场。
- R1 Mission/Attempt/Evidence/NodeGate仍唯一运行事实，E01必须最小Mission身份校验先于明细，不可回写正式事实。50完整产品、F01-F04、DSH现场、Windows离线及许可发布门禁仍未满足，不合RC7.2、不出银行ZIP。


## C02/E01 与统一产品入口集成（2026-11-10）
- C139/cdfeb458获F141/3619b2e2组件接受：真PG/HTTP/Chromium1/1+Node24；E140/c00ca464获F142/b5e6f747组件接受：真PG/HTTP/持久R1 35/35+旧E82+F2。不改正式R1，Evidence只读校验，NodeGate UNKNOWN/发布HOLD。
- A联合574b54e1754c2c7b6de876ce4feb3c0f2870a12c本地E35/35、真浏览器1/1，远端PG/W0 PASS及专属E01 run42807484469、浏览器run42807492097精确同SHA均SUCCESS。首次PG venv缺playwright未执行保留，复用有效环境后重跑通过，未作产品失败或假PASS。
- 统一入口144/66a57fab获F148/905d036b接受：同源真PG/HTTP/Chromium1、E35、路由隔离攻击1通过，同源5CI成功。product_server静态界面与B/E校验handler同源，缺Host provider默认503、无旧API回退；旧admin兼容。
- A最新联合97917526bb875c276ee5541d0fb377c11f0d9580同源真PG/HTTP/Chromium1/1、通用合同398发现/264执行/134未配置PG明确skip；远端联合检查另核，不继承旧源数字。
- B07增量合同143/22fc88ff及D39e7bccd/E44828bf0职责签署已集成，里程碑真库/HTTP首slice独立施工中，尚无CRUD通过声明。
- C02/E01/统一入口仅COMPONENT_QA_ACCEPTED/MERGED，F01整体、真实Host认证/DSH1.18.26、Windows/离线、实际并发恢复、50完整产品及许可发布门禁未完成，不合RC7.2、不出银行ZIP。


## 现场环境访问约束（用户确认，2026-11-10）

用户确认行外无法访问真实DSH/Windows，必须搬运行内。现场状态统一 FIELD_NEEDS_BANK_TRANSFER；停止行外尝试真实现场访问，fixture仍只是组件测试。接续操作和证据字段见 BANK-TRANSFER-ACCEPTANCE.md。只在集中回归候选点准备搬运材料，不提前生成最终银行交付ZIP，不跳过D01/D04/F04或许可证门禁。


## 里程碑 API 与正式 Mission 图联合集成（2026-11-10）
- B07首milestone PR152/49063661获F153/072694aa接受：真实PG/HTTP141/141+F2。初源历史Scope可追加连边缺陷已加不可变link_count/延迟约束并复验；其余六kind尚在独立施工，B07整体不关闭。
- E02旧72dd3f9f由F150真实发现同批次跨Mission NodeGate引用P1；新1136bea2完整node/delivery/gate/ETU/workitem/attempt谱系校验，获F154/161398b4复验关闭，真PG/HTTP/R1 35/35及谱系攻击通过，原失败保留。
- A精确联合76d6d9c8583df1ed74e44a40b16b4f0d6351a1b5解决business_http共同路由冲突，保留资产与Mission查询：本地真PG141/141、E02 35/35、同源浏览器1/1、Node24；轻量475发现/265执行/210明确未配置PGskip，不混作真库结果。
- 同联合源远端：PG SUCCESS42815706578/job129828136986、W0 SUCCESS42815706397/job129828135567、专属E01/E02 SUCCESS42815837222、正式浏览器 SUCCESS42815845374。SHA均核实76d6d9c8。
- C里程碑UI PR156/a7fd0827正在F独立验收，未集成或记C03/C04整体通过。E03调查确认缺通用正式控制面，BLOCKED_FORMAL_CONTROL_API；依赖提案PR155，未写R1或伪accepted。E04–E06继续按正式依赖受控。
- 新增第三方实物审计THIRD-PARTY-WORKBENCH-AUDIT.json：Psycopg3.2.13安装元数据为LGPL-3.0-only（纠正旧or-later表述），依赖固定本次已验版本并记录许可证哈希；不是最终Windows包SBOM或LICENSE_RELEASE_APPROVED。
- 真实宿主与Windows FIELD_NEEDS_BANK_TRANSFER，接续见BANK-TRANSFER-ACCEPTANCE.md；不合RC7.2、不出最终银行ZIP。


## 草稿资产扩展与界面恢复缺陷（2026-11-10）
- 六kind后端4c3c30a1获F160/47574ed4独立组件接受：真实PG/HTTP190/190、F2；A联合d0ee15ad9f97ad1990a8eba43dcccab18d3071b3本地190/190，远端PG SUCCESS42822241991/job129850419532、W0 SUCCESS42822241919/job129850418701，精确同SHA。R1引用保持UNRESOLVED，未实现可信正式映射或B07整体关闭。
- C156/a7fd0827由F157发现未知提交刷新丢request_id；修复da1a7e82后原问题关闭，但F159/884d132f实际发现Alice旧pending在合法Bob会话重放产生新资产。当前C156不接受/不集成，必须B/D/C主体绑定context修复后新SHA复验。
- 最小context增量D/C6661e80d、B确认仅恢复主体域绑定；不授权限、不替代CSRF/ACL/真实SSO。后端和界面分支修复中，token缺失/换key/换主体保持HOLD，不以当前Bob context替换原请求。
- E03依赖提案0e8259cd已集成仅作DESIGN_REVIEW_PENDING；独立设计复核任务被平台内容检查中断，未产生F设计接受。E03仍BLOCKED_FORMAL_CONTROL_API，不新增伪accepted或第二状态机。
- FIELD_NEEDS_BANK_TRANSFER；正式Host、Windows、F01-F04及发布门禁未通过，不构建最终银行交付包。


## 主体绑定恢复修复集成与集中回归（2026-11-10）
- B161/3fc3c1a4与C162/37a025fa获独立F本地报告1728c731接受。A仅代推F原提交并建PR164，未代写结论；F本地16PG/HTTP、四browser、Node24、原F159主体切换反例通过。F157未知刷新与F159主体切换两P1关闭，旧失败记录保留。
- 每资产写入先验证可信Host/mutation及原opaque write-context，再进入业务连接；context不授权限，CSRF/ACL仍独立。未知pending固定原context/request_id，不以Bob或新key的context替换；Alice恢复同key原回执无重复。
- A联合d0fbd1ee9164b05d0516f24b44807a211bd2b860本地PG/HTTP206/206、真实browser4/4+原F1591/1、Node24；轻量540发现/265执行/275明确PGskip。该源远端PG SUCCESS42826010909/job129863371353、W0 SUCCESS42826011099/job129863372191、专属E SUCCESS42826008090与browser SUCCESS42826017673，headSha均独立核对d0fbd1ee。
- 首milestone详情/日历同资产生命周期与主体恢复COMPONENT_QA_ACCEPTED/MERGED；六kind界面在独立分支，不代表C03/C04完整完成。B07可信R1引用映射仍UNRESOLVED，未授全B07完成。
- E03提案B审查163/4c02b8af已集成，要求精确幂等/FK/CAS/fencing及丢权威回执的恢复查询。E03仍BLOCKED_FORMAL_CONTROL_API；正式writer跨进程原子准入尚待设计，不以实例锁或PG本地journal冒正式控制事实。
- FIELD_NEEDS_BANK_TRANSFER；最终交付/真实宿主/Windows/实际并发及F01-F04/许可证门禁未通过。


## A 发现同源挂载后的遗留私有路由缺口（2026-11-10）
- A在ebce951e本地临时R1/loopback真实复现：显式workbench_handler的Host provider返回None，新workbench Scope为403，但旧/api/missions/M_FOREIGN/overview仍200且含fixture Mission。没有访问银行网络或生产R1。
- 状态P1_FIX_IN_PROGRESS，E独立分支修复显式工作台模式的遗留私有读写默认拒绝，保留独立legacy模式及非敏感meta兼容。safe CLI不能因缺失R1而创建空文件；固定源后须F独立验证。当前尚未签署此缺口关闭。
- 六kind表单与只读项目目录仍在独立验收/施工，FIELD_NEEDS_BANK_TRANSFER及正式命令阻断不变。

## 2026-11-11 P04-01 年／月／日组件施工检查点

- 独立worktree `c-calendar`，分支`work/dsh-wb-c-calendar`；[PR #182](https://github.com/TongAITech/opencode-test-digital-employee/pull/182)完整候选源`1492a572fd4a50f1dce20815b69e3db437e40f2d`，实现源`810660377dbe5852711722527edadc03f7d1cc7d`。原C任务额度中断后由A施工，不代签C/F；CODE_COMPLETE / A_LOCAL_REGRESSION_PASS / F_REVIEW_REQUIRED / NOT_INTEGRATED。
- 当前合法Scope内复用真实PG里程碑资产，新增年/月/日视图、跨年/月导航、日期跳转及选日新建预填；不改变全局投产日期/batch/关联，不新增正式R1写入或第三方依赖。缺失/错误读取显示未知数量，撤权清空，迟到响应不回填；未知提交保留原请求恢复域。
- A本地：18项新日期边界测试；全部Node91/91；真实PG/HTTP/Chromium7/7；原F反例复跑5/5（不是独立F）；轻量561发现中269执行通过、292明确跳过。首轮延迟夹具捕获fetch位置错误、旧Scope夹具白名单漏两个模块导致的失败及修正均保存在[候选证据](https://github.com/TongAITech/opencode-test-digital-employee/blob/1492a572fd4a50f1dce20815b69e3db437e40f2d/docs/dsh-workbench/WB-C-CALENDAR-YMD-EVIDENCE-20261111.md)，未删用例或转成跳过。
- 同候选完整SHA远端：[W0 run42866382338](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42866382338) SUCCESS；[浏览器run42866382450](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42866382450)两个job均SUCCESS（含Node91和新增真实PG日历用例）。CI成功不替代F签署。
- P04-02独立日程管理、P04-03临期/逾期提醒、P04-04提测/冻结绑定仍未实现；权威BUSINESS_TZ未取得时不能用浏览者本地日期编造逾期。完整C03/C04仍不核销。
- PR #180断连补丁与#181绑定V2维持独立待审；真实DSH/Windows仅可搬运行内。F不可用期间不把A自测或CI当独立签署，不集成未经所需验收的候选，不生成最终交付包。

## 2026-11-11 本轮连续施工：独立验收与正向集成

- 起始远端aa533c21、RC7.2 edaf9290均重新核实；主线未写入。重新发起F/B/D后工具均正常，不能沿用上一轮“F额度不可用”的推断。本轮不再按单个PR结束施工。
- HTTP源47950777与F报告904493cf一起合入15c57c1c；F明确接受13项实际执行，包含真实RST后换主体/CSRF/撤权/原请求恢复，报告#183。
- 日历源1492a572与F报告3ac4d157一起合入9642f5b2；F除91 Node/7浏览器/5旧反例外，独立核对168个月格、5116个日期，并以真实PG验证分页末页坏日期、跨Scope/换主体未知写入、原键恢复、撤权及迟到清空。F报告#187，仅组件接受。
- B报告2f631331（#184）与D报告29df5051（#185）只以单独报告提交摘取到主集成。没有顺带合入V2。P1真实阻断和最小修订明确，E在独立V3工作区继续；纯编码/DTO与缺能力拒绝组件不必等真实Host现场。
- C06只读事实界面已实际实现并局部测试，仍在独立分支，待最新完整SHA的F独立验收。所有联合回归按新集成SHA另验，历史完整7586a80c资格不转签。FIELD_NEEDS_BANK_TRANSFER及最终发布NOT_APPROVED不变。

## 2026-11-11 连续施工第二阶段

- 运行界面#189精确f1b6b24e经F #193独立接受，已正向集成；整批次三路快照一致后才发布，筛选子集明确拒绝、外Mission/坏Gate/撤权/503/来源漂移整组清空。NodeGate PASS及文件哈希匹配不推投产通过。
- A合入后b6d93e41实测117 Node、8真实PG浏览器、5旧反例通过；轻量566发现273执行293跳过。f1候选实际PG223/E76通过。完整平台资格run42870053745四原生job成功、全继承源码job运行中，不能记最终全PASS。详见WB-A-PHASE-RUNTIME-UI-20261111.md的精确SHA分母。
- V3设计04ca9716经B94ee70bc/#192、Dcf74b3d3/#194、F35c43a55/#196仅准入纯组件，当前已集成文档；正式模型/创建及008不越过门禁。E #195新增纯codec候选，F旧c4发现P1保留#197，新a975修复与真实3.8/3.11 CI已通过，F复验进行中。B在隔离分支继续真实PG只读来源预览；正式创建仍未接通。
- 本轮没有按单个PR结束；持续调度已正常运行的B/D/E/F。原usage推断已纠正，不以旧状态替代真实调用结果。现场与最终发布未通过，继续施工，不生成最终交付包。

## 2026-11-11 连续施工：纯Scope与真实PG来源集成

- E #195严格codec只在8618676e修复两类真实P1并经F #201精确复验后合入。保留c4非hashable异常#197、a975非空SST过滤仍带UNSPLIT#200；不把原9/10测试通过转成完成功能。当前11原例+独立数百类型/组合/实库兼容及直接head真实3.8/3.11均独立确认。
- B #199源026ddff9及F #202仅准已批准project-only RLS/schema的内部只读预览；实际多req/version/SST来源和date/双revision已接通，但snapshot只是as-of候选，不是创建许可证。额外关系级RLS隐藏→假UNSPLIT诊断原样保留；未知/漂移schema未资格，最终锁端口与生产admission之前须补策略资格，不绕RLS。
- A在02ae2d80实测完整594 Python用例全部执行通过无跳过，117 Node、8真实PG浏览器通过。证据WB-A-INTEGRATION-02AE2D80-20261111.md；当前源码与这些结果逐SHA绑定，不签现场或全产品。
- 下一ready工单：PR198紧凑绑定pure parser/serialize/immutable设计，B对b61发现legacy outer有限浮点兼容P1，E新3266cb2d澄清仅scope域严格数字；B/D/F窄复签进行中，正式模型/reader/writer零改动。继续收齐新SHA准入后实际编码，不停在单个PR。

## 2026-11-11 连续施工：紧凑绑定纯模块完成

- 原b61设计B #205发现“全局拒绝float”会误伤合法legacy unknown outer 0.5/1e3；E新3266cb2d明确strict numeric只scope域，raw全局重复key/非finite规则只新helper不改现有reader。B612116f1/#206、De48f5800/#207、F67c358f8/#208精确复签；旧B P1与F204字段接受范围均保留，不互相抵消。
- E实现#209精确968430ed经F2c280269/#210独立接受后合入。新9/9+Scope11/11，独立609次拒绝数据检查（不是609个unittest）、完整709字节黄金/无IO/深不可变/3进程均验证，实际3.8/3.11各9项与显式head checkout已核实。A在73cdb971执行两模块20/20通过（0.321秒）。
- parser/serializer只处理紧凑绑定及scope片段，旧无绑定scope输出{}且外层Mission/release仍不可变；null/partial/flat-only/错镜像拒绝，未知outer有限数不被新scope模块改变。有效自造DTO仍只结构，不是正式事件/PG来源/Host证明。
- 该实现没有接入正式model/overlay/control/reader/writer、008或新正式事件。E下一候选#212只拟对未准入Scope Mission首业务副作用前HOLD，具体受保入口/mtime/Field-start/未封闭底层边界先跨组评审，再代码实施；不能把它或已通过纯模块当生产绑定完成。
- B在新隔离分支实现只读Scope schema/policy资格快照，D #211已提交项目/看板真实权限与字段候选；不修改已有已接受接口，不按单PR结束施工。FIELD_NEEDS_BANK_TRANSFER和RELEASE_NOT_APPROVED保持。
