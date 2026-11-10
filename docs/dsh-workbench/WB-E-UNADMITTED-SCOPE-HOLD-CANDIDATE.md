# E：未准入 Scope Mission 防丢失 HOLD 最小冻结行为增量

状态：B_D_F_EXACT_SHA_REVIEW_REQUIRED / NO_IMPLEMENTATION_YET。基线远端W0 `199a316334abb41c77890ed5608b989e2a7e6126`（本次fetch核对仍相同）；承接typed调查PR198/3266cb2d和纯codec PR209/968430ed。仅新增候选，不修改模型/control/factory/R1/008、冻结原文或08–10。目标只是在限定正规入口保护现有未准入Scope数据，**不是生产绑定修复或全R1写端封闭**。

## 1. 最小判断与兼容域

保留字段集合恰好为顶层 `project_id`、`batch_id`、`scope_binding`。判断仅为键存在性：任一键存在即拒绝，不看truthy、不解析DTO、不调用纯codec、不验证来源或Host。null、空值、list/dict、单边flat、双flat、partial typed及完整typed一律相同HOLD。现阶段不存在经本正规Control准入的Scope Mission，因此不能给“结构完整”放行特例。完全没有这三个键的旧Mission继续原行为和wire；未知legacy诊断字段如diagnostic_score、scope_ref、namespace不扩入保留集合。字段名嵌在不相关outer extra内部不触发，拒绝仅针对Mission顶层。

实现建议置于rc7_runtime内部小型纯存在性helper（不import tools/dsh_workbench，保持现有离线包闭包）。raw row用Mapping键检查；bootstrap/持久化输入Mission除当前row外还检查vars(mission)顶层动态属性，避免to_payload/asdict先丢动态字段而漏检。helper不改输入、不删字段、不补来源、不append HOLD事实。

统一reason建议 `MISSION_SCOPE_NOT_ADMITTED`；Control用ClosedLoopControlError（既有RuntimeError家族），bank用BankMissionError，dispatch用MissionNodeDispatchError，外层CLI沿既有HOLD/非零路径。不能在reason泄漏project/batch/typed内容。业务上HOLD，不把拒绝记录为缺陷、执行失败或NodeGate变化。完全旧数据的既有错误优先次序不改；检测到保留字段时在本入口首个业务副作用之前拒绝，先读identity和既有必需只读资格检查可保留。

## 2. 真实顺序与最小受保入口

| 入口（行号基线199a） | 当前先发生什么 | 要求的最早guard |
|---|---|---|
| ClosedLoopControlPlane.__init__:103 | install overlay、组装scheduler/planner/session，最后_mission_row；这些构造本身无R1 append | 当前Mission row存在性检查后拒绝；不得仅靠构造检查，长存实例每次动作还须重查 |
| bootstrap:114 | 查重→append Mission→runtime身份attestation | append前查输入vars及已有同ID row保留字段；存在scope先HOLD，不因already registered路径覆盖事实；无Scope旧查重语义不改 |
| register_task:126 | scheduler.register先写task，之后才_mission/sync | 方法入口当前row guard，早于scheduler.register及任何状态转换 |
| refresh_ready:137 | scheduler.refresh_ready先写task | 入口guard，不能等_mission |
| lease_next:142/start:165/submit_worker_output:170 | 先scheduler动作，随后gap/mission同步 | 入口guard，早于lease/task/output artifact变更；本guard不授资源许可 |
| accept_evaluation:175 | 只读检查后:212 append evaluation，再task/gap/planner/mission更新 | 入口guard，早于任何append/transition/planner；所有PASS/REPAIR/BLOCKED/HUMAN分支都覆盖 |
| accept_defect_resolution:281 | 校验后:320 evaluation及defect append→task/gap→mission | 入口guard，避免正式缺陷/证据先写后拒绝 |
| converge_mission:336 | 校验后:382 persist Mission，再evaluation及CONVERGED同步 | 入口guard，早于可变Mission对象转态与任何append；不改充分性/NodeGate规则 |
| _resolve_source_gaps:486 | 先transition/persist多个gap，后_mission | 私有方法入口guard，不能只在后半段阻断 |
| _reactivate_source_tasks:503 | 先重置/transition/append多个task，再_mission | 私有方法入口guard，避免直接调用私有路径半写 |
| _sync_mission:536 | 改传入Mission.active_task_ids/open_gap_ids再persist | 先guard当前row与输入vars，早于修改传入对象 |
| _mission:564 | 显式旧字段构造，丢flat/typed extras | 构造前guard当前row，不允许从损坏scope反序列化成legacy |
| _persist_mission:582 | 当前row版本+1后append，未比较scope | guard当前row及传入Mission vars，早于to_payload/append；不是CAS |
| _persist_gap:619 | 读取gap版本后append | guard当前Mission row，早于append，保护直接私有写调用 |
| bank_mission.start_or_resume:132 | mkdir→TruthRuntime→读Mission→读graph；new bootstrap/install，resume assert+refresh | 读row后立即guard，早于图恢复/新增及refresh；禁止resume丢scope或新建替代Mission。无row只走旧无scope构造，未来scope参数另审 |
| rc72_mission_node_dispatch._preflight:190 / dispatch:277 | 从canonical batch及N1/精确Field-start查身份，查现有rc7 row；existing receipt可直接RESUMED；new bootstrap→task→N1 RUNNING→dispatch receipt | _preflight取得既有rc7 row后guard，并在dispatch入口完成preflight后、existing receipt分支前重核；有scope连RESUMED也HOLD。新Mission输入仍无scope；bootstrap防御兜底 |

只读/pure私有函数 `_mission_row`、`_open_gap_rows`、`_gap`、`_gap_from_row`、`_validate_new_gap`、`_require_*` 本身不append，不扩成全局查询策略；snapshot:463只是旧内部快照读，不授Workbench身份读取。__init__ guard可能让新Control实例连snapshot也无法构造；如需独立治理只读查询，另用既有受控投影，不以跳过guard创建可写Control。不能把这次HOLD改为接受typed reader。

## 3. 明确不能由这些方法保证的范围

**并发限制**：guard基于当前TruthRuntime投影的Mission row；实例可能未看见另一个进程raw append。不存在统一writer/CAS时，不能保证“检查后外部加scope，再由旧实例写回”竞态被阻断。本增量保障的是入口当前可见row已含保留字段、无并发绕过writer介入的调用；不得用这个检查宣称跨进程线性化。后续V3封闭writer/重读CAS/Host/factory门禁仍必需，任何bound生产写继续不准入。

**底层绕过**：Control.scheduler是公开属性，直接TaskScheduler.register/refresh_ready/lease_task/lease_next/start/submit_worker_output/persist_evaluated_task（control_plane.py:89起）不经过Control；Control.gap_planner.plan及其_persist_gap、Control.sessions.prepare/activate也可被直接调用。raw truth.append_atomic、store.append、append_entity、直接state machine/其他services同样不在本增量保护域。此阶段不修改它们，必须在文档/测试明确绕过仍存在，不能把“私有方法guard”称所有调用封闭。

**上游已发生副作用**：rc72_release_driver.start先ReleaseBatchFieldMissionLauncher.start(:574)，然后才到节点调度；Field-start可bootstrap节点/写receipt（rc72_field_mission_start.py:209–257）。仅在N1 dispatch加guard不能回滚此前launcher或driver准备。候选只承诺dispatch调用本身零新增业务事实；不宣称整个driver.run事务零副作用。要保障更上游，需要另审driver/field-start入口的同样先验guard，不能删除或绕过Q7/Field-start来提前“成功”。bank_mission_start.main在start_or_resume后才discover配置；该CLI在guard拒绝时不能继续配置/工人启动，但autopilot/其他包装若在调用前已做I/O，不能追溯保证。

**文件元数据**：bank.start_or_resume当前mkdir且TruthRuntime构造经JsonlEventStore.__init__:103调用path.touch(exist_ok=True)，可能更新已有R1 mtime；即使append前guard，不能声称字节以外的所有文件metadata从未变化。最小退出承诺原R1内容字节/hash、所有projection事实/任务/租约/资源业务状态不变。若门禁要求mtime也不变，必须先另审只读预检/无touch读取端口；本候选不暗改通用TruthRuntime构造语义。无scope旧新建行为不改。

bootstrap/bootstrap并发查重或多进程初始化也不由guard修复；新建scope意图仍禁止。持有bound row的legacy CLI拒绝后不得换mission_id、重新分配release、删除scope或覆盖日志“恢复”。

## 4. 零业务副作用、恢复与旧legacy退出矩阵

每个受保入口均用**本方法实际可达且原本可成功/会写**的fixture验证，不能只传无效参数先触发旧错误冒充scope保护。测试矩阵保留旧scope丢失characterization历史，新增产品测试应断言HOLD与原数据保留，不能继续断言bug存在当产品PASS。

| 组 | 必须有的正/负/边界/恢复证据 |
|---|---|
| 存在性 | 三保留键逐一×null/false/空字符串/[]/{}/partial/full结构、双flat、混合；全部同reason拒绝，raw row/输入Mission不修改；未知diagnostic_score=0.5/scope_ref/namespace继续legacy |
| 全入口零写 | 每个表列公开及直接私有路径：R1 bytes/hash/全部projection深快照不变，append_entity/append_atomic/scheduler/planner/attestation spy零调用；Task/WorkerOutput/Evaluation/Gap/Defect及输入Mission对象深相等 |
| 长存与cold | 先无scope建Control，再用隔离临时R1注入scope事实（仅测试），重新投影后各方法拒绝；重启Control拒绝，至少三次重复调用不增事件、不删字段；不因新Session换Mission |
| bootstrap | 输入Mission动态setattr三个reserved之一：append/attest零调用；已有row scope不被新Mission覆盖；旧无scope构造正常 |
| bank | 临时实际正式start/resume：已有scope日志调用HOLD、R1 bytes不变/无graph任务证据；已有无scopev1/v2恢复行为不变；无scope新建仍原图合同；metadata边界单独记录 |
| N1真实第二入口 | 保留有效canonical batch/N1/精确Field-start先验、真实dispatcher调用；有scope在existing receipt与新dispatch两个分支均HOLD，task/N1/dispatch receipt及R1 bytes不增。缺Q7/Field-start仍原先拒绝，不用假PASS绕先验 |
| legacy完整回归 | control/core/defect桥、bank entrypoint/start/autopilot/turnkey、mission_node_dispatch、session handoff与现有RC7.2专用门禁测试；模型/to_payload旧wire无新增字段，原正常路径与原错误码不漂移 |
| 未覆盖实证 | 受控临时fixture说明direct scheduler/raw append仍可绕过该guard及stale projection竞态，报告为残余依赖，不运行生产注入、不把绕过计全写端PASS |

## 5. 冻结合同影响与下一单准入

00§6 R1/Session与不模拟现场保持；00§7需先批准本冻结行为增量。01§10恢复同Mission不换绑，本增量将未准入Scope恢复显式HOLD，旧完全unbound继续；02§2/Phase1/CT09–10增加“不静默丢字段、拒绝前零业务写”的验收；03§3/§17保证这次不推进/重置任何Node、不改变Gate或lease，且明确不是并发writer证明。无需此阶段改变Mission字段schema、N1–N10定义、正式创建事件或008。

B复核仅存在性域/旧wire兼容、无PG数据写；D复核不把HOLD转授权、包装器/资源副作用边界；E核实际方法顺序/所有列出路径及未覆盖writer；F对完整候选SHA独立审查，认可后再独立实现PR。实施应限定rc7_runtime内部helper、列出Control/bank/dispatch guard和相应tests；不得拉入tools依赖、扩大到无关legacy scope字段、改原始R1或将HOLD称绑定完成。真实Host/Windows继续FIELD_NEEDS_BANK_TRANSFER，完整正式创建/读取仍待V3门禁。
