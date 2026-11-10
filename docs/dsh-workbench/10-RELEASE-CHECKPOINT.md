# 工作台交付检查点

## 当前权威状态（2026-11-11）

- 当前代码集成检查点：`d31d8ef70229942215060bd58ef3b593b1b95be1`（PR #84）；本账更新会产生新文档HEAD，实际继续前重新核对远端与同SHA checks。
- W0设计冻结源`a73ed52d`及F #121保持历史结论。已正向合入RC7.2新基线`edaf9290`，未修改主线。精确`7586a80c`的ABCD-v4完整源码/Chromium及四组Ubuntu/Windows原生资格共五job全部SUCCESS（run42847197247）；F联合报告#173。该结论不转签d31或现场Windows离线安装。
- 本轮d31本地回归：真实PostgreSQL222/222、真实PG→浏览器6/6、目录键盘/撤权3/3、Node43/43；轻量561项中269执行通过、292明确跳过。A复跑F测试不构成新独立F签署；目录修复独立F源16fe658d、报告777b8bd7（#178）已集成。
- d31远端同SHA：W0 run42859333314、真实浏览器run42859326708均SUCCESS；本次新台账HEAD另核检查，不转签旧SHA。
- 六类草稿表单、B07七kind与E02读取为组件集成；旧legacy API隔离P1、目录键盘/撤权P2已按独立报告修复。完整项目编辑、看板业务状态、日历年月日视图、正式R1资产映射及生产纵向链仍未完成，不能把只读目录当项目管理全功能。
- HTTP断连P3候选`47950777`独立PR #180：A真实socket4/4、真实PG断连提交恢复1/1通过，尚未合入，F_REVIEW_REQUIRED。F任务额度不可用，不用A自测替代独立验收。
- 正式Mission绑定生产缺口已复现：正式创建无project/batch、typed更新丢extra；PR #175初稿、B #176及D #179有required details。新协议V2 PR #181源`957874d6`仅候选，B/D/E/F复签PENDING，未改R1/冻结模型。E03仍BLOCKED_FORMAL_CONTROL_API，B08/E04–E06等依赖未齐。
- 现场统一FIELD_NEEDS_BANK_TRANSFER（用户确认行外无法访问）；真实DSH/SSO、Windows离线、实际并发/资源恢复、F01–F04与LICENSE_RELEASE_APPROVED未通过。RELEASE=NOT_APPROVED；#84保持Draft，不生成最终交付ZIP。

## 初始与历史检查点（仅追溯，以当前状态和最新同SHA证据为准）

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



### C 组新增 W0 source fence 检查点（2026-11-10）
- FG23 C-side 修复：F #104 原真实 A+B+C 合并 CI `183/1 FAIL` 的 `C_BROWSER_RERUN_ON_LEDGER`，C 提交 `7fa4d0c`，仅移除 Chromium 工作流 08/09/10 PR 触发路径；新源同 SHA C 30/30 Node + Chromium + 3 PNG + B→C 30/30 + E W0 成功。[run 42733902992](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42733902992)、[artifact 13725373516](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42733902992/artifacts/13725373516)。**F 合并后全量策略复验仍未完成，不自行核销 FG23 或冻结 W0。**
- 同源实测：C #97 HEAD 15d37ec22e758922cab513a2d403be9211eddaf8；[W0 Chromium job 129545127122](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127122) 实际 30/30 Node PASS + 真浏览器交互 PASS + 3 PNG；[B→C job 129545127428](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127428) 30/30 PASS；[E 合同 job 129545126959](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943656/job/129545126959) SUCCESS。只核销 W0 源反例探针，不证明 W1/F02。
- artifact [13723922528](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/artifacts/13723922528)，scope PNG sha256 6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae；历史 6249f1a 测试漏跑事实保留。
- F 对本 follow-up 最新 UI 和真实截图仍独立审核待办；W0_NOT_FROZEN / A02_BLOCKED_LICENSE / C01_C02_W1_NOT_STARTED / NO_BANK_ZIP。
- C PR #97 维持六页面、十区、投产日期→需求→系统版本→SST 多选关系；新增源错误和迟到响应模拟，零真实 API、零假 QA_PASS。
- 第一轮 6249f1a 的 20 Node + 真 Chromium CI PASS 不覆盖新增10项；工作流修复已提交，需要新 SHA 30/30 与浏览器截图复核，不冒用历史绿灯。
- W0_NOT_FROZEN、C01/C02 W1_NOT_STARTED、F02_NOT_RUN、B06_NOT_IMPLEMENTED、A02_BLOCKED_LICENSE，禁止银行 ZIP。

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


## B 组 F 审查后提交检查点：WB-FG18（2026-11-09）
- F 独立审核显示 704c86a 设计 10/10、共同 68/68 成功但新增 SST 上游 ID 跨版本重复场景真实失败：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336677。B 已修复设计 DDL 的 source ID 唯一域及相应来源审计，补四个专门反例；核验必须使用修复后同 HEAD CI 和 F 独立重跑。
- 当前 W0 NOT_FROZEN、A #84 Draft、B #89 Draft、F #85 REVIEWED_WITH_BLOCKERS，FG17/FG19/FG20 等跨组阻断未关闭。B01/B02 真库未开始，PCC 现场、R1/Host/API/Windows ZIP 均未验；商业授权 BLOCKED_LICENSE。

- WB-FG18 CODE_FIXED_DESIGN_CI_PASS（历史修复 SHA eb48d161bd5c7caa29733fccfabc44654a376dd6）：B 14/14、W0+B 72/72、原 F pinned-SHA 测试 1/1；run 42637588144 job 129229772001。F 审查意见仍待，W0 NOT_FROZEN；当前提交只是追加已经成功的可审计记录。

## 第二轮 B/C/D/E 精确源 SHA 统一验收候选（F 独立复核必需）
- B PR #89 `98bac426a35063a306f4eaa4b43c80cf0a0a1745`：FG18 由 B 组自行修复，SQLite 约束新增全项目内部 sst_id UNIQUE、同系统版本来源键 UNIQUE，另设 `sst_source_trace` 保留 namespace/revision/source_ref；F 原始同 raw SST ID 跨版本反例需在当前联合树重跑。B 仍为 DESIGN_SIGNOFF，仅 W0。
- C PR #92 `4394f7fef7f19035220ea2398af9ff9f19a4b865`：新增 50 个 feature_id 差异表、15 项 Node 测试、原始证据与 B→C 隔离 Git 合并成功；这不是全功能 F02。
- D PR #90 `a332e6c575cac9d2b6ef0b2038615b276dcfa602`：13/13 基线合同、宿主 allowlisted manifest 检测、真实 loopback GET 负向，近期 D 同 SHA 30/30 局部 CI；不是行内 DSH1.18.26 FIELD PASS。
- E PR #91 `8401ab85cefb2876ce4451252d3d9a6e7d14704c`：新增旧 Admin R1 的只读合成/拒绝测试、B06 source-verified 合法关系 DTO 原型；无 /api/workbench/v1、SQL、SSE 或执行。E 新共享合同改为独立 `WB-E-A03-LEDGER-MERGE-HANDOFF.md`，A 上次已保留 E 原 08/09/10 增量。
- 上述改动需要 **统一合并树同 HEAD CI 和 F 独立复核**。FG17 CDP 定向测试仍须真实通过，不可通过 W0 轻量 CI 代替完整 CI。W0 NOT_FROZEN；BLOCKED_LICENSE；不推送运行主线、不出银行 ZIP。


## C follow-up PR #97（原始 W0 对账证据保留；旧 FG 状态由下文 A 最新段覆盖）
### C 组 2026-11-10 W0 follow-up 检查点
- 源基线 75fd2c64159db863cfd1319d41a887785b556d40；本轮仅新增原创 W0 原型交互，正式 C01/C02 未启动。
- 十区领域表单、必填字段、fail-closed 提交；多选 Scope 的合法关系过滤/级联清理/原子拒绝/不可变查询快照；浏览器脚本逐区核验共享上下文。
- 最新源 SHA d4863bab1cc65ed78b5c3d7edbf8e6e242c7b6a8 已获得同 HEAD W0 probe 20/20 Node + Chromium + 3 PNG 成功（run 42662706264，artifact 13693719815），以及 B→C merge probe 15/15 成功（job 129318183968）。F 对本 follow-up 新交互的独立视觉复核仍待；不得借用上一轮 A HEAD 的 L0 结果作为本 HEAD 证据。
- W0_NOT_FROZEN / A02 BLOCKED_LICENSE / FG17 ROOT_CAUSE_PENDING / FG21 MAINLINE_MERGE_DIRTY；无主线合并、无银行 ZIP、无 W1 QA_PASS。

## 2026-11-10 A 组同源集成与 F #101 检查点（新状态优先于历史快照）

- F 最新审查 A `b385e042c4543f5d918d61bff5e01be1d88afba7`：[F PR #101](https://github.com/TongAITech/opencode-test-digital-employee/pull/101) 与 [审查意见](https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6754968337)。FG17 Python3.8/3.11 真 Chromium+adapter 31/31 各自成功、Py3.8 教学五次 0 failure；R4 100/100 源码靶向成功；**FG22 W0 159/1 FAIL、F 164/1 FAIL 仍是历史真实红灯**。
- FG22 A 代码修复 `5bba94c213e2d54a83f8aa360b0f3d71ea8d26a1`：统一 Q1 validator 拒绝码，另验用例缺失和 Draft 假运行，不删除负向测试；**新集成 HEAD 的 CI 结果必须另验**。
- FG21 Git 冲突已解决，RC7.2 R4 基线 `87f956f1388f58beabf7116c937fd6fda5fae2ca` 已作为 A b385e04 第二父提交合入 W0；PR #84 mergeable=true，但 CI unstable 非 release ready。R4 逻辑名册32/默认 active4，不是银行现场 32 并发。
- 本次 B #95 领域复签 @ `67c4fc592f290710d6242aef2d4144000e7d82fd`、E #96 R1 consumer @ `c70ad0da92c5a4899a72d3096fad5e46fded74d5`、C #97 原创 UI 原型 @ `78837f45d01acc9fdddc4daffa9e575804c542dd` 纳入 A 候选，保留各组独立 PR 供 F 审查；B06 只读 Scope 使用服务端可信主体、source_refs、顶层 next_page_cursor，E 检查显式 Mission project+batch。
- C 原型最新可重复源 d4863ba：20/20 Node、Chromium 六页十区多选及表单、3 PNG 通过，F 后续视觉独立复查和正式 F02 尚未进行；B 23/23、E 47/47 属各自源 SHA，不预填联合 HEAD 绿灯。
- A 当前集成源码的 W0 155+/FG22 新测试/F 独立边界仍需同 SHA 运行；PR #84 继续 Draft，W0_NOT_FROZEN、A02 BLOCKED_LICENSE、B01/C01/E01 真实实现 NOT_RUN、无现场 DSH、无 Windows 离线 ZIP、不得合并运行主线。


## 2026-11-10 A 组最新 B/C/E 合并候选—检查点
- 当前源任务：B #95 最新 `50bd16d9e2c321eb5eaa21e96f663e89ae377b34`，C #97 FG23 整改 `b2a64df65661880808510d0486f6aefc70ca23df`，E #102 全分页 `26b2deaf5485193133e418da81982291c8056d64`，A #103 W0 source fence CI policy `d082e71f7eb9260afe450203bd160f8cd9e65948`；集成 A `work/dsh-wb-w0` 保留父提交来源。以 PR #84 新 HEAD 与同 SHA workflow 为唯一新验收结果；旧 B26、E68、C30、A181 成功不可自动挪用。
- **F #104 发现 FG23 的原始失败** https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/job/129552134247 保留，C 仅提交 CI PR paths 修复，同源 Browser+30Node 源工作流成功 https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42734198368；需新联合 HEAD F recheck；仅改 08/09/10 的 PR synchronize 仍可能因累计差异触发浏览器，CI 经济优化需单独实测，不宣传已完全消除。
- 新源 CI 在明确完成前状态 `NEW_HEAD_W0_CI_PENDING / F_W0_DESIGN_RECHECK_REQUIRED`；W0 非产品 QA；B06 真 API、R1、DSH Host1.18.26、PostgreSQL、32真实团队、Windows免安装都不在这里验收。
- **W0_NOT_FROZEN, A02_BLOCKED_LICENSE, W1-W4_QA_NOT_RUN, NO_RC72_MERGE, NO_BANK_ZIP**。正式 L1/L2 在 release-ready 同 SHA 准入；不得以本轮减负抹去真实 Q1/FG17 负例。


### A 组 `db1026fd` W0 同源回归 checkpoint（2026-11-10）
- 原 C #97 FG23 浏览器 PR paths 回退，F #104 于旧 A+B+C 源发现 183 tests /1 FAIL `C_BROWSER_RERUN_ON_LEDGER`；A 在新联合 SHA `db1026fd1036d2e0b00853f56383e89b8bb0b9d0` 实测 [job 129563488731](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42735465054/job/129563488731) **Python 206/206、Node 30/30、CI Policy 13/13 通过**。这是 A 持有的同 HEAD L0，F 对新联合源复核尚未签。
- 同一 Git commit 的父提交包含 B #95 50bd16d（verified sst_source_trace）、C #97 b2a64df（SourceReadFence 30 Node/FG23 修复）、E #102 26b2dea（B06 all-pages consumer）、A #103 d082e71（scope fence CI policy），不把旧子组绿灯冒充本 HEAD；三本账与 A03 已同步。
- W0 设计未获 F 独立 ACCEPT，PR #84 仍 Draft；W1 B01/B02/C01/E01、真 PostgreSQL/DSH Host/HTTP/R1/32 Teams/Windows 免安装未进行；商业 PolyForm Noncommercial 源码不得复制进入银行交付，A02 BLOCKED_LICENSE，最终正式交付仍 BLOCKED。


## 2026-11-10 F #106 最终 C W0 验收 / A01 双语保留检查点
- F #106 在精确 A `a3555b187eb35d27a2d712313dd8ea7daa28915f` 源 [run #42740012204](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42740012204) 独立验收：206/206 Python、30/30 Node、FG16 2/2、FG18 1/1、21/21 CI 负例、原型真 Chromium PASS，3 张 PNG F 已目视；**FG23_CLOSED、FG20_DESIGN_RECONCILIATION_PASS、C_W0_PROTOTYPE_REVIEW_PASS**。该结论不覆盖 W1 50 功能。
- A01 产品范围决定 `KEEP_ZH_EN_W1_REQUIRED`：保留 `P05-03` Skill 双语说明与 `X01-01` 完整中英文/浅深系统主题，中文为 W0 默认；W1 C/D 正式实现与 F02 真实验收必须覆盖 `zh-CN,en-US` 12 个正反例。只标记 `A_SCOPE_RECORDED_F_DESIGN_REVIEW_PENDING`，没有擅自签 `WB-A01_DESIGN_SIGNED` 或 `WB-F00_DESIGN_ACCEPTED`。
- A `fc2619d` 范围合同单测真实 [run #42743331421](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42743331421) **218 Python、30 Node、CI policy 13 PASS**；完整产品 QA/许可证/现场仍不同门槛。W0_NOT_FROZEN、A02 BLOCKED_LICENSE、NO_BANK_ZIP。

## 2026-11-10 A01 原版语言入口真实性设计核查检查点
- **唯一正式双语合同：** `WB-A01-LOCALE-SCOPE.json`（`KEEP_ZH_EN_W1_REQUIRED`），不另建第二套语言设计。A 原先并行 PR #109 已关且未合并，以最新 A `b4bea4a405a2325fbbf7f59e29fa6e6cf2017b68` 作为本轮补强源。
- 新增 upstream 固定 SHA `fc5a054a48973d004580a3cc1de60da3f701150b` 和 `public/i18n.js`、`public/app.js` 语言 picker 只读锚点，拒绝主题开关冒充语言实现、未授权源码误标 MIT、来源 SHA 脱钩以及删除真实设置入口；所有官方 12 条 W1 中文+英文真实 UI/Host 资格均 NOT_RUN。
- F #106 已证实旧 A@a3555b1 C 原型/FG23 的 206 Python、30 Node、FG16 2/FG18 1 和真实 Chromium；**不推导本增量源码或 A01 英文实现已获 F 接受**。本 PR 需最新 HEAD 同源 W0 L0 与 F 单独增量审计。
- `W0_NOT_FROZEN / A02_BLOCKED_LICENSE / B06/C01/E01/D Host/Windows FIELD_QA_NOT_RUN / RC72_NOT_MERGED / NO_BANK_PACKAGE`，不构建银行交付物。

## 2026-11-10 A01 来源合同合入检查点
- A01 精简 PR #110 已合并至 W0 candidate：`afcda9a5737e181a1d1d5e08f926943664c594d5`，不是运行主线 `work/rc7.2`。重复 PR #109 未合并即关闭，A 的既有 12 条 W1 正反例和 50 个功能合同保持唯一来源。
- 该合并 HEAD 的 [GitHub W0 fast CI run #42744769517](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42744769517) 真实 225/225 Python、30/30 Node、A01 locale PASS、policy 13 PASS。只核销设计层，而非 W1 bilingual UI QA_PASS；完整 Q1/L1/L2/Windows Host 现场不由该运行覆盖。
- F #106 对旧 A@a3555b1 的 C 原型接受继续有效但**不能自动承诺新增 A01 源码锚点已审完/整体 W0 已冻结**。产品仍 50/50 NOT_RUN，A02 `BLOCKED_LICENSE`，`W0_NOT_FROZEN / PR84_DRAFT / RC72_NOT_MERGED / NO_BANK_PACKAGE`。

## 2026-11-10 A/B/E Round-1 安全整改统一检查点
- **旧 F 审查源：** F #111 A `f870ad5` 225 Python/30 Node/真 Chromium；B108 30 定向+210 W0，旧 E107 73 E+211 W0，临时 overlay 234 Python+30 Node。此阶段 F 发现 E P1 先读 R1 details 后校验 Mission Scope，结论 `W0_NOT_FROZEN`。历史 E P1 记录保留。
- **新 B 集成：** #108 @ `b801c25bbec361e6a791c561d5a7dd0ec9440aaf`，F 已签 W0 领域设计见证；不具备生产 Postgres 关系迁移或真实 B06 状态推导 API。
- **新 E 集成候选：** #107 @ `a04933fbe7b651c10b589b90cade5da65bdd8b81`，AdminProjection R1 Mission identity-only scope-first query，拒绝时 related query 0，老 unscoped API 无 fallback；[E 单 SHA W0 239](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42752449330/job/129618982111) / [Python3.8+3.11 各82](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42752443232/job/129618962172) 为独立分支的工程证据，**F 必须对新 A 精确 HEAD 独立签核 E P1**。
- A 单一 Draft 集成分支 `work/dsh-wb-w0` 维护唯一 08/09/10 并保留 B/E 独立 Git 父提交。另将 00/02/03/04/05/07 “W0 候选冻结”状态统一改为 `W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN`，避免代码状态与合同不符。
- **任何 L0 PASS 不自动签 `WB-F00_DESIGN_ACCEPTED`**：A01 双语 W1 NOT_RUN，A02 `BLOCKED_LICENSE`，B/C/D/E 真实 PostgreSQL/API/R1/Host/Windows/W2-W4 和 50/50 产品功能均未完成；PR #84 保持 Draft，禁止 RC7.2 主线合入和银行 ZIP。

## 2026-11-10 A 同 HEAD CI 证据校验施工检查点
- 核实旧源：PR #84 OPEN/DRAFT、HEAD f6aa541a7c82b74bcd1937754637d8341111fb70；target 87f956f1388f58beabf7116c937fd6fda5fae2ca，ahead=167/behind=0，GitHub check-runs 15 条仅 w0-contracts success、另外 14 skipped。旧 job https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42754283361/job/129624916743 只属于 f6aa541a。
- A 新增标准化只读检查工具 tools/dsh_workbench/w0_checkrun_evidence.py，严格按完整 JSON snapshot 和 40 位源 SHA、required status=completed/conclusion=success 核对；14 个 skipped 不可计 PASS。纯函数结果一律 product_qa_pass=false、f_independent_approval=false、license_release_approved=false。tests/test_dsh_workbench_w0_checkrun_evidence.py 提供敌意输入反例。
- 新提交后必须查新 HEAD 实际 GitHub Actions checks，原始 f6a 的成功不自动转移；F 对 E107 P1 和 W0 全局冻结仍需独立复核。A02 BLOCKED_LICENSE、W1–W4/50项产品 NOT_RUN、PR DRAFT、不可合 RC7.2，不得构建或银行交付 ZIP。


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
