# B07六类业务草稿组件扩展

基线76d6d9c8（B07 milestone49063661及E02联合路由已接受后）；独立worktree wb-b07-kinds / work/dsh-wb-b07-kinds。来源合同22fc88ff与既有D/E设计签署保持，未新增正式R1验证接口，不修改08/09/10/R1。

实现case_draft、obligation_draft、defect_note、report_draft、knowledge、meeting_minutes，复用已接受的root/current revision、CAS、原响应幂等、合法BRV/BRVS Scope、权限/RLS、审计/outbox、退役恢复、历史读与Host写授权/CSRF门禁。milestone原接口与历史数据保持兼容；不是UI/现场/全部B07发布验收。

## 严格内容形状

| kind | payload允许字段 | 必需内容 |
|---|---|---|
| case_draft | preconditions:string[]、steps:string[]、expected_results:string[]、oracle_notes:string | steps与expected_results非空 |
| obligation_draft | business_rule:string、scenario:string、oracle_notes:string | business_rule与scenario非空 |
| defect_note | reproduction_notes:string、expected_notes:string、actual_notes:string | 三者非空；只是候选记录，不确认缺陷 |
| report_draft | body:string、tags:string[] | body非空；不生成正式报告 |
| knowledge | body:string、tags:string[] | body非空 |
| meeting_minutes | body:string、tags:string[] | body非空 |

未知或嵌套对象/正式facts字段拒绝400，步骤/前置/预期仅扁平字符串数组，不能装入执行结果对象。普通文本每项最多8192字符；列表最多100项，tags最多30项/每项128字符；payload总UTF8上限49152 bytes，HTTP整体64KiB门禁仍有效。NUL/无效Unicode、缺必填内容及错误类型拒绝。正文写PASS仅人工文本，不被解释为Oracle或正式状态。

全部草稿仍只有ACTIVE/RETIRED业务可见状态。新kind响应r1_reference_state固定UNRESOLVED；不提供客户端verified/R1 payload参数，不写Mission/Case/Obligation/Attempt/Defect/Report/Evidence/NodeGate。milestone旧NOT_LINKED保留兼容且不表示已验证；真实R1映射仍须后续E最小身份/谱系验证接缝，当前没有该接口，不伪造STALE或已验证事实。

## 存储与接口

migration007新增不可变asset_payload表，复合PK/FK绑定同一project/batch/asset/revision；版本kind只能是评审的七个枚举。新增kind的due_date必须NULL，不伪造里程碑日期。payload须同事务随版本完整创建，PG CHECK验证kind专属字段/必需内容/类型/边界，延迟约束验证payload与版本kind一致；无payload或向旧milestone补JSON均失败。表禁止UPDATE/DELETE，PK阻止历史新增第二份payload。

不回写既有milestone版本：其原DATE/description/owner字段继续提供同一响应。007是增量表与约束，不更改006校验和、已接受历史Scope计数或旧审计。迁移owner显式migrate(target=7)，runtime执行007_draft_kinds.runtime.sql；非空新payload自动降级HOLD，空payload降到006保留现存milestone并可重新升级。

复用`projects/{p}/batches/{b}/assets`的POST/PATCH/DELETE/restore/GET。GET kind=枚举精确过滤；不传kind列出全部已实现草稿，due_from/to仅milestone允许（不传kind而使用due范围时兼容推断milestone）。签名cursor绑定kind、Scope和双修订/资产水位，不能跨kind续页。PATCH payload按允许字段合并，kind永远不可变；历史/退役读取仍受当前权限。

## 真实验证与已知边界

```
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

新增DraftKinds测试类47项=milestone及B01–B06继承41项+6个新增测试方法；新增方法内逐六kind测试真实CRUD/幂等原响应/历史/退役恢复、真实HTTP创建与kind查询、复杂JSON/正式facts负例、Scope非法SST/撤权、payload故障回滚与恢复、DB payload类型/不可变历史、非空迁移HOLD、保留milestone的空表降级与重升级。首次007 PL/pgSQL CASE条件解析失败真实暴露并修复括号，后47/47已真实通过；完整联合回归/同源CI与F独立结果需另验，不搬用旧源数字。

FIELD_NEEDS_BANK_TRANSFER：Host/Origin/CSRF使用已声明fixture；真实DSH/Windows/离线/业务来源与正式R1验证映射必须搬运行内验收。未扩大正式事实边界，未实现自动草稿提升、正式缺陷资格或正式报告生成。

实现联合真实PG188/188通过；随后补无效Unicode零副作用例与HTTP严格Unicode/过深JSON拒绝，定向2/2通过。最终新增类48项（7新增+41继承），完整总数应189，必须以最终源CI/F实际结果为准，不将此前188沿用为新源数字。轻量此前522发现/257明确跳过，仅265实际合同；不等于真实PG验收。

固定前另补DB跨版本kind不可变触发器，拒绝绕开PATCH allowlist直接把case_draft改成knowledge；攻击/六kind完整生命周期/保留milestone降级定向3/3通过。最终DraftKinds49项=8新增+41继承，预计联合190项，以最终同SHA CI/F实测为准。
