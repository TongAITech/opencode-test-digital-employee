# F 独立验收 PostgreSQL 版本化围栏隔离验证

接受 #296 精确提交 `cb3106313becdc82eec9b38b64bd7c0ecce78df5` 的隔离测试范围。独立工作区在真实 PostgreSQL 17.6 执行 3 项，零跳过，1.366 秒。覆盖 READ COMMITTED 与 REPEATABLE READ 等待者、终止登记连接后保留标记、日期与关联原子拒绝及恢复、旧 generation 清理拒绝。

独立反向并发探针先让撤权事务持锁，实测登记连接等待。撤权提交后登记事务推进到 generation 2，读取到 ACL 已不存在，随后回滚。持久状态保持 generation 1 且无登记标记。

本次范围限于隔离数据库的顺序与回滚证明。生产入口覆盖、正式 R1 写入权与恢复、Host 撤权和运行环境仍需实际验收。
