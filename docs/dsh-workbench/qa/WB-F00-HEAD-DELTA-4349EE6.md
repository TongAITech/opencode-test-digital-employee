# WB-F00 增量独立验收 — A HEAD 4349ee63：FG15 设计修复核销 / FG16 新 P0

**Date:** 2026-11-09  
**F scope:** 对 PR #84 从 `6edb9fb7e3901bb8a72706c5522ce759b0318672` 到 `4349ee63015c390e4b6c092e1ba048560be2e292` 的单次整改独立复验。  
**source_sha:** `4349ee63015c390e4b6c092e1ba048560be2e292`  
**test_command:** A CI `python -m unittest discover -s tests -p 'test_dsh_workbench*.py' -v`  
**result:** `28/28 GitHub checks success`，`48/48 W0 contract tests pass`；`WB-FG15_DESIGN_FIX_ACCEPTED`，但 `WB-F00 REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN`。  
**evidence_ref:** [current W0 job](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42608094947/job/129129112007)，[PR #84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84)，[PR #85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85)。

## 核验范围及可重现依据

- GitHub compare 仅 1 commit、8 个文件：`WB-A03-CROSS-GROUP-SIGNOFF.md`、`08/09/10`、`W0-W1-GATE-MANIFEST.json`、`w0_dependency_gate.py`、`test_dsh_workbench_gate_dag.py`、CI workflow。
- 最新 HEAD 的 `GET commits/{SHA}/check-runs` = 28 success / 28 total（两次 `w0-contracts` 成功）。
- 直接读取 GitHub Actions job #129129112007 原始日志：`Ran 48 tests in 0.014s`、`OK`，包含 FG15 相位回边、缺少许可证、缺少现场门禁的负向单测。测试宿主 ubuntu-latest Python 3.11；非行内 DSH/数据库/R1/Windows 现场。
- 主线 `work/rc7.2` 查询 HEAD `58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d`。PR #84 为 Draft/Open/Not Merged。

## FG15（原 P0）复验：仅设计层修复认可

旧缺陷：`A03` 的 W0 签署条件要求 B/E/D W1 的真实运行证据，但 W1 又依赖 A03，造成闭环。
本次修复：A03 签署明确只需字段/权限/协议/负向合同/角色可实现性，并将真实数据库/HTTP/SSE/DSH Host/R1 Evidence 拆至 W1–W4 `IMPLEMENTATION_QA / INTEGRATION_QA / FIELD_QA`；静态 DAG 中 W0 没有向 W1 的回边，负向测试会拒绝新增 W1→W0 逆依赖。
**F 结论：`FG15_DESIGN_FIX_ACCEPTED / CONTRACT_CI_PASS`**。这只是修复验收，**不等于 B/D/E 正式 DESIGN_SIGNOFF，也不等于 A03/W0 整体签收**。

## WB-FG16（新 P0）：机器发布依赖图可绕过 W2/W3 及离线资格

**可复现路径：**
1. 打开 `docs/dsh-workbench/08-CONSTRUCTION-PLAN.md` W4：`WB-F04`（离线安装/重启/恢复/证据与 SHA）明确**依赖 `F03,D04`**；`WB-F03` 为 W3 真实批次自主闭环/防假 PASS 验收，`WB-D04` 为 Windows Git Bash 免安装资格；W2 `WB-F02` 是原版六页十区能力回归。
2. 打开新增 `docs/dsh-workbench/W0-W1-GATE-MANIFEST.json`：`WB-F04_FIELD_QA_PASS` 的 `depends_on` **仅 `["WB-W1_INTEGRATION_QA_PASS"]`**。清单中根本没有 `WB-F02`、`WB-F03`、`WB-D04` Gate，也没有任何 W2/W3 节点。
3. 最终 `WB-W4_BANK_RELEASE_APPROVED` 只依赖 `WB-F04_FIELD_QA_PASS` 与 `WB-A02_LICENSE_RELEASE_APPROVED`。逆向遍历该 DAG，先驱集合没有任何 `F02`、`F03` 或 `D04`；也就是说即使 W2 完整性回归、W3 N1–N10+Agent Teams 真实闭环、D04 离线检查未通过，**这个静态图仍会声称依赖完整**。A 的现有测试只删除整个 `F04` 或 `LICENSE` 门禁，未检验 `F04` 自身先驱。
4. 复现命令（在包含本次 A HEAD + F 测试的合并工作树上）：
   ```bash
   python -m unittest tests.test_dsh_workbench_release_dependencies_f -v
   ```
   两个独立负向断言 `test_w4_field_gate_requires_autonomous_closed_loop_and_offline_proof` 和 `test_w4_bank_release_requires_original_six_page_ten_section_regression` 应在当前 A manifest 上失败；修复后必须在同 HEAD 运行成功。F 已将该测试实际提交至 **PR #85** 的 `tests/test_dsh_workbench_release_dependencies_f.py`。单独 F 分支尚无 A manifest 时测试明确 skip，**不把 skip 说成 PASS**。
5. 机器静态图通过不代表**运行时状态**真的绑定审批人、源 SHA、测试 Evidence 或不可伪造资格。发布服务应另建立真实运行门禁与权限审查；目前未实施，保留 `FG13/14` 阻断，不将静态 DAG 视为真实发布授权。

**影响：** FG15 的循环已解除，但新增 release gate 的闭合性不满足原 08 工程施工合同。如果作为放行依据，会在 W1 通过但 W2/W3/D04 未执行的情况下产生逻辑漏检。

**整改要求：**
- 将 DAG 扩展覆盖 W2、W3、W4 全部必须项，至少添加 `WB-F02_*QA_PASS`、`WB-F03_*QA_PASS`、`WB-D04_*QA_PASS`；使 `WB-F04_FIELD_QA_PASS` 必须依赖 F03 和 D04，并保证 W4 Release 的全部先驱闭包包含 F02。
- 同步更新 `w0_dependency_gate.py` 的必备 Gate 与**传递依赖闭包**验证；不能只检查最终发布有 `F04` 与 `LICENSE` 两个直接入口。
- 为“移除 F02/F03/D04 但保留 F04/License”加入恶意变更负向测试，必须 fail-closed；保证尚未运行的 W2/W3/D04 不能虚构 QA_PASS。
- 同步 `08`、`09`、`10` 的 FG15/F16、整改 SHA、单测和状态；请求 F 复验新 HEAD。

## 当前签收矩阵

| 工单/缺陷 | F 本轮状态 |
|---|---|
| FG15 W0/W1 环依赖 | **DESIGN_FIX_ACCEPTED**，不是全产品 QA_PASS |
| FG16 W4 发布依赖遗漏 | **P0 OPEN / CONTRACT_REJECTED** |
| A01 原版六页面十区功能来源与实测 | CANDIDATE / PRODUCT_NOT_IMPLEMENTED |
| A02 商业授权/原创 provenance/SBOM | BLOCKED_LICENSE |
| A03 B/D/E 设计正式签署 | B_PENDING / D_PENDING / E_PENDING |
| F00 W0 设计最终签收 | REVIEWED_WITH_BLOCKERS；NOT_ACCEPTED |
| W1–W4 真实 SUT/DB/R1/UI/Host/Windows | NOT_RUN |

**Release conclusion:** PR #84 保持 Draft，W0 `NOT_FROZEN`，不可称 `QA_PASS` 或商业授权通过，不合入 `work/rc7.2`、不构建银行 ZIP。

**known_limitations:** 此次审查在 GitHub 连接中核查源文件与 GitHub Actions 原始日志，利用依赖图的确定性祖先关系复现 FG16；F 新提交的独立 Python 回归测试尚未在 A HEAD 合并树的 GitHub Actions 执行。没有在真实行内设备或数据中执行测试；不以推演充当运行时证据。
