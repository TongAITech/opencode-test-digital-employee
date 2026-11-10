# B：Scope project-only 来源配置只读资格快照

状态：CODE_COMPLETE / B_LOCAL_REGRESSION_PASS / F_REVIEW_REQUIRED。基线`199a316334abb41c77890ed5608b989e2a7e6126`；代码、测试、固定manifest与本证据同次冻结提交，完整HEAD以本PR为准。不修改Preview/ScopeStore、迁移、权限或现有HTTP，不将profile匹配当正式admission许可证。

## 接口、批准模板与实际边界

内部接口：`ReadOnlyScopeSourcePolicyQualification(connection).probe()`。要求空闲autocommit连接，自持REPEATABLE READ READ ONLY，只读pg_catalog与自身backend身份；SET LOCAL仅限本事务search_path/statement_timeout，不设置或替换wb.principal，不读业务行或R1，不执行GRANT/DDL/迁移/命令。

唯一已实现profile：`dsh.scope-source.project-only.pg17.001-007.v1`。固定manifest从**新建隔离PG17.6数据库、仓库已批准001–007迁移**提取，不是从被检查部署动态学习：13张Scope来源/ACL表的列、PK/FK/CHECK定义、SELECT/ALL policies、15个直接source revision/append-only triggers、5个直接guard函数及wb.allowed的属性/body；包含原7份up.sql SHA256。常量固定manifest规范JSON内容hash，单独改JSON同profile_id不能静默放宽批准模板。owner/OID不硬编码；运行时另外查真实owner、能力与继承。manifest只限此来源子集，不证明全WB资产表、全部写协议、数据来源真实性或完整迁移历史已合格。

真实17.6所见read_scope表达式为`wb.allowed(project_id, false)`，函数依赖为`wb.allowed(text,boolean)`；wb.allowed为SQL/STABLE/SECURITY DEFINER，固定`search_path=pg_catalog, wb`，PUBLIC EXECUTE已撤销。直接比较此固定定义，不用模糊regex把其他策略自动认成等价。函数body、相关类型/键/策略/触发器未知或漂移即不匹配。其他PG major返回UNQUALIFIED/无法完成，不猜pg_get_expr跨版本等价；实际现场/其他平台未验。

查询当前role/session role、**自身pg_stat_activity建连role**，拒绝切换/遮蔽高权建连身份、superuser/BYPASSRLS/CREATEDB/CREATEROLE/replication、迁移owner/可关联owner、wb schema/database DDL能力、未知成员角色、ACL列读写或verified-source写权限等超出此运行role profile的能力。NOINHERIT不被猜作无owner关系：实际pg_has_role MEMBER/USAGE分别检查，保守拒绝未批准membership。当前source有效SELECT与row_security必须存在/启用；额外RESTRICTIVE、permissive、ALL、甚至不适用于当前role的额外SELECT policy均视未知配置，不静默MATCH。

结果为`MATCHED_AS_OF`或`UNQUALIFIED`，带profile_id/profile_hash、as_of及其时钟来源、facts_hash、原因与实际catalog事实，**admission_authorized永远False**。查询超时/目录不可读/闭连接给不可完成UNQUALIFIED，明确客户端失败观察时钟，不能伪装数据库已完成快照；外层事务/构造错误直接拒绝。默认单语句5秒超时，不声称整个调用或建连≤5秒。

**TOCTOU：** 本模块没有schema/DDL/role围栏。MATCH只说明该次观察与模板匹配，检查结束后一条CREATE POLICY/GRANT/ALTER即可失效；facts_hash不签权限，也不验证Host或actor。最终admission仍须另审受控schema/DDL及role配置稳定性协议，在其围栏内重验全部资格/来源/当前主体动作。不能先probe一次再永久缓存为许可证，不能把此模块接到已有Preview旁边便宣称消除了并发DDL或正式Scope来源问题。此前F202的未知/漂移RLS依赖只得到一个可检测组件，并未被全局核销。

## 真实反例与测试结果

环境：本地官方源码PG17.6，Psycopg3.2.13；每例独立临时数据库/运行角色，非SQLite。实际迁移owner名字为`tatu`；未假设Docker的postgres用户名，manifest定义去owner/OID而运行时核其真实关系。

- 实际加入关系级RESTRICTIVE隐藏SST后，**未修改的旧ScopeStore**把已seed的R1/SST1显示为UNSPLIT；新probe明确UNQUALIFIED。删除策略后恢复SPLIT和MATCH。额外permissive/ALL/不适用角色policy同样拒绝，未“学习”新策略。
- 冻结前额外核查SET SESSION AUTHORIZATION：owner连接可使current_user=session_user都变成runtime，但仍能RESET回owner；只检查两者会误MATCH。真实PG17.6的system_user此时为NULL，不能猜它能证明原身份；自身pg_stat_activity.usename仍为原建连role。已修正三方检查并加真实专门反例，现拒绝此遮蔽。该候选发现/修复未当成发布产品通过。
- 真正NOINHERIT owner membership、表/列/复合FK缺失、RLS关闭/row_security off、wb.allowed body/SECURITY INVOKER/search_path/PUBLIC EXECUTE漂移、source SELECT缺失、ACL列写/verified-source INSERT/schema CREATE、BYPASS/owner、guard trigger/function漂移、外层事务不串主体、真实pg_sleep超时回滚/恢复、错误配置撤销回滚后仍拒绝、闭连接及重连均已覆盖。probe只执行只读catalog查询，当前设置与业务审计计数保持。

| 最终冻结代码内容实测 | 结果 |
|---|---|
| 新真实PG profile用例 | 17/17，9.910秒 |
| 全B真实PG集中回归 | 257/257，98.314秒，无跳过 |
| 轻量test_dsh_workbench*.py，无PG DSN | 612发现，285执行通过、327明确跳过，6.553秒；不是612实测通过 |
| 新纯artifact完整性用例 | 同ID但不同定义的manifest在任何DB调用前拒绝；计入轻量执行，不混算真实PG分母 |
| py_compile / git diff --check | 通过 |

manifest规范内容hash：`050442decb1813588b05f3e14c6771d1af7dfc526a4b71f5d1ededd0e72723d5`。冻结文件SHA256：模块`da03e1842faf3e0ee0bb76ac0f1417c5b0edd2e3d38f07dff1a59b248f1f62bb`；manifest原字节`b537b9b58e4ec3b8ca85575325e74198d2e6f0c3cd11f5087e7480a73933c1b9`；真实PG测试`c0623263bacea5e04221ebb6c374abe08c89a4218a750ad9ba6880fac8cd40f8`；纯artifact测试`6512303fa62bc925e3a3bd5fff0c03c9fefd947ecb700b65c11fad332ea8b91f`。内容hash允许JSON无语义格式/行尾差异；不允许改变批准定义。

命令：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_scope_policy_postgres.py -v
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py'
python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'
```

测试中的DDL/GRANT仅由隔离临时数据库fixture owner为正反例执行并恢复；生产probe自身没有这些行为或能力。没有新依赖/许可证变化，未改02/06冻结原文、08/09/10、R1或正式模型。待最新完整HEAD独立F验收；真实DSH/Windows继续FIELD_NEEDS_BANK_TRANSFER，最终发布未批准。
