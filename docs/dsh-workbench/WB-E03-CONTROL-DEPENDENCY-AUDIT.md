# E03 正式控制面依赖调查

精确基线：76d6d9c8（E02独立验收集成源）。状态：BLOCKED_CANONICAL_COMMAND_PORT；不是E03实现完成。

| 候选动作 | 实际源码调查 | 判定 |
|---|---|---|
| pause | MissionStatus无PAUSED；TaskScheduler拥有任务就绪/租约/执行状态但无Mission暂停命令或原子资源停派协议 | UNSUPPORTED |
| resume | bank_mission.start_or_resume是创建/恢复持久Mission的启动器，不是带principal/expected_revision/command_ref的暂停恢复命令 | UNSUPPORTED |
| retry_failed | ExecutionRecoveryController.authorize_direct_retry要求特定RecoveryWorkPlan、PreparedAttempt、诊断Evidence及原Gap/Task；不是任意Mission失败重试 | BLOCKED_REQUIRED_RECOVERY_PLAN_AND_CONTROL_PORT |
| request_human_gate | N9ReproductionHumanGateService只审核已有正式签名复现request，构造须可信bank verifier；不能拿通用action生成新Human Gate | BLOCKED_CANONICAL_REQUEST_AND_SIGNED_AUTHORITY_REQUIRED |

检查源码：rc7_runtime/control_plane.py、state_machine.py、models.py、execution_recovery_control.py、runtime_execution_control.py、rc72_economy_control_plane.py、rc72_n9_reproduction_human_gate.py、bank_mission启动接缝及现有rc7_admin端点。没有找到供工作台四动作调用的正式command_ref/幂等/主体/Scope/修订控制协议。以上结论仅针对现有通用候选命令；不能否认已有专项恢复及人审控制面。

不得将Task FAILED→READY、Mission WAITING_HUMAN或R1 append当作这些通用命令实现。工作台不得创建第二状态机；任何accepted都必须来自正式控制面可对账command_ref。当前无动作可合法发起，缺签名时只能BLOCKED/UNSUPPORTED，不可通过fixture executor宣称支持。

后续需独立评审正式控制面接缝：server-derived trusted mutation identity、project+batch+Mission显式绑定、合法动作专属payload与状态/租约/人审校验、expected_state_revision、持久idempotency、原command_ref查询及UNKNOWN副作用HOLD。PG008可预留命令journal，但不应在没有正式执行/查询协议时伪建accepted记录。不得写R1、NodeGate或把outbox提交视作执行成功。

E03当前仅完成真实依赖盘点；未新增HTTP写入口、PG迁移或正式命令支持。08/09/10由A记BLOCKED及依赖owner。行外现场状态FIELD_NEEDS_BANK_TRANSFER，不尝试访问真实银行DSH/Windows。

## 正式控制面增量提案（DESIGN_REVIEW_PENDING）

E03工单状态：**BLOCKED_FORMAL_CONTROL_API**。以下为待B/D/F评审方案，不是现存能力，不改变冻结主线。

建议调用链：工作台HTTP命令意图 → D可信Host mutation授权/CSRF证明 → B真实project/batch Scope → RC72正式CommandGateway → 专项正式controller → 正式R1事实/控制回执 → 工作台只读状态及恢复对账。UI请求只含action/reason/幂等键/expected revision/合法scope_ref，不含principal、签名权威、任意R1 payload或NodeGate结果。正式gateway拥有动作校验和签名上下文，工作台不能直接append或绕过它调用scheduler。

- pause：新增正式“停派意图/已停派”控制事实与可查询命令回执；正式gateway先校验Captain身份及Mission修订，再停发新worker/browser/model租约。活跃Attempt必须按现有取消或安全终止协议处理；不能强杀后伪造终态。无法确认在途副作用则HOLD。PAUSED若进入MissionStatus，须专门变更冻结状态机设计而非工作台本地字段。
- resume：要求同一正式暂停命令/停派事实及当前资源、新鲜Scope、人审和租约状态；正式gateway解除调度屏障并由原scheduler重新计算ready。不能调用bank启动器假装恢复，也不能恢复过期租约或把原成功Attempt重跑。
- retry_failed：先限特定Task/Attempt的DIRECT_RETRY已支持路径。gateway必须解析当前正式Gap、RecoveryWorkPlan、PreparedAttempt、诊断Evidence及执行资格，再调用ExecutionRecoveryController.authorize_direct_retry；动作payload需要明确源task/attempt/plan refs，现有泛Mission动作不够。签名、资源租约、状态修订与plan来源不全即BLOCKED；非DIRECT_RETRY走原N8回边，不扩展为通用重试循环。
- request_human_gate：应复用已有专项正式request创建服务，而非调用N9 review生成批准。需要定义目标Gate种类及正式request对象、审批主体/签名、资源及有效期。N9复现请求沿原request service→可信bank verifier→N9ReproductionHumanGateService；其他种类未定义时UNSUPPORTED。任何请求仅REQUESTED，不表示审批通过。

正式gateway需提供submit/query两接口及稳定command_ref、principal/project/Mission/Scope/payload digest/expected revision绑定。重复同键同payload返回原回执，异payload409；授权必须先于幂等结果读取。PG008在该协议获审并落地后保存工作台意图journal、outbox及正式command_ref；它不是R1控制事实。PG和R1无跨存储原子假设：READY→投递中→已提交/已拒绝/UNKNOWN仅是投递journal状态，不能替代Mission状态；未知结果通过正式query对账，同command_ref不能盲目重执行，无法确定副作用保持HOLD待人工。先在正式控制面证明幂等与恢复，再增加工作台发送路径。

可在行外实施：纯确定性gateway协议校验、正式控制面提交/查询幂等单元、隔离持久R1的拒绝/回执/冷恢复与PG008事务对账、真实PG+HTTP端到端组件测试。必须先完成接口设计评审及正式control-plane实现，不使用模拟执行器作为支持证据。

FIELD依赖：真实Host principal与mutation/CSRF证明、银行签名authority/verifier、现场Worker/Browser/模型租约与可安全停止协议、DSH1.18.26和Windows恢复。行外只能FIELD_NEEDS_BANK_TRANSFER；fixture签名/租约不授予生产资格。

冻结合同影响评审范围：docs/rc7.2/00、01、02、03（Mission命令/状态/回执和退出条件），05（停派与活跃租约/恢复），以及专项N9人审与恢复设计；docs/dsh-workbench/05、06及A03（gateway权威/每动作payload/错误/HOLD/幂等对账）。先以独立增量设计PR由B/D/E/F明确接受，再由A决定冻结合同变更，不直接改work/rc7.2。B评审PG008和Scope/事务，D评审可信Host/签名/租约接管，E负责正式controller映射，F独立攻防及假accepted/假审批/重放测试。
