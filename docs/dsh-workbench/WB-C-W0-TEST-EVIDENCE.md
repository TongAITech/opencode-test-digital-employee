# WB-C W0 原创 UI 可行性验证：证据与独立验收缺口

状态：`C_W0_PROBE_CODE_SUBMITTED`，`C_W0_LOCAL_UNIT_PASS`，`C_W0_BROWSER_SCREENSHOT_BLOCKED_LOCALLY`，`C_W0_BROWSER_CI_PROBE_PASS`、`C_W0_MULTISELECT_FORM_CI_PASS`、`C_W0_FOLLOWUP_HEAD_CI_PASS`，`C01/C02_W1_NOT_STARTED`，`F_RECHECK_75FD2C6_CONTRACT_PASS`、`FOLLOWUP_VISUAL_REVIEW_NOT_RUN`、`F02_NOT_RUN`。该状态**不能**转化为 W0 DESIGN_FROZEN 或 W1 QA_PASS。

## 证据来源与版本
- 最新已查 A 组源基线（建 C 分支时）：`work/dsh-wb-w0@515f6a367bd16d3b83197fa2c89e15d63a83c4fe`；PR #84 OPEN/DRAFT，PR #85 OPEN/F REVIEWED_WITH_BLOCKERS。
- 固定上游只读产品参照：`naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`；原版为 PolyForm Noncommercial 1.0.0。未复制其受限源码或素材。
- 产品能力差距：`WB-A01-ATOMIC-FEATURE-REGISTER.md` 共 50 个**设计候选**原子项；C 在 `WB-C-W0-ORIGINAL-UI-AUDIT.md` 对六页面、十区、交互、表单、错误、组件/API 给出独立设计；真正全按钮逐项原版对照及正式 UI QA **NOT_RUN**；W0 原创演示的真实浏览器截图已在独立 CI 采集。
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
**退出码 1**，`Page.goto: net::ERR_BLOCKED_BY_ADMINISTRATOR at http://127.0.0.1:<port>/`。原型页被执行环境策略阻止加载。**无截图产物，不能报告可视化或交互已 PASS**；失败不是产品实际 403，不能混入业务接口测试。运行脚本 `qa/run_browser_evidence.py` 使用测试专用内置 HTTP Server 而非正式宿主；随后已在 Ubuntu 24.04 CI 成功运行；上传截图后须带同 HEAD SHA、run/job 链接、图片 SHA256，由 F 重验。工作流 `.github/workflows/dsh-wb-c-w0-ui.yml` 只跑 W0 独立源代码/浏览器探针，不构建 Windows 包；若 CI 依赖下载或浏览器受阻，需保持 BLOCKED 而非绿灯。

## W0 交互 QA 场景与截图验收表
| 证据 | 目标行为与负向 | 当前实际 |
|---|---|---|
| `wb-c-w0-scope-ten-sections.png` | 5 主导航加项目详情第六页面，十区任意切换仍保持同 B12/R1/V2/S3；切需求 R3 显示 SST 待拆分，日期 B19 清旧筛选 | CAPTURED_IN_CI_PROBE_SHA_465d_F_UNREVIEWED |
| `wb-c-w0-six-stage-board.png` | 业务六阶段，点击新增弹未接业务 API，不能以拖拽改 NodeGate | CAPTURED_IN_CI_PROBE_SHA_465d_F_UNREVIEWED |
| `wb-c-w0-mobile.png` | 390px 窄屏、折叠侧栏、项目导航和筛选可读，主题切换 | CAPTURED_IN_CI_PROBE_SHA_465d_F_UNREVIEWED |
| 真实 F 组 UI/HTTP/Host/R1 证据 | 50 项原版候选逐按钮逐异常回归、并发 SSE、主题/搜索、完整表单和授权 | NOT_STARTED; W1/W2 gate |

## 依赖与阻断
- W0 保持 `NOT_FROZEN`，A01 仍待 F 原版功能完整性核验；B/D/E A03 设计签署 PENDING；A02 许可证 `BLOCKED_LICENSE`。C 的原创 W0 探针不改变任一 Gate。
- `WB-C01`（W1 六页/十区正式导航骨架）必须在 A01 设计签署、A/F W0 冻结后才施工并验收。
- `WB-C02`（W1 十区统一业务 Scope）除了 C01 还必须等待 B06 的真实复合关联分页查询 `IMPLEMENTATION_QA_PASS`；W0 演示 `scope.mjs` 不能替代 B06。
- `WB-C03/C04/C05` 依赖 W1 正式实现及各自 W2 Gate；`WB-C06` 还依赖 E02 和 C04。
- 正式 API 预期字段、HTTP 错误与 SSE 约束见 02/03/06 与 `WB-A03-CROSS-GROUP-SIGNOFF.md`，全部待实现；`rc7_admin` 现有接口不能冒充 /api/workbench/v1。
- 用户/法务授权未确认时，PolyForm Noncommercial 受限文件一律不可复制进入银行离线 ZIP；本 PR 不包含原版受限代码。

## 待 F 评审的项目
原版 50 个行为候选（35 项原版入口候选、15 项新增目标）是否仍缺底层 DOM/handler、B06 scope contract 及图形辅助状态、CI 同 HEAD 实际结果、浏览器截图是否真实采集、无跨项目/批次泄漏、无 NodeGate 伪 PASS、原创代码溯源以及 B/D/E 签署状态。**未经 F 独立审查不得关闭此账本。**

## GitHub 同 SHA 首次真实浏览器与截图验收（新增事实，不替代 F02）
- 已运行 SOURCE SHA `465d1006e1b0f8d9ce537436d46912e527d9d096`，Ubuntu 24.04 独立 CI run [42622094284](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622094284)，[job 129176561107](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622094284/job/129176561107)：**同 SHA W0 原型 Node 9/9 PASS，真实 Chromium 浏览器交互步骤 PASS，截图上传 SUCCESS**。
- 真实 artifact [dsh-workbench-c-w0-screenshots（ID 13675694071）](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622094284/artifacts/13675694071)，3 张 PNG：
  - `wb-c-w0-scope-ten-sections.png` SHA256 `9264ff1d6646acf208bb4ca2d0060468b955ba8ccdc0cac79cadd88afcfafa35`，126941 B；
  - `wb-c-w0-six-stage-board.png` SHA256 `d850b8a2e703cd473d80d21e91b332f40bfd31f005841af93b4620050825abd1`，94604 B；
  - `wb-c-w0-mobile.png` SHA256 `0f8d9d2e68d3f356b1b18c2347611955c0d11f39383188da30064a03817fdb42`，63277 B。
- 历史红 CI [run 42621898654](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42621898654) 因 ubuntu-latest 指向 Ubuntu 26.04，Playwright 1.56.0 不支持；修复是固定 runner ubuntu-24.04，**没有删浏览器测试或跳过截图**。
- 这是 **W0 原创静态演示 UI / 业务关系可行性验证**，不是银行正式 DSH 1.18.26 Host、/api/workbench/v1、B06 数据库关联、E R1、正式项目数据、真实 F02 原版全功能 QA。F 仍须独立审核截图和真实产品验收。当前 W0_NOT_FROZEN、C01/C02 TODO、A02 BLOCKED_LICENSE。


## 2026-11-10 W0 交互深化的待验证证据
- 本轮源码基线 A 75fd2c64159db863cfd1319d41a887785b556d40；C follow-up 分支 work/dsh-wb-ui-followup。目标是把单值筛选提升为合法关系多选、十区表单字段/必填校验和统一只读快照。
- 新增 5 个纯函数反例：多需求→多系统版本→多 SST、非法多选原子拒绝、上级缩小级联、清空筛选保留下级合法选择、query 快照冻结；原 9 项保留。
- Playwright W0 浏览器探针扩充为逐一打开十区、验证十区同一 Scope 快照、检查十个分区表单必填与提交 fail-closed、验证空搜索结果和窄屏/主题/原六阶段。
- follow-up 源 SHA `00f3a2e8e3360a5f550a69e9ec92d0c852d98170` 已有同 SHA 实测：20/20 Node tests、Chromium 逐区交互与截图 PASS；证据 job 129316185577 / run 42662146741。该 SHA 的 B→C 隔离 merge probe 15/15 PASS，job 129316185823。仅代表 W0 原型。
- F 的 75fd2c6 独立复验：156 W0 合同、C Node 15/15、FG18/FG20 设计层通过；FG17 仍 FLAKY_OBSERVED / ROOT_CAUSE_PENDING，FG21 work/rc7.2 merge dirty；W0 仍 NOT_FROZEN，A02 BLOCKED_LICENSE。F 未对本轮新交互视觉逐项签收，F02 NOT_RUN。


## Follow-up 同 SHA 真实浏览器与交互证据（2026-11-10）
- 产品/测试源码 SHA：00f3a2e8e3360a5f550a69e9ec92d0c852d98170；PR #97。
- [Original W0 probe job 129316185577](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662146741/job/129316185577)：Node **20/20 PASS**；真实 Chromium 完成六页面入口、十区逐个表单、必填校验、fail-closed 提交、多选 Scope 同一快照、UNSPLIT、跨批次清理、搜索 0 结果、六阶段、主题与窄屏；输出 W0_BROWSER_PROBE_PASS。
- [截图 artifact 13695171448](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662146741/artifacts/13695171448)，3 张 PNG：
  - wb-c-w0-scope-ten-sections.png SHA256 65a67e7c67126eaec25238f9197a522413b839799480969025dd81e306181e69，192026 B；
  - wb-c-w0-six-stage-board.png SHA256 d850b8a2e703cd473d80d21e91b332f40bfd31f005841af93b4620050825abd1，94604 B；
  - wb-c-w0-mobile.png SHA256 e50d647e763bbe120c82544233444fcae17b20922af6bf0360443850fa93a4f7，63752 B。
- [B→C isolated merge job 129316185823](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662146741/job/129316185823)：真实顺序合并探针 PASS，合并树 Node **15/15 PASS**。不代表完整 A/B/C/D/E 最终发布合并。
- [E 同源 W0 contract job 129316182812](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662146333/job/129316182812) SUCCESS。
- F 对本 follow-up SHA 的独立视觉复核尚未执行；F02 正式 UI/API/Host QA 仍 NOT_RUN。旧 A 75fd 的 F 结论不转移。


## 最新 follow-up HEAD 同 SHA 复跑（2026-11-10）
- 最新 PR HEAD：d4863bab1cc65ed78b5c3d7edbf8e6e242c7b6a8；此 HEAD 仅在已通过的代码 SHA 00f3a2e 上回写证据与扩展 CI 路径，没有改动 Scope/UI/测试实现。
- [最新同 SHA C run 42662706264 / job 129318183234](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183234)：**20/20 Node PASS、真实 Chromium PASS、3 PNG 上传成功**；截图哈希与上节一致。
- 最新 [截图 artifact 13693719815](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/artifacts/13693719815)。
- 最新 [B→C merge probe job 129318183968](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706264/job/129318183968)：合并探针 SUCCESS、15/15 Node PASS；最新 [E contract job 129318139591](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42662706275/job/129318139591) SUCCESS。
- F 已完成对 A 75fd 源的独立审核，但对 follow-up 最新 SHA 的视觉复核仍待；W0_NOT_FROZEN / C01-C02 NOT_STARTED / A02 BLOCKED_LICENSE 不变。
