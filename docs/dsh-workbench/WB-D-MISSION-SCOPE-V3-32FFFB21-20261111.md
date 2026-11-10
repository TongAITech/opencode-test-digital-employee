# D 正式 Mission Scope 协议 V3 精确独立复审

被审：[PR #188](https://github.com/TongAITech/opencode-test-digital-employee/pull/188)，完整源 `32fffb2115251f2860954fe0772ec45ef433b3b7`。独立 worktree `d-binding-v3-review` 从被审源建立；承接 D V2 报告 `29df505104321e71b662e77851a736359994c1a3`，不是转签旧结论。V3 相对 `aa533c21` 仅新增一份协议文件，没有正式模型、Host 适配器、PG 或 R1 实现变更。

结论：**D_V2_TWO_P1_SUBSTANTIVELY_RESOLVED / D_PURE_COMPONENT_SCOPE_ACCEPTED / D_FORMAL_COMMIT_RESULT_RULE_CHANGES_REQUIRED / FIELD_NOT_VERIFIED**。

## V2 两项 P1 的逐项结论

| V2 项 | V3 精确规则 | 本次 D 结论 |
|---|---|---|
| D-V2-01 lookup 与再次 submit 动作矩阵不明确 | 第54–63行明确首次和再次 submit（含 NOT_FOUND 重交及部分初始化继续）同样重新核 mission.create、mutation/CSRF+Origin 或受审原生证明、当前 can_write、完整快照/提交围栏；lookup_creation 单独 mission.creation.lookup，禁止暗转 submit，撤销 create 后保留 lookup 不能重交；Bob 不得改包 Alice 的原主体域 | **规范歧义已消除**。这些动作名是所需抽象合同，不宣称真实 DSH 已实现。旧 mutation boolean、项目 read 或原 write-context 均不能替代它们。 |
| D-V2-02 Host 围栏只有义务、无可测抽象端口 | 第69–73行定义 server-derived Acquire 的 authority/actor/action/完整身份与 digest/epoch/cursor/期限，HELD 不可自签；CommitWithinFence 包含正式 append 回调与撤权全序；Release 幂等、过期和重启代次拒绝、崩溃/未知先原域查询、缺真实适配器生产默认 HOLD | **所需能力的抽象协议已实质补齐**，不再把这一项笼统列为“只有现场地址未知”。但正式提交结果分类有下列一项新的窄 P1；真实适配器仍必须证明该全序，而不是通过类型检查就算有能力。 |

## 剩余真正 P1：D-V3-01 不得把 COMMITTED 归为未 append

V3 第71行列举结果为：`COMMITTED、DENIED_BEFORE_APPEND、EXPIRED_BEFORE_APPEND、CAPABILITY_UNAVAILABLE、UNKNOWN`，紧接着写“只有前两类明确未append结果”。按列举顺序，“前两类”包含 COMMITTED，与同段“append 先线性化则返回带事件引用的 COMMITTED”和第81行 fsync 后正式回执矛盾。实现者若按这句将已提交事实走未发生分支，会破坏未知副作用恢复分类；即使 K/正式 writer 去重仍可兜底，也不能靠它容忍许可结果合同互相冲突。

最小修订只需显式枚举结果，不用位置措辞：

| 结果 | 必须含义及后续 |
|---|---|
| COMMITTED | 已发生唯一 durable append，带同 operation/K/digest/事件回执；不得作为零副作用或新创建依据。后续 PG/响应失败以该事实恢复。 |
| DENIED_BEFORE_APPEND / EXPIRED_BEFORE_APPEND | 只有这两个明确表示回调未进入且零 append 的结果才可按未发生处理；再次 submit 仍需重新取得所有当前许可。 |
| CAPABILITY_UNAVAILABLE | 在 Acquire/回调前且有零副作用证明时 HOLD；若发生阶段或零副作用不能证明，归 UNKNOWN，不得自行推断 NOT_FOUND。 |
| UNKNOWN | HOLD + 原 authority/K/digest lookup；不改 actor/context、不重新分配、不自动 append。 |

这里是**未实现协议的 P1 歧义**，不是声称当前产品已产生重复 Mission。被审源没有正式新创建实现；不能把查到这句文字等同于已复现运行越权或假 Evidence。修订后须给新精确 SHA，由 D 核对该差异；本报告不提前签新 SHA。

## 按施工范围区分准入

| 范围 | D 的精确决定 |
|---|---|
| 纯 canonical codec／带 tag DTO/schema／K与摘要纯函数 | **D 侧接受隔离组件施工**；不产生 PG/R1 副作用，不接受浏览器 verified/主体权威，不授正式创建。真实来源与数值/字节规则仍由 B 签相应范围。 |
| 缺 Host 能力即 CAPABILITY_UNAVAILABLE/HOLD、零副作用的适配器 | **D 侧接受隔离组件施工**；必须测试拒绝缺能力而非用 fixture 开生产提交。不得实现 COMMITTED 路径为成功 stub。 |
| 仅 DTO 内 typed 绑定的不可变保存/校验 | 可在上述无副作用组件范围准备；绑定值不是授权。旧无来源数据保持 HOLD，不补来源。 |
| 修改正式 Mission typed 模型、序列化/重建/正规更新以保存绑定 | D 对“不丢绑定、不重绑、旧数据不迁移”原则无剩余异议；**本报告不单独批准修改冻结正式模型**。按 V3 第85行仍须 B/D/E/F 对该精确实现增量认可，尤其 E/RC72 owner 与 F；不能用纯 codec 通过替代此门禁。 |
| 新正式创建、部分初始化继续、重新 submit 或正式 writer/008/Host 围栏 COMMITTED 路径 | **当前不准入上线或对外宣称已接通**；先修 D-V3-01，并取得 B/E/F 相应精确设计/实现审阅、真实并发/崩溃/权限证据及受控适配器证明。 |

第71行“持有权威撤权读锁贯穿回调”只是一种拟议实现，不自动证明跨进程或远程 Host 崩溃时的全序。实现验收必须覆盖：撤权先/后于 durable append、Acquire 后代次变化、回调进行中 Host 重启/锁丢失、到期边界、fsync 成功但回执丢失、PG 事务失败及旧 fence 再用。若任何一个顺序无法由实际适配器/writer共同保证，生产保持缺能力/HOLD。fixture 可验证抽象状态机及零副作用，不构成真实 Host qualification。既有 CaptainDispatchFencer、ledger lock、资源租约、人审/NodeGate 权威继续独立，不能被新绑定代替或绕过。

## 实际核查与证据边界

- 完整读 V3 与上轮 D V2 报告，逐项核动作矩阵、Host 输入/结果、回调线性化、过期/崩溃、分阶段准入和正式事实所有权。`gh pr diff 188 --name-only` 及 `git diff aa533c21..32fffb21 --name-only` 均只有 V3 文档；HostIdentity/write-context/正式 factory/bank_mission 对上轮被审源无 diff。
- 在精确源运行 `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`：3/3 **缺口复现**，0.048秒，仅 TemporaryDirectory R1；说明 typed 生产链缺口仍在，不是修复或产品通过。
- 没有重跑并转签上轮16项PG/33项Host fixture；本次无相应实现改变，也没有新的真实 DSH 证据。GitNexus 工具在本任务未暴露，按真实文档 diff/已核调用点审查，不伪造调用图或动态权限证明。
- PR188完整HEAD核对仍32fffb21，RC7.2远端仍edaf9290。工具正常，未发生额度错误。只新增本独立报告，不改被审协议/实现、08/09/10、冻结正式模型、原始事实或许可证。

真实 DSH/Windows 仍 **FIELD_NEEDS_BANK_TRANSFER**。上述 D 侧隔离施工接受不是 F 签署、行内资格或最终发布许可。
