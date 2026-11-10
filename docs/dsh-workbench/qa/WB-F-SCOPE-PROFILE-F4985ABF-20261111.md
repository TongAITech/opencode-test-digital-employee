# F：Scope 来源 profile 修复窄范围独立复验

被审 [PR #216](https://github.com/TongAITech/opencode-test-digital-employee/pull/216) 精确源：`f4985abf93d35b94fdcacd2193e65808e5d9816b`。新独立worktree `f-scope-policy-fix`；测试前后被测HEAD固定且干净。本提交随后只加报告，未修改候选模块、manifest、测试、功能、迁移或08/09/10。

结论：**NARROW_COMPONENT_QA_ACCEPTED_EXACT_F4985ABF**。在本轮明确缩窄的“只读源码/固定manifest审查 + 仓库已有自动化回归”范围内，F220的两项配置校验遗漏已明确修复，已有对应回归实际通过，未发现阻断该只读检测组件集成的新P0/P1。原f93e4ab1的F220失败报告保留，不倒写为通过。此结论不称为新增权限攻击面验证、任意角色图穷尽、部署资格、全WB、Host或正式admission通过。

## 本轮实际授权范围与分母

按A后续窄任务执行：只审本仓库修复代码、固定批准模板、现有测试，并在本机已有隔离PostgreSQL测试环境运行**仓库已有自动化测试**。未新设计/执行临时权限或数据修改探针，未重跑F220临时三红脚本，未访问外部目标。仓库已有测试本身包含隔离fixture的角色/DDL/回滚事务；本报告不将它们描述成“完全没有SQL变更”，也不将B作者先前执行结果当作F本轮结果。

| F实际执行 | 结果与精确范围 |
|---|---|
| 本地既有PG17.6 / Psycopg3.2.13，`test_dsh_workbench_b_scope_policy*.py` | **27/27，12.537秒，0跳过**；包含原17 profile与新增10 guard回归 |
| 本地 `test_dsh_workbench_scope_profile_artifact.py` | **2/2，0.013秒**；同ID改变manifest/参数规则/RI期望不能放宽批准模板 |
| 固定manifest只读重算 | v2规范内容hash与代码常量一致，`161c779c3fe956364fd381573f356fdc43fef98fbec8edb84e2706f64588d898`；88条规范RI记录，无物理触发器名称/OID键 |
| F触发精确branch `workflow_dispatch` PG | [42889306617](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42889306617) SUCCESS；实际checkout `git log -1` 为f4985abf；**267/267，68.991秒**。Ubuntu/Python3.11、postgres:17服务，未另核remote具体PG patch |
| F触发精确branch `workflow_dispatch` W0 | [42889313022](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42889313022) SUCCESS；实际checkout `git log -1` 为f4985abf；**623发现、286执行通过、337明确跳过，6.300秒** |

原PR成功checks使用默认PR merge checkout，不被当成精确候选HEAD证据；因此F另外触发并核实上述两个dispatch实际checkout日志。各层分母分别记录，不能相加宣称唯一测试数，也不能把337跳过称通过。

## 两项旧P1的实现与现有回归核对

**F220 P1-1：replication执行态及能力。** 新`_parameter_capabilities`直接读取当前`session_replication_role`，通过PostgreSQL有效权限函数读SET/ALTER SYSTEM；非origin、当前可用参数能力均UNQUALIFIED。membership同时记录USAGE、SET角色路径与目标role参数能力；能够SET到有相关能力的role有独立拒绝原因，所有未知membership仍保守拒绝。因此NOINHERIT、SET FALSE或ADMIN等会员通道不被默认为无风险，也不把当前role无直接SET能力等同不存在潜在角色路径。

已有新增回归实际覆盖：origin但获SET授权、实际replica及非法BRV/修订绕过后显式回滚、保留replica但撤去grant、ALTER SYSTEM能力、PUBLIC有效权限（仅未提交事务helper实测，不提交集群PUBLIC权限）、继承权限、NOINHERIT后SET/RESET携带GUC，以及SET FALSE后仍拒绝未知membership。没有实际执行ALTER SYSTEM，也没有在本轮另设计ADMIN角色图实验；相关保守拒绝判断来自只读源码核对，不能夸大为任意权限图的动态穷尽证明。

**F220 P1-2：内部FK执行态。** 新catalog单独读取触及Scope表的FK及内部RI，规范化保留逻辑constraint/source/target/trigger关系、函数/事件/deferrable/mode与参数hash，保留重复记录；不依赖跨库生成的物理RI名称或OID。与固定88条模板严格比较，缺失或禁用/REPLICA/ALWAYS模式都不会因FK仍convalidated而误MATCH。已有回归实际切换child检查及parent action执行态并拒绝，两个新建测试数据库物理名称不同但规范事实相同，正常runtime匹配恢复。

本轮没有重新执行F220临时负例脚本；上述是新候选的**现有仓库回归**实际执行及实现分支核对，旧实验的历史失败不移用成新源测试分母。

## 其他兼容与诊断边界

原profile回归继续实际通过：F202未知关系级RESTRICTIVE政策、额外permissive/ALL/其他role SELECT漂移拒绝；RLS关闭、字段/复合约束/来源权限/函数安全属性、owner/NOINHERIT/切角色/原建连身份遮蔽、timeout/闭连接/外层事务及设置恢复。当前正常runtime不被新条件误拒。固定模板不从部署学习，修改同profile_id的JSON定义在任何DB调用前拒绝。

P2函数正文观察已修：内部仍按批准body hash比较，返回facts对allowed/support函数只含body_sha256，删除prosrc；已有哨兵测试及facts_hash可重算回归通过。不把这称为任意catalog文本的通用secret扫描或全库脱敏证明；当前没有新增外部HTTP输出。probe实现不读取连接密码、Host token、业务行或R1；仓库测试fixture对自身资料的读取和回滚写入范围已在上文单独说明。

## 复现命令

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b_scope_policy*.py' -v
python3 -m unittest discover -s tests -p test_dsh_workbench_scope_profile_artifact.py -v
```

## 保留实施门禁

只接受PG17/001–007 Scope来源profile v2的**只读as-of检测组件**。任何MATCHED_AS_OF均`admission_authorized=False`，不是当前或未来DDL/role稳定性的保证；检查后可改变配置，最终受控admission仍必须在另审DDL/角色围栏内重验。未在本轮执行新增临时SQL、任意权限/ADMIN图、其它PG major/patch、Windows、连接池身份方式或真实DSH现场测试；未审全数据库能力或数据真实性。

A需正向集成并对新联合HEAD做相应回归；本报告不向其它SHA转签，不批准正式绑定/命令、008、Host、离线交付或最终发布。真实现场继续FIELD_NEEDS_BANK_TRANSFER。
