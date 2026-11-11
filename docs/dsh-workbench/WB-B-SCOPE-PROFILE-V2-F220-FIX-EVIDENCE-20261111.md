# B：F220两项配置资格P1修复候选

状态：CODE_COMPLETE / B_LOCAL_REGRESSION_PASS / F_RECHECK_REQUIRED。承接PR216历史源`f93e4ab17b7b4947990da3b0561d8979d6de65e4`；F220报告源`cb76c165fe92767df3e0e63028ea730f8ba7f7e1`明确拒绝该旧源。本次在原分支正常追加，代码/测试/固定manifest/本证据同次冻结新HEAD；未reset/force push，未改A主台账、正式模型、迁移、已接受Preview或ScopeStore。B自测不代签F。

## 先确认原红测试，不把条件或分母移动

完整读取F220报告及其独立Python脚本。在修改前的f93原样提取脚本至临时路径运行：**3执行、3失败，1.088秒**；分别是SET能力仍MATCH、replica态仍MATCH（坏BRV可插、relation_revision 7→7、强制回滚后坏行0）、内部RI trigger禁用但FK仍convalidated时仍MATCH。均是资格组件应识别的真实配置漏检，不改称并发fence残余，也不把原17项通过当全验。

当前代码原样重跑该F脚本：3/3通过，1.277秒。这是**B复跑F原反例**，不是F新独立接受；旧f93和F拒绝报告保留。

## P1-1：当前执行态、有效参数权限与可SET ROLE渠道

实际PG17.6接口已核为`has_parameter_privilege(name/oid,text,text)`与`pg_has_role(...,'USAGE'/'SET')`，不从rolreplication/superuser推测参数能力。新增只读观察：

- `session_replication_role`必须严格origin；即使SET能力已撤销但backend仍replica，也UNQUALIFIED。probe不SET origin或掩盖当前会话。
- 当前role对该参数的有效SET、ALTER SYSTEM任一能力都拒绝；由PG自身有效权限函数解析直接/PUBLIC/继承，不自行猜ACL规则，也不执行ALTER SYSTEM。
- 额外membership仍属未批准profile；另记录USAGE、SET ROLE和该role的参数权限。NOINHERIT但可SET ROLE的潜在参数渠道明确拒绝；真实测试先以helper设replica、RESET ROLE回runtime，GUC仍在，当前role自身没有SET也不能MATCH。SET FALSE对照按实际结果识别，不把每个MEMBER都说成可SET ROLE。
- PUBLIC参数ACL是cluster级。PUBLIC语义测试在**同一未提交事务**中GRANT、SET LOCAL ROLE至runtime并调用相同只读权限helper，观察SET/ALTER SYSTEM均True；另一个真正runtime连接同时仍False。事务强制ROLLBACK后正常MATCH，未向共享测试cluster提交PUBLIC授权；未假称在非IDLE事务运行了正式probe。

这些能力只影响资格拒绝，不授新权限。所有测试授权仅给唯一临时role并finally撤销；坏业务行只存在于显式回滚事务，最终0。

## P1-2：Scope-touching FK的真实内部执行trigger

不再用FK定义/convalidated代替执行态。新固定V2 manifest来自全新001–007迁移fixture，包含22个触及13张来源/ACL表的FK所需**88条**内部RI执行trigger。按逻辑constraint源/目标表与定义、trigger所在/关联表、事件type、执行mode、deferrable、函数schema/name/参数/语言/返回type和参数hash归一化；**没有数据库生成trigger名或OID**。LEFT JOIN保留缺失观察，数量/重复/缺失/函数或事件形状/mode与固定模板不同均拒绝，不运行时学习当前坏库。

实际分别禁用child check与parent action内部RI trigger，FK对象与convalidated仍在，新probe都UNQUALIFIED；R/A模式也不自动认成批准O模式，恢复ENABLE后MATCH。另建独立数据库，其实际`RI_ConstraintTrigger_*`名称不同，但规范列表完全相同、两库正常MATCH，验证没有固定某库OID或自动名称。这里只核配置执行形状，不检查已有业务行真实性，不因恢复配置就证明历史数据已清理。

## P2：函数body结果改为hash，不回传源码

已批准/未知的allowed及直接guard函数body统一只在返回facts中保留body_sha256；固定manifest也只保存批准body hash。比较仍基于实际body，未知假哨兵修改会UNQUALIFIED，返回序列化结果不含哨兵/prosrc，facts_hash可从脱敏后的返回facts重算。哨兵不是真实secret，未宣称发现凭据泄漏；其他任意DDL/policy/名称metadata仍可能包含操作者写入的文本，不能承诺所有metadata无敏感信息，结果仍仅内部审计边界，非新增HTTP。

## 固定profile、实际回归与局限

新profile_id为`dsh.scope-source.project-only.pg17.001-007.v2`，规范内容hash `161c779c3fe956364fd381573f356fdc43fef98fbec8edb84e2706f64588d898`，与代码常量一起冻结。来源001–007原文件hash保持；同ID放宽参数policy或删RI期望行也在任何DB调用前拒绝。不是将坏配置收进模板。

| 最终代码内容实测 | 结果 |
|---|---|
| F220原样脚本：旧f93→本修复 | 3失败→3通过，1.088秒→1.277秒；B复跑 |
| 原真实PG profile用例 | 17/17，11.187秒 |
| 新真实PG参数/RI/body边界 | 10/10，4.575秒 |
| 全B真实PG集中回归 | 267/267，103.524秒，无跳过 |
| 固定artifact纯测试 | 2/2，0.016秒；不混入真实PG分母 |
| 轻量test_dsh_workbench*.py，无PG DSN | 623发现，286执行通过、337明确跳过，6.686秒；不能写623项实际通过 |
| py_compile / git diff --check | 通过 |

最终实现文件SHA256：模块`4d00e1422b494825e26c7255edd25063fa496f0b0f8b2f5d61dc795f8f9b6d32`；manifest原字节`d4b88c94480987a9dbe60b4ae6a4945ab3c9c51c9aa977acb116ae86dae8f75a`；原17PG测试`74ef729e343161fda71c89846a2b04ed05298afa8abaa193b34a483d03e763de`；新10PG测试`6c371b4f6d022974eae4512f5aac549acd6e73281bbcc44ea4740cd2e12c4d1b`；artifact测试`64634b34c29f74bb59d9c934c4ed20908935a87621bf3957d385775cb01da0cc`。

命令：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python /tmp/dsh-f220-replay.py
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b_scope_policy*postgres.py' -v
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py'
python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'
```

生产probe仍只有只读catalog观察及事务局部search_path/timeout，未新增grant/policy/migration，不写业务事实/R1；admission_authorized仍永远False。没有DDL/role/参数稳定性围栏，检查后配置可变，MATCHED_AS_OF不能缓存成许可证；最终admission须在另审的稳定性协议内重验。只实测PG17.6及对应本地环境，不沿用为真实Host/Windows/银行资格。待新完整SHA独立F复验，最终发布未批准。
