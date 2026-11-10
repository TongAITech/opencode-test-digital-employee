# B：正式 Mission Scope 绑定增量独立评审

被审合同：`32f3f69484364f42387b24c2fd93bc4c19ab7df4`（PR #175）。调查实现基线：`7586a80c0d8f5cd5205a78ca735b1ca15e12a4b2`。

结论：**B_DESIGN_REVIEWED_WITH_REQUIRED_DETAILS**。接受由正式 RC72 创建/恢复控制面持有 typed 绑定、B持有业务关系、旧数据HOLD、工作台不补写R1的原则。当前合同尚不足以无保留准入“可信创建/跨库恢复”实现；下述P1规范缺口须在实现提交前补齐并由职责方核对。本报告不是D/F签署、产品QA或现场批准。

## 实际核查

已读取ScopeStore/DirectoryStore、RelationStore、003–005来源白名单/复合FK/修订触发器、Mission类型、ClosedLoopControlPlane.bootstrap/_mission/_persist_mission、bank_mission.start_or_resume及JsonlEventStore。B06每页REPEATABLE READ，绑定principal/project/batch/date/filters/relation_revision/access_scope_revision和page_size；它提供分页查询，不是已存在的跨全部页不可变创建快照或PG–R1事务。

本地运行 `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`：3/3缺口复现；使用TemporaryDirectory R1，未修改任何生产R1。正式创建不接受绑定，手工extra在正规refresh后丢失，scoped查询拒绝，均独立复现。结果不记为未来产品通过，也不把既有B/E读取组件接受转移为正式创建接续通过。

## 实现前必须明确的B规范

| ID | 级别 | 缺口与必须补齐的内容 |
|---|---|---|
| B-MS-01 | P1 | 定义版本化完整Scope snapshot及canonical digest编码。必须消费全部页到null，核对同一principal/project/batch/filter及双revision；每条BRV/BRVS保留精确来源ref/revision，UNSPLIT显式null，不能展开笛卡尔积。说明字段集合、UTF-8/JSON编码、tuple排序、去重/重复拒绝、scope_digest算法与版本。语言、page_size、传输游标不得改变同一逻辑集合摘要；不同需求共享版本但SST不同必须产生可区分的关联内容。身份不得隐式Unicode归一化或按label连接。 |
| B-MS-02 | P1 | 显式mapping的权威载体、唯一性与生命周期未定。应写明business(project_id,batch_id)与canonical release_id/mission_id/binding_ref的字段、owner、来源证明和冲突规则；至少release_id不可在两个project/batch下重复授予，mission_id绑定不可变，同批次可有多Mission。若使用PG映射/快照表，须给复合PK/FK、RLS、owner/runtime权限、append-only和迁移回滚要求；若正式R1持有映射，PG只能保存引用，不能靠PG行假定R1已经创建。新运行身份可以由正式控制面分配，但不能据此把任意既有release映射到业务批次。 |
| B-MS-03 | P1 | 明确定义正式创建的稳定幂等域、payload digest、持久Mission/创建身份与权威查询协议。首次尝试前已确定的正式身份/绑定ref不能因重试重分配。需覆盖R1提交前失败、R1已提交但PG/响应未完成、回执丢失/服务重启、同键异payload。原command_ref丢失时必须能按原权威幂等键+digest查得原结果或安全重复同一正式submit；找不到可靠结果保持HOLD，禁止新建第二Mission。不能用工作台request_result或outbox成功代替正式创建回执。 |
| B-MS-04 | P1 | 定义最终Scope/权限/日期修订核查与正式append的并发顺序。B06各页一致及读取后检查并不自然与另一个R1提交构成原子性。说明创建验证有效期/撤权和关系变更时拒绝或HOLD、正式writer串行/CAS机制、冲突时零关联明细或执行副作用。当前JsonlEventStore只有每实例threading.RLock，不能推断跨进程两次bootstrap的唯一性或把PG锁当正式R1锁。此处可以由经审查的正式单writer/admission端口提供保证，不能让工作台自行append。 |

## 保留与边界

绑定历史creation release_date与当前B业务日期分开；稳定batch_id改期不变，原Attempt/Evidence provenance不移动。关系source append-only不能被当作“永远不需重验”：新增边会推进relation_revision，撤权/重授会推进access_scope_revision。旧绑定可保留审计但新执行须按明确规则HOLD/STALE，不静默升级摘要。

旧无绑定Mission不自动写回迁移。缺BUSINESS_TZ、正式来源映射或冲突分母时MIGRATION_HOLD；不能让typed字段本身或verified=true成为创建权威。D仍须证明真实Host创建授权/恢复主体，E必须保证所有正规重建/序列化保留并验证绑定，F须在修复后的完整SHA独立验正式PG→factory→R1→HTTP链路。

建议下一步：E/A补一份可实现的字段/摘要/映射与创建恢复协议增量，B核对以上四项后再签相应实现范围。不得仅以现三条characterization通过启动声称“正式创建已接通”。现场继续FIELD_NEEDS_BANK_TRANSFER，未改08/09/10、正式模型或任何R1事实。
