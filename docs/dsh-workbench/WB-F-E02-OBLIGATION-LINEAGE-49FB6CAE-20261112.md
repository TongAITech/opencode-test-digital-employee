# F 独立复验 E02 义务批次一致性

**结论：接受 PR #269 的只读一致性修复。** 候选提交为 `49fb6cae99c38f1cbd777d01ed3a25596d287e03`，红灯对照为其父提交 `074183cf89a1d689871ee127f733c49cd7005cf7`。F 在两个隔离工作树运行同一独立探针，使用 PostgreSQL 17.6（ICU 构建）、实际 loopback HTTP 和临时持久 R1 fixture。Host 主体由显式测试 fixture 提供。

| 观测项 | 父提交 | 候选提交 |
| --- | --- | --- |
| 合法同批次独立义务，另有不同 Mission 的异批次义务 | 两路 HTTP 200 | 两路 HTTP 200 |
| 同 Mission/release、异批次、无 ETU 引用的正式义务 | 两路 HTTP 200，探针失败 | 两路 HTTP 503，`R1_LINEAGE_UNRESOLVED`，探针通过 |
| 无 Host 身份及 PostgreSQL ACL 完全撤销 | 两路 HTTP 403 | 两路 HTTP 403 |
| 恢复干净 R1 fixture，重新创建 HTTP 服务 | 两路 HTTP 200 | 两路 HTTP 200 |

探针经正式 `append_rc72_entity` 入口写入义务，经新建 `TruthRuntime` 查询验证同一 Mission 下两条记录的 release 和批次值。合法读取保留 `HOLD`、`UNKNOWN_NOT_QUERIED` 与 R1 SHA-256，响应记录未包含义务行。成功、拒绝与 ACL 撤销均逐字节检查 R1。探针在父提交 2.336 秒红灯，在候选提交 2.318 秒通过。探针保存在本次 F 工作环境的 `/tmp/f_e02_49fb_probe.py`。

候选提交本地 E02 真库套件 **36 通过、0 跳过**（17.169 秒），E02 独立纯 lineage 单测 **1 通过**。GitHub [E01/E02 组件工作流](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43065127893) 通过，checkout 为 PR 合成提交 `4964b74bfee1fadf73a5e29b38930bac11494cb3`，精确候选证据来自上述本地工作树。

验收范围是现有 E02 两条只读入口对当前 canonical 义务集合的批次检查。D263/F264 的正式运行批次独立映射、源事件唯一性和历史不漂移仍待相应实现与验收。此次复验未连接行内真实 DSH 或 Windows 环境。
