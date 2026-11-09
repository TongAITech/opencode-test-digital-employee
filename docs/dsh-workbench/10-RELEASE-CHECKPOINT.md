# 工作台交付检查点
状态：W0 文档阶段；不是已交付产品
基线仓库：TongAITech/opencode-test-digital-employee
基线分支：work/rc7.2
初始源码 HEAD：3de74c2bf3a0f3a555ccd979edd2832f26c9963a
独立设计分支：work/dsh-wb-w0
当前已验：原版六页面/十分区从公开源码与指南核对；RC7.2 01/04 设计合同及 rc7_admin/server.py 当前接口核对；11 份 W0 合同已通过 GitHub API 写入分支并建草稿 PR。
未验：独立实现源码、现场宿主、同 SHA CI、商业源码授权、真实批次数据、人工门禁、完整 Windows ZIP。
当前 W0 工单：WB-A00 CODE_COMPLETE，草稿 PR #84（https://github.com/TongAITech/opencode-test-digital-employee/pull/84）待 F 组独立审阅；35 个工单中其余未核销。
下次会话入口：先核对最新 HEAD/PR/check-runs，读取 00–10，核销 W0，按工单依赖继续；不得凭本文件旧 SHA 直接施工。
交付声明必须明确“设计完成”“代码完成”“CI 通过”“现场通过”四种不同状态。

## 2026-11-09 A 组持续检查点
- work/rc7.2 @ 3de74c2bf3a0f3a555ccd979edd2832f26c9963a；草稿 PR #84 OPEN，Review=0，未合并。
- W0 原始 HEAD=12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8；首个实际代码提交=4046029591b0b324e6a33028629dc22034d511d0；修复通知路径提交=82c18fdd93867e7d27107f665e124c5edcae8b2c。
- 首轮同 HEAD 轻量 CI: https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42582069489 运行 32 个，30 通过、1 失败、1 错误。此处不写 CI_PASS；必须重新检查后续 HEAD。
- WB-A00 文档/PR 产物确认 CODE_COMPLETE；WB-A01 候选功能清单确认，实际页面未实现；WB-A02 BLOCKED_LICENSE；WB-A03 跨组签收待完成。F 尚未签名，W0=NOT_FROZEN。
- 银行真实部署、DSH 宿主、Teams 32 并发、实库映射、R1 真实 API、F 现场 QA、全量 Windows ZIP 均未验，本轮不构建/不合并/不放行。
