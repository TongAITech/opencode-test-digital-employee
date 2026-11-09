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
| WB-A03 | A | W0 DESIGN_SIGNOFF：字段/状态机/负向合同、跨组可实现性评审（不得要求 W1 实库证据） | WB-A00 | CONTRACT_DRAFT / B-D-E_DESIGN_SIGNOFF_PENDING |
| WB-F00 | F | W0 独立 DESIGN_REVIEW（不是 W1 产品 QA） | WB-A01_DESIGN_SIGNED, WB-A03_CONTRACT_SIGNED | REVIEWED_WITH_BLOCKERS / WB-FG15_DESIGN_FIX_ACCEPTED / WB-FG16_FIX_PENDING_F_REVIEW |

## W1 — 最小真实业务纵向链路
| 工单 | Owner | 内容 | 依赖 | 状态 |
|---|---|---|---|---|
| WB-B01 | B | 投产日期与唯一性/变更历史，真实数据库 IMPLEMENTATION_QA | A03_CONTRACT_SIGNED, W0_DESIGN_FROZEN | TODO |
| WB-B02 | B | 系统/系统版本规范对象，真实数据库 IMPLEMENTATION_QA | A03_CONTRACT_SIGNED, W0_DESIGN_FROZEN | TODO |
| WB-B03 | B | 批次-需求/批次-版本关系 | B01,B02 | TODO |
| WB-B04 | B | 需求-版本多对多合法关系 | B03 | TODO |
| WB-B05 | B | 需求-版本-SST 关联及错误阻断 | B04 | TODO |
| WB-B06 | B | 跨分区 Scope 关联查询与分页 | B05 | TODO |
| WB-C01 | C | 六页面/十分区不缺失的导航骨架，真实 UI IMPLEMENTATION_QA | A01_DESIGN_SIGNED, W0_DESIGN_FROZEN | TODO |
| WB-C02 | C | 项目详情投产日期/需求/版本/SST 联动 | B06,C01 | TODO |
| WB-D01 | D | DSH 宿主版本/面板真实兼容性探测 | A00 | TODO |
| WB-E01 | E | RC7.2 R1 只读 Scope 与 Evidence 适配 | B06 | TODO |
| WB-F01 | F | 真实日期、跨版本、多 SST 纵向核验，独立 INTEGRATION_QA | C02_IMPLEMENTATION_QA, D01_IMPLEMENTATION_QA, E01_IMPLEMENTATION_QA | TODO |

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



### C 组 2026-11-10 W0 原创交互深化（不启动 W1）
- F #94 已对 A 75fd2c64159db863cfd1319d41a887785b556d40 完成独立复验：C 50 项/15 Node 与 156 W0 合同为设计期通过；FG17 FLAKY_OBSERVED / ROOT_CAUSE_PENDING、FG21 work/rc7.2 merge dirty；W0_NOT_FROZEN、A02 BLOCKED_LICENSE。不得把“F 审查完成”写成“F 接受/冻结”。
- C follow-up work/dsh-wb-ui-followup 仅做 W0 允许的原创原型深化：需求/系统版本/SST 多选关系过滤、不可变 Scope 快照、十区领域表单必填校验及 fail-closed 提交、逐区共享上下文浏览器验证。
- 新增 5 项 Scope 单测（累计 14 项）和 Playwright 逐区表单/多选/无结果搜索测试；最新 HEAD `d4863bab1cc65ed78b5c3d7edbf8e6e242c7b6a8` 的 [W0 job 129318183234](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183234) 20/20 Node + Chromium 逐区表单/多选/截图 PASS，artifact 13693719815；[B→C merge job 129318183968](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183968) 15/15 PASS。仅 W0 原型证据，C01/C02 不标 W1 完成，不连接旧 API 或 mock B06。

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
