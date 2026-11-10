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
