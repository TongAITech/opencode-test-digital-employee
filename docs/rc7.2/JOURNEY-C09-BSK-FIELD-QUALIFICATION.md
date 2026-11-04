# RC7.2 C09 — BSK 原生 Journey：完整移交与行内验收合同

> 2026-11-04 C09 收尾分支 `work/rc7.2-journey-closure`。本文件是施工与验收合同，不是 Field PASS 报告。合入权归会话 A，独立验收归 E。

## 一、不得改变的职责

1. **BSK/DSH BrowserSkill**：Agent 浏览器操作与真人教学、协作控制、调试采集、网络请求元数据、物理 PNG。必须连接 B 组签发且仍有效的 Session+Tab；不得用旧 CDP 连接冒充 BSK，不能默认拥有用户浏览器。
2. **BrowserPool / B 组**：BrowserInstance、Profile、4A AuthAsset、BSK endpoint、独占 BrowserLease、Worker/Attempt、DSH Session、真实 BSK Session+Tab、绑定凭证。会话 ID 字符串不是授权凭证。
3. **C09 引擎**：BSK DebugRecording v1 → 逐操作 BSK sync/PNG → 录制 R1 → Candidate → Journey IR → 受控回放/Oracle → Benchmark → 人类 Field 审批 → Official Journey → L4/L5。
4. **A 组**：将 `journey_bsk` 正式注册到冻结 N6→N7 ToolDispatch，原有 Field Gate、R1 和 N8 恢复不可绕过；整包只从最终集成 HEAD 构建。
5. **E 组**：独立比较设计与实现、同 SHA CI、整包冷解压、现场真 BSK/4A/Business Oracle、证据 Viewer 和签名；不以这份设计合同代替结果。

## 二、已提交的 C09 实现

| 模块 | 实现 |
| --- | --- |
| `rc7_runtime/rc72_journey_bsk_live_teaching.py` | 受控 BSK `debug start`、一次操作一次 `debug operations` + `cooperate sync --save-full` + `screenshot`；溢出/未完成/页面快照失效 fail-closed，最后 `debug stop/export`。不会建立/结束 BKS Session |
| `rc7_runtime/rc72_journey_bsk_import.py` | 原生 BSK 调试导出 JSON v1 + 绑定凭证 + 授权证据根目录；逐操作唯一 snapshot/PNG，完整性+来源检查；原子 R1 Case/Attempt 谱系；Oracle 紧随原操作 |
| `rc7_runtime/rc72_journey_bsk.py` | 原生 `bsk step/evaluate/screenshot`、每步 fresh `cooperate sync`、固定 Tab/BSK/4A/租约、实体 UI Oracle、真实 PNG SHA/CRC；重启后同一步不重放；网络 Oracle 未获独立业务证明前不得 PASS |
| `rc7_runtime/rc72_journey_png.py` | PNG 结构、分块 CRC、尺寸和 SHA256 标准库验证 |
| `rc7_runtime/rc72_journey_n7_adapter.py` | `SignedN7OfficialBSKAdapter` 的 `journey_bsk` 工具；沿用批准、Case/ETU/Attempt/Lease 预检 |
| `rc7_release/rc72_journey_bsk_qualify.py` | 行内整包只读资格检查、真实 BSK+Extension/Tab、物理截图、SOURCE_COMMIT、哈希、失败码；永远 Field=false |
| `packaging/rc7.2/QUALIFY-JOURNEY-BSK.sh` | 免安装 Windows Git Bash / 包内 Python 启动脚本；不从公网下载安装 |

单元和合同测试文件：`tests/test_rc72_journey_bsk_import.py`、`tests/test_rc72_journey_bsk_live_teaching.py`、`tests/test_rc72_journey_bsk_native_adapter.py`、`tests/test_rc72_journey_bsk_field_probe.py`。旧的 Playwright/CDP 测试属于补充能力，**不得替代 BSK**。

## 三、A 组应合入和打包的验收顺序

1. 从最新 `work/rc7.2` 和 PR #13 新 HEAD 重新计算合并。会话 A **唯一**有主分支写权限，C09 不主动合并。
2. 在生产 N6 ToolDispatch 注册 `journey_bsk`，要求冻结合同 `source_ref=official-journey://<asset>`、ScopeDigest、ETU L4/L5、Case、Attempt、B WorkerLease、BrowserLease、真实受信任 SessionResolver。
3. B 组提供与真实 BSK daemon+extension 通讯的 SessionResolver，输出字段 `bsk_session_id`、`tab_id`、`browser_instance_id`、`profile_dir`、`bsk_endpoint`、`auth_asset_ref`、`browser_lease_id`、`mission_id`、`workitem_id`、`attempt_id`、`worker_id`、`dsh_session_id`、`state=ACTIVE`、`source_receipt_ref`，并在每步核查 R1 真值；不得手填这份结构绕过 B/4A。
4. A 组最终整包必须含 `bsk.exe`、对应 Chromium 扩展、DSH BrowserSkill 插件和离线工具，包内 Python 可导入上述 C09 模块。若仍交付补充 CDP 能力，须另外包含兼容的 Python Playwright 依赖，不能把 Node Playwright 当作替代。
5. 用最终 HEAD 构建完整 zip，生成 `SOURCE_COMMIT`、SHA256、包内清单，按 A 的 Windows 干净解压 CI 验证；E 复查同 SHA 其他 CI 及包内真实运行。

## 四、行内实际资格探针（只读，不修改 PCC）

在解压后 Windows Git Bash，B 组已给出授权 BSK session 与确切 tab 后：

```bash
# BSK 可执行文件自动从 workspace-template/runtime/browser/browserskill 内定位唯一的 bsk.exe
export PFC_RC72_BSK_SESSION_ID="<由 B 组实际签发的 BSK session>"
export PFC_RC72_BSK_TAB_ID="<对应 tab 数字>"
bash packaging/rc7.2/QUALIFY-JOURNEY-BSK.sh
```

BSK 二进制路径以整包清单为准；脚本自动定位 `workspace-template/runtime/browser/browserskill` 下唯一的 `bsk.exe`，多份或缺失都失败，不会调用 PATH 中其它版本。必要时可显式设置 `PFC_RC72_BSK_BIN`。不得从旧版本复制 BSK。运行输出位于 `runtime-state/field-qualification/c09-bsk-readonly/c09-bsk-probe.json` 与 `live-browser.png`，包括 SOURCE_COMMIT、BSK 二进制 SHA、PNG SHA/尺寸、实时 Extension capability 和合作控制状态。即使结果为 `READ_ONLY_BSK_PROBE_PASS`，也只是**真实环境只读工具探针**，绝不是 Field、业务测试或官方资产审批通过。若成功后需要重新执行，指定新的报告目录；禁止覆盖旧证据。

## 五、PCC/4A 正式 Field 路线

- 以 PCC 实际版本批次、SST、需求、L4/L5 ETU、Case 和独立 Attempt 建立真实任务；B 组先确保真实 4A 自动登录和 BSK Session/Tab 可用，不允许借历史会话假状态。
- BSK debug start 必须在操作前；真人或 Agent 在授权标签页教学并逐操作录快照和 PNG。业务前置、步骤、数据、业务 Oracle 要有独立设计；不能只做 happy path。
- BSK 录制完成后 `debug stop/export`，走 JourneyImporter → Compiler。Candidate 默认不可执行，若缺 Oracle 明确不能晋级。
- 用新的 Attempt、独立 BrowserLease 从 BSK 回放；校验实际 HTTP 业务返回+DOM/系统状态，失败要保留 Actual、PNG、R1，未知副作用不可自动重试。当前 BSK `network_status` 因无法证明时序窗口即因果而 fail-closed；**A/B 必须补真实业务证据联动**，不要改为凭 HTTP200 通过。
- 多次真实 Field 回放达到 Benchmark Policy 门槛后，由 B/A 外部可信 Field 适配器核销 Field=true（当前普通 adapter 绝不自行置 true），再交真人独立审查授权、签名和 ScopeDigest，方可晋级 Official。
- 官方资产通过冻结 N6→N7 签名工具路由 `journey_bsk` 实际 L4/L5 执行。要求反向验证：4A 失效、错误 Tab、重复 Attempt、租约回收、超时、网络业务失败、页面错误、数据不一致、版本代码漂移。

## 六、尚未核销的事实

**CI**：C09 当前工程测试需要在 PR #13 最新 HEAD 有有效同 SHA PASS；旧 SHA/queued/cancelled 不能代替。
**A/B 接线**：生产路由、BSK SessionResolver、外部可信 Field 适配器、业务网络 Oracle 尚未与 Field 验证合并核销。
**整包与现场**：会话 A 未交付本 PR 合入后的完整 SHA 对应包，现场 PCC/4A 真机验收未完成。以上缺口不能靠生成演示报告或手动改 `field_verified=true` 解决。

当前交付状态：**C09 BSK-first ENGINEERING_CANDIDATE / PRODUCT_INTEGRATION_PENDING / FIELD_PENDING**。

## 七、2026-11-04 后续增量（C09 编码收尾）

- BrowserSkill 已扩展为原生 `NAVIGATE / CLICK / INPUT / SELECT / PRESS / HOVER / SCROLL_TO / DRAG`。键盘操作仅接受可审核的固定按键（Enter/Tab/Escape/方向键等），拖动必须有稳定目标引用；不支持的 iframe/Canvas/native 对话框或其他 BSK 操作必须 FAIL_CLOSED，不许无声跳过。输入凭证一律由 B 组原生受控工具处理，不能把 4A 密码/验证码放在 CLI 进程参数中。
- 点击导致页面跳转时，Journey CLICK 使用 BSK operation.before 的**原始页面**定位，结果 Oracle 使用 operation.after 的**目标页面**。源页面缺失或操作数据不完整直接拒绝生成 Candidate；所有 URL 去掉查询参数后才保存 Evidence。UI 业务 Oracle 紧跟源操作，不能追加到 Journey 末尾。
- 真实 PNG 必须经过 IHDR/IDAT/IEND、分块 CRC、尺寸和 SHA-256 校验；教学的 BSK 原生 DOM 快照、截图必须按操作独立留存，源文件位于 B 组授权的 capture root，不能跨会话借用或伪造路径。
- `rc7_runtime/rc72_journey_bsk_field.py` 新增**外部受信任 Field 适配器**：标准 BSK 适配器永远不自称 Field。只有 A 在受信任的 adapter kind allowlist 注册、B 的签名验证器返回与 Case/Attempt/BrowserSession/Tab/4A/Lease 完全匹配且未过期的 Field 证明，才可能向 JourneyReplay/Official 报告 Field。任何跨 Scope、签名无效、过期、模拟适配器静态布尔值都不能通过。BSK 执行中如果 Field 证明过期，即使 UI 返回成功也必须 FAILED。
- 工程级长链路测试 `tests/test_rc72_journey_bsk_full_chain_contract.py` 使用明确标为 **SIMULATED** 的 B 签名器与人类审批器，验证 BSK 导入→两次不同 Attempt 回放→Field Benchmark→审批合同→Official L5 的**状态机与代码连接**。模拟数据只属于 CI，绝不代表银行 Field 已验收；真实 Field 签名和现场 R1 需 A/B/E 验收。
- 如 BSK DebugRecord 只包含不完整的操作前页面状态，或者一次 poll 有多项未消费操作，不能补猜操作或把最后一页截图冒充前一步 Evidence；应 BLOCK 并通过新 Attempt 重试，保留诊断记录。

**最新尚未完成事项**：A 将 PR #13 合入正式 N6/N7 ToolDispatch、B 提供真实签名验证器与 4A Session/Tab 权威资产、E 验证最新集成 SHA 的 CI 与完整 Windows 离线包和真实 PCC Field。只有三方证据齐全才能把本文件的状态从 `PRODUCT_INTEGRATION_PENDING / FIELD_PENDING` 核销。

## 八、C09 收尾核销增量：原生 BSK 协议、授权与业务真值

1. **真实 BrowserSkill 协议校对**：已按 Tencent BrowserSkill CLI 的 DebugRecording v1、`cooperate sync`、`step`、`evaluate`、`screenshot` 参数/回执收紧；严格协作产生的 `context_id` 必须真正随 `--context` 传给 `step/evaluate`，实际结果的 tab_id 不能和 B BrowserPool 绑定标签页不一致。导航后必须真实读取 URL，4A 重定向到登录页面不能判业务通过。截图必须匹配 PNG CRC/SHA、宽高、tab，禁止 capture_unavailable。
2. **独立 B 组 Session Authority 强制接入**：`JourneyBSKAdapter` 与 `BSKJourneyTeachingImporter` 都要求 `session_receipt_verifier`，不能再拿调用方自填的 `source_receipt_ref` 和匹配字段作为授权真相。A/B 将此方法接到真实 B/DSH/BrowserPool R1 签名租约并核查吊销；CI lambda 只是测试替身。真人教学启动、每一次操作、截屏后、导入前均需完整校验，未接权威服务要失败。
3. **断电/重启前置 Intent**：`JourneyBSKAdapter` 在 BSK 真实动作前用独占文件 `dispatch-intent.json` 写入+fsync；既有未决意图（即使无 Actual/PNG）一律不重执，同一 Attempt 冷重启进入副作用诊断并保留原文件。这是对正式 N7 原有 IN_FLIGHT/Claim 双重保护的补充，而不是替代 N7 全局 Fence。
4. **原生 BSK 操作完整度**：IR 已包含 CLICK/NAVIGATE/FILL/SELECT/PRESS/HOVER/SCROLL_TO/DRAG/WHEEL，按 BSK 源码真实支持 `tool.scroll_to` 以及限定范围的 wheel Delta；按键受白名单限制，跨对象/页面的操作需稳定 selector。对 BSK 不可安全回放的原生手势明确 BLOCK，不编造动作。
5. **业务 Oracle 不是 HTTP200**：`JourneyBSKAdapter` 新增外部 `business_oracle_verifier` + `trusted_business_verifier_kinds`。对于 `type=backend_state`，需使用独立 API/DB/CAT 业务状态查询，证明当前 Mission/ReleaseBatch/Requirement/SST/Obligation/Case/Attempt/BrowserLease/BusinessRule 与 `expected` 匹配，并返回 `source_kind`、已验签的 verifier_kind、有效 `observed_at`、真实 evidence_refs；原有仅有 BSK 请求时间窗/HTTP200 的 `network_status` 仍 FAIL_CLOSED。外部校验器由 A/B 绑定实际 PCC 系统与现有 CAT/TDSQL/接口路由技能，C09 合成测试不可冒充行内业务证据。
6. **真实运行版本提醒**：A/B 打整包应与 `rc7_release/runtime_payload_materializer.py` 物料对应的 BSK CLI + Extension + DSH 插件配套版本执行原生 `debug capabilities` 实测；这份 C09 工程实现只基于公开 BrowserSkill 协议审计，必须以**打包版本在行内真实输出**为准。

### 会话 A 的具体 N7 注入边界

在 B 组 `rc7_runtime/rc72_n7_tool_dispatch.py` 现有 `N7ToolDispatch(preparation, adapters=...)` 初始化时，A 统一注册 `adapters["journey_bsk"] = SignedN7OfficialBSKAdapter(OfficialJourneyExecutionService(..., adapter=JourneyBSKCertifiedFieldAdapter(...)))`，并保证 C09 的 `journey_bsk` 在 N6 冻结合同、Worker allowed_tools、浏览器租约、清理/验证工具 allowlist 中存在。不得借用 `journey_playwright`，也不得绕开正式 N7 dispatcher 直接调用 Official service。必须调用 B 的真正 SessionResolver、外部 SessionVerifier、Field 证明校验器和 API/DB/CAT BusinessOracleVerifier；否则不给出 Field PASS。

**工程测试**：`tests/test_rc72_journey_bsk_native_adapter.py` 新增后端独立业务证据和正式 N7 回归，`tests/test_rc72_journey_bsk_full_chain_contract.py` 保持模拟完整链验证，`tests/test_rc72_journey_bsk_field_attestation.py` 核实外部签名门槛。只有 PR #13 最新同 SHA CI 全绿、A/B 产品接线、E 独立现场验收才可从 ENGINEERING_CANDIDATE 提升为 CLOSED。
