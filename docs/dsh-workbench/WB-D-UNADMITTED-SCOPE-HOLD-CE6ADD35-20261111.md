# D 未准入 Scope HOLD 冻结行为增量独立审查

被审：[PR #212](https://github.com/TongAITech/opencode-test-digital-employee/pull/212)，完整源 **`ce6add35be9e59166c7bdae67cef89fd1a35365f`**。独立 worktree `d-scope-hold-review` 从该源建立；只新增本报告，不修改候选、实现或08–10。

结论：**D_NEGATIVE_GUARD_DIRECTION_ACCEPTED / D_TARGET_MISSION_P1_CHANGES_REQUIRED / NOT_FULL_WRITER_OR_BINDING_ADMISSION**。这是可以在行外推进的明确负向保护，不需先取得真实Host才能实施；但当前表列“只查self当前row+input vars”的方案仍有一项列内入口P1，修订精确设计后方可按该范围准入。它不是要求本轮封闭所有writer。

## 接受的边界

- 仅Mission顶层`project_id`、`batch_id`、`scope_binding`任一键存在就HOLD，包括null/false/空值/完整DTO；不解析真值、不调用tools纯codec、不授来源/Host权限。`scope_ref`、`namespace`及未知legacy诊断字段不扩大到受管集合。没有这三个键的原legacy语义和wire应保持。
- runtime内部小helper不import tools，不依赖业务PG/宿主；对输入Mission先查vars，不能先asdict丢动态字段。错误常量不含Scope内容，不append一个“HOLD事实”伪造缺陷/Gate，不抹字段、不换Mission/release。
- __init__构造的scheduler/planner/session本身无业务append；在最小Mission identity row确认后可拒绝。长存实例每次动作仍须重查，不能只靠构造时检查。新保护只是拒绝未准入输入，不替代原Q7/Field-start、Host、Worker lease、Human/NodeGate资格。

## P1 D-HOLD-01：self Mission无Scope，不代表实际被写目标无Scope

候选对`start`/`submit_worker_output`及私有persist/sync等列内入口只要求guard“当前Mission row”，persist/sync另加“输入Mission vars”。但实际Control并非所有入口都保证目标属于`self.mission_id`：

- `closed_loop_control.py:165–167` 的start直接让scheduler按task_id找到并写task，没有先核task.mission_id=self；`:170–172`的output路径同样以output.task_id寻址；evaluation亦先按task_id读目标。
- `:582–588` `_persist_mission(mission)`拿self Mission的artifact_version，却append传入mission；没有校验传入mission_id或读取该目标旧Mission。`:536–549` `_sync_mission`还会先改传入Mission对象，再调persist。
- `:619–622` `_persist_gap(gap)`按gap_id版本直接写传入gap，没有先查该gap实际所属Mission；类似私有路径不能只看self row。应审计列出的输入Task/Gap/Evaluation/Defect/WorkerOutput等可达目标，但不等于扩入未列出的direct scheduler全局路径。

因此无Scope的Control A可以经**候选表中受保入口**触及已含Scope的Mission B，self-row存在性检查为false、输入旧typed Mission也可无reserved属性。它不是候选已经声明残余的“直接调用scheduler/raw append”，也不依赖并发或陈旧projection。

### 已在精确源实复的两例

全部仅在TemporaryDirectory R1；setup先合法bootstrap A/B及正常Task lease，再以隔离fixture方式给B注入reserved字段，未触碰生产日志。下面的would_reject只计算候选规定的存在性谓词，不冒称尚未实现的guard已经运行：

| 操作 | 实际观察 |
|---|---|
| A、B均同release；B的TB正常LEASED后B row加project_id；`A.start('TB', worker_ref='worker-b')` | A当前row无reserved，self guard不会拒绝；TB从LEASED变RUNNING，R1 bytes改变。B row有reserved但未被当前方案查询保护。 |
| A/B初始各version1；B row加project_id到version2；A.refresh_ready到version2；`A._persist_mission(Mission(mission_id='B',release_id='R',goal='B target'))` | A当前row及输入vars都无reserved；实际B变version3，原project_id消失，R1 bytes改变。版本对齐避免以无效版本先拒绝掩盖此路径。 |

实测输出：

```json
{"case":"Control.start A targets scoped B","A_current_guard_would_reject":false,"B_reserved_before":true,"target_state_before":"LEASED","target_state_after":"RUNNING","R1_bytes_changed":true}
{"case":"_persist_mission A targets scoped B","A_current_guard_would_reject":false,"input_vars_guard_would_reject":false,"B_scope_after_present":false,"R1_bytes_changed":true}
```

最小修订：对列内方法**实际会写的目标**先做最小身份归属核验，覆盖self row、按task/gap等稳定ID取得的既有目标Mission、传入Mission/Gap等身份及会被覆盖的旧对象所属Mission。目标有reserved时必须在scheduler/append/对象原地修改前HOLD；已有身份不一致错误能在零副作用前拒绝的路径可保留。若要保持全unbound旧错误/行为，此阶段可只新增目标Scope存在性拒绝，不必顺便重构全部legacy身份语义。至少增加上述两例、output及直接_sync/_persist_gap目标反例，不能用invalid task/lease先失败代替验证。

修订不需新Host/PG能力，不需接纳绑定创建，也不需修改底层TaskScheduler或关闭所有raw入口；只是使本候选**列入保护的方法**不因目标身份错位漏掉目标Scope。

## 权限/读取顺序与真实零副作用承诺

guard只需Mission身份/键存在性，不应取PG、解析绑定内容或返回Scope值。N1的canonical batch/node及精确Field-start等既有只读资格检查可保留原先拒绝顺序；不能绕过Q7得到“成功”。当前_preflight在取rc7 Mission row前还读legacy task冲突；本负向guard不是公共Workbench reader，不能宣称它证明了公共“身份先于全部明细”的读隔离。现有E01受控reader边界另保留，不因这项helper而放宽。

bank start_or_resume实际先mkdir和TruthRuntime，再读Mission/图；JsonlEventStore构造在`rc6_runtime/truth.py:106`执行touch。候选准确区分R1内容bytes/hash、projection/任务/租约等**新增业务事实零变更**和mtime/目录metadata；本轮不能声称mtime也不变。无Scope旧新建/恢复保持，Scope检测后不得进入graph安装或refresh。更严格只读预检可另单实现，不需要为此回退本负向保护。

N1 dispatch之前release driver可能已调用Field launcher，写canonical节点/Field-start回执；该事实不会被dispatch拒绝回滚。实施测试应以dispatch调用前基线比较bytes/Task/N1/dispatch receipt无新增，不能把先前Field-start也算“本次从未发生”。既有valid先验必须保留，existing receipt RESUMED分支亦需guard，不能靠“以前有receipt”给Scope Mission放行。

## 残余不应伪称已闭环

候选已承认stale projection/外进程追加、公开scheduler/planner/sessions、raw truth/store/append_entity等旁路未保护；D接受这一明确边界，不把这些本来排除的路径另报成本单P1，也不据此要求等全writer或行内现场再做局部保护。必须保留受控fixture残余证据，不给“全部入口封闭”“生产绑定已修复”或跨进程线性化结论。

## 实际审查与后续门禁

本次完整读取候选，手工跟踪Control、TaskScheduler、bank、N1 `_preflight/dispatch`、release driver/field-start及store touch顺序；PR212 HEAD核对仍ce6add35。实际运行上面两个TemporaryDirectory当前源码调用并记录结果；它们是**缺口/设计反例**，不是未来实现通过。只新增文档，没有运行未经实现的HOLD测试或转移旧测试PASS。

本次没有D侧现场依赖阻断：修正目标Mission范围并经B/E/F精确签署后，可仅实现helper+列内前置guard及legacy/有效前置测试。不增加模型字段，不把typed结构正确变成准入，不授新Host动作或执行权；正式创建/reader/008/writer及Windows现场继续各自门禁。
