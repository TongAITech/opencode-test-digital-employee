# WB-C W0 原创 UI 可行性验证：证据与独立验收缺口

状态：`C_W0_PROBE_CODE_SUBMITTED`，`C_W0_LOCAL_UNIT_PASS`，`C_W0_BROWSER_SCREENSHOT_BLOCKED_LOCALLY`，`C01/C02_W1_NOT_STARTED`，`F_INDEPENDENT_QA_NOT_RUN`。该状态**不能**转化为 W0 DESIGN_FROZEN 或 W1 QA_PASS。

## 证据来源与版本
- 最新已查 A 组源基线（建 C 分支时）：`work/dsh-wb-w0@515f6a367bd16d3b83197fa2c89e15d63a83c4fe`；PR #84 OPEN/DRAFT，PR #85 OPEN/F REVIEWED_WITH_BLOCKERS。
- 固定上游只读产品参照：`naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`；原版为 PolyForm Noncommercial 1.0.0。未复制其受限源码或素材。
- 产品能力差距：`WB-A01-ATOMIC-FEATURE-REGISTER.md` 共 47 个**设计候选**原子项；C 在 `WB-C-W0-ORIGINAL-UI-AUDIT.md` 对六页面、十区、交互、表单、错误、组件/API 给出独立设计；真正全按钮逐项原版对照、真实 QA、截图仍 **NOT_RUN**。
- W0 原创组件：`tools/dsh_workbench/ui_w0_prototype/index.html`、`app.mjs`、`style.css`、`scope.mjs`。只读演示数据，不挂主导航，不接旧 `rc7_admin` API，不写 R1/DB/Attempt，不提供发布伪操作。

## 已实际执行的本地检查（2026-11-09）
```sh
node --check tools/dsh_workbench/ui_w0_prototype/scope.mjs
node --check tools/dsh_workbench/ui_w0_prototype/app.mjs
python -m py_compile tools/dsh_workbench/ui_w0_prototype/qa/run_browser_evidence.py
node --test tests/test_dsh_workbench_ui_w0.mjs
```

执行环境：本地 Node 测试进程；**9 tests / 9 pass / 0 fail**。单测覆盖：六页面/十区/六阶段常量、同需求多系统版本 SST、共享版本不同 SST、显示名相同的版本 ID 区别、UNSPLIT、跨投产日切换清理、跨项目阻断、需求变更级联清理和 YYYY-MM-DD 字面值。只证明演示数据控制器的纯函数行为，不代表服务端 ACL/事务/分页/SSE/浏览器/UI/真实业务通过。

本地真实 Chromium 尝试：
```sh
python tools/dsh_workbench/ui_w0_prototype/qa/run_browser_evidence.py \
  --chrome /usr/bin/chromium --output /mnt/data/wb_c_w0_screenshots
```
**退出码 1**，`Page.goto: net::ERR_BLOCKED_BY_ADMINISTRATOR at http://127.0.0.1:<port>/`。原型页被执行环境策略阻止加载。**无截图产物，不能报告可视化或交互已 PASS**；失败不是产品实际 403，不能混入业务接口测试。运行脚本 `qa/run_browser_evidence.py` 使用测试专用内置 HTTP Server 而非正式宿主，待允许使用浏览器的 CI 环境运行；上传截图后须带同 HEAD SHA、run/job 链接、图片 SHA256，由 F 重验。工作流 `.github/workflows/dsh-wb-c-w0-ui.yml` 只跑 W0 独立源代码/浏览器探针，不构建 Windows 包；若 CI 依赖下载或浏览器受阻，需保持 BLOCKED 而非绿灯。

## W0 交互 QA 场景与截图验收表
| 证据 | 目标行为与负向 | 当前实际 |
|---|---|---|
| `wb-c-w0-scope-ten-sections.png` | 5 主导航加项目详情第六页面，十区任意切换仍保持同 B12/R1/V2/S3；切需求 R3 显示 SST 待拆分，日期 B19 清旧筛选 | NOT_CAPTURED_LOCAL_POLICY |
| `wb-c-w0-six-stage-board.png` | 业务六阶段，点击新增弹未接业务 API，不能以拖拽改 NodeGate | NOT_CAPTURED_LOCAL_POLICY |
| `wb-c-w0-mobile.png` | 390px 窄屏、折叠侧栏、项目导航和筛选可读，主题切换 | NOT_CAPTURED_LOCAL_POLICY |
| 真实 F 组 UI/HTTP/Host/R1 证据 | 47 项原版候选逐按钮逐异常回归、并发 SSE、主题/搜索、完整表单和授权 | NOT_STARTED; W1/W2 gate |

## 依赖与阻断
- W0 保持 `NOT_FROZEN`，A01 仍待 F 原版功能完整性核验；B/D/E A03 设计签署 PENDING；A02 许可证 `BLOCKED_LICENSE`。C 的原创 W0 探针不改变任一 Gate。
- `WB-C01`（W1 六页/十区正式导航骨架）必须在 A01 设计签署、A/F W0 冻结后才施工并验收。
- `WB-C02`（W1 十区统一业务 Scope）除了 C01 还必须等待 B06 的真实复合关联分页查询 `IMPLEMENTATION_QA_PASS`；W0 演示 `scope.mjs` 不能替代 B06。
- `WB-C03/C04/C05` 依赖 W1 正式实现及各自 W2 Gate；`WB-C06` 还依赖 E02 和 C04。
- 正式 API 预期字段、HTTP 错误与 SSE 约束见 02/03/06 与 `WB-A03-CROSS-GROUP-SIGNOFF.md`，全部待实现；`rc7_admin` 现有接口不能冒充 /api/workbench/v1。
- 用户/法务授权未确认时，PolyForm Noncommercial 受限文件一律不可复制进入银行离线 ZIP；本 PR 不包含原版受限代码。

## 待 F 评审的项目
原版 47 个行为候选是否仍缺底层 DOM/handler、B06 scope contract 及图形辅助状态、CI 同 HEAD 实际结果、浏览器截图是否真实采集、无跨项目/批次泄漏、无 NodeGate 伪 PASS、原创代码溯源以及 B/D/E 签署状态。**未经 F 独立审查不得关闭此账本。**
