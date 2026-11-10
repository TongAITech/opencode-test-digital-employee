# E：M1项目元数据与迁移边界独立设计审查

被审B230精确 `a21b82fe805926a22b5d90babec5670dd912c6aa`（base D211 `1e1a75ff6c49cfaf36a6f36f3bdde1e047cf77d2`），并对照A范围决定 `9a41b145` 的 WB-A-PROJECT-METADATA-M1-DECISION-20261111.md。独立worktree e-project-metadata-review从B精确源建立，只新增E本报告；E未参与B/D候选编写。

结论：**E_M1_DESIGN_ACCEPTED_EXACT_A21B82FE_WITH_A9A41B145_SCOPE / NO_NEW_P0_P1_IN_E_SCOPE**。可推进已完整治理命名域内已有根PROJECT rename的隔离实现；不是009 SQL/runner/profile实现签署、PG功能PASS、正式Scope绑定或现场验收。D动作/Host范围、C目录wire、F独立验收不由E代签。

## 1. 项目元数据与正式事实零副作用

接受单一wb.project.name及独立metadata_revision，binding只维护规范name_key。project_id、batch/date/access/relation修订和BRV/BRVS身份不因改名变化，metadata修订不进入现有Scope摘要/正式Mission绑定；不能为刷新看板伪造relation_revision。旧未知legacy仅保留原name可按ACL读，不自动认定PROJECT、归域或清理重名。行政完整成员/排除依据及冲突治理达到NAMING_ACTIVE才有M1写资格；A已明确不得每项目私有域规避唯一性。

rename一个PG事务只修改受限name/key/metaRev并提交history/audit/result/project outbox，不触Mission/Attempt/Evidence/NodeGate，不生成正式执行/发布命令，不建文件目录/Host会话，不引入跨库Mission PREPARE或新HostAdmissionFence。R1零写是实现退出Oracle：真实rename/NO_CHANGE/冲突/中断均比对原R1字节与正式事实；不能用UI截图或outbox行当执行事实。若实现新增任何这些外部副作用，应重新升合同，不继承本次单PG事务接受。

## 2. PROJECT outbox是业务事件，不是BATCH/正式事实

接受独立project_metadata_outbox，唯一(project_id,metadata_revision,event_kind)，原actor/request/结果引用可追溯；不填假batch_id/asset_id复用现有asset_outbox。009实现须把PROJECT结果/历史引用复合一致性、append-only、最小写角色及事务故障原子性落实为受审SQL，而不是只靠应用顺序。

project.metadata.changed仅表示PG元数据变化；NO_CHANGE保存原结果但不加metaRev、不造rename history/changed事件。NO_CHANGE审计和变化历史分开。outbox入库不是SSE/实时可靠投递，M1可用明确手动刷新；将来PROJECT/BATCH事件schema、水位→补放→订阅、当前ACL与主体更换检查另单冻结。已有asset/BATCH端点不因本设计接受PROJECT事件；更不允许由业务事件推进R1门禁。

## 3. 009与保留008：显式依赖可无环，不伪装已可运行

真实business_migrations.migrate只接受1..7并range连续扫描；本次只读/无DB探针migrate(None,target=9)实际返回UNKNOWN_MIGRATION_TARGET，当前只有001–007 up SQL。B/A准确识别这是尚未实现的runner前置，不是数据库/行内环境阻断。

接受009_project_metadata候选编号，显式依赖集合001–007，不依赖008，禁止空008、跳checksum或把009写成008成功。008继续留E正式Scope绑定，M1表只依赖既有project/request/audit等及本迁移新表，不引用尚不存在的正式Mission绑定表，因此没有必然循环。未来008原则上也可基于001–007独立建设；若需依赖009必须另审依赖声明及Scope profile，不能静默增边。禁止未来把009补成依赖008又让008依赖009。

首个runner实现需受审manifest固定version/id、SQL内容hash、依赖与明确applied集合，已有001–007 hash不变；拓扑排序、缺依赖/重复版本/循环/歧义文件/已应用checksum不符都在执行前拒绝。不能以max(version)=9推断008已应用；009后的down应按依赖叶子及实际applied集，不能继续仅version>target扫到未知表而KeyError或越过未来008。当前downgrade有固定版本字典，因此up/down runner必须同单审实现。空历史up/down/up、非空history/result/outbox拒绝破坏性down、授权撤销与备份/forward修复证据均是实施退出要求，不是本报告宣称已有能力。

本次在内存以008/009各依赖001–007的示意图做拓扑检查：无环、009不含008；没有执行SQL迁移。示意图不是未来008正式依赖签署。

## 4. 固定profile必须新批准，不自动学习

另对照当前W0 `16ae40e8a86b5193da0a1f97b3b5f7a5f76204cc` 的实际ScopeSourcePolicyProfile：profile_id固定dsh.scope-source.project-only.pg17.001-007.v2、固定JSON内容hash；project列/约束/触发器/权限及scope-touching RI依赖被精确比较，漂移为UNQUALIFIED、admission_authorized=False。该模块不在B旧基线中，不能把当前W0代码检查转为B源的功能PASS。

009增加project.metadata_revision、rename权限/维护触发器/新FK将使旧profile不匹配，接受这一显式未资格状态；不能改“允许任意新列/UPDATE/trigger”、从部署catalog自动重写模板或按009已应用推断安全。新固定profile须从真实PG捕获可复现catalog并逐项审新写函数/角色/RLS/触发器/RI作用，B/E/F接受后再随版本发布；不冒用旧v2签署。元数据业务成功不授正式Scope admission，未批准新profile必须继续UNQUALIFIED。旧允许ACL触发器仅更新access_scope_revision的路径仍需真实测试，不可被新name约束误拦。

## 5. 原主体未知恢复与旧回执

B K=(project_id,principal,request_id)及动作/完整payload摘要与D211原主体write-context规则一致。current Host mutation/CSRF/Origin、原context及当前can_write先重核；Bob不能替换Alice context重放其待恢复意图，服务器key轮换不能验证旧context则HOLD。write-context仅原主体域HMAC，不是项目/命名治理或创建权限；不把现有mutation扩为create/members动作（由D另审）。

已提交同K同digest返回完整原历史receipt，先授权但不再用当前meta/ACL CAS或后来改名重算结果；receipt明确applied_metadata_revision，UI随后GET当前值，不能回滚新name。不同action/payload同K409；跨asset与metadata共享request_log时动作入摘要，不能用新的结果表绕开原claim。旧receipt与当前治理状态处理不允许产生新写；域停用等导致HOLD时仍不得换key或伪装无结果。未提交原意图才核所见CAS，ACL epoch改变拒绝旧许可新写；UNKNOWN不能当NOT_FOUND，权威PG确认无原结果与明确新意图规则保留。

单事务history/key维护/outbox任一失败必须原子回滚；响应丢失/重启只按原K/digest找原结果。NO_CHANGE同样持久化原结果而非临时推算。源码现有AssetStore已用claim后读asset_request_result先于当前batch CAS，require_write_context由server principal与key核验；这是参考模式，不得复用asset/batch结构承载rename。具体新HTTP/PG恢复仍要真实故障注入，不能转移资产测试PASS。

## 6. Directory ABA与Scope兼容退出

现business_directory.py项目digest取project_id/name/access_scope_revision，A→B→A可能恢复原digest；B/A要求metadata_revision及新投影schema进入全部当前授权项目的稳定排序快照可消除该ABA。实现须使旧项目cursor409（含schema旧token），rename仅影响项目目录；batch目录date/relation/access及十区合法Scope不因纯rename被清空/伪造修订。revision以规范十进制字符串传输、正bigint边界和溢出拒绝保持；Directory摘要内部采用确定且版本化编码，由C/B实现审定，不直接沿旧v1混改token语义。

同域不可见冲突仍由唯一索引Oracle判定，只允许A已选择的一位NAME_UNAVAILABLE信息，不回传另一项目或命名成员。rename历史/恢复优先不等于跨主体读取旧结果。上述Directory、NO_CHANGE、双并发CAS/唯一性、治理/ACL停用竞态、所有事务故障和原batch/BRV/Scope/R1不变均须真实PG+HTTP证据。

本轮仅设计审查、源码读取与内存/无DB入口检查，未运行新metadata产品测试、未改候选/实现/冻结原文或08–10。明确实施依赖不构成新P1设计拒绝：B230/A9a已经把runner/SQL/profile列为必须另审的下一施工内容。真实Host/Windows仍FIELD_NEEDS_BANK_TRANSFER，M2/M3/M4与最终投产纵向链均未核销。
