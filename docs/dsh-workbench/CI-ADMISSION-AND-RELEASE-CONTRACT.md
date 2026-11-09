# DSH 工作台三级 CI 施工与验收合同（2026-11-10）

状态：A 组 CI 限流候选。该合同只管理运行时机，不是 F 设计验收、W1 真实产品实现、现场验收或商业许可的证明。

## 根因
上个 A 集成 HEAD f8de595 上 11 次工作流、38 检查任务：V3 完整 Chromium 34 分钟，V4 完整 Chromium 53 分钟，内容大量重复；二者并发键带 SHA、cancel=false，不能取消已过时 PR；W0 同一 SHA push/PR 双运行；C04/C07/C10/N8 没有 PR 路径过滤。

## L0 / L1 / L2
| 门槛 | 触发条件 | 内容与边界 |
|---|---|---|
| L0 W0 快速准入 | 每次 A 集成分支 push | Python W0 + B/D/E/F 负向用例 + 机器 CI 策略反例；同 SHA 只触发一份 push，避免 GitHub App 写入 ref 时 PR synchronize 事件不可靠；不意味着真 UI/DB/R1 通过 |
| L1 综合集成 | PR 标记 ready_for_review 或以 expected_source_sha 手动运行 | B/C/D/E/F 联合契约 + C 15 个 Node 测试；仅人工选择 include_browser 才下载 Chromium 运行原型截图 |
| L2 正式 RC7.2 QA | 非草稿 PR 与明确手动验收 | V4 完整 4 环境矩阵 + 真实 Chromium + 原有全部 test_rc7*.py，不删除用例；V3 历史对比转手动/历史分支 |

草稿期不自动执行 V3/V4 全量和 C04/C07/C10/N8 四矩阵；L0 只需数分钟。进入 ready_for_review 和之后的正式 PR 修改仍必须在新的同 SHA 完整执行 V4；V3 历史能力保留 workflow_dispatch。手动验收不被 PR 后续同步取消，自动 PR 任务以 PR 编号而非 SHA 分组取消过时执行。

RC7.2 平台的 q1 Python3.8 浏览器反例保持启用。历史 FG17 Python3.8 下页面提示断言失败不能因减负隐藏；真正修复后需新 HEAD 负向回归。W0 145 项/原版 50 原子功能、F02/F03/F04、真实 B06/R1/Host、法务 LICENSE_RELEASE_APPROVED 仍为独立门禁；CI 限流绝不等于 W0 FROZEN 或银行可交付。

## 机器防回退与外部限制
tools/dsh_workbench/ci_admission.py 静态检查十个 GitHub Actions 源文件，tests/test_dsh_workbench_ci_admission.py 做 11 个真实/篡改反例；由 W0 专项 CI 同 HEAD 执行。检查会拒绝恢复 V3 的普通 PR 双全量、V4 Draft 全量、用 SHA 切碎并发组、W0 双触发、L1 源 SHA 不校验、旧模块无过滤、移除 q1 FG17 反例。

当前连接读取 GitHub branch protection API 返回 HTTP 403。因此 required-status-check 名单尚未核对；主线管理员必须确认 V3 取消自动 PR 检查不会造成受保护分支等待已废弃的 check。禁止因无法读取保护策略就声称验收要求已经解除。
