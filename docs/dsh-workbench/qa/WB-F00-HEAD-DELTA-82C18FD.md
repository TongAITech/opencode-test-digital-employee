# WB-F00 第二次增量审查：A 组 HEAD 82c18fd

审查时间：2026-11-09；候选 HEAD `82c18fdd93867e7d27107f665e124c5edcae8b2c`；来源：PR #84 HEAD 与 Github compare API，父审查 HEAD `4046029591b0b324e6a33028629dc22034d511d0`。

## 增量变更与验证

- 仅修改 `tools/dsh_workbench/w0_contract_gate.py` 一行：
  - 旧：`notice_path == entry["path"] and notice_path in by_name`
  - 新：`notice_path != entry["path"] and notice_path in by_name`
- **WB-FG11：CODE_FIX_PRESENT / CI_PENDING**。新判断消除“正常第三方源码与独立 LICENSE 必须是同一路径”的逻辑错误；但未检查 NOTICE 文件内容合法性/原始代码来源，不能关闭整体 WB-FG14 授权门禁；不得直接标 QA_PASS。
- **WB-FG12：仍复现（源码级静态断言）**。`tests/test_dsh_workbench_w0.py` 仍要求 `fc5a054a48973d004580a3cc1de60da3f701150b` 在 `docs/dsh-workbench/01-PAGE-FUNCTION-MATRIX.md`，该矩阵开头和此前完整读取版本均无此 SHA；本次差异未修改两文件，因此仍然是可复现的确定性 CI 失败，除非后续修订。
- 同 HEAD `GET /commits/82c18fdd93867e7d27107f665e124c5edcae8b2c/check-runs?per_page=100` 查询时共有 28 checks、两个 `w0-contracts` 均 queued；**未从旧 HEAD 继承任何 CI_PASS**。新 jobs 入口：<https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582670677/job/129044920724> 和 <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582665760/job/129044904047>。
- A 组 A01/A03 是否已经完成、行内 DSH1.18.26 与 Windows Git Bash 离线真实运行、未授权源码隔离等，在该单行提交中均无新证据。

## F 当前决定

WB-F00 = `REVIEWED_WITH_BLOCKERS`；W0 = `NOT_ACCEPTED`；WB-FG11 `CODE_FIX_PRESENT/CI_PENDING`；WB-FG12 `OPEN`；WB-FG01–10、13、14 继续按原审查文档整改和举证。未将任何项目标记 QA_PASS。A 必须在修复后的候选 HEAD 出具同 HEAD 全部适用检查及独立测试证据，并保证 08/09/10 账本准确后，再请求 F 重新审查。
