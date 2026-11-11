# D：紧凑 Mission Scope 模型、reader／writer 与恢复闭包调查

状态：**SOURCE_CLOSURE_AUDIT / NEXT_INCREMENT_REVIEW_INPUT / NOT_IMPLEMENTATION_OR_CLOSED_WRITER_ACCEPTANCE**。

本调查固定源码为 `1e3776bcc1a9ad11166cc2f504da0797cf306d0e`（当前局部负向guard修复），参考已签V3 `04ca971676509da9379ed53a29b495d2a32c325c`、紧凑合同 `3266cb2d814c8f2233733ba4b53642940a7892a0`、纯compact codec源 `968430ed354bed17a9a726ea73617ac194082a7e`。调查期间A工作台HEAD继续前进，不把本源行号/观察转移到新联合HEAD。独立worktree `d-mission-scope-closure`；不改模型、reader、writer、SQL、R1源事实或08–10。

## 1. 可重查源码索引与限制

[静态索引JSON](evidence/WB-D-MISSION-SCOPE-CLOSURE-INDEX-20261111.json)从本源git tracked Python读取，不扫描tests/workspace-template/sources。463个文件中记录8处字面量Mission构造/重建、36处直接或_one/_safe_query的rc7_mission访问、26个关键文件的408个定义位置。索引给path、caller、line与decorator，便于E逐项核对；它不是动态调用图、不是每个定义都写Mission，也不证明别名/插件/任意raw调用已封闭。

以下表覆盖本仓库实际查到的官方创建、重建、持久层、公开投影与恢复路线；底层动态event_type、加载的Host/provider和外部代码必须由正式writer策略封闭，不能用“grep只看到一个事件字符串”代替。GitNexus未在本任务暴露，按rg/AST/实际调用和源码逐层核查，不伪造图分析结果。

## 2. 模型与事实持久化的真实链

| 源路径／行（均基于1e3776bc） | 真实职责／写端 | 尚缺的紧凑绑定闭包 |
|---|---|---|
| rc7_runtime/models.py:100 Mission、:115 __post_init__、:288 to_payload | Mission只含旧运行字段；to_payload为asdict再转换顶层Enum | 无scope_binding/project/batch字段；不会从纯codec自动保留15键。既有_required(:85)会strip外层ID，和紧凑合同原字节身份不能静默混用。 |
| truth_overlay.py:26/:49映射、:60 _base、:85 validate_rc7_mission | RC7_MISSION_UPSERTED→rc7_mission；_base deepcopy保留extra，只验证旧域 | 不核15键、镜像、PREPARE/正式creation事实或与旧绑定不变。_base经rc6 contracts._require_str(:26)也strip mission/release ID。 |
| truth_overlay.py:243 _r1_payload、:373 append_entity | 先既有durable acceptance→_r1_payload（to_payload、显式覆盖release_id、设artifact_version）→TruthRuntime.append_atomic | 覆盖release_id目前未与binding.mapping作不变域检查；_MODEL_EVENT按type精确映射，新增类型/内部值不可随意塞入既有payload。既有PASS/CONVERGED审查不可因新绑定省略。 |
| rc6_runtime/truth.py:88 _canonical_payload、:122 JsonlEventStore.append | registry validator canonical化；store用每实例RLock、_next_seq缓存、写整行/flush/fsync | 不是V3单writer owner能力或全局K去重；不能据此授bound事实写。raw store仍可被直接调用。 |
| truth.py:182 apply_atomic/:194 _apply_validated，:309 TruthRuntime构造、:315 rebuild_projection、:326 append_atomic | append→projection/RAW；cold逐条expand_for_replay重建，投影深复制 | 没有旧/新compact绑定历史不变比较、正式creation来源验证或所有writer准入。改全局replay validator会影响整本旧日志，须独立兼容设计。 |
| rc7_runtime/rc72_truth.py:322 install_rc72_truth_overlay、:332 append_rc72_entity | 另注册RC72批次/节点/ETU等事件，通往同一TruthRuntime | RC72 MissionNodeRecord及scope_ref不是RC7 Mission.scope_binding；release-batch://运行身份不能拿PG batch替换。 |
| rc7_runtime/rc72_ledger_lock.py:21 ledger_lock/:53 resource_guard | 参与路径有OS文件锁、重建projection/刷新seq | **确有跨进程锁**，但只有调用它的路径受保护；不等于所有legacy/raw append都采用V3封闭writer。 |

### 当前究竟丢／不保留什么

scope_binding作为整体未被正式Mission声明；其schema_version、嵌套mission_id、project_id、batch_id、binding_ref、snapshot_ref、scope_digest、release_date、date/relation/access三revision、creation_key_scope(K4)、request_digest、mapping(7)、creation_operation_ref这15键都不属于现有typed model。旧外层mission_id/release_id是原有字段，不等于嵌套绑定已经保留；两个flat镜像也不在typed model。动态setattr后直接asdict会省掉动态Scope属性。

**不能再沿用旧说法“当前Control.refresh仍成功丢Scope”**：1e3776bc的受保Control在进入旧字段构造/写入前已经HOLD。字段丢失风险位于未整合的模型/serializer与绕开该局部路径的写端；当前受保路径的正确行为是拒绝，不是生产绑定已成功。纯codec ScopeIdentity是含canonical binding_bytes的NamedTuple，不能直接当JSON-ready正式Mission字段或授权凭据塞入asdict；需受审运行域表示与显式wire转换。

## 3. 官方创建与Control更新路线

| 创建／调用路线 | 行号与事实写路径 | 需要逐项签审的接续 |
|---|---|---|
| bank_mission.start_or_resume | bank_mission.py:132；:149旧Mission构造→Control.bootstrap→MissionTaskGraphCompiler.install(:318)→register_task，随后graph/工具/执行恢复证据；resume检查release/goal/graph后Control+refresh | 仍无业务绑定入参。现:142局部guard挡既有Scope；不要加CLI自报verified或改ID重建。新正式入口必须先PREPARE/正式事件，旧无Scope路径保持。 |
| Control bootstrap／重建 | closed_loop_control.py:116 bootstrap是真正append Mission；:580 _mission是第三处字面量Mission调用（重建），:599 _persist_mission才写旧模型 | 当前bootstrap先vars reserved/旧row检查，原Scope一律HOLD；新模型及可接受分支需独立设计，不得把codec成功作为豁免。 |
| N1第二个实际构造入口 | rc72_mission_node_dispatch.py:189 _preflight／:277 dispatch／:369 Mission构造 | 从canonical RC72 batch、N1及精确Field-start取身份；新增guard在:292前后核当前/WorkItem目标，existing receipt也不放Scope。不能只改bank入口遗漏这里。 |
| 五个qualification旧构造 | rc7_release/dsh_bridge_qualification.py:222；code_qualification.py:338；script_qualification.py:403；test_design_qualification.py:410；execution_qualification_strict.py:392 | 都是实际旧Mission→Control bootstrap路径，不能给它们补PG来源当正式绑定；纳入legacy无Scope构造/wire兼容分母。 |
| Control所有mutation入口 | closed_loop_control.py:131 register_task，:143 refresh_ready，:149 lease_next，:173 start，:179 output，:185 evaluation，:292 defect resolution，:348 convergence | 通过protected目标收集/存在性guard，再scheduler/append_entity/planner；全source索引含decorator。新bound普通运行若仍调用这些方法，会HOLD，必须先给正式受控准入分支和writer闭包，不能只加字段。 |
| Control私有恢复/持久化 | :499 _resolve_source_gaps；:517 _reactivate_source_tasks；:551 _sync_mission；:580 _mission；:599 _persist_mission；:637 _persist_gap | 已局部guard实际目标，防早写/错目标丢字段；未来保留绑定必须在最新目标旧row/版本上比较，不可拿self row替目标，也不能只在最终persist补比较。 |
| graph、运行driver调用 | mission_graph.py:318 install；mission_autonomous_driver.py:102 drive/:119 step及:280 Mission读；bank_mission_autopilot.py:218构造/:347 drive | graph逐项register；driver使用Control、producer/evaluator、supervisor。Control持有对象的已知闭包检查不是整个driver及外部worker/factory都封闭。 |

## 4. 原生factory、CLI、Session及上游先发生的事实

| 官方路线 | 实际入口／端口 | 不能漏掉的副作用边界 |
|---|---|---|
| 原生factory | rc72_mission_factory.py:117 create_mission_driver | compose worker/captain/execution能力并返回ReleaseBatchDriver，不构造RC7 Mission、不持业务project/batch；零R1 compose契约不等于创建事实。外部Host bindings代码本身不能因配置成功自动授Scope创建权。 |
| RC72 CLI／release driver | rc7_release/rc72_mission_cli.py:99 main，:249 factory；rc7_runtime/rc72_release_driver.py:547 run/:574 Field launcher | 现Q7/source/package/Host检查在前，CLI还可先绑定economy/budget；随后Field-start/N1等官方链。未来Scope admission应在本次首预算/Worker/资源/Field事实前设正确前置，不能等Control创建处才整体宣称零副作用。 |
| canonical Field-start | rc72_field_mission_start.py:209 start | 原Q7/mirror/源身份校验后，经RC72 state machine bootstrap节点、append field-start receipt；不创建typed RC7 binding。N1局部HOLD不回滚这一步此前已发生的合法事实。 |
| N1 assignment及后续节点 | rc72_mission_node_assignment.py:219 _preflight/:274 assign／:381 raw append；N2/N3/N4/N5源码点列下节 | 可基于已有dispatch/Task直接查Mission release并分配Worker；不因Control局部guard已覆盖就当这些原生路径都做了compact/creation来源验证。 |
| 旧bank启动／自动驾驶CLI | bank_mission_start.py:88 main/:92 start_or_resume后才discover/autopilot；bank_mission_autopilot.py:392 main/:394 start，:218构造Control后建authority/launcher；bank_mission.py:244 main | 现start/cold Control会HOLD Scope；外层包装在调用前已做的I/O/后续自定义Host入口需分别列账。不得以旧CLI调用正常当新绑定正式创建。 |
| Session持久handoff | session_continuity.py:93 prepare→truth.append_atomic SESSION_EVENT；:136 activate→append_entity Task换lease owner+SESSION_EVENT；:199 resume_envelope只读 | 不构造/更新Mission，却能绕过Control业务方法直接写Task/handoff；只核task/lease/generation，不核compact创建来源或原actor/context。新绑定不能靠找回Session历史认权。 |
| 官方活跃恢复上游 | active_task_supervisor.py:41 resume_active（先_assign再prepare/activate）；:121 handle；:135 lease reset；:158 human side-effect boundary | reset先写Evidence/Task，之后才Control._sync；human boundary也先写Evidence/Gap；它们属于当前guard明确未覆盖的官方上游/其它service，不应藏成“只有恶意raw外部”。 |
| Captain/执行/资源恢复 | rc72_captain_dispatch_fencing.py:114 acquire_initial/:142 assert_owner/:220 prepare_handoff/:247 takeover；N7/N8/N9/N10各正式pipeline/lease/approval服务 | 它们的签名/租约/人审规则继续独立，不被compact binding替代。未来统一writer须覆盖它们到同R1的事实写调用及恢复，不把Scope parser当execution authority。 |

**上游残余实际观察，不重开本地guard既定范围：** 临时R1中先合法创建旧Mission/Task并lease，再注入未准入project_id。长期Control调用官方supervisor.handle(LEASED)得到MISSION_SCOPE_NOT_ADMITTED，但该错误发生于后续Control检查；此前已写恢复Evidence并把Task改READY，bytes已变，Scope仍保留。直接官方SessionContinuityManager.prepare同样可写PREPARED handoff。两例在本次源实测；supervisor构造只用SimpleNamespace(control=c)夹具，LEASED reset分支未调用外部worker。没有真实DSH执行或业务通过；确认P212承认的other-services/upstream残余真实存在。未来“bound可运行”准入必须先封这些首副作用，不能只审批Control。

## 5. reader与派生结果闭包

| reader／适配层 | 实际边界 | 下次正式增量默认 |
|---|---|---|
| rc7_admin/projection.py:159 mission_overview_scoped | 先Mission flat project/batch再tasks/executions/evidence；不验证15键、原creation事实或PG历史snapshot；返回的scoped_mission只有三身份字段 | 受控PG授权后先严格typed/mirror+正式creation定位+历史snapshot核验，再明细。缺正式lookup/未知/重复/冲突HOLD，不因现flat接受宣布生产已接通。 |
| tools/dsh_workbench/e01_service.py:38 quality | B06全页授权→复制原R1 bytes到temp→TruthRuntime replay→scoped reader→复核PG修订；HOLD；hash仅完整性 | 新绑定source/operation/K/digest验证必须在明细前；temp replay仍会重建整份日志，不宣称物理上只读该Mission字节。raw JSON新codec规则不自动改旧replay。 |
| e02_service.py:16 graph及e02_lineage.py:35–37 | 再核flat身份、取节点/Task/ETU/Attempt，lineage检查；当前把业务PG batch直接拿去等于正式ETU/Obligation.release_batch_id | runtime release_batch_id是另一正式身份，compact mapping只有runtime_release_id，不能猜与PG batch相等。E须给受控正式runtime batch定位/单值关系合同，必要信息来自正式creation事实而不是偷偷扩compact15；现在不满足就继续拒绝/HOLD。 |
| AdminProjection.mission_overview(:146)、list_resource(:114)、get_resource(:136)，derived.py:92 mission_detail | 旧unscoped管理视图及通用资源映射 | 与Workbench隔离。product_server.py:51 handler在workbench模式阻断私有legacy API；不能以legacy fallback补新reader缺口。 |
| final_report.py:93；reporting.py:72；mission_evidence_builder.py:81；mission_conformance.py:75；mission_evaluation_runtime.py:100 | 依据Mission/tasks/evidence等内部事实组成报告、充分性或评估 | 不是Host/PG授权适配器；绑定正向运行时应在正式入口核范围/创建来源。报告或模型结论不生成绑定事实/投产PASS。 |
| attempt_cat.py:139、case_runtime.py:78、script_contract.py:97、execution_chain_evidence.py:99、node_tool_conformance.py:231、bank_field_services.py:89 | 任务/执行/Case/工具证据资格只读Mission或用其release身份，再可能由各service写Case/Attempt/Evidence | 不等于已读compact。保留现有严格资格，并将bound调用的正式Scope上下文/写端能力另行串联；查不到不自动legacy。 |
| RC72直接Mission上下文读点 | N1 assignment:269；N2 assignment:253/dispatch:321；N3 code-dispatch:216/source-target-dispatch:314/source-target-revision:287/completion:154；N4 assignment:250/completion:226；N5 completion:160；economy ingress:220 | 全路径/函数名见JSON。多数只核mission/release；日后不同节点可以有不同Scope快照，但不能用节点scope_ref伪造根Mission创建绑定。 |
| rc7_release内部读点 | bank_field_launcher.py:91；contracted_runner.py:53；one_sst_field_qualification.py:111；real_mission_qualification.py:432 | 旧字段/合同资格查询，不是自动业务映射或全局创建权。contracted runner还能直接写实际执行/文件证据，须在正式执行入口前约束，不能只改最终reader。 |

普通授权用户可读取已有Mission与“原创建者恢复同K”是不同能力。creation_key_scope.actor_ref/authority及永久op只是不可变数据，不授权当前principal；original_context_ref仍在V3 intent/当前Host恢复域，不补进15字段。历史date/三revision代表创建快照，不替代当前ACL；改期不移动原Attempt/Evidence，也不能悄改历史binding。对历史事实可读/STALE、新运行需重基线的具体策略由E签，缺策略不新派发。

## 6. 当前没有的正式命令与底层raw边界

rc7_admin/server.py:60 dispatch_post只支持测试用例及修订/隔离，不支持Mission暂停/恢复/重试创建。tools中的w0_contract_gate/e_contract_oracle是设计期校验/内存fixture，不是正式命令处理器。E03 `/missions/{id}/commands`、正式create/lookup及不可分割创建事件/索引尚未实现；本调查不为它们杜撰方法名或event常量。

append_entity、append_rc72_entity、TruthRuntime.append_atomic、JsonlEventStore.append是实际通用端口；任意受信Python代码还可加载动态event_type，OS层亦可改文件。正式调用者应通过受控owner策略/capability端口；目前这些raw入口尚不因此被封闭。正式writer设计必须明确进程/ledger模式、OS写入权限和插件信任边界，不能承诺对任意OS管理员或同权限外部文件写者物理不可写。目录/模型/会话服务可见并不自带该能力。

V3的单writer、最新投影重读/CAS、PREPARE原K/身份/永久op、原authority lookup、Host撤权/append全序仍是待实施要求。不能仅给raw append加一个可自报verified布尔值；也不能假设普通RLock或已存在Captain锁覆盖整个ledger。未完成闭包时bound生产写默认HOLD，legacy无Scope资格不自动迁移为bound。

## 7. 下一最小增量建议，逐单精确签审

| 拟议增量 | 有界目标／仍不开放什么 |
|---|---|
| 先提交“runtime typed表示与absence兼容”设计 | 明确紧凑15如何进入正式模型、严格row→typed与wire；共享纯codec应置于已审运行包闭包或受控共享层，不直接让rc7_runtime import tools工作台。旧legacy保持wire省略，Bound结构仍无创建权。此项不需真实Host，E可现在设计。 |
| typed serializer/overlay/replay隔离候选 | 解决下面三项真实冲突，先对象级/冷重建/版本历史/legacy测试；现负向guard仍拒绝Scope，不能因此开放bound Control。新schema或旧raw兼容是冻结行为变化，需A/B/D/E/F精确签审。 |
| 正式来源reader与runtime batch映射设计 | 给出creation_operation_ref/K/request_digest及所有身份的正式事实定位/单值性、PG snapshot_ref复合域和historical/current区分；接口不存在/未知默认HOLD。旧flat-only不接受为来源，错误先于明细、不泄漏，不能先靠fixture核销纵向通过。 |
| 全writer/正式创建与初始化恢复 | 定义真实事件schema/权威回执索引、单writer能力边界、PREPARE和append切点故障、scope不可变CAS、部分图初始化、所有raw/legacy入口策略及Host适配器；正向生产绑定须这些实施证据，不是提前加模型字段。 |
| factory/CLI/dispatch/Session/上游执行接续 | 把同一正式绑定/授权结果穿过真实native链，覆盖首budget/assignment/handoff/Evidence/Attempt等副作用；保留Q7、Captain、租约、人审和NodeGate。未覆盖正向入口保持HOLD，不以换Session/ID重建。 |

三项已由本源确定的兼容冲突，下一设计不能略过：

1. **不能简单给Mission加scope_binding:Optional=None。** 现reject_reserved看vars键存在，dataclass默认None也在vars内，会令旧bootstrap全部HOLD；asdict还会写scope_binding:null，违反3266“缺省完全省略”。需明确absence哨兵/运行域表示/serializer/guard协同方案，不能偷偷把现键存在性改成truthy或解析成功放行。相关行为变化必须另签。
2. **不能静默trim绑定身份或用release参数覆盖。** 现models._required和overlay._base会strip外层ID，_r1_payload另以release_id参数覆盖。紧凑合同保留文本原字节/要求镜像一致；bound路径必须明确精确保留或拒绝不一致，不能改变nestedK/mapping来“对齐”，也不能顺便改变所有legacy strip行为。
3. **不能把新raw codec直接替换旧全日志replay。** raw新入口拒重复键/NaN，严格数字仅scope域；旧overlay保留extra、logger有自己的JSON语义。历史flat-only/null/partial完整原字节保留，不能静默删字段降legacy；新validator全局拒绝可能使整本旧R1无法启动。需版本化兼容/治理诊断与新写入口拒绝分别设计，不能自动迁移或重写正式事实。未知outer有限float不纳入scope比较。

## 8. 本轮实际观察，非产品准入

本源使用已签纯codec测试结构向量（明确非授权事实）在TemporaryDirectory做以下源码观察：

- 正式Mission构造scope_binding参数仍TypeError。临时定义一个继承旧Mission、加Optional scope_binding=None的纯dataclass，仅调用当前reject_reserved就得到MISSION_SCOPE_NOT_ADMITTED，证明absence冲突；未修改正式类。
- raw fixture注入完整紧凑15及两个flat后，overlay原样保留15；既有长期Control.refresh与cold Control构造均HOLD且R1 bytes不增。当前legacy scoped reader仍可凭匹配flat返回三个身份，不证明其核了creation事实；没有把该结构向量记成真实已创建。
- 官方supervisor.handle已述先改READY再HOLD，Session.prepare可写PREPARED；它们是已知边界的真实现象，不把它们计为guard全写端PASS或伪造业务执行Evidence。无真实Host/外部执行，原生产R1未访问。

静态索引已用JSON parser重读，并按固定源码检查每条索引的文件/行位置；这仅校验文档索引，不是产品测试。

本轮没有生产绑定实现、命令、正式模型改动、PG/009/008或现场验收；未重复整套测试冒充闭包通过。调查期间远端A已有更新，所有行号/观察仅签1e3776bc。真实Host/Windows继续FIELD_NEEDS_BANK_TRANSFER，但上述源级兼容与闭包设计可以继续，不需要把工程整体停到行内。
