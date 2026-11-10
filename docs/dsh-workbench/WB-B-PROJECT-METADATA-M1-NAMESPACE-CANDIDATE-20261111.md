# B：M1 既有项目名称与命名域最小实施候选

状态：**A_D_E_F_DECISION_REQUIRED / DESIGN_ONLY / NOT_IMPLEMENTED**。独立审查D PR211精确`1e1a75ff6c49cfaf36a6f36f3bdde1e047cf77d2`。本文件不修改冻结合同、数据库、API、R1或08/09/10，不代表其他组签署。

## 1. 事实与结论

已完整读取D候选及其真实PG17.6 catalog JSON/调查报告；本轮没有重新运行数据库测试，不把D已有fixture证据转写为本次产品验收。来源：`evidence/WB-D-PROJECT-BOARD-CATALOG-20261111.json`，调查源`199a316334abb41c77890ed5608b989e2a7e6126`。实际project只有project_id/name/access_scope_revision；name无唯一约束；runtime无项目写权限；project_acl不是人员目录。当前不存在本文件拟议字段、端点或全局创建动作。

B接受A的最小方向：project_id稳定，name是显示业务名，禁止用于join；A01重复名称拒绝仍由**受控命名域中的规范名称唯一性**满足。不可采用可见列表、登录用户/owner或客户端namespace作为去重分母。安装/组织选哪一个不是数据库可以推断的事实；服务器行政来源批准一个不透明namespace_ref即可，不必在M1引入完整租户/组织系统。

建议M1只开放**已治理的根PROJECT改名**。iteration域规则本轮固定，实际iteration绑定/重挂/创建留M2；不把成员、新Host动作或全看板塞入M1。若A要求M1也编辑既有iteration，必须先提供真实父项/类型绑定清单，不能把未知legacy默认为根项目。

## 2. 命名域、规范字节与历史治理

命名域候选：根PROJECT为(namespace_ref, ROOT)，ITERATION为(namespace_ref, parent_root_project_id)。父项必须同namespace且kind=PROJECT；仅一层iteration，禁止自己为父，因PROJECT不能有父自然无环。根和迭代域独立；同父迭代规范名称相同拒绝，不同父可同名；根与子项ACL独立且不继承。name改变不改变project_id、父项或任何BRV/BRVS身份。

名称策略`project-name/utf8-exact-v1`：先拒绝非法UTF8/孤立代理、U+0000–001F及U+007F，再仅移除两端U+0020；结果须1–128个Unicode标量且UTF8不超过512字节。规范name就是该结果，name_key就是其UTF8原字节。禁止隐式NFC/NFKC/casefold和数据库语言排序比较；Alpha与alpha、预组é与组合e+重音均不同；` A `与`A`相同。其他Unicode空白不隐式trim，因此其精确保留是明确产品选择，C须在输入提示中说明。若A希望禁止更多空白，另冻结固定码点表后再实现，不使用随运行库版本变化的trim。规范函数必须服务端执行且DB验证name/key一致，客户端验证只改善提示。

**历史分母是启动条件，不是静默迁移。** 行政受控绑定清单须含source_ref/revision/hash、namespace、完整成员project_id/kind/parent及其余legacy明确排除依据。namespace状态仅在批准分母完整、全部已绑定名称通过策略、冲突解决后成为NAMING_ACTIVE。未知行可能属于该域而没有排除依据时，该域不能启用命名写入；不能将未知行留NULL、排除唯一索引后宣称全域无重复。新安装明确空域可以由批准的安装来源直接建立，不需要真实DSH现场才能设计/测试。

旧同域重名/非法名：先输出行政冲突清单；业务方批准保留者及其他新名称，治理动作有独立行政审计，再激活域。禁止按可见列表/最小ID/当前用户自动改名，禁止重生成ID或把旧重复改成跨域来消除错误。治理不是新增HTTP超级用户接口。M1未知项目仍可按既有ACL读取原name，metadata写返回METADATA_NOT_GOVERNED；不能让普通writer自行填写namespace/type完成治理。

## 3. 精确数据与约束候选

建议迁移预留名 **009_project_metadata**，008继续留正式Scope绑定；这是A排程候选而非已占号。009独立于尚未实现008，迁移runner须能显式选择已审核清单，不因编号跳跃伪称008已执行。实际`business_migrations.py:migrate`目前target仅1–7且按range(1,target+1)连续扫描，不能直接执行009；因此首个实施单必须增补经审核的显式迁移依赖manifest/runner路径（009依赖001–007、不依赖008），或由A重新排号并取得E对008预留调整的明确签署。B建议前者，不先执行不存在的008、不放空008占位；这项行外代码依赖须单列，不隐瞒为现有可用能力。

| 逻辑载体 | 必须字段/约束 |
|---|---|
| wb.project | 保留唯一当前name；新增metadata_revision bigint>0，机械初值1仅表示版本起点；不改access_scope_revision。未知legacy仍保留原name而非强制规范化。 |
| project_namespace | namespace_ref PK、state(GOVERNANCE_HOLD/NAMING_ACTIVE)、policy_version、governance_ref/hash、namespace_revision>0；只有行政来源写，不对runtime开放全局列表。 |
| project_name_binding | project_id PK/FK project、namespace_ref FK、kind、parent_root_project_id、name_key bytea、binding_revision、governance_ref。M1只插治理批准PROJECT绑定，不允许runtime插删/重挂。ROOT唯一(namespace_ref,name_key)；ITERATION唯一(namespace_ref,parent_root_project_id,name_key)，均以bytea比较。 |
| 绑定父项 | parent复合FK指向同namespace的已绑定PROJECT；可用父kind固定PROJECT及复合唯一(namespace_ref,project_id,kind)落实，不能只FK裸project_id。PROJECT父NULL；ITERATION父非NULL且非自身。 |
| project_metadata_history | PK(project_id,new_metadata_revision)，前后name、key、old/new版本、可信actor/request/action/reason/time，FK project；append-only，治理与普通rename动作明确区分。 |
| project_metadata_result | K=(project_id,principal,request_id)，与已有request_log同域/同事务；action、payload_digest、完整原始receipt、history引用；不造asset_id/batch_id。FK/唯一保证同K只有同一历史结果。 |
| project_metadata_outbox | 唯一(project_id,metadata_revision,event_kind)，PROJECT事件域，原actor/request和结果引用；不填假batch来借用BATCH格式。 |

绑定表name_key不是第二个可独立编辑的名称事实：project.name唯一当前文本；受控DB一致性约束/事务内受审维护机制确保绑定key等于规范name字节，任何一个单独更新必须被拒绝。具体触发器/受控函数及最小角色DML在009 SQL审查逐一固定；本文件不声称已存在。保留单一文本比额外metadata.display_name覆盖project.name更小，避免旧目录和新页面读两个不同名称。

runtime不获project INSERT/DELETE、身份/ACL UPDATE或namespace/绑定结构写权限；仅受控rename端口可更新name、metadata_revision及对应key。普通表写若可绕history/key/CAS则不接受。授权机制可选择最小列权限+RLS+强制维护约束，或严格固定search_path/非owner非BYPASS的受控函数，但不得在HTTP使用migration owner。现有ACL触发器只推进access_scope_revision时不应被metadata维护约束误拦。项目表列/权限/触发器变化会使固定Scope profile v2不匹配，须独立评审新profile，不自动学习或绕过现有资格检查。

回滚：空新增业务历史时可受控撤销009并保留旧name；已发生rename时禁止drop历史/receipt/outbox的破坏性down。先停写、备份对账、撤新增runtime写权，再做保留数据的forward修复；不得用旧包启动就删除新审计。迁移含schema checksum、空库up/down/up及历史非空拒绝down测试。

## 4. M1 API与事务候选

采用D拟议GET/PATCH `/api/workbench/v1/projects/{project_id}/metadata`，尚不存在。GET按当前项目读ACL返回project_id/name、metadata_revision/access_scope_revision十进制字符串及命名治理状态；不返回全namespace成员。PATCH允许且只允许request_id、expected_metadata_revision、expected_access_scope_revision、changes{name}、reason。revision字符串必须规范正十进制且≤9223372036854775807；递增溢出拒绝，不能转JS浮点。request_id为1–128 ASCII `[A-Za-z0-9._:-]`，reason规范UTF8最多2048字节；body上限16KiB、拒重复JSON键/未知键/错误类型。namespace/type/parent/owner/role均不可提交。

写需可信server principal、当前Host mutation与CSRF/Origin证明、原主体write-context、当前project can_write；另外需已有受控绑定所在域NAMING_ACTIVE、政策允许existing-project-rename。后者是服务端域政策而不是新全局create能力；writer不能切换域。namespace管理/绑定治理另需行政权限；当前mutation+can_write不授project.create、iteration.create或members.manage，这些留M2独立动作。

建议锁顺序：IDLE入口独占事务→SET LOCAL可信主体→namespace行共享锁→project行更新锁→绑定行锁→幂等claim/结果→当前ACL/治理版本及CAS重验→改name/key/metaRev→history/audit/result/outbox→commit。行政绑定重配也必须namespace先锁；涉及多个域按namespace_ref字节顺序，随后project_id字节顺序。ACL变更锁project须与既有触发器实测无反向依赖；SQL审查必须给真实两连接死锁/撤权测试，不能以此文字代替证明。namespace锁和project锁取得后重读绑定；发现迁域则回滚重试，不拿旧域锁继续写。

已提交原K同digest优先返回完整原回执（仍先重新授权和主体context核验），不被当前metadata/ACL CAS或后来改名覆盖；未提交新请求才核expected revisions。K同异action/digest为409；摘要含action、原project/revisions、规范name与reason，不含可变Cookie/CSRF。原回执明确applied_metadata_revision，并注明历史结果；UI重读当前值。新意图若规范name与当前相同，返回NO_CHANGE的持久原回执，不增加metaRev/history/changed事件，不能假装一次改名。审计该操作与metadata变化历史分开。

409至少区分REVISION_CONFLICT、IDEMPOTENCY_CONFLICT、NAME_UNAVAILABLE、METADATA_NOT_GOVERNED；撤权/不可读项目不泄漏是否存在。唯一索引是包括不可见项目的业务Oracle，不做全局名称可用性端点。冲突响应不含另一project/namespace成员/owner/父项；允许本域rename动作必然透露有限一位“该名称不可用”，不能宣称零存在性泄漏。用户不能自报namespace探测别域；严格零此类信息披露与可交互唯一命名本身不相容，需要A另作产品决定。

单PG事务提交未知只按原主体K/digest查权威原回执；不可读/权限撤销/原context不能验证时HOLD，不换key或主体。审计、key维护、outbox任一失败全部回滚；无R1/文件/Host会话副作用，故不引入正式Mission PREPARE。事务重试、超时和池复用必须RESET/rollback后不串主体。

## 5. 目录、卡片与阶段

项目Directory digest新增metadata_revision（及投影schema版本），对全部当前授权项目稳定排序编码；只含name无法使A→B→A之前cursor永久失效。rename使旧项目cursor409；仅rename不改batch目录、date/relation/access revisions，也不清空十区合法Scope。wire增量与旧cursor失败关闭须C/D review；不假装当前目录已包含metaRev。

B接受卡片身份(project_id,batch_id)，前五业务计划阶段和独立plan_revision；未建batch不伪装阶段。RELEASED不属于人工可写plan值；当前E02 HOLD/human UNKNOWN全部拒绝，某Mission/NodeGate单个PASS不能替代完整批次资格。metadata不重写R1。计划、事件补放、正式全量release资格均独立工单，不阻断已治理根项目M1。

## 6. 可开工与真实依赖

**本候选签署后可独立施工**：009 schema/列权限/受控rename、确定性codec、全历史回执/CAS、Directory ABA失效、真实PG正负/并发/故障测试，服务器fixture主体验证及双语UI。无需行内DSH才能实现并验证这些组件；真实Host/Windows仍分别待现场证据，不以fixture核销。

**M1上线真正缺项**：A批准上述root-first/字节政策/009排程；行政来源提供至少一个完整根域绑定与冲突治理清单；D签当前Host mutation适用已有项目rename；B/E/F签精确SQL/权限/profile与接口增量，C签revision/目录兼容。未治理legacy只读不影响合格域施工。M2创建/成员新权限、iteration真实关系、现场Host、正式发布/SSE不是M1数据库编码的前置。

更小可正确范围就是一个经完整批准namespace内的既有根项目rename；不能缩成每项目私有namespace、允许任意同名显示名或仅visible-list检查，这会消失原duplicate-name负例。若行政批准来源暂未到位，仍可完成codec/009候选及隔离PG测试，但运行拒绝未治理域，不宣称整个P03-01完成。

最低验收Oracle：同域两个不可互见项目同规范name仍冲突且不泄漏详情；跨域/不同parent允许同名；双并发只一成功；未知legacy潜在成员阻止激活；非法字符/长度/大小写/组合字符边界；ACL撤销与域停用竞态；rename ABA cursor拒绝；同K旧回执不覆盖后值/跨动作冲突/主体切换；history/key/outbox失败全回滚；role/直接DML绕过拒绝；原batch/BRV/R1字节事实不变。本文没有运行或宣称这些新功能测试通过。
