# 工作台交付检查点
状态：W0 文档阶段；不是已交付产品
基线仓库：TongAITech/opencode-test-digital-employee
基线分支：work/rc7.2
初始源码 HEAD：3de74c2bf3a0f3a555ccd979edd2832f26c9963a
独立设计分支：work/dsh-wb-w0
当前已验：原版六页面/十分区从公开源码与指南核对；RC7.2 01/04 设计合同及 rc7_admin/server.py 当前接口核对；11 份 W0 合同已通过 GitHub API 写入分支并建草稿 PR。
未验：工作台真实 UI/API/数据库、现场宿主、商业授权、批次数据、人工门禁、Windows ZIP。已核实 fd9e60e 同 SHA 28/28 checks 及 W0 32/32，但新 HEAD 必须另验。
当前 W0 工单：WB-A00 CODE_COMPLETE，草稿 PR #84（https://github.com/TongAITech/opencode-test-digital-employee/pull/84）F 组已初审带阻断意见，待新 HEAD 再审；35 个工单中其余未核销。
下次会话入口：先核对最新 HEAD/PR/check-runs，读取 00–10，核销 W0，按工单依赖继续；不得凭本文件旧 SHA 直接施工。
交付声明必须明确“设计完成”“代码完成”“CI 通过”“现场通过”四种不同状态。

## C 组基于 F #85 复审的最新检查点（2026-11-09）
- C 先前原型 HEAD `e9094bf5267ebc840ffae6bf3e8a707380ecaf7f` 已获得 F 独立 **W0_DEMO_BROWSER_CI_PASS** 认可：Node 9/9、真实 Chromium 与截图 3 张，[CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622464425)；F 未独立解包截图进行视觉逐项审查，也不接受 50 功能 PASS。
- F 新增 FG20 已指向 C 历史 47 项与 A01 当前 50 项不一致。本轮新 `WB-C-W0-50-FEATURE-DELTA.md` 对 50 项逐 ID/类别/动作/演示范围及 50/50 正式 `NOT_RUN` 核对，并增加契约反例。验证以新 HEAD workflow 为准，未完成前状态 CODE_SUBMITTED。
- FG19 多组账本合并真实冲突：保留全部 C 历史 W0 账本内容，调整 C 独立记录插入位置，新增 B→C ephemeral Git merge CI。**仅 C 冲突预修，不代表 A/B/C/D/E 单一 SHA 或 F 接受**；B FG18、E 的签收文档与账本冲突、A FG17 仍须相关负责人修复。
- F 最新结论 REVIEWED_WITH_BLOCKERS；A02 BLOCKED_LICENSE / W0_NOT_FROZEN / C01&C02 NOT_STARTED / NO_BANK_PACKAGE / NO_MERGE_TO_RC7.2。

## 2026-11-09 A 组持续检查点
- work/rc7.2 @ 3de74c2bf3a0f3a555ccd979edd2832f26c9963a；草稿 PR #84 OPEN，Review=0，未合并。
- W0 原始 HEAD=12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8；首个实际代码提交=4046029591b0b324e6a33028629dc22034d511d0；修复通知路径提交=82c18fdd93867e7d27107f665e124c5edcae8b2c。
- 首轮同 HEAD 轻量 CI: https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582069489 运行 32 个，30 通过、1 失败、1 错误。此处不写 CI_PASS；必须重新检查后续 HEAD。
- WB-A00 文档/PR 产物确认 CODE_COMPLETE；WB-A01 候选功能清单确认，实际页面未实现；WB-A02 BLOCKED_LICENSE；WB-A03 跨组签收待完成。F 尚未签名，W0=NOT_FROZEN。
- 银行真实部署、DSH 宿主、Teams 32 并发、实库映射、R1 真实 API、F 现场 QA、全量 Windows ZIP 均未验，本轮不构建/不合并/不放行。

## A 组 2026-11-09 新检查点（优先于上面旧快照）
- 历史主线 work/rc7.2 @ 58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d（PR #83 的 32 队员容量源码侧改动）；不证明现场 Agent Teams 32 实并发。合入前须重新查询最新主线 HEAD。
- PR #84 OPEN/DRAFT/NOT_MERGED；F PR #85 OPEN/NOT_MERGED；F 审核 A HEAD fd9e60e 后结论 REVIEWED_WITH_BLOCKERS / W0_NOT_ACCEPTED。F 证据：https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6736506135。
- 历史 GitHub 同 SHA CI：fd9e60e 28/28 checks SUCCESS、W0 32/32；A 加固提交 3fc09ca W0 38/38 SUCCESS（https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42595773766/job/129087916062）。**本次文档新 HEAD 的全部 CI 结果必须重新核查，不能沿用上述结论。**
- WB-A00 代码/PR 存在及 F 初审已确认，尚未满足 F 最终接受；WB-A01 原子功能清单设计候选、UI NOT_RUN；WB-A02 BLOCKED_LICENSE；WB-A03 B/D/E/F 签收 PENDING，真实接口/迁移/事件 NOT_IMPLEMENTED。
- W0_NOT_FROZEN / NO_BANK_PACKAGE / NO_MERGE；禁止将本次文档和纯函数 W0 Oracle 说成业务领域、实际工作台、宿主现场或 F QA_PASS。

## 2026-11-09 WB-FG15 W0/W1 门槛环修复检查点
- F 最新审查 A HEAD `6edb9fb7e3901bb8a72706c5522ce759b0318672`，同 SHA 28/28 checks success，W0 39/39 tests success；F 发现 **FG15 P0** 并记录在 [PR #85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85) 的 `WB-F00-HEAD-DELTA-6EDB9FB.md`。结论仍 REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN。
- A 本轮修订分离 `A03_CONTRACT_SIGNED`（W0 B/D/E/F 设计签署）与 `B01_IMPLEMENTATION_QA_PASS`（W1 实库）及 `F01_INTEGRATION_QA_PASS`（真实纵向链路），使用独立 JSON DAG、Python 验证、负向测试，防止复发；不允许设计签收充当产品 QA。
- `W0_DESIGN_FROZEN` 必须等 F 对新 HEAD 接受及 B/D/E 正式签署；签署仍 PENDING，不得自动状态晋升。
- 银行交付独立门槛 `A02_LICENSE_RELEASE_APPROVED` + `F04_FIELD_QA_PASS`；商业许可/原创来源审查仍 BLOCKED_LICENSE，未构建/未放行 Windows ZIP。
- 本段记录的是提交前设计整改意图，**新 HEAD 及同 SHA CI 以真实 GitHub API 结果为准**，不得重用 6edb9fb7 的绿色结果。

## A 对 F 组 FG16 的最新整改快照（本次 HEAD 自证后才可更新）
F 已在 PR #84 对 A `4349ee6` 复核 28/28 CI、48/48 W0 tests；接受 FG15 设计修复，FG16 发布依赖遗漏 P0 OPEN。本轮 A 新增 W2/W3/W4 Gate 及必需的 F02/F03/D04/F04/A04/LICENSE 发布闭包校验，更新 08/09 及负向单元测试。
**F 对最新 HEAD 尚需独立复验，B/D/E 的 W0 DESIGN_SIGNOFF 尚未获得，A01 源码入口锚点仍需补，A02 商业授权或原创来源审计仍 BLOCKED。W0_NOT_FROZEN / NOT_MERGED / NO_BANK_PACKAGE。**

## 2026-11-09 当前 A01 / FG16 改进检查点
- A 组当前 W0 基线演进：`16740b7` FG16 W2–W4 DAG 闭包；`80efa1b` FG16 全路绕过反例；`515f6a3` A01 原版源码行号锚点。功能原子登记共 50 项，其中 35 项参考原版固定源码入口，15 项为新增目标，不是目标 UI PASS。
- 最近验证成功事实：`515f6a3` 的 W0 定向 job #129168577337 **58 tests OK**；提交后要检查新 HEAD 28 项 CI，不可拿旧 HEAD success 报全绿。
- F 上次结论：FG15 DESIGN_FIX_ACCEPTED、FG16 P0 OPEN；待独立复验最新 A 代码。B/D/E W0 设计签署 PENDING，A02 LICENSE BLOCKED；**W0 NOT_FROZEN / PR #84 DRAFT / 不合入、不打银行 ZIP**。


## B 组 WB-A03 W0 签署交接（2026-11-09）
- task=WB-A03-B-DESIGN_SIGNOFF；owner=B；source_sha=80efa1bfa585fe29a5939c889d5b5a08e4f742ed；branch=work/dsh-wb-domain；artifact=WB-B-A03-DESIGN-SIGNOFF.md、02/06 增量、tests/test_dsh_workbench_b_a03_design.py；PR / CI 结果必须用各自真实 HEAD 复核。
- status=B_DESIGN_SIGNOFF_SUBMITTED；W0_DESIGN_FROZEN=NO；B01..B08 REAL_IMPLEMENTATION_NOT_RUN；正式 PostgreSQL/API/R1/银行 FIELD_QA=NOT_RUN；A/F review pending。
- open=BUSINESS_TZ_APPROVAL / SOURCE_MAPPING / D_E_SIGNOFF / F_DESIGN_ACCEPTANCE / BLOCKED_LICENSE / FG16_RECHECK。
- next_ready：A/F 完成 W0 冻结及跨组合同合并后，B01、B02 可进入 READY 并开展真实 schema/事务开发；再 B03→B04→B05→B06（供 C/E 消费），B07→B08。绝不将 SQLite 设计见证写成真实 W1 QA_PASS。

- W0 B 实际红测：GitHub workflow run 42620348983 / job 129170552735 在 SHA 8a7a11612327bf237f8d0df6a72c127384b7b0ed 失败（8 项：7 pass / 1 fail），原因是 BRV 缺独立来源认可需求—版本关系；B tests 已在 d0a38886048bd2183ef364295e6204eb6a742257 增强双层来源 FK。最新 HEAD CI 待核，不沿用绿色历史结果；W1/F QA 仍 NOT_RUN。

- WB-A03 B 组 CI 校验：B PR #89 HEAD 历史 SHA 7b916e295d8f8461a8134ed2da9583ecb897022a，run 42620657398 job 129171616901，B SQLite 8/8 SUCCESS、W0+B shared 66/66 SUCCESS。该结果只属于上述 SHA；当前账本提交的新 SHA 仍须另查。B_DESIGN_SIGNOFF_SUBMITTED / DESIGN_CI_PASS_HISTORY，W0_NOT_FROZEN、W1_NOT_RUN、F_QA_NOT_RUN、BLOCKED_LICENSE。


## C 组独立 W0 验收检查点（2026-11-09，尚待 PR/CI 核验）
- 原创产品能力对账文件：`WB-C-W0-ORIGINAL-UI-AUDIT.md`；原子候选覆盖六页面、十个项目分区、跨区 Scope、中文、主题/搜索、表单、对话、异常与组件/API；参照原版固定 SHA `fc5a054a48973d004580a3cc1de60da3f701150b` 只读行为。
- 隔离的静态 W0 原型、9 个 Node 单测、专用浏览器/截图脚本与独立 CI 配置均位于 C 分支；本地 9/9 PASS，不代表产品 QA。具体命令/失败日志/截图状态见 `WB-C-W0-TEST-EVIDENCE.md`。
- 本地浏览器访问受环境策略阻挡，`ERR_BLOCKED_BY_ADMINISTRATOR`；当前 **SCREENSHOT_NOT_CAPTURED、BROWSER_QA_NOT_RUN**。只能在真实 CI 出具 artifacts/job/SHA 后另行核销。
- A01 设计审查与 B/D/E A03 签收未闭环，F W0 设计未接受；C01/C02 仍 TODO、B06 未完成、E02 未完成；不合入 RC7.2，不构建离线 ZIP、不发布；A02 许可证 `BLOCKED_LICENSE` 不变。

## C 组 W0 Probe 同 SHA 成功检查点（非正式 F QA）
- SOURCE `465d1006e1b0f8d9ce537436d46912e527d9d096`：[GitHub job 129176561107](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622094284/job/129176561107) 9/9 单测、真实 Chromium demo 交互与 3 张截图上传均 PASS；artifact ID 13675694071，3 个 SHA256 见 `WB-C-W0-TEST-EVIDENCE.md`。
- 旧本地 `ERR_BLOCKED_BY_ADMINISTRATOR` 及首次 Ubuntu26.04 依赖失败仍记录为历史事实；最终浏览器演示以同 SHA GitHub job 为准。**不等于**六页十区完整原版功能、正式 B06/E/R1/Host/F02 通过；C01/C02 TODO、A02 BLOCKED_LICENSE，W0 NOT_FROZEN。F 对本轮新 PR 仍待独立评审。


## 2026-11-09 E 组来源审计及 W0 设计签署（需 A/F 复核）
- W0 PR #84 审核来源 HEAD `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`；F PR #85 仍 REVIEWED_WITH_BLOCKERS。E 施工分支 `work/dsh-wb-runtime` 对独立控制面协议形成 `E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS`，详见 `WB-E-A03-DESIGN-SIGNOFF.md`。E 分支实际提交 SHA/CI 必须以创建 PR 后同 HEAD API 结果更新，不借用 A 的历史 success。
- 已核对真实 `rc7_admin/server.py`, `product_server.py`, `projection.py`, `rc6_runtime/truth.py`, `rc7_runtime/rc72_domain.py`, `rc72_linkage.py`, `models.py`, `truth_overlay.py`, `derived.py` 的 blob SHA；旧 HTTP 没有可信项目 ACL、正式命令、SSE 或 `/api/workbench/v1`；R1 是 JSONL 原子事实源；Evidence content_hash 可选。对应实现 HOLD 见 09。
- E 的 W0 独立设计测试包含跨项目/跨批次越权、请求伪 principal、幂等/修订冲突、事件水位/改包/撤权、hash 篡改、人审/NodeGate 假 PASS、Attempt 缺 lease/trace。**仅 W0 内存 oracle，不是 HTTP、DB、真实 SSE、持久 R1、行内 DSH 和 Agent Teams 现场验证。**
- WB-E01 BLOCKED_DEPENDENCY_B06；E02–E06 NOT_STARTED；E07 OPTIONAL_NOT_ADMITTED。A02 BLOCKED_LICENSE，W0 NOT_FROZEN，PR DRAFT，禁止合并主线或构建银行 ZIP；F 未独立 QA_SIGNOFF。

## A 组 ABCDE 唯一集成候选检查点（当前文件未承诺最终 CI 全绿）
- source parents: A `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`; B `704c86aaf9b2c5a9b9b4088648ccd0c50204f2f8`; C `e9094bf5267ebc840ffae6bf3e8a707380ecaf7f`; D `f0b7faeb22f9bf03d2487061a8f81a2776a5213d`; E `bee612b2dd94a6040404db4b9a4a5fd816e136dd`. F 独立基线 `work/dsh-wb-qa@5111044d87a97120d57cddc1b6d3c8e177502c2f`，原始审查见 PR #85。
- 施工目标：构建一个带五个父提交的 A HEAD，完整集成 B/C/D/E 新文件与 A03/02/06/08/09/10 合同差异，并增加 F 发布闭包测试及 SST 原始身份跨版本重用反例；该 SHA 的新 CI 必须另验，不得重用此前各分支 PASS。
- F FG16 静态修复已独立接受；FG18（B 来源 SST 设计）、FG19（同 HEAD 合并）与 FG20（C 清单）的修订须 F 独立核销；FG17 RC7.2 CDP 完整 CI 失败尚无根因，禁止 FINAL_CI_PASS。
- B/D/E W0 设计签署附件已纳入候选，但 B 的 FG18 来源域语义改动须 B 复签，F 的整体 W0 设计独立接受尚未获得。W0_DESIGN_FROZEN=NO，A02=BLOCKED_LICENSE，W1–W4 真实运行 NOT_RUN，主线 work/rc7.2 不合入/银行 Windows ZIP 不构建。
