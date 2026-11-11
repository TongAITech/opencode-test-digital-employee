# D 审查正式创建与业务撤权的提交顺序

审查 A #275 精确提交 `f4f6f557751f55f75fea50ace5c793b29fa96829`。允许隔离验证持久提交中记录、PG 源修改顺序和恢复状态机。生产接入继续 HOLD。以下探针使用可删除的本地 PostgreSQL 和 R1 数据，未修改行内 Host 或 R1 正式事实。

## PostgreSQL 源修改及可见性

- `005_scope.up.sql` 的项目 ACL 插入、修改和删除推进 `access_scope_revision`。ACL 换项目会触及两个项目。业务日期通过 `release_batch` 和日期审计修改，`002_membership.up.sql` 推进日期变化的 `relation_revision`。同批次 requirement、version、BRV、BRVS 插入也由 005 推进关系版本。这些正常修改须在同一个 PG 事务内参与提交中记录的顺序检查。
- `business_scope_preview.py` 还读取 requirement、system、system_version、SST 和已验证的 BRV/BRVS 源身份。需要以固定角色、真实 grants、RLS 和目录证明这些已引用内容不能原地改写。来源导入、维护 owner、TRUNCATE、约束或触发器修改、复制模式等管理路径须单独收口。009 的名称与治理字段当前未参与 Scope 编码，锁检查应按相关字段确定，保留现有业务语义。另测项目 ACL 双行移动、批次更新、关系触发器和 009 项目行更新的锁顺序，记录死锁或序列化失败后的原 K 恢复。
- 仅锁同一父行再插入独立标记存在 MVCC 漏洞。本次在真实 PostgreSQL 17.6/ICU、B06 fixture 中，撤权连接先以 REPEATABLE READ 读取无标记的快照。创建连接锁同一 project 行，插入测试标记。用 `pg_stat_activity` 实测撤权的 `FOR NO KEY UPDATE` 处于 Lock 等待，待创建提交后撤权连接取得锁，仍读取零标记，随后实际删除 `wb.project_acl` 并提交。第三连接看到标记仍在而 ACL 已删除。对照只增加 marker 事务的父行版本写入，撤权在争用后得到 `40001`，标记存在且 ACL 保留。两轮在同一实库测试通过，0.526 秒。对照使用 no-op 列更新验证 MVCC 版本行为，生产应设计独立且显式推进的序列化版本，或对全部参与入口强制并证明适用的事务可见性；单次应用层读标记不构成证明。

## R1 的写入权与陈旧写入者

`rc6_runtime/truth.py` 的实例内锁和追加后投影验证覆盖不了其他写入进程。`closed_loop_control.py` 的 Mission 创建与更新经 `truth_overlay.append_entity`，银行启动在 `bank_mission.py` 进入 Controller。canonical Batch 经 `rc72_repository.persist`，再经 overlay/append_atomic。资源与 Captain 等部分路径使用 `rc72_ledger_lock.py`，worker-start 和 release driver 各用其他锁文件。即使是无关类型的追加也可能竞争同一 R1 seq/cursor，锁端口须覆盖该账本的全部可写入口，或由权限和进程部署确保只能经一个 owner 服务追加。

实测临时 JSONL：父进程持现有 ledger_lock；同路径、同锁的子进程被拒绝。随后同路径直接调用现有 append_entity 的子进程可完成写入；另一子进程经同 inode 的硬链接取得不同的路径派生锁，也可写入。冷读得到两条 fixture Mission。该探针实耗 4.197 秒。路径 resolve 无法解决硬链接，锁 inode 被替换、日志轮转、跨宿主存储、父子进程继承以及具有文件写权限的旧二进制也需要实证。候选优先选用由配置固定的物理账本和单写入服务，持久 writer epoch 与进程凭证切换须在该服务内强制。清理只可在确认旧进程无法再 append 后进行。

## 撤权和恢复验收

标记存在时的冲突只说明撤权尚未提交。API、运维和审计必须清楚区分撤权请求、冲突和真实提交，向当前已授权读取者按现行读取合同处理；如产品决定在恢复窗口主动阻断读取，须单独签署。长期损坏或写入者挂起时，禁止以超时清除标记或假定旧持有者已退出。若业务要求在 R1 无法读取时仍立即生效，应先在同一权威执行可证明的写入隔离，再重新论证撤权顺序；若仍无法建立共同序列，保持 HOLD。Host 的撤权与 deadline 由真实 HostFence 独立判定。

可独立实现的隔离验证分三步：

1. 用真实 PG/B06 fixtures 增加版本化 gate 行，仅以显式测试入口执行标记登记、撤权、日期、关联变更；覆盖 READ COMMITTED/REPEATABLE READ、等待顺序和 40001 恢复、ACL 两项目迁移和跨批次影响。验证失败事务无 audit、ACL 或关系副作用。
2. 在受控临时目录验证单写入服务的多进程独占和进程死亡。测试旧进程持有句柄时恢复被拒绝、硬链接与替换策略、释放后冷读以及 stale epoch 在真实写入口被拒绝。分别验证 Windows 和 POSIX，不将现有 resource lock 当作全局门禁。
3. 结合两个隔离组件，注入 PG commit 回包中断、R1 fsync 前后退出、回执写入失败和不可读日志。只有原 operation 唯一核实或在排他权下证明未写入才允许清理。记录不可用时间。正式事件格式、真实 Host 和生产撤权 SLO 单独签署后才准入。

本报告只接受上述隔离验证范围。独立 PREPARE 可继续施工，生产 allocator、正式创建和跨存储发布维持 HOLD。
