# WB-F00 独立验收跟踪 — A 组 HEAD fd9e60e3

- 审查日期：2026-11-09
- 审查人：F 组独立质量验收
- 代码基线：`work/dsh-wb-w0@fd9e60e3069a913547edbaa3a880cd5cc855d5de`，PR #84（Draft/Open，尚未合并）
- 本轮任务：仅对前次 WB-FG11、WB-FG12 的修复、A01/A03 设计差异、同 HEAD CI 进行增量复核；**不代表完整产品或行内 QA_PASS**。
- test_command：`python -m unittest discover -s tests -p 'test_dsh_workbench_w0.py' -v`（实际由相同 HEAD GitHub Actions 执行）；CI 数据来源 `GET /commits/{sha}/check-runs?per_page=100`；另查验 `naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b` 的真实 Git commit。
- evidence_ref：
  - <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582831350/job/129045460677>
  - <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582825572/job/129045443261>
  - <https://github.com/TongAITech/opencode-test-digital-employee/pull/84/files>
  - <https://github.com/naodeng/dsh-qa/commit/fc5a054a48973d004580a3cc1de60da3f701150b>

## 1. 最新事实

查询时该 `fd9e60e3` HEAD 的全部 28 个 GitHub check-runs 均为 `completed/success`，包含两次 `w0-contracts`。抽查其中一次 job 原始日志：

```text
test_third_party_requires_notice_and_inventory ... ok
test_six_pages_and_ten_sections_present_in_contract ... ok
Ran 32 tests in 0.010s
OK
```

这使此前失败的 **WB-FG11、WB-FG12 在 W0 纯函数合同单测层面可关闭**，应记录为 `CONTRACT_CI_PASS`，而不是 `QA_PASS`。同 HEAD 其他 26 checks success 证明既有 CI matrix 的执行结果，但它们并非新增 DSH 工作台的真实运行验收。

- WB-FG11：`notice_path != entry["path"]` 修复了合法独立 LICENSE 的错误拒绝；缺少真实 SBOM、来源/授权人工审核和最终打包集成，**WB-FG14/商业 LICENSE 门禁仍 BLOCKED**。
- WB-FG12：`01-PAGE-FUNCTION-MATRIX.md` 增补源 commit `fc5a054...` 与 27 条可观察功能对账候选。该 SHA 已通过上游真实 GitHub Commit API 验证，原版来源可追溯。仍是功能清单候选，未有六页面/十区新 UI 的操作截图、后端真相与按钮级完整实测；**WB-FG01 仍 OPEN**。
- WB-A03：`06-API-AND-EVENT-CONTRACT.md` 补充可信 principal 不得在请求体自报、scope/ACL 关系、命令幂等、SSE snapshot/replay、数据迁移与证据规范，且明确是设计、无 `/api/workbench/v1` 真 API。需 B/D/E/F 交叉签收，**A03 IN_PROGRESS**。
- 同轮 `08`/`09`/`10` 有计划与 GAP 同步，但仍有旧文案，如 `WB-F00 TODO`、`F 尚无 Review`、`同 HEAD CI 尚未验证`，与已提交独立审查 PR #85、已发表 PR #84 阻断评论及本次同 HEAD 28/28 successful 不一致。A 应修正为 `F_INITIAL_REVIEWED_WITH_BLOCKERS`、`CONTRACT_CI_PASS`（非 QA_PASS）。
- 原 `02-BUSINESS-DOMAIN-CONTRACT.md` 未在本增量发生变更；旧 `ReleaseBatch` 到稳定项目+日期与复合需求/版本/SST 关联的真实迁移、约束、事务和跨批次拒绝仍没有业务数据层运行证据。
- `naodeng/dsh-qa` PolyForm Noncommercial 商业授权尚未证明；宿主 DSH 1.18.26、Teams 配置 32 与实际并发、Windows Git Bash 离线包、R1 双向追踪/命令/审批皆没有本次真实现场证据。

## 2. 更新后的审查缺口摘要

| 项目 | 最新状态 | 解释 |
|---|---|---|
| WB-FG11 | CONTRACT_CI_PASS | W0 LICENSE notice 正例单测通过，非授权审批 |
| WB-FG12 | CONTRACT_CI_PASS | 上游 SHA 真实、功能矩阵编号单测通过，非页面功能 PASS |
| WB-FG01 | OPEN | 27 条行为是设计候选，尚未见实际交互核验 |
| WB-FG02/03/04 | OPEN | 业务日期与多对多复合关联、跨批次/跨项目 ACL、历史迁移无真实运行证据 |
| WB-FG05/10 | OPEN | N1–N10 / R1 / Evidence 与实际工作台 API/UI 尚未真验 |
| WB-FG06 | NOT_RUN | DSH 宿主 1.18.26 / 会话 / Agent Teams 真验证待做 |
| WB-FG07/14 | BLOCKED_LICENSE | PolyForm 权利与第三方包来源门禁未核销 |
| WB-FG08 | NOT_RUN | Windows Git Bash 无网免安装完整包未验 |
| WB-FG09 | CONTRACT_CI_PASS / INTEGRATION_NOT_RUN | `fd9e60e3` 的 28 个 checks 成功，但与独立功能 QA 是两回事 |
| WB-FG13 | OPEN | W0 oracle 在内存/fixtures 中运行，实际持久化/API/事件/权限无交付测试 |

## 3. W0 与 A 组合并门槛

WB-F00 = `REVIEWED_WITH_BLOCKERS`，**不是 QA_PASS**；W0 = `NOT_ACCEPTED / NOT_FROZEN`。

A 组需：
1. 将 F 组 [PR #85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85) 的证据与评论纳入 08/09/10；纠正旧的 F TODO、CI 未验、F 无 review 表述。
2. 按 `01` 的 27 条候选能力归一化完整功能清单，逐项标记现状、缺 UI/API/Host 功能、正反例；A01 可将候选文档进一步完善，但不得宣称页面已实现。
3. 由 A/B/D/E 共同确定 `02/06` 的关系约束、SST 来源身份、迁移、ACL、命令/事件幂等及 N1–N10/R1 映射的接口签署证明，A03 才可请求 F W0 复验。
4. 保留 BLOCKED_LICENSE，不得将任何受限源代码未经适用授权打入行内交付，或者在可审计的原创实现条件下维持隔离；许可审查与发布许可状态独立。
5. 对新的整改 SHA 重新审查，不用历史 HEAD 的绿灯代表未来 HEAD 的验收。

known_limitations：本轮只读取 GitHub 文件、原版源 commit、同 HEAD check-runs 与一个 job 原始日志；没有直接在银行宿主中运行 UI/API/R1，也没有 Windows 离线启动/卸载/恢复测试。所有实现场景维持 NOT_RUN。
