# A 联合回归 c397d016

测试源 `c397d016b60146dd640cc2b87fb4513d8ef54b54`。独立 detached worktree 固定源，包含 F #294 的固定 R1 批次历史校验及 F #295 的 Evidence 夹具修复。

- 本地真实 PostgreSQL 17.6 + ICU 工作台 743 通过、零跳过，204.347 秒。
- 本地真实 PostgreSQL、HTTP 与 Chromium 11 通过、零跳过，62.598 秒。
- 本地 JavaScript 124 通过、零跳过。
- 远端 [E01/E02 组件](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43069965675) 精确 headSha 一致，SUCCESS。
- 远端 [继承 RC7/RC7.2 完整回归](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43069965805) 精确 headSha 一致，尚在排队。

旧 `44222081` 联合本地 720 项有两处 `NameError`。后续固定旧源 `388b21b4` 742 项复现两处相同错误。F #295 对该旧源及精确修复 `a5ae9bf2` 做真实 PG/HTTP 独立对照，修复源 73 项组件测试通过。旧失败保持。行内及发布资格待验。
