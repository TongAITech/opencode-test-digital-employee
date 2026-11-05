# RC7.2 — BrowserSkill v0.4.1 移动端 H5 正式施工与验收

> 状态：ENGINEERING_CANDIDATE / FIELD_PENDING / BANK_FINAL=NO。本文不是行内已验收报告。
> 施工 PR #33；从 ABCD-v4 冻结候选独立施工，不覆盖 C09 已冻结的 B 授权、4A、N7、N8 与 R1。

## 1. 离线物料绝对版本

* BrowserSkill CLI/Daemon：腾讯官方 `cli-v0.4.1`，Windows x64 `bsk-v0.4.1-x86_64-pc-windows-msvc.zip`
* CLI 官方发布包 SHA256：`f4a62af2dde31508188ea0c80feee11dbb62d9e7b7bf388f3f3a9856cfffb37d`
* Chrome/Edge 扩展：官方 `ext-v0.4.1`，`browser-skill-extension-v0.4.1-chrome.zip`
* 扩展官方发布包 SHA256：`75e38414e732679b7fe7616de9f3bb80dbb9cfcc55d9cab2566dbcebb4cd9b51`
* DSH 插件：npm `@wxg-prc-cpg/browser-skill-dsh-plugin@0.4.1`，工程构建时 `npm pack`，存储实际完整性摘要和 package.json；旧版/替换规格拒绝。
* 协议：CLI/Daemon/Extension v0.4.1 需要协议 `1.8`。仅检查 exe 文件存在、`bsk --version` 或安装新 CLI 都**不足以**证明活跃 Daemon/Extension 已升级。

`rc7_release/runtime_payload_materializer.py` 精确请求版本标签、单一资产名与上述 SHA，下载时再校验实际字节；`plugin_payload.py` 拒绝 BSK 插件被环境 override 改为 `latest`，离线包 materialize 时也要核对插件实际版本。Python 3.8 与 3.11 均需验收。

## 2. H5 移动端控制面

受 B 组签名 Session/Tab/BrowserPool/独占 WRITE BrowserLease 约束，只有 Host 可通过 `JourneyBSKAdapter(mobile_device="pixel-7", mobile_orientation="portrait", ...)` 显式选择预设。支持：

| 预设 | 竖屏 CSS 视口 | DPR | 方向 |
| --- | --- | --- | --- |
| iphone-14 | 390 × 844 | 3.0 | 竖/横 |
| iphone-14-pro-max | 430 × 932 | 3.0 | 竖/横 |
| iphone-se | 375 × 667 | 2.0 | 竖/横 |
| pixel-7 | 412 × 915 | 2.625 | 竖/横 |
| galaxy-s23 | 360 × 780 | 3.0 | 竖/横 |
| ipad-mini | 744 × 1133 | 2.0 | 竖/横 |
| galaxy-tab-s8 | 800 × 1280 | 2.0 | 竖/横 |

一次 Attempt 第一步**先**获取独占浏览器租约、校验 B 签名与 Tab、严格合作控制同步、在证据根目录持久写入并 fsync `dispatch-intent.json`，然后才对同一 Session/Tab 执行真实 `bsk emulate --device <preset> --session <id> --tab-id <id> --json`；横屏需附 `--width` 和 `--height`。真实 CLI 回执须准确包含 viewport、mobile=true、touch=true、UA、DPR 和 Tab。

每个后续 H5 步骤用受控只读 `bsk evaluate` 证明浏览器实际的 `window.innerWidth / innerHeight / devicePixelRatio`、`navigator.userAgent / maxTouchPoints` 与 Host 预设相符，重新 `cooperate sync --policy strict` 后才可下发一次性动作。发生 Tab 切换、会话撤销、触控/尺寸不一致、无截图/业务 Oracle 时立即失败；失败保留独立 Actual 与源 Intent，不以新线程重放未知副作用。非移动端仍采用旧 C09 行为。手机号/验证码/4A 凭证禁止写入 CLI argv。

> **不能夸大：** CDP viewport、UA、TouchEmulationEnabled 仅模拟移动浏览器环境，不能替代真实手机、多点触控、摄像头、生物识别、物理键盘、特定 App WebView 或设备传感器。原生手势不支持时需明确 BLOCK/HUMAN_GATE。

## 3. 现场银行验证（E 组独立执行）

在正式同 SHA 离线 ZIP 解压后、禁止联网安装的 Windows Git Bash：
1. **物料**：检查 `SOURCE_COMMIT`、ZIP SHA256、`bsk --version`、`bsk status --json` 的活跃 daemon_version=0.4.1、protocol_version=1.8、无 version_skew_browsers；`bsk debug capabilities --session <B-issued-session> --tab-id <tab> --json` 的 CLI/扩展均为 0.4.1。
2. **只读资格探针**：提供 B 组已签发且未到期的 BSK session、同 BrowserLease Tab，调用 `bash packaging/rc7.2/QUALIFY-JOURNEY-BSK.sh`。生成 `c09-bsk-probe.json`、物理 `live-browser.png`。它只可判 `READ_ONLY_BSK_PROBE_PASS`，不得置 `field_verified=true`。
3. **真实 H5 测试**：由 A/B 正式签名任务以 iphone-14、pixel-7、galaxy-s23、横屏至少各一次运行进件、审批跳转、签约、提款场景。新 Attempt + 独占 BrowserLease + 4A 每次新认证 + 真实 BSK Session/Tab；需要滑块、人脸或短信等时严格使用 4A Skill/Human Gate。
4. **业务 Oracle 与负例**：页面 DOM 与实际 API/DB/CAT 状态一致；必须覆盖登录态失效、SSO 跳转、手机断点布局、表单校验、滑动/拖拽失败、错误 Tab、租约回收、模拟/真浏览器差异、超时和重启未决副作用，不能只测 happy path。
5. **证据核销**：原始 BSK debug/capabilities、真实 `emulate`/evaluate 回执、PNG SHA、R1 Event/Evidence/Actual/Defect、SUT 独立业务 Oracle、有效数据准备和版本代码快照。E 组逐 Case 复核签名、完整性、同一 HEAD、可复现性。无银行现场凭证不得宣布 BANK_FINAL。

## 4. CI 与资格边界

GitHub CI 四平台工程测试证明：Host 选择、模拟 CLI 参数、移动端真值探针**解析及 fail-closed 逻辑**、真实来源素材的版本固定、原有 C09 状态机不回退。CI 使用明确标注的 `MobileBSK` fake，**不证明**真实银行浏览器移动执行，也不代替真 BSK daemon/extension 的同机协议核验。正式 C12 需在最终 A 总集成 HEAD 从零构建离线包，E 组独立解压验签；RC7.2 主线未合并前始终 FIELD_PENDING/BANK_FINAL=NO。
