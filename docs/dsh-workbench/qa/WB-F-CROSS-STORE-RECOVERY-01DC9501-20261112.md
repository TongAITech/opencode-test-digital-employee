# F 独立验收 PostgreSQL 与临时 R1 恢复夹具

接受 #309 精确提交 `01dc95012e7d477fb88d761b40aa09c1cb38fad1` 的隔离范围。独立工作树连接真实 PostgreSQL 17.6 并运行 Darwin POSIX 子进程，4 项通过，零跳过，2.071 秒。精确 [CI 43071434755](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43071434755) checkout 相同提交，Linux 与 PostgreSQL 17.11 实际 4 项通过，1.098 秒。

官方用例覆盖写入前进程死亡、fsync 后无回执退出、原事件冷恢复、陈旧代次、重复恢复、重复原行及截断原行保留标记。独立探针通过同 inode 硬链接发起竞争，确认故障前及恢复清理期间其他进程均无法取锁，真实撤权在标记持有期间冲突。成功恢复后撤权提交，B06 返回 403。冷投影仍仅有原 Mission，原字节未变化。

范围限于本地测试夹具和受控的空账本／单一原行。正式事件来源、权限部署、HostFence、Windows 与正式跨库恢复仍须验收。
