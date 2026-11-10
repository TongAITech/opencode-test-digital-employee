# D 未准入 Scope HOLD 真实目标域精确复签

被审：[PR #212](https://github.com/TongAITech/opencode-test-digital-employee/pull/212)，完整新源 **`9623f30c1baf81d1a78490cca373689e42ceed80`**。对照旧源 `ce6add35` 及D失败报告 `898098d2`（含a934初报告），新独立 worktree `d-scope-hold-recheck` 从本源建立；不修改候选或运行实现。

结论：**D_HOLD_TARGET_DESIGN_ACCEPTED_AT_9623F30C / D_HOLD_01_DESIGN_RESOLVED / NO_NEW_D_P0_P1 / NOT_PRODUCTION_BINDING_OR_CLOSED_WRITER**。

D接受仅本次明确冻结的负向行为增量进入独立实现：三reserved键存在的未准入Mission，在列出入口首业务副作用前HOLD；完全无Scope旧legacy及其有效跨目标可达行为保留；目标无法解析时按本源明示新增的TARGET_UNRESOLVED HOLD处理。真实Host/Windows不可达不阻断这一负向保护。实际实现仍需B/E/F相应精确审查与测试，本文不授已实现或运行QA_PASS。

## 旧P1在设计上已修复

新§2.1明确优先于上表“当前row”简写，T包括self、输入/稳定ID指向的实际拟写目标，以及被覆盖旧对象所属Mission；先只读收集**全部T**并核raw Mission三键，完成后才准transition、scheduler/planner、append/attestation或输入对象原地修改。

旧两例A.start(Scoped B.TB)及A._persist_mission(旧typed B)被明确列入受保，不能移到raw/direct scheduler残余。Task真实所属、输入Mission目标旧row、同ID旧对象归属都必须核验，故不能再以A无Scope/input vars无Scope放行。_sync必须在改lists前完成；_persist_gap须含incoming及同gap_id旧row的双归属；output须在第一个Evidence前全检所有Artifact/Evidence新旧所属；evaluation/source-reactivation/planner多目标不得逐个写后才发现后续Scope。

这消除了旧D-HOLD-01所指的self-only设计漏洞。旧源实际反例仍保留为历史失败；新源尚未实现guard，不能把设计修订当这两项产品测试已经通过。

## 实际planner/回调与只读目标可确定性

已再次逐分支核Control及control_plane.py：

- TaskScheduler.start/output以稳定task_id读取旧Task；output的Evidence/Artifact输入数组及同ID旧row可预先只读核。refresh/lease依赖Mission任务集合、输入有效性与能力匹配；新规范明确一次性capabilities物化后计划/执行复用，不能重复消费改变选中项。
- GapRouter.route是runtime内确定性路由，普通repair task_id由mission/gap/target稳定计算；product-defect repro/qualification ID由mission/gap及读取所得source_artifact_id稳定计算。其资格来源读取可只读完成，已有派生Task旧归属可查。未发现列内真实分支必须先调用外部执行/Host callback或先append，才能知道其写入目标。
- 现有GapRepairPlanner.plan确实会先transition/persist gap再创建派生Task；**不能调用这个有副作用的方法来“预览”目标**。新规范已允许runtime内只读收集/计划步骤或在Control边界复用稳定ID规则。实施必须固定物化输入、只读资格结果和确定性目标集，并用有效分支测试证明没有漏目标，不是仅以helper名称表示保证。
- 若实际实施发现某分支无法无副作用确定目标，已明示TARGET_UNRESOLVED并在首写前HOLD；不能半写后再扩T。未来列内新增可写分支须同样审阅；本审阅不把假想Attempt写入加入当前模型。直接Attempt执行等不在本单内。

这些是源码可实现性判断，不是实际read-only planner已实现的证明，也不授跨进程原子性。任意调用者自带Python monkeypatch/带副作用回调不是新增授权能力；实现不得主动引入这种扩展来绕开只读预检约束。

## 兼容域与错误优先清楚

- 仅Mission顶层project_id/batch_id/scope_binding键存在触发，null/false/空/完整均同HOLD；不扩展scope_ref、namespace或无关诊断，不递归扫描任意outer extra。不用tools codec解析“完整就可准入”，无PG/Host依赖。
- 既有missing task、owner mismatch、register_task身份不一致等若在零副作用前能确定，允许保留原错误；不以无效fixture先触发旧错误冒充保护。没有新增所有foreign Control目标一概拒绝规则。
- 不能解析/不唯一/归属矛盾且旧零副作用错误尚不能决定的实际写目标，明示新增MISSION_SCOPE_TARGET_UNRESOLVED，不猜成self或legacy。仅合法new bootstrap在确无旧row且输入无reserved时可沿旧创建；普通persist无此例外。
- 批量已解析集合不能空/漏目标后按“全部unbound”成功；要先证明实际会写的目标域。对正常全unbound旧路径和原错误分母必须完整回归；实施不得为简化收集而暗改legacy wire、路由、租约或状态机。

## 原边界保持，不冒充权限或全写端封闭

本helper是负向拒绝，不是Host主体/来源许可，不新增metadata/业务Scope读取，也不替代公共Workbench reader的身份先于明细隔离。N1原canonical batch/N1/精确Field-start与Q7检查可以先行保留；不得为了触发guard伪造PASS或删除资格前置。dispatch即使有existing receipt也需守目标检查，不自动RESUMED。

bank的mkdir/TruthRuntime/store.touch仍可能触及mtime/目录metadata，承诺仅bytes/hash及业务projection/任务/租约/资源无新增；不是文件元数据零变。driver/Field-start在dispatch之前已写的合法事实不由dispatch拒绝回滚，测试以该入口调用前基线判断；不能宣称整个driver.run零副作用。

同一Runtime当前投影之外的并发/stale projection、direct scheduler/planner/sessions/raw append等残余仍明确排除；本单不关闭它们，不给全writer/CAS/Host fence或正式绑定创建准入。不能抹Scope、换ID或写一个假HOLD事件来“恢复”。

## 本次证据

完整读ce6→9623的文档及审计证据，按实际Control、TaskScheduler、GapRepairPlanner、GapRouter和既有bank/N1/driver/store调用顺序复核。PR212 HEAD核对为9623f30c，RC7.2远端edaf9290；两源runtime目录无diff。工具正常，没有额度错误。

本轮只有设计变化，没有重跑旧反例或旧回归数字并转签成新guard PASS，也没有运行不存在的产品实现。新实现必须兑现候选全目标有效输入测试、bytes/projection/输入对象零改、长存/cold、多目标最后一项Scope、旧全unbound跨目标、旧错误和TARGET_UNRESOLVED分母；F须对完整实现SHA独立验收。

只新增本独立报告，不改候选、代码、冻结原文或08–10；不代签B/E/F。此明确负向行为增量可继续施工，正式生产绑定/全writer/行内现场仍各自独立门禁。
