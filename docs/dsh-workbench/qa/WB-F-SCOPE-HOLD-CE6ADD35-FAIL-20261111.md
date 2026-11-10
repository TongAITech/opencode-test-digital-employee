# F：未准入Scope HOLD设计实际目标域缺口

被审PR：[212](https://github.com/TongAITech/opencode-test-digital-employee/pull/212)。精确设计源：`ce6add35be9e59166c7bdae67cef89fd1a35365f`。独立worktree`f-runtime-hold-design`；只有候选文档，没有HOLD实现。F未修改被审设计/功能、08–10、冻结合同或生产事实；本报告中的执行只操作TemporaryDirectory R1。

结论：**DESIGN_REVIEWED_WITH_P1_TARGET_MISSION_GUARD / NOT_ACCEPTED_FOR_IMPLEMENTATION_AT_CE6ADD35**。在列入保护域的Control入口，不能只检查控制器self的Mission row；必须在首个副作用前覆盖实际写目标Mission，或明确先作经兼容审查的身份拒绝。新精确设计修订后可窄复核，不需要银行现场作为负向保护的前提。

## 唯一P1：self Mission不等于实际写目标

候选§2的_persist_mission/_sync_mission只要求当前self row和输入Mission vars的保留键；start等只要求当前self row。但现有方法可接受/获取另一个Mission的合法对象或task_id：_persist_mission会按**输入mission.mission_id**写事件，scheduler.start会按**task_id所属Mission**写task，未必是self.mission_id。

因此两个拟议判断都可为false，实际被更新目标却已有project_id/batch_id/scope_binding。此路径经过候选明确列入保护域的方法，不属于已披露的raw scheduler绕过、旧投影跨进程竞态或上游Field-start副作用。范围必须先说清，不能在实现时仅照表加入self guard便宣称目标Scope被保护。

### 反例A：受保私有persist仍可丢目标Scope

同一真实临时TruthRuntime：bootstrap无Scope M1/release R的Control；另append合法Mission M2/release R的raw row，附project_id='P2'。传给M1._persist_mission的是普通Mission(M2,R)，没有动态Scope属性。实际执行：

```text
target before keys ['project_id']
proposed current-row guard keys []
proposed input-vars guard keys []
target after keys [] artifact_version 2
```

候选的self row/vars检测均无键，当前实际持久化从M2 v1→v2并丢project_id。此处是证明候选目标选择不足；不把尚未实现的guard说成已测试失败。

### 反例B：公共start仍可推进Scope目标任务

先让M2通过正规Control.register_task/lease_next建立可成功启动的T2，状态LEASED、owner W；然后在隔离R1为M2加project_id。M1 Control无Scope，调用其公共start('T2',worker_ref='W')：实际M2 Task由LEASED→RUNNING，M1 raw row依旧无保留键、M2 Scope仍可见。不是用无效worker/状态先触发旧错误冒充保护，也不是在动作中直接调用未受保scheduler。

进一步代码审查：submit_worker_output以output.task_id获取实际Task，accept_evaluation以task_id获取Task/evaluation及Gap；_persist_gap以输入gap.mission_id写入；_resolve_source_gaps可由gap_refs取实际Gap。修订应逐路径明确actual target来源/目标Mission核查及顺序，不能简单给这些方法都套self guard。已有明确task.mission_id不匹配拒绝的register_task则应保留其原约束和旧无Scope错误次序。

## 最小修订方向与验收要求

- 对可影响Mission/Task/Gap/WorkerOutput/Evaluation/Defect的受保方法，枚举实际目标Mission来源；在任何transition、输入对象修改、scheduler/planner、append/attestation前检查该目标raw row以及适用的输入Mission动态属性。只读获取目标identity可先行。
- 或明确拒绝与Control Mission不一致的目标，但需评审此额外旧legacy行为变化；不能未经说明把所有原本无Scope的跨目标旧行为都改掉。仅按保留键存在性拒绝目标Scope、不扩大到未知scope_ref/namespace，仍是本候选最小目的。
- 实现测试必须加入同release、self无Scope/target有Scope的上述两个实际成功fixture，以及相关task/gap目标变化，证实零目标事件/对象修改。目标有Scope时统一HOLD，不因为self无Scope或输入typed丢动态字段而漏检。

## 其他已核正确边界（不抵消P1）

三键顶层存在性、null/partial/full均HOLD而不调用tools codec/授绑定资格是可行最小保护。__init__组装scheduler/planner/session本身无R1业务append，但长存实例仍须每次重核。_reactivate_source_tasks/_resolve_source_gaps/_persist_gap等在其早期就会修改/append，不能只依赖末尾_mission。bootstrap需在asdict丢动态属性和attestation前检查；bank在读row后、graph/resume/refresh前检查。N1 dispatch须保留canonical batch/N1/精确Field-start只读先验，取得既有rc7 row后检查，且existing receipt RESUMED分支不能跳过。

候选已正确披露：直接scheduler/planner/session/raw append不封闭，跨进程/过期投影不具CAS，release driver/Field-start在dispatch前的副作用不能追溯承诺。JsonlEventStore.__init__实际touch(exist_ok=True)，bank构造会改变文件mtime，候选只保证内容字节/事实不变，不声称metadata全无变化。无需为负向保护先取得Host/Windows资格，但不能据此称完整writer已封闭或生产绑定已完成。

## 可重复临时R1探针

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission,Task,to_payload
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
reserved={'project_id','batch_id','scope_binding'}
with TemporaryDirectory() as tmp:
    truth=TruthRuntime(Path(tmp)/'r1')
    control=ClosedLoopControlPlane.bootstrap(truth,Mission(mission_id='M1',release_id='R',goal='controller'))
    target=Mission(mission_id='M2',release_id='R',goal='target')
    payload=to_payload(target);payload.update(project_id='P2',artifact_version=1)
    truth.append_atomic('RC7_MISSION_UPSERTED',payload)
    assert not reserved&set(control._mission_row())
    assert not reserved&set(vars(target))
    control._persist_mission(target)
    assert 'project_id' not in truth.query('rc7_mission',mission_id='M2')[0]
with TemporaryDirectory() as tmp:
    truth=TruthRuntime(Path(tmp)/'r1')
    first=ClosedLoopControlPlane.bootstrap(truth,Mission(mission_id='M1',release_id='R',goal='controller'))
    second=ClosedLoopControlPlane.bootstrap(truth,Mission(mission_id='M2',release_id='R',goal='target'))
    second.register_task(Task(task_id='T2',mission_id='M2',node='N1',task_type='TEST',objective='valid target'))
    assert second.lease_next(worker_ref='W',capabilities=[]).task_id=='T2'
    row=dict(truth.query('rc7_mission',mission_id='M2')[0]);row['project_id']='P2';row['artifact_version']+=1
    truth.append_atomic('RC7_MISSION_UPSERTED',row)
    assert truth.query('rc7_task',task_id='T2')[0]['state']=='LEASED'
    first.start('T2',worker_ref='W')
    assert truth.query('rc7_task',task_id='T2')[0]['state']=='RUNNING'
```

两例均独立实际运行成功，确认现有写入顺序及拟议self guard遗漏；不计未来保护的产品PASS。没有实施修复、没有使用真实生产R1或银行现场，原型/source/Windows资格不被转签。最终发布NOT_APPROVED。
