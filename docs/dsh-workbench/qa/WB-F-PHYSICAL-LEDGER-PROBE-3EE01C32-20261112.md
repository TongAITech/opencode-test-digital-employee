# F 独立验收 POSIX 物理账本测试

接受 #304 精确提交 `3ee01c3289b88f69e7e97859675c237811f596ea` 的隔离测试。真实 Darwin x86_64 独立工作树以警告视为错误运行 3 项，全部通过，零跳过，1.116 秒。精确 [CI 43070912099](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43070912099) checkout 同一完整提交，Linux x86_64 实际 3 项通过，0.592 秒。

官方用例验证硬链接竞争、进程死亡后的接管、旧代次拒绝、路径替换拒绝及现有直接写入入口仍可绕过协作锁。独立额外探针通过符号链接持锁，确认原路径无法并发获取。写入并 fsync 后终止进程，恢复进程通过原路径获取锁并拒绝旧代次。冷回放保留唯一测试 Mission，字节一致；恢复进程正常退出后，另一进程从符号链接再次获得锁。

旧精确 `7dd376af` 的 [CI 43070780343](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43070780343) macOS job 在 checkout 前因 runner 配置 `macos-14-arm64-us-default` 不支持而失败。后续提交仅调整该工作流的支持范围及对应文档。macOS ARM、Windows、生产写权限闭包、持久代次和跨存储恢复均待各自证据。
