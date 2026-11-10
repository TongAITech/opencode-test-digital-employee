# 正式 Mission Scope 创建与恢复协议 V2 候选

状态：A补齐设计候选 / B_D_E_F_REVIEW_REQUIRED / IMPLEMENTATION_NOT_AUTHORIZED。承接PR #175源32f3f694及B报告a4670bb4、D报告b6d42a77。这里的表、端口和事件均是拟议增量，不是现有功能；没有修改冻结合同、正式模型或R1。独立评审额度中断后由A整理，不代签任何职责方。

## 1. 完整关联快照与编码（B-MS-01）

候选schema `dsh.scope-snapshot.v1`，顶层键仅允许：schema、project_id、batch_id、release_date、date_revision、relation_revision、access_scope_revision、filters、edges。ID逐字保留，不trim、不Unicode归一化、不以显示名称联结；拒绝空串、非法Unicode和未知键。日期为ISO日历YYYY-MM-DD，三个revision为正整数；浮点、NaN和重复JSON键拒绝。principal不放进可共享Scope摘要，放入创建请求摘要与回执域。

filters固定含requirement_ids、version_ids、sst_ids三个数组；无筛选为[]，ID按UTF-8字节排序，重复输入拒绝。edges只含实际verified BRV/BRVS：每行字段为requirement_id、system_id、version_id、sst_id、requirement_source、version_source、brv_source、sst_source、brvs_source。source对象固定含source_system、source_namespace、source_object_id、source_revision、source_ref；对应现有表字段缺少显式ref时必须采用经B批准的结构化来源引用适配，禁止拼label或临时补猜。UNSPLIT仅在经验证BRV没有SST拆分时表示为sst_id/sst_source/brvs_source全部null；有SST的BRV按实际BRVS一行一边，不加虚拟null边，不把不同需求的SST做笛卡尔积。缺关联来源返回HOLD，不签快照。

相同逻辑边重复拒绝；矛盾来源或同一身份不同来源修订拒绝。排序键为(requirement_id,system_id,version_id,sst_id)，每分量按UTF-8字节序，null排在字符串之前。source对象字段不可省略，nullable字段显式null。先固定schema校验并排序，再按JSON对象键ASCII升序、UTF-8、无BOM/空格/换行、非ASCII不转义、仅JSON必要转义序列化。此schema没有浮点和动态键；实现必须给出跨进程黄金向量，不能依赖语言默认JSON输出。

scope_digest = SHA256(UTF8("dsh.scope-snapshot.v1\n") || canonical_json_bytes)，小写64位hex。语言、标签、page_size、游标、验证时间不进入快照。date和双revision进入摘要，改期/关联/撤权代次改变必须得到不同摘要。创建摘要另包含原主体、动作、Scope摘要、已确定正式身份、创建键、Host权威引用，采用独立域dsh.mission-create.v1，不能复用Scope摘要作为幂等身份。

服务端受控verifier必须消费全部页直到next_cursor=null，固定同一主体/project/batch/filters及日期/双revision；中途变化、重复边、游标重放、缺页或预算耗尽整体丢弃并HOLD，不返回部分成功。正式提交前还需第4节最终围栏；B06分页一致性本身不够。空Scope拒绝创建。

## 2. 显式映射及PG载体（B-MS-02）

正式R1的不可变创建事实是mission_id、release_id、binding_ref与业务(project_id,batch_id)映射的权威；PG只是快照、请求日志及正式回执引用。候选正式创建事实必须原子包含完整绑定和映射，不允许先无绑定创建再补写。一个release_id只能映射一个业务project/batch；一个mission_id/binding_ref只能出现一份创建绑定；同批次允许多Mission，同一已正式映射release可在同批次下按正式策略创建多Mission。V1只分配全新release，不接受浏览器选择任意既有release；后续复用另案评审。

拟议008迁移（不是已存在表）：

| 表 | 约束与所有权 |
|---|---|
| wb.scope_snapshot | PK(project_id,batch_id,snapshot_ref)；FK(project_id,batch_id)→wb.release_batch；UNIQUE(project_id,batch_id,scope_digest)；完整canonical bytes、schema、digest、创建日期及双revision；append-only |
| wb.mission_create_intent | PK(project_id,batch_id,actor_ref,creation_key)；FK(project_id,batch_id,snapshot_ref)→scope_snapshot；UNIQUE(mission_id)、UNIQUE(binding_ref)、UNIQUE(release_id)限V1新运行身份；完整请求摘要、身份、原主体域引用、权威引用均不可变；不是accepted事实 |
| wb.mission_create_receipt | PK与FK(project_id,batch_id,actor_ref,creation_key)→intent；正式receipt_ref/event_ref、R1摘要及正式身份；append-only，仅正式回执验证适配器可INSERT；没有回执不推导成功 |

所有project带复合FK，RLS启用并FORCE；普通owner迁移角色、业务runtime、正式receipt适配角色分离。runtime不持BYPASSRLS/所有权，不可UPDATE/DELETE上述行，原主体请求日志查询须当前can_write且actor匹配；授权只读映射查询另行投影不暴露创建键。owner也受append-only触发器约束，迁移DDL不能被运行进程调用。down须在停写、导出校验及正式回执引用清单留存后进行；有正式绑定/未知提交时拒绝破坏性回滚，不级联删R1或历史Evidence。具体SQL仍须B/E审查及真实PG迁移/回滚测试，不能凭本表记B08完成。

## 3. 原主体幂等及未知结果（B-MS-03、D-MSB-02）

权威域=(formal_authority_ref,actor_ref,project_id,batch_id,creation_key)。在任何正式副作用前持久化intent并确定mission_id/release_id/binding_ref，重试不得重分配。正式端口必须支持submit与lookup两种动作；lookup可仅按原权威域+完整请求digest找到原正式回执，不要求已知command_ref。key丢失、权威换代不能验证旧域、R1截断或身份冲突均HOLD，禁止另建Mission“修复”。

同域同digest返回原回执；异digest冲突且原R1不变。R1前失败可重试同intent；R1已提交但PG回执/HTTP响应失败，查询正式权威取得原结果再补PG引用。PGintent或outbox成功绝不表示正式accepted。查询NOT_FOUND只有在权威证明完整读取、writer围栏及同域唯一性后，才可安全重交原intent；未知/超时不是NOT_FOUND。正规端口返回CREATED、EXISTING、REJECTED、HOLD，HOLD不得在UI标为运行中或成功。

Alice未知提交后Bob即使同项目can_write，也不能改actor/context重放Alice的key。恢复重新核当前Host及项目授权，匹配原主体域；原write-context仅恢复线索不是创建许可。Alice恢复应取得原Mission，撤权则拒绝并不泄漏关联明细。V1不开放跨主体委派恢复；未来委派必须独立动作授权、审计和只读回执查询，不能继承原主体执行权。授权用户可另行读取既有Mission，但读取权不授原主体幂等域。

## 4. 创建线性化、权限及跨库围栏（B-MS-04、D-MSB-01）

创建入口先验证server-derived Host动作mission.create、可信mutation/CSRF/Origin或原生调用证明、B项目can_write，再构造候选；浏览器、任意import verifier、自签字段不构成权威。缺真实Host接口/不可验证动作或会话代次返回未就绪，不能用测试provider上线。绑定创建不派发执行，不替代Captain签名、资源租约、人审或NodeGate。

候选提交顺序：正式单writer跨进程OS围栏→PG事务锁project与release_batch（固定顺序）→重读主体can_write、日期/关联/ACL修订及完整快照→Host权威最终动作/会话代次围栏→正式R1重新读取与同域唯一性/CAS→单个不可分割绑定创建事实durable append→正式回执→PG引用提交。Host围栏必须有正式可证明的提交时效/撤销顺序；仅“刚验证过”不足以保证撤权与append竞争。若行内Host不提供这项语义，设计退回评审，创建保持HOLD，不能以时间戳或本地缓存替代。禁止在释放围栏后使用旧验证结果执行。

PG锁仅证明PG关联/ACL修改不能越过最终检查，不能授R1写权。必须审查ACL/关系触发器涉及的锁顺序、死锁重试和跨库中断；在append前被数据库中止须零R1副作用，append后数据库失败按正式回执恢复，不能回滚已正式创建事实。PG锁持有期间不得等待模型或用户交互。需要确定超时、租约过期的拒绝路径及持久fence代次，当前尚无实现证明。

仓库现有rc72_ledger_lock提供部分OS锁，JsonlEventStore每实例RLock不能证明所有writer已被覆盖。准入清单必须枚举bank_mission、正式factory、ClosedLoopControlPlane的bootstrap/refresh/任务注册/状态写入、恢复、CLI及所有Mission append路径；涉及绑定Mission的writer共同采用正式围栏并保留校验绑定。未覆盖入口对绑定Mission失败关闭，不得丢字段后当legacy继续。此项由E/RC72所有者给出精确调用清单与回归，未完成前不准实现为“已接通”。不能绕过既有lease或把新锁当执行许可。

## 5. 评审与退出证据

B需复核完整schema/来源适配、008复合约束、锁及回滚；D需复核原主体恢复及Host真实能力/围栏；E需确定原子创建事件、正式writer覆盖及lookup/CAS语义；F独立验证最新完整SHA。以上均PENDING，旧W0与32f3f694方向接受不能转签本V2。

未来必须测：摘要黄金向量/乱序同摘要/换语言同摘要/跨需求SST不同摘要/重复与缺页拒绝；真实PG→正式创建→R1→HTTP；两个进程同键及异payload竞争；关联/ACL/改期/Host撤权竞争；每个append前后故障注入与新进程恢复；Alice未知→Bob拒绝→Alice原回执；所有正规Mission重建与至少三次更新保留绑定；旧无绑定拒绝不迁移。characterization的3项仍仅缺口复现，不能计修复PASS。真实DSH/Windows继续FIELD_NEEDS_BANK_TRANSFER，最终发布未批准。
