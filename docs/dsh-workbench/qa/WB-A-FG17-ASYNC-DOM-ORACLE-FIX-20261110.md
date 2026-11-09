# FG17 异步 DOM 业务 Oracle 修复记录（2026-11-10）

## 来源与审核基线

- F 独立复验：PR [#94](https://github.com/TongAITech/opencode-test-digital-employee/pull/94)
- 被审 A 产品源：`75fd2c64159db863cfd1319d41a887785b556d40`
- F 结论：`FG17_FLAKY_OBSERVED / SHORT_REPEAT_PASS / ROOT_CAUSE_PENDING`；此前同一产品源出现过 Python 3.8/Playwright 1.48 真 Chromium 的 1 次失败，不能用后续五轮通过抹掉历史红灯。
- A 修复分支：`work/dsh-wb-w0-fg17-fg21`

## 根因定位

旧 C09 真浏览器测试在实际 POST response 200 后执行 `wait_for_load_state("networkidle")`，随即读取 `#toast.inner_text()`。这两者不是同一个完成条件：

1. HTTP response 到达只证明传输层收到响应。
2. `networkidle` 只表示当前网络请求静默，不保证 SPA 的 Promise/状态更新已经写入 DOM。
3. Playwright 的 `locator.inner_text(timeout=...)` 中 timeout 主要约束 locator 查询，并不会轮询直到文本等于业务期望值。
4. 因此测试可能读到旧值 `Before save`；Journey Replay 同样在 `text_equals` Oracle 上立即读取，产生真实 `FAILED`。

## 修复内容

- `rc7_runtime/rc72_journey_playwright.py`
  - 新增有界 `_wait_for_oracle_value`，按 50ms 间隔轮询 DOM 值，最长不超过 adapter 配置的 timeout。
  - `text_equals` 必须等到精确文本相等才通过；超时仍产生 `JOURNEY_ASSERT_TEXT_MISMATCH`，不降级为 HTTP PASS。
  - `attribute_equals` 使用同样的有界等待；属性缺失或值不匹配仍失败。
  - 网络来源、HTTP 状态、SST/Attempt/Lease 约束、证据持久化逻辑均未绕过。
- `tests/test_rc72_c09_real_chromium_cdp_smoke.py`
  - 本地 SUT 在 HTTP 200 与 JSON 解码后延迟 650ms 才更新 SPA Toast，刻意覆盖 network-idle 先于 DOM commit 的竞态。
  - 保留真实 HTTP POST 200、Toast 精确业务 Oracle、CDP network response lineage、R1 step、PNG 字节和 Journey compile candidate 断言。
  - 教学录制用例同样等待精确 DOM 文本，不以 network-idle 代替业务 Oracle。
- `tests/test_rc72_journey_playwright_adapter.py`
  - 负向文本 Oracle 仍必须失败；将该单测 timeout 缩至 1 秒，避免负向用例无意义地等待完整默认超时。

## 同源验证

- Q1 环境：Ubuntu 22.04 / Python 3.8 / pytest 8.3.5 / Playwright 1.48.0 / 真实 Chromium。
- A 修复源 SHA：`f41e8ca882d674150349f9a1b4f0aab44e30d197`。
- [GitHub Actions run #42661016254](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42661016254) / job `129312276833`：五次连续执行，每次 3/3 PASS，`FG17_FIVE_TRIAL_FAILURES=0`。
- Artifact：`13694826014`，包含各轮 JUnit XML、R1 与实际浏览器证据。
- 后续 A 提交 `5de7cad44608847d4cc735f2a1dfb862247d0274` 增加 Python 3.11 / Playwright 1.62.0 同样五轮验证及 adapter 单测；结果待完成，不预填 PASS。

## 结论与边界

当前结论：`FG17_ROOT_CAUSE_IDENTIFIED / ASYNC_DOM_ORACLE_FIX_SUBMITTED / PY38_5X_REAL_CHROMIUM_PASS / PY311_PENDING / F_RECHECK_PENDING`。

历史失败仍保留为真实证据。新修复尚未获得 F 对新 HEAD 的独立复验，也不是行内 Windows/DSH Host/银行业务现场 QA_PASS。只有 Python 3.8 与 3.11 同源回归、F 新 SHA 独立复核及最终 RC7.2 单源资格完成后，才可评估关闭 FG17。
