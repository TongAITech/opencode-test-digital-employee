# F 独立复验 008 PREPARE 日期格式

验收源为 [PR #278](https://github.com/TongAITech/opencode-test-digital-employee/pull/278) 的精确提交 `e6eccf1d9a137ae4c9844efbad67f7e57ec155e4`。独立工作树使用真实 PostgreSQL 17.6 + ICU、UTF8 和 8 KiB 块。

- 旧提交 `93289a93787225e48cc251c2a4c5fdbf26045f6c` 在 German DMY 下将同一 DATE 显示为 `12.11.2026`，PREPARE 误报 `SCOPE_008_SNAPSHOT_CONFLICT`，四表全部回滚为空。保留 [F #280](https://github.com/TongAITech/opencode-test-digital-employee/pull/280) 的旧源证据。
- 在精确新源执行同一首次 PREPARE 后，分别以 Postgres DMY、SQL MDY 和 ISO YMD 的独立冷连接验证原 K 重查及新 K 复用同一快照。最终快照、意图、日志、回执计数为 `(1, 4, 4, 0)`，原 K 重查保持原预留。
- 精确新源完整组件套件 11 项通过，零跳过，8.086 秒。独立并发探针实际观测等待者，撤权后拒绝为 `42501`，取消等待者为 `57014`，两者均零残留。随后新连接恢复成功，同 K 陈旧输入保留原持久版本，reader 角色查询不到正式准备记录，非空 down 拒绝并保留数据。

接受本次 008 隔离 PostgreSQL 测试夹具。生产迁移图、权威分配、Host 与最终 R1 写入仍待各自验证。
