# D E03正式控制面增量设计审查

精确被审提案源：0e8259cd（WB-E03-CONTROL-DEPENDENCY-AUDIT.md）；角色：本轮D；结论D_DESIGN_DIRECTION_ACCEPTED_WITH_REQUIRED_PRECONDITIONS。本报告只接受继续设计的权威边界，不签实现/现场，不允许任何未支持动作accepted。真实DSH/Windows统一FIELD_NEEDS_BANK_TRANSFER。

提案正确保留BLOCKED_FORMAL_CONTROL_API：现有专项恢复、人审和银行启动器不能冒充通用pause/resume/retry_failed/request_human_gate。PG意图journal/outbox不是R1正式回执，不得以其提交制造accepted。D同意正式gateway submit/query、独立command_ref、原幂等键对账和UNKNOWN HOLD方向。

## 必要设计前置与未闭合点

1. Host用户mutation授权/CSRF证明与Captain membership/独立Host observation必须分别验证。普通浏览器用户权限不能变成签名Captain；opaque业务write-context只绑定恢复主体，不授予Mission控制权。gateway需定义每动作所需主体、签名发行者/信任根、audience、精确Mission/Scope、有效期、代次与撤销语义；不能复用一个任意字符串或同一authority伪造双签名。
2. pause停派必须是正式持久调度屏障和fencing epoch，覆盖跨进程/多Captain及新Worker/Browser/Model/Data lease准入。设置屏障与最后一次派发/租约取得必须可证明原子排序；仅内存flag或UI“已暂停”不够。需先定义停派意图/确认回执及其与既有冻结状态机关系，再由A批准合同增量。
3. 活跃Attempt不能因Host断线、lease TTL或取消请求accepted就判已停止。每种工具需定义安全停止/可查询副作用/checkpoint；无法确定是否已提交业务动作保留UNKNOWN/HOLD，禁止重新派发相同副作用或释放仍有真实写owner的资源。资源回收必须有正式owner/fencing证据，不靠会话消失推断。
4. resume须绑定同一Mission/暂停command_ref、当前签名Captain代次及新鲜Scope、人审和资源所有权；旧签名/旧lease不复活。scheduler重算READY时已完成Attempt不得重跑；缺少暂停事实、未对账的UNKNOWN或活跃冲突应拒绝/HOLD。
5. request_human_gate必须分离请求者与审批权限，保留正式request、目标Gate/修订、审批身份/签名与有效期。创建请求只可REQUESTED，不能代人工批准；review与request service不可混用。未定义Gate种类继续UNSUPPORTED。
6. 重放submit/query须每次重新Host/项目/Mission授权，授权先于读取原幂等回执；主体切换不能以新主体幂等域重放旧未知payload。缺真实Host、签名authority、专属动作payload、当前lease或可查询正式回执时保持BLOCKED，不能fallback直接调用scheduler/R1 append。

## 可施工范围与验收

在上述接口/状态机增量经B/D/E/F及A批准前，只可做确定性协议拒绝与设计准备，不新增可执行通用动作。实现后需真实跨进程并发停派/fencing、旧Captain/过期签名拒绝、in-flight UNKNOWN/副作用对账、暂停后冷启动、恢复不重跑、撤权后原回执不可泄露、双签名独立、请求不变批准等反例。fixture控制器不能当正式能力；行外真实持久R1组件验收也不授予现场资格。

本轮未发现需要改变R1唯一事实边界的理由。以上是下一正式设计必须具体化的前置，不是D代E/F接受当前尚未实现动作；E03继续BLOCKED_FORMAL_CONTROL_API。未修改08/09/10或work/rc7.2。
