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

## B 组 WB-A03 W0 签署交接（2026-11-09）
- task=WB-A03-B-DESIGN_SIGNOFF；owner=B；source_sha=80efa1bfa585fe29a5939c889d5b5a08e4f742ed；branch=work/dsh-wb-domain；artifact=WB-B-A03-DESIGN-SIGNOFF.md、02/06 增量、tests/test_dsh_workbench_b_a03_design.py；PR / CI 结果必须用各自真实 HEAD 复核。
- status=B_DESIGN_SIGNOFF_SUBMITTED；W0_DESIGN_FROZEN=NO；B01..B08 REAL_IMPLEMENTATION_NOT_RUN；正式 PostgreSQL/API/R1/银行 FIELD_QA=NOT_RUN；A/F review pending。
- open=BUSINESS_TZ_APPROVAL / SOURCE_MAPPING / D_E_SIGNOFF / F_DESIGN_ACCEPTANCE / BLOCKED_LICENSE / FG16_RECHECK。
- next_ready：A/F 完成 W0 冻结及跨组合同合并后，B01、B02 可进入 READY 并开展真实 schema/事务开发；再 B03→B04→B05→B06（供 C/E 消费），B07→B08。绝不将 SQLite 设计见证写成真实 W1 QA_PASS。

- W0 B 实际红测：GitHub workflow run 42620348983 / job 129170552735 在 SHA 8a7a11612327bf237f8d0df6a72c127384b7b0ed 失败（8 项：7 pass / 1 fail），原因是 BRV 缺独立来源认可需求—版本关系；B tests 已在 d0a38886048bd2183ef364295e6204eb6a742257 增强双层来源 FK。最新 HEAD CI 待核，不沿用绿色历史结果；W1/F QA 仍 NOT_RUN。
