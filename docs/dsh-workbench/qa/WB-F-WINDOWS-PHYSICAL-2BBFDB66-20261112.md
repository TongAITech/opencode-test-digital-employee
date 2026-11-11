# F 独立验收 Windows 物理账本锁夹具

审查 [#315](https://github.com/TongAITech/opencode-test-digital-employee/pull/315) 精确提交 `2bbfdb66ff5999f67c6a451b0a4cb94a651cde38`。核对 [实际 CI 日志](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43072034145) 三个 job 的 checkout 和记录的 HEAD 均为该精确提交。

- Windows Server 2022 runner，内核构建 20348，Python 3.11.9 x64。Windows 专项运行 1 项通过、零跳过，0.178 秒。使用临时 R1 文件验证主路径和硬链接竞争都被拒绝、旧持有进程退出后可接管、旧代次请求不改变字节、新代次追加后冷回放只有一条 Mission。
- Linux x86_64 的 POSIX job 执行 3 项通过，Windows 用例按平台明确跳过 1 项。Linux 实库恢复 job 4 项通过、零跳过。
- 本地独立精确工作树用 warnings-as-errors 复跑。Darwin POSIX 3 项通过、Windows 跳过 1 项，1.051 秒。真实 PostgreSQL 17.6 和 POSIX 子进程恢复 4 项通过、零跳过，2.043 秒。

变更限测试夹具、测试和 CI。Windows 证据范围是协作进程的字节范围锁和进程退出恢复。Windows 路径替换、非协作直接写、Windows 跨库恢复以及行内离线部署仍待验证。生产写入权限闭包须另行证明。
