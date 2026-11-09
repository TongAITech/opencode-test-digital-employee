# WB-F00 增量独立审查：A 组新 HEAD 4046029

审查日期：2026-11-09；原始审查 SHA：`12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8`；增量审查 SHA：`4046029591b0b324e6a33028629dc22034d511d0`；PR #84 的 head 已变化，原审查文件仅代表原始 SHA，**不能误写为最新 HEAD 只有文档**。

## 增量范围

对比 `12a16a2...4046029`：A 组新增三个文件：
- `.github/workflows/dsh-wb-w0-contract.yml`
- `tests/test_dsh_workbench_w0.py`
- `tools/dsh_workbench/w0_contract_gate.py`

增量为独立编写的 **设计期范围/命令/事件/许可候选校验器及其模拟单测**；模块 docstring 明确 `NOT a production workbench endpoint`，无 R1/DSH/真实 HTTP 服务读写。不得将其测试通过外推为工作台功能实现。原 `docs/dsh-workbench/00–10` 在这次增量中无变化，WB-FG01–10 的主体门槛仍然有效。

## 新增阻断问题

### WB-FG11（P0，A，**实际 CI 红**）：第三方 LICENSE 正例被错误拒绝
- **重现命令**：在新 HEAD 仓库根目录运行 `python -m unittest discover -s tests -p 'test_dsh_workbench_w0.py' -v`。
- **实际证据**：<https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582069489/job/129042933937>，`Ran 32 tests`，`FAILED (failures=1, errors=1)`；其中 `TestLicenseGate.test_third_party_requires_notice_and_inventory` 报 `THIRD_PARTY_NOTICES_MISSING`。
- **根因可定位**：`tools/dsh_workbench/w0_contract_gate.py` 末尾校验 `_require(notice_path == entry["path"] and notice_path in by_name, "THIRD_PARTY_NOTICES_MISSING")`。正常 MIT 被声明为 `vendor/mit.js`，许可证文件是另一项 `vendor/LICENSE`，两者当然不应是同一路径；该判断把“独立 NOTICE 文件”的合法正例拒绝。
- **修订要求**：正确的约束应要求 `notice_path != entry["path"]`、`notice_path in by_name` 且对应 notice 文件内容、哈希、来源声明受验证；加“同文件自引用拒绝/不存在 notice 拒绝/独立合法 notice 允许”正反例，并由 A 重跑相同 HEAD 的门禁。不得通过删除测试或取消许可证门禁换取绿灯。

### WB-FG12（P0，A/C，**实际 CI 红**）：页面合同测试依赖未提供的硬编码 SHA
- **重现**：同命令，`TestPageContract.test_six_pages_and_ten_sections_present_in_contract` 断言 `fc5a054a48973d004580a3cc1de60da3f701150b` 在 `docs/dsh-workbench/01-PAGE-FUNCTION-MATRIX.md` 出现；已读取的新 HEAD 文件并无此串，必然失败。
- **实际证据**：同一 W0 workflow job，`AssertionError`；第二次 W0 job <https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582063531/job/129042913467> 结果相同。
- **修订要求**：A01 固定明确上游 `naodeng/dsh-qa` tag/commit/页面映射及可复查来源，将实际 source_sha 写入合同、解释该 SHA 的对象；测试读取可验证字段并交叉对账，不能仅把任意字面常量补进文件就视为“十区功能实现”。独立实现的功能验证应另有可运行测试。

### WB-FG13（P0，A/B/E/F）：32 个 W0 单测测试的是模拟 Oracle，不是领域/运行集成
- **重现**：`legal_scope_rows` 输入调用者提供的 `fixture_rows()`；`validate_command` 只验证请求包、不写命令或核对 R1；`accept_event` 只使用进程内字典；`test_t8` 仅直接更改 fixture 中的 release_date；`test_t1` 实际数据仅 R1 两版本三 SST，未覆盖原合同“同需求三版本各多 SST”。
- **预期/观察**：模拟 T1–T10 及 License/Command/Event 的判定逻辑可以作为 W0 设计期快速检测，但尚无真实 DB 复合唯一/外键、权限、R1 状态、API、会话、迁移、事务、断线续订证明。
- **修订**：保留原有负向单测，但须补真实适配器上的接口/数据/命令/事件契约用例和完整 T1 数据；每条执行证据必须标为 `DESIGN_ORACLE_ONLY` 或 `INTEGRATION_VERIFIED`。A03 提供联调接口后 F 独立复核。

### WB-FG14（P1，A/F）：许可证门禁仍不能自行证明源码独立性
- **观察**：`verify_bank_staging` 根据清单自报 `source_repository` / `origin_kind` / 任意非空 `provenance_review_ref` 并做字符串扫描，不能自动识别被重命名、去许可文本的派生源码；代码注释已明确仍需人工来源审计。
- **修订**：继续 `BLOCKED_LICENSE`，要求明确受授权许可文档或独立实现的审查路径、代码来源链和 SBOM；不能将 `verify_bank_staging` 返回正值认定为商业授权或独立产权证明。

## 新 HEAD 同 SHA CI

查询 `GET /repos/TongAITech/opencode-test-digital-employee/commits/4046029591b0b324e6a33028629dc22034d511d0/check-runs?per_page=100` 时共有 28 个 check。两个 **w0-contracts** job 均已明确 failure，另有 RC7.2 Windows Python 3.8 等 job failure/queued/in_progress；该结果与旧 SHA 的 `13 success / 4 failure / 9 in_progress` 是不同快照，绝不能混写为同一轮。

**更新验收结论**：W0 = NOT_ACCEPTED；WB-F00 = REVIEWED_WITH_BLOCKERS；不存在任何可标 `QA_PASS` 的工作台功能。A 应把 WB-FG11–14 纳入 09 GAP、在 08 计划和 10 checkpoint 标明新 HEAD 的真实状态；修复后 F 针对新 HEAD 复核。F 的证据 PR 仅用于独立审查，未经重新验证不得作为最终验收签字。
