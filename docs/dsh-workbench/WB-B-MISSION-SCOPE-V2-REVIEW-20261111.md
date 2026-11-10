# B：Mission Scope 协议 V2 独立复审

被审：PR #181，精确 `957874d6d24b78b6c61b243f3c952d57bc33a0b2`；对照原B报告 `a4670bb4`、集成 `aa533c21` 及RC7.2 `edaf9290`。角色：B；未参与被审V2编写。结论：**B_V2_REVIEWED_WITH_BLOCKERS / B_SIGNOFF_NOT_GRANTED**。V2明显补齐了规则，但下面三处P1仍须修订，不能把“未来接口必须存在”当成当前可实施的已签接口。没有P0实现漏洞判定；这些是设计增量的接口/一致性阻断。

本次工具实际正常执行，没有额度错误。只新增本审查报告，未改被审合同、数据库迁移、正式模型、R1、08/09/10。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER。

## 原四项的逐条结论

| 原ID | V2补齐部分 | 剩余与是否核销 |
|---|---|---|
| B-MS-01 | schema、排序、null、重复拒绝、摘要域及全页一致性已有明确方向 | **未核销/P1**：统一source对象无法从现有真实link字段生成；缺实际来源适配与最终快照端口；转义规则仍须精确到字节 |
| B-MS-02 | R1唯一权威、PG只存引用、V1新release、append-only/FORCE RLS/分权及拒绝破坏性down可接受 | **未核销/P1**：008意图/回执的幂等主键与正式权威域不一致，回执所携身份/digest与intent的一致性未由复合约束明确保证 |
| B-MS-03 | 原主体域、submit/lookup、未知≠NOT_FOUND、持久身份不重分配、禁止Bob重放及不以outbox冒充accepted可接受 | **未核销/P1**：与008域统一后才可冻结；正式lookup/CAS/不可分割创建事件仍是E待定义端口，不是既有可调用能力 |
| B-MS-04 | 规定正式writer→PG→Host→R1顺序、append后PG失败走回执恢复、缺Host围栏HOLD；不再误称仓库无OS锁 | **未核销/P1**：现有B06不能在所述持锁事务中调用，现有runtime不能直接锁project；新受控端口、权限与事务隔离/超时尚待给出。Host及正式writer能力还需D/E签署 |

## P1-1：来源结构及B06适配不是一个待填source_ref

V2第1节第9行要求每个source固定含 `source_system/source_namespace/source_object_id/source_revision/source_ref`。真实 `verified_requirement_version` 只有 `(project,batch,requirement,version,source_link_ref,source_revision)`；`verified_sst_link`只有对应五元业务键及 `source_link_ref/verified_source_revision`。后两张表没有前三个来源身份字段，不能只补一个ref就符合统一形状，也不能把业务ID或标签猜作来源ID。

真实B06页没有 `date_revision`，没有 `system_id` 或requirement/version/SST身份来源；BRV实际为 `{source_link_ref,source_revision}`，BRVS为 `{source_link_ref,verified_source_revision}`。B06的游标字段是 `next_page_cursor`，V2第15行写作 `next_cursor`；B06过滤参数叫 `system_version_ids`，V2内部叫 `version_ids`，需明示映射。

最小修订建议：在新协议中冻结带tag的实际来源结构，而不是补猜缺列。例如BRV source固定为 `{kind:"VERIFIED_REQUIREMENT_VERSION",source_link_ref,source_revision}`；BRVS source为 `{kind:"VERIFIED_SST_LINK",source_link_ref,verified_source_revision}`。requirement/SST身份来源使用各自现有五字段；version身份没有source_ref，固定保存现有 `(project_id,version_id,system_id,source_system,source_namespace,source_object_id,source_revision)` 的结构化来源身份，明确schema/tag，不伪装已有外部链接。新端口在同一最终事务中从真实复合FK关系连结身份来源和 `release_batch.revision`，不能从浏览器或旧B06 DTO补来源。若坚持统一五字段，需要另行受控来源schema迁移及来源证据，不能直接声称当前数据足够。

摘要还应精确定义控制字符转义：JSON中换行可编码为 `\n` 或 `\u000a`，均属于必要转义但字节不同；现有DB允许非空来源字符串包含控制字符。请固定 `"/\\`、短转义和其余U+0000–001F的编码方式/hex大小写、拒绝未配对surrogate，以及整数可表示域，再给黄金向量。仅“JSON必要转义”和后续测试要求不能代替规范字节。

## P1-2：权威幂等域、008主键与回执一致性

V2第33行正式域包含 `formal_authority_ref`，第26–27行PG意图/回执PK及FK却不包含它。同actor/project/batch/key在不同authority下按第33行是两个域，按008却是同一行；恢复按哪个域查、authority轮换后是否碰撞，不能留给实现自行决定。

最小修订二选一：把authority纳入intent/receipt完整PK及对应复合FK；或明确V1一个project/batch被不可变固定到单authority，PK故意排除authority，并规定任何authority差异恒冲突/HOLD，绝不自动重新创建。禁止一边称它为不同域、一边靠未说明的唯一冲突决定恢复语义。

回执还携带mission/release/binding/digest，当前表只写PK→intent，不保证这些重复列等于该intent的正式身份。建议receipt只保留经验证的正式回执引用与hash，正式身份全部从intent读取；如必须重复存，增加包含authority/actor/project/batch/key/mission/release/binding/request_digest的intent唯一键和receipt完整复合FK。snapshot和request摘要固定长度/schema校验、NOT NULL、actor与受控当前principal映射、RLS读写角色也需作为008签署内容，不靠应用错误路径补救。

本建议不要求在设计审查时假造008 SQL已经落地；它要求合同把上述不变量定清后再实施/实库测试。正式R1创建回执、lookup及持久CAS仍由E所有，B不代签接口已存在。

## P1-3：现有B06不能充当最终持锁快照端口

`BusinessStore._scope`（business_store.py:28）明确拒绝外层事务；`ScopeStore.scope`每页自行进入REPEATABLE READ READ ONLY事务。实测先在同一connection建立外层事务，再调用scope，得到 `ValueError: IDLE_CONNECTION_REQUIRED_FOR_SCOPED_TRANSACTIONS`。这条保护来自已修复的旧身份泄漏，不应为新协议直接删除。

当前最小runtime角色执行 `SELECT project_id FROM wb.project WHERE project_id='P1' FOR UPDATE` 实测 `InsufficientPrivilege / 42501`。因此V2第43行不能直接由现有runtime+B06组合执行。另开连接分页后再append也不是它声称的“同一最终锁定事务”。这不是现有只读B06产品故障，而是新提交协议缺少受控端口。

最小修订：定义独立server-only锁定快照端口/事务所有者，明确它使用的连接、隔离级别、project→batch固定锁序、Host围栏及R1提交保持期间、SQLSTATE中止/超时处理；以受限经过审查的锁函数/专用角色授锁权，不为普通runtime开放任意project更新或关闭FORCE RLS。最终SQL在同一事务内重读can_write、date_revision/双revision、实际来源连边；不得嵌套现有B06事务，也不能用PG锁宣称已取得正式R1写权。ACL和关联AFTER触发器的等待、死锁/撤权竞争需真实两连接及进程中断试验。所有正式writer覆盖仍必须由E明确清单，Host撤权/提交线性化由D明确；缺能力保持HOLD正确，但不是解除依赖。

## 本次实际证据

在本worktree精确957874d6运行本地官方源码PG17.6、Psycopg3.2.13，DSN `host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres`；使用既有 `test_dsh_workbench_b_scope_postgres.Scope` 临时fixture，`setUp→scope_seed→scope`，查询information_schema列并执行两个反例，随后doCleanups。实际输出：

```text
page_keys: access_scope_revision,batch_id,gap_indicators,next_page_cursor,project_id,records,relation_revision,release_date,source_refs,warnings
record_keys: requirement_id,source_verified_link,source_verified_requirement_version,split_state,sst_id,system_version_id
BRV_source: {"source_link_ref":"source:rv","source_revision":"r1"}
system_version: project_id,version_id,system_id,version_label,source_system,source_namespace,source_object_id,source_revision
verified_requirement_version: project_id,batch_id,requirement_id,version_id,source_link_ref,source_revision
verified_sst_link: project_id,batch_id,requirement_id,version_id,sst_id,source_link_ref,verified_source_revision
runtime_project_lock: InsufficientPrivilege 42501
scope_inside_final_lock_transaction: ValueError IDLE_CONNECTION_REQUIRED_FOR_SCOPED_TRANSACTIONS
```

`business_scope.py`在957874d6与aa533c21的SHA256同为 `05f4d3629c34613888178b0c2e0fdc6473352104006228acd3dc576e2e2a90d1`。此外运行 `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`，3/3 **缺口复现**（0.029秒），不计产品修复通过。没有生产R1、正式Host或现场Windows操作。

下一步：A/E落实上述三处最小规范后给出新的完整合同SHA，B可复核该增量；可优先实现经签署的纯canonical codec/PG快照原语，正式创建仍不得越过D/E/F门禁。当前不无保留签008或正式绑定实现，不把本报告当F验收。
