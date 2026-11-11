# D 审查 008 物理候选

审查 [B PR265](https://github.com/TongAITech/opencode-test-digital-employee/pull/265) 精确 `4d058cf3363e129a45846fafd1f583850c07626a`，结合 V3 `04ca971676509da9379ed53a29b495d2a32c325c`、D263 和 F264。D 接受按已冻结字段开展独立 PG 结构及事务测试。最终 R1 append 保持 HOLD。候选明确承认跨库时序尚未证明，故该缺口阻断最终通路，不阻断纯 PG 工单。

- snapshot、intent、append-only journal、receipt 引用历史、复合 FK、角色分离和事务级 K claim 可独立施工。PREPARE 在自身事务 durable commit，未知提交查原 K。以测试预留输入验证事务恢复和不重分配。生产 PREPARE 接入外部 authority 分配器前另审该首个外部副作用及当前 create/mutation/can_write。正式 request digest、runtime batch 预留物理形状及 receipt 发行者认证待对应冻结，不能使用伪造回执或占位 digest 启用创建。
- 专用锁函数 owner 的 NOLOGIN/NOINHERIT、无成员或表所有权、无 BYPASSRLS、固定 search_path、无动态 SQL 和列级 UPDATE 是合理候选。函数执行者只获指定 EXECUTE。实库必须验证 FORCE RLS 下 SELECT 与行锁都可用，且 restrictive UPDATE WITH CHECK(false) 压住任一既有 permissive UPDATE，不允许锁 owner 实际更新列。固定目录 profile 还需包含有效角色关系、PUBLIC 与 schema 写入授权。事务 principal 必须来自可信 Host 映射和隔离服务连接，GUC 或用户自报上下文无法证明主体。009 的锁证据只说明其既有场景。
- 当前受管路径下，`migrations/005_scope.up.sql:2–3` 的 ACL 插入/更新/删除会更新 project，`:6–7` 的四类关系插入会更新 release_batch。`002_membership.up.sql:11–12` 在批次日期 UPDATE 时推进关系版本。持有 project→batch 的 FOR NO KEY UPDATE 时，这些事务的相关 UPDATE 无法越过锁提交，FK KEY SHARE 仍可并行。该结论以实际覆盖的写路径为前提。锁不保护未触碰两行的全局配置、来源治理、角色/DDL、Host 撤权、raw ledger 或绕触发器维护。实现审查须逐一核参与锁和版本的真实路径、READ COMMITTED 等锁后重读、反向锁序与故障退出。V3 原 FOR UPDATE 到 FOR NO KEY UPDATE 的差异按实库证据另签。
- D263/F264 已证明当前唯一投影无法证明原始 creation 唯一或批次历史三元组稳定。008 的 PG authority 内唯一仅约束意图。正式 reader/writer 必须从可信配置固定一个 authority 对应受管 ledger，在同一快照核原始 creation 和该 ledger 的 exact-ID 全历史。不能以 PG FK、当前单行、按 digest 去重或外部自报 authority 替代来源。永久 operation ref 可贯穿 PREPARE、事件、回执和恢复。
- 最终事务的反例时序是 PG 完成锁内复验，应用收到最后 ping 成功，PG backend 崩溃或断线并释放锁，第二连接提交撤权或关系变化，已发起的 Host 回调再 durable append。PG rollback 不会撤销外部 R1。HostFence 只能证明其覆盖的撤权与提交排序，若 PG 变化不参与同一可证明顺序，R1 writer 排他、最后 ping 和超时预算都不排除该交错。提交未知后 lookup 用于恢复，不能使此前的越界写入合法。
- 生产准入前应另审可跨 PG 会话故障的 durable reservation 或把相关授权和变更纳入共同 authority 排序，亦可提出有同等证明的协议。普通 PREPARE intent 只保存身份，并未冻结并发变更。任何 durable reservation 需定义各相关变更的服从规则、epoch、释放、超时和原 K 对账，证明失联进程不能在失效后追加。不得自行将候选方案视为授权。最终验收用真实 PG 和两个正式 writer，在锁后及 append 前设置同步点，杀 PG backend、并发提交 ACL/关系更新并观测 R1 原始事件及零副作用承诺。append 已发生时须能查到唯一原回执，保留 R1 并单独处理回执失败。Host fixture 只验协议，真实动作、撤权围栏和执行租约仍待现场资格。

本次为源码与已有证据审查。未运行新的权限或跨库故障探针。
