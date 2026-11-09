# RC7.2 第三轮合并后 Q1 Windows N10 超时修复（2026-11-09）

基线：`work/rc7.2` @ `7d4c945da2241b76a747eaeec62c24125c97dfc3`，PR #80 已合入。
Q1 Construction Qualification `42490990629` PASS；Platform Qualification `42490990654` FAIL，Windows Python3.8 的 `test_rc72_n10_control.py` 命中 **180s 有界文件预算**。Linux PASS。

## 事实与根因边界

- 失败日志：`RC72_BOUNDED_PYTEST_TIMEOUT::tests\\test_rc72_n10_control.py::timeout=180s`，其余文件多数 PASS，整体 `FAIL::count=1`。
- 同样的 Windows 单文件在上一主线运行 `42476894626` 通过，耗时约 121s。新运行看到 11 个已完成的 pytest 点，然后 180s 截断：可证明有单文件耗时波动，**不能仅凭日志认定产品 N10 断言失败或无限循环**。
- 当前同一文件包含 6 个业务/Repair/终态类测试和 7 个每次重新启动业务+模型环境的独立 R1 Tamper 场景。将两组分别保持原始函数体和 180s 文件超时，是测试执行颗粒度优化，**不是增加失败宽容度、跳过用例或缩减质量要求**。

## 实际施工

- 原六个 N10 用例保留在 `tests/test_rc72_n10_control.py`，七个参数化独立签名快照篡改场景完整移到 `tests/test_rc72_n10_feedback_tamper.py`，两个文件均受 Q1 `tests/test_rc72_*.py` 纳入。
- 新增 `tests/test_rc72_n10_qualification_partition.py` 断言六个原用例+七个篡改维度完整存在。
- 新增 Windows/Linux Python3.8 专项流水线 `rc7.2-q1-n10-file-budget.yml`，**每个文件继续 180s**，先验证收集和分母、后验证两组原场景，采集 JUnit。中间不得构建 ZIP。
- 如果分组仍超时，须进一步根据独立文件定向诊断耗时，不得通过简单拉长全局预算宣称成功。修改后必须在同源 PR 工程资格和合并后的 Q1 Windows 中重新取得 PASS。

状态：`SOURCE_FIX_COMMITTED`，验证结果以同源 Actions 为准；`C12_PHYSICAL_HOLD` / `BANK_FINAL=NO`。
