# E：typed Mission Scope 保留增量与真实路径调查候选

状态：EXACT_SHA_B_D_E_F_REVIEW_REQUIRED；本PR仅文档，不授实现准入。基线W0 `b6d93e41`；上位V3 `04ca971676509da9379ed53a29b495d2a32c325c`。PR195冻结 `a9758687cae73f49d9b62e44f49e85625f0eea7c` 未改。本候选不修改冻结00–03、正式模型/工厂/R1、008或08/09/10。

## 1. 已读冻结约束与最小影响

本次按实际源码查阅00全文及01模型/WorkItem/Attempt/Session、02不变量/Phase1/CT08–10、03核心对象/状态/并发/验收条款，并完整读 NATIVE-MISSION-FACTORY-CONTRACT 与 CONFIGURED-MISSION-BINDING-CONTRACT；没有宣称本次重读01–03所有非本增量章节。00§7要求权威边界/层次/验收标准的实质变化先单独设计基线提交；01§3.1–3.3固定ReleaseBatch/Requirement/SST，§10要求Captain换会话不新建Mission；02§2的R1事实、Worker STRICT及不减测试义务保持；Phase1要求schema/兼容策略和repository合同测试。03§2/§3/§17要求持久对象、Scope、版本冲突检测和门禁，typed保留不得生成NodeGate PASS或改N1–N10状态。

需A与RC72 owner先评审的冻结增量：00明确业务PG映射与正式R1事实分工，01在Mission及恢复模型加入完整不可变绑定，02增加绑定丢失/改绑/部分字段/旧数据兼容测试，03说明Mission Scope与已有MissionNode.scope_ref的一致性规则（不能用PG batch替换release-batch://运行身份）。工作台02/05/06与A03按V3同步。factory合同强调compose零R1副作用，不能为绑定在构造时偷偷append；配置能力对象不是业务绑定/Host创建授权。这里不直接覆写冻结文本。

## 2. 精确现有路径（行号基于b6d93e41）

| 层/入口 | 实际行为与未来修改范围 |
|---|---|
| rc7_runtime/models.py:100 Mission / :288 to_payload | Mission无project_id/batch_id或typed绑定；asdict只输出声明字段，顶层Enum转value。未来新增optional typed值及严格反序列化；纯codec结构合法不授权 |
| truth_overlay.py:26/:49映射，:60 _base，:85 validate_rc7_mission | Mission映射RC7_MISSION_UPSERTED→rc7_mission；_base deepcopy保留未知extra，现有validator不验证业务Scope。必须分清无绑定、完整绑定、部分/flat-only，不把extra当正式来源 |
| truth_overlay.py:243 _r1_payload / :373 append_entity | _r1_payload按传入release_id覆盖payload.release_id，现无与Mission.release_id/绑定mapping一致性检查；append_entity经durable acceptance后直接TruthRuntime.append_atomic。未来不得让override悄悄跨release，绑定比较须在正式writer持锁最新投影上执行 |
| rc6_runtime/truth.py:315 rebuild_projection / :326 append_atomic | replay每条事件经expand_for_replay重建；append验证canonical→store.append→projection→RAW。不能仅在control方法比较而绕过raw append/replay；历史版本不可变冲突检查需正式writer入口与重放检查协同，不擅改所有legacy回放语义 |
| closed_loop_control.py:114 bootstrap | 先查mission不存在，再append typed Mission，随后runtime identity attestation。现非跨进程创建事务，不是V3正式create事件/CAS；只加字段不能宣称修复创建幂等 |
| :564 _mission / :582 _persist_mission | _mission手列旧字段，丢所有Scope extras；_persist按当前artifact_version+1 append，未比较不可变绑定。未来共享严格row→typed解析，旧完整绑定逐字保留，部分字段先拒绝而非删掉继续 |
| :536 _sync_mission | 更新active_task_ids/open_gap_ids，再persist；必须只动可变运行字段 |
| :126 register_task / mission_graph.py:318 install | register_task先scheduler.register，再重建Mission/转RUNNING/refresh/sync；graph.install对每个task调用此方法。若绑定损坏，必须在任何task写前先做identity/绑定完整性检查；不能先写task再因scope拒绝 |
| :137 refresh_ready / :142 lease_next / :165 start / :170 submit_worker_output | scheduler任务写入与后续Mission重建/sync路径；必须在任务/lease等副作用前验证绑定，不只在persist最后失败。现有执行权限/资源围栏不可由保留校验替代 |
| :175 accept_evaluation / :281 accept_defect_resolution / :336 converge_mission | evaluation分支直接_persist(:243/:258/:274)或sync(:278)，defect结束sync(:333)，converge persist(:382)/sync(:391)；现有Gate/Evidence规则保留 |
| :486 _resolve_source_gaps / :503 _reactivate_source_tasks | 分别:persist(:501/:534)，以及间接任务/gap写入；需纳入绑定前置与持久保留测试，不能只测refresh |
| bank_mission.py:132 start_or_resume / :146 | 新建Mission(mission_id,release_id,goal)→bootstrap→compiler.install及正式图证据；无业务绑定入参。resume只_assert_resume_identity(:66)的release/goal和图合同，随后refresh_ready(:195)，因此extra真实丢失 |
| rc72_mission_node_dispatch.py:190 _preflight / :277 dispatch / :359 bootstrap | **另一条实际生产构造路径**：从正式rc72_release_batch取mission_id/release_id；核N1 scope_ref和精确BOOTSTRAPPED field-start回执、拒legacy图冲突；无rc7_mission时:362 Mission旧构造，随后注册WorkItem。不得遗漏或绕过Q7/Field-start，不把运行release_batch_id当PG batch_id |
| rc72_mission_factory.py:117 create_mission_driver | 接受真实worker/captain/执行能力，组成driver，不创建Mission、无业务project/batch输入；不能把“factory已构造”当正式绑定事实 |
| rc7_release/rc72_mission_cli.py:99 main / :249 factory | package/source/canonical batch与Host bindings校验在factory前，run后经Field admission；rc72_release_driver.py:574调用ReleaseBatchFieldMissionLauncher.start，真实节点/调度后续才产生rc7 Mission。接入要贯穿此链并保留Q7/lease/Human/NodeGate |
| bank_mission.py:227 build_parser/:241 main；bank_mission_start.py:88 main/:92；bank_mission_autopilot.py:394 | legacy启动/恢复CLI汇入start_or_resume；不能直接加可由CLI自报verified的正式创建开关。legacy旧用法继续，但不授Workbench Scope |
| rc7_runtime/session_continuity.py:93 prepare/:136 activate/:199 resume_envelope | 持久handoff和上下文恢复，不自行构造Mission；重建后的同Mission继续须保留binding，换Session不改K/actor/authority或新建 |

额外真实构造调用：rc7_release/dsh_bridge_qualification.py:222、script_qualification.py:403、code_qualification.py:338、test_design_qualification.py:410、execution_qualification_strict.py:392。这些qualification legacy Mission不能被当成已由业务Scope创建；保留原资格语义，typed路径另行测试。全仓排除tests/workspace-template后的RC7_MISSION_UPSERTED字面量仅truth_overlay映射；不等于raw append已封闭（调用者可用动态event_type），仍需V3正式writer入口封闭审计。rc72_domain.MissionNodeRecord是不同对象，不能拿其scope_ref补造Mission来源。

## 3. 真实E01依赖与旧兼容

rc7_admin/projection.py:159 mission_overview_scoped先query(rc7_mission,mission_id)，要求flat project_id/batch_id相等后才读tasks/executions/evidence；它明确自述legacy in-process guard，不是Host/PG RLS。tools/dsh_workbench/e01_service.py:38 quality先真实B06全页授权，再复制原R1字节到临时目录读取投影；之后再核PG修订。Scope不匹配映射403，相关读失败503，release_decision始终HOLD。

现行reader可以接受手工extra的flat字段，但普通factory/start不提供它，typed roundtrip还会丢失。**这不是正式生产绑定能力**。下一增量应将typed绑定的project/batch作为权威内一致身份，flat两字段仅由正式序列化确定性镜像供现有E01投影，二者必须精确相等；原flat-only fixture不能冒充正式factory事实。reader必须先验证完整typed绑定/正式创建来源引用及镜像一致后再读任何明细；如短期只做保留而reader未升级，生产Workbench正式接通资格持续HOLD，不能凭现有flat接受宣布完成。

兼容矩阵：

| 原数据 | legacy RC7运行 | Workbench正式读取/写入 |
|---|---|---|
| 完全无绑定且无flat身份 | 保持旧创建/恢复/更新正常；序列化不凭空加null或来源 | Scope未解析，403/HOLD；不从release/名称猜 |
| 完整新typed绑定且镜像一致 | 仅正规获准入口可产生；更新/恢复必须原样保留 | 正式来源/PG/Host条件均满足才开放；typed结构本身不授资格 |
| typed字段存在但null/部分/畸形；flat单边或与typed冲突 | 新增量先HOLD/拒绝任何会写入的动作，不静默降级成legacy | 同一不泄漏拒绝，不读明细 |
| 历史flat两字段但无typed来源 | 不迁移、不抹除；保留原日志，需明确人工治理策略；不能把丢extra当正常更新 | 当未具正式来源，保持HOLD；若保留代码尚未覆盖此类输入，写路径先拒绝 |

旧无绑定“正常legacy继续”与“Workbench拒绝”是两件事。禁止把None默认值用asdict写回导致legacy出现半绑定；绑定缺省应在wire上完全省略。部分绑定检测在row解析、任何相关副作用前置、正式append和重放诊断均需要覆盖。

## 4. 最小typed候选与不可变比较：待审，不直接定生产wire

建议 optional `scope_binding` 作为一个整体不可变值，缺省完全不存在；对象最少承载V3 schema_version=1、binding_ref、完整K、request_digest、mapping（含显式runtime_release_id）、snapshot_ref、Scope完整canonical快照与scope_digest、正式creation事件/receipt引用。正式creation引用在创建事件自身如何自引用、事件ID何时分配须与V3 writer事件设计一起定，**本候选不编造已签wire字段**。可先采用纯内存保存类型/明确parse结果，最终字段命名/可选性/事件自引用策略由B/D/E/F专门签署；不能以dataclass可以构造证明它是权威。

不可变集合至少为K/mission_id/release_id/binding_ref/mapping/Scope canonical bytes及digest/request_digest/snapshot_ref；创建回执引用应按已签事件协议不可变引用，不能由普通更新补写来源。比较按已严格解析的规范结构/字节，不依赖mutable dict引用或仅project/batch相等；重复JSON键/未知schema/矛盾来源失败关闭。正式writer持锁重读旧行后，拒legacy→bound、bound→legacy、任何改绑，确保并发CAS；旧无来源正式绑定迁移永不自动执行。to_payload传入release覆盖必须同时拒不一致。纯codec只做结构与摘要，不验证任何ref存在、来源verified、Actor/Host动作或R1事件真实性。

“保留”必须是读已有绑定→校验→原值再序列化；不允许从当前PG变化重算后写到原Mission。PG/Host撤权影响是否允许当前动作，不改变历史创建绑定。新Scope另走新已授权意图，绝不本地改写旧Mission。

## 5. 可先准入与正式依赖边界

候选P1（仍须精确增量签署）：纯typed DTO/parser/serializer、完整与缺省互转、canonical不可变比较、legacy缺省wire省略、部分字段拒绝；隔离测试fixture，不开放正式创建。它可在模型变更前先独立纯模块实现，不能让它绕过writer。若要接入models/closed_loop/replay/reader，即触及冻结正式模型与行为，需B/D/E/F明确签署后才改，不能仅引用PR195纯codec准入。

候选P2：模型/row解析/普通更新保留与前置校验，可作为独立实施单；但bound生产写必须依赖V3统一writer、重读CAS、不可分割正式创建事件与可信Host fence。未封闭的raw/legacy writer对绑定Mission保持拒绝。P1/P2通过不开放Workbench创建，不补造旧绑定，不声称PG→factory→HTTP全链完成。

候选P3：正式PREPARE/PG锁端口、Host admission适配、factory/CLI/dispatch桥传入、独立创建事件与回执/partial graph恢复。这些依赖真实B SQL/Host action/fence资格及正式writer，不属于本次可先准入范围。真实Host未知继续FIELD_NEEDS_BANK_TRANSFER。

退出至少覆盖：真实正式构造而非手工extra；bootstrap/任务注册/refresh/lease/start/output/evaluation/defect/converge/gap恢复/三个更新/cold replay/handoff全程不可变；同键异payload/并发改绑/传错release/旧flat-only/partial绑定均拒绝且零额外任务或租约；旧无绑定legacy回归继续而Workbench拒绝；identity拒绝时spy证明tasks/executions/evidence零查询；real PG→正式factory/dispatch→原R1→HTTP另有完整证据。任何缺口characterization通过只表示复现，不是修复PASS。
