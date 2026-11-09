# WB-F00 独立增量验收 — A 组新 HEAD 6edb9fb7

**Date:** 2026-11-09  
**role:** F Independent QA  
**target PR:** #84 `work/dsh-wb-w0` → `work/rc7.2`  
**source_sha:** `6edb9fb7e3901bb8a72706c5522ce759b0318672`  
**compare_base:** `fd9e60e3069a913547edbaa3a880cd5cc855d5de`  
**F output:** PR #85，`work/dsh-wb-qa`  
**result:** `CONTRACT_CI_PASS / REVIEWED_WITH_BLOCKERS / W0_NOT_ACCEPTED`.

## 独立检查输入/证据

- GitHub Compare `fd9e60e...6edb9fb`：2 commits，11 个增量文件（01/02/06/08/09/10，三个新 A01/A02/A03 文档，W0 Python 代码及测试）。
- 读取新 HEAD 的 `00`、`01`、`02`、`06`、`07`、`08`、`09`、`10` 以及 `WB-A01-ATOMIC-FEATURE-REGISTER.md`、`WB-A02-LICENSE-BOUNDARY.md`、`WB-A03-CROSS-GROUP-SIGNOFF.md` 和新增/修改测试代码。
- `GET /commits/6edb9fb.../check-runs?per_page=100`：28/28 completed/success；W0 checks 两个成功。
- 抽查同 SHA 的 W0 job 原始日志：`Ran 39 tests in 0.011s`、`OK`。**不是上一个 SHA 的 38 tests**。证据：<https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42596712939/job/129091014781>。执行命令：`python -m unittest discover -s tests -p 'test_dsh_workbench_w0.py' -v`；Ubuntu CI/Python3.11；只代表设计期 Python Oracle，不涉及真实数据库/HTTP/UI/行内 Windows。
- `work/rc7.2` 真实主线 HEAD 查得 `58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d`；PR #84 当前为 OPEN/DRAFT/NOT_MERGED；主线相对原初基线已有变化，今后合并前应基于最新主线进行兼容回归。

## F 逐工单复核结论

| 工单 | 本轮观察 | F 结论 |
|---|---|---|
| WB-A00 | PR #84 及 00–10 合同与构建计划真实存在 | `CODE_COMPLETE / F_REVIEW_BLOCKED`；不得 CLOSED |
| WB-A01 | 原子操作候选表横跨原六页十区，每项有正反向 Oracle、真相来源及责任，记录 `NOT_RUN` | `DESIGN_ARTIFACT_PRESENT / F_REVIEW_PENDING_SOURCE_ANCHORS`；不是已实现原版按钮和目标 UI QA_PASS |
| WB-A02 | 正式声明 Noncommercial 不可进入行内商业包，提出原创+SBOM+人工 provenance 与打包前检查 | `DESIGN_GUARDRAIL_PRESENT / BLOCKED_LICENSE`；尚未验证真实 staging/源码审计 |
| WB-A03 | 新增项目/批次/关联约束、迁移 HOLD、服务端 principal、ACL、命令 idempotency、batch SSE 和 N10 NodeGate 真值表 | `CONTRACT_DRAFT / F_REQUEST_CHANGES / B-D-E_PENDING`；**FG15 设计与实现签收门槛形成依赖环** |
| WB-F00 | 同 SHA CI、代码、设计与负向合同复核，有明确返工意见 | `REVIEWED_WITH_BLOCKERS`；不能宣称 QA_PASS |
| W1–W4 | 未获得真实工作台实施证据 | `NOT_RUN/NOT_IMPLEMENTED`；按真实依赖执行 |

## 新发现：WB-FG15（P0）— W0 设计签收与 W1 真实施工存在门槛环

**可复现证据路径：**
1. `08-CONSTRUCTION-PLAN.md` 中 `WB-A03` 是 W0 设计阶段的“API/事件/数据迁移合同跨组评审”，`WB-F00` 依赖 A01+A03；同一文件定义 W1 `WB-B01` 依赖 A03，`WB-E01` 依赖 B06。故 A03 设计签收是后续实际实现的前置。
2. `WB-A03-CROSS-GROUP-SIGNOFF.md` 的“必须带回的可复核证据”却要求 B 提供 T1–T8 **真实存储、422 rollback、重启保持**，D 提供**现场宿主日志/重启恢复**，E 提供 T9–T14 **R1 Evidence/签名 Attempt/真实 API 日志**。
3. 按严格依赖执行，则 B01 必须在 A03 签署后启动，而 B 的 A03 签署却被要求拿出 B01–B06 及 E 的真实实现运行证据，形成循环；这并非单测失败，而是施工 Gate 设计无法按规则完成。

**建议修订（不能放宽真实 QA Gate）：**
- W0 `A03_CONTRACT_SIGNED`：由 B/D/E/F 对稳定 ID/复合 FK/ACL/幂等/SSE/R1 语义签署**字段、状态机、负向验收用例和可实现性**，不要求在 W0 提供 W1 才能形成的真实产品/实库证据。
- W1/W2/W3 的 `IMPLEMENTATION_QA_PASS`：仍须在对应 B/D/E 代码提交后，以真实 DB、HTTP/SSE、DSH Host、N1–N10 R1、重启和失败副作用验证独立核销；不得用 W0 合同签署替代。
- 修改 `08` 依赖及 `WB-A03-CROSS-GROUP-SIGNOFF.md` 的签署要求，区分 DESIGN_SIGNOFF、INTEGRATION_QA、FIELD_QA；逐项 source SHA 与证据留档。
- A 组调整后请 F 对新 HEAD 再审并签 W0 设计合同；许可边界独立保持 BLOCKED，不能以本 Gate 拆分规避法律审查。

## 未消除的原 FG 项

- `FG01`：新 atomic feature register 没有逐行 `original_source_ref(源码文件+函数/DOM+位置)` 的已核实值；当前表只有类别 O/A/N 与宏观来源。对账仍是候选，UI 未实现。
- `FG02–05/10/13`：复杂关联、迁移、ACL、真实 R1、真实 HTTP/命令/事件持续缺实现证据。W0 的 39 个 Python 单测是设计 Oracle，不能合并为产品 QA_PASS。
- `FG06/08`：行内 DSH1.18.26/Teams32 真并发与 Windows Git Bash 离线未运行。
- `FG07/14`：无银行商业使用适用授权与可独立审计原创来源/最终 SBOM 门禁，仍 BLOCKED_LICENSE。
- `FG11/12`：上轮已按相同 SHA 合同测试层核销，此次新增 W0 CI 39/39 继续保持通过。

**Release:** W0 `NOT_FROZEN`、PR #84 `DRAFT`、no RC7.2 merge、no bank offline ZIP。此结论不等于正式 GitHub REQUEST_CHANGES Review：当前审查账号与 PR author 相同，GitHub 不允许对自己的 PR 提交该 review；使用 F 证据 PR 和 PR #84 issue comments 作独立阻断记录。

## A 组下一轮核销条件

1. 修正 FG15 设计/实现签署循环，并按 B/D/E/F 角色形成可审计的合同审查结论（即使异议也须记录）。
2. A01 按实际原版源码逐条补源锚及覆盖差异，正反向用例要在 W1–W2 实现后逐条实测。
3. A02 维持 restricted-source 与商业许可阻断，不将“清单中写 first_party”当成来源审批。
4. 把本次 SHA/28/28 CI/39 tests 和 FG15 纳入 08/09/10；下次仍先查新 HEAD 同 CI，不沿用历史绿灯。

known_limitations：F 通过 GitHub connector 查证 PR、文件、原始 CI 日志，未在金融机构办公 PC/真实 DB/API/R1 执行。本报告只关闭此次设计期同 SHA 契约测试事实，不关闭产品与现场功能。
