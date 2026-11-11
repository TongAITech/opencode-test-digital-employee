# F：Scope 来源 profile 精确独立审查——两项配置资格 P1

被测 [PR #216](https://github.com/TongAITech/opencode-test-digital-employee/pull/216) 完整源 `f93e4ab17b7b4947990da3b0561d8979d6de65e4`；独立worktree `f-scope-policy-exact`，测试前后HEAD固定且干净。F未修改被测模块、manifest、测试、迁移、角色授权实现或08/09/10，本提交仅报告。

结论：**F_QA_REJECTED_EXACT_F93E4AB1 / TWO_P1_CONFIG_QUALIFICATION_GAPS**。正常17项PG用例和1项artifact测试通过，不能覆盖以下三条独立失败断言。当前不得记录该精确源无剩余P1接受；修复后以新完整SHA复验。这里不是已上线默认配置的越权漏洞声明，而是通过临时owner注入**资格探针本应识别的相关配置/能力漂移**后仍错误MATCHED。

## 实际执行与已正常工作的范围

环境实际PG **17.6**、Psycopg **3.2.13**，本机Python3.9，隔离Unix socket及每例临时数据库/非owner runtime，无SQLite、生产库、真实Host或Windows现场。

| F实际范围 | 结果 |
|---|---|
| `test_dsh_workbench_b_scope_policy_postgres.py` | 17/17，7.002秒；原F202额外RESTRICTIVE关系隐藏确实UNQUALIFIED，普通runtime MATCHED但admission_authorized=False，未知SELECT/ALL/其他role policy、字段/FK定义/RLS/源权限/function体/guard漂移、NOINHERIT owner、SET ROLE与SET SESSION AUTHORIZATION伪装、外层事务、真实timeout/闭连接/恢复等已覆盖 |
| `test_dsh_workbench_scope_profile_artifact.py` | 1/1，0.001秒；同ID改变manifest不能放宽批准模板 |
| F独立负例断言（附完整脚本） | **3项执行、3项失败**，1.057秒；均实际得到MATCHED_AS_OF而应UNQUALIFIED，分别覆盖P1-1能力/执行态和P1-2内部FK执行态；不计产品通过 |
| F202组合诊断 | 正常预览R1/SST1；额外关系级RESTRICTIVE后旧预览仍假UNSPLIT，但本新probe已正确UNQUALIFIED；删除后恢复MATCHED。这证明原目标的检测有效，不代表并发DDL fence完成 |

17+1通过不被称全验通过。F不借B的257项自测分母、远端PR merge checkout或旧报告给本源转签。所有DDL/参数GRANT只在F临时fixture数据库注入并finally恢复；负面INSERT在显式回滚事务内完成，最终坏行0。没有操作银行数据或修改产品实现。

## P1-1：角色可关闭来源 guard，当前replica执行态仍MATCHED

模块41–44行session字段只采row_security，没有session_replication_role；45–46/173–175行只看常见role旗标，没有保护参数的SET能力。实际owner对runtime执行：

```sql
GRANT SET ON PARAMETER session_replication_role TO <runtime>;
```

此时`has_parameter_privilege(current_user,'session_replication_role','SET')=true`，probe仍MATCHED且reasons=[]；再由真正runtime连接执行`SET session_replication_role=replica`，probe仍MATCHED。该状态不是其他backend伪装，current/session/backend角色全部正常runtime，原高权flag仍false。

F进一步在此runtime、项目alice合法RLS上下文的临时事务中实际插入不存在Requirement/Version/verified BRV的 `('P1','B1','F_NONEXIST_R','F_NONEXIST_V')`：行count=1，`release_batch.relation_revision`仍**7→7**。replica同时绕过O模式FK和来源revision触发器，profile却继续给MATCHED。随后F强制ROLLBACK并恢复origin/REVOKE，坏行count=0、正常MATCHED恢复。

因此这是可影响来源完整性和修订语义的**配置资格漏检**，不是仅理论参数建议。虽然结果admission_authorized=False，不自动授创建，但不能把带该能力/执行态的role判为批准的guard来源profile。

最小建议：只读采集/核对批准的session_replication_role值及当前role对相关参数的SET/ALTER SYSTEM能力（包括PUBLIC/继承的有效能力），未批准则UNQUALIFIED。不要通过SET origin临时掩盖实际输入会话，不授任何新权限；仍需单独role/DDL稳定性围栏解决检查后变化。

## P1-2：内部RI trigger禁用未改变FK定义，probe仍MATCHED

模块79–82行明确过滤`NOT t.tgisinternal`。F从实际catalog选取wb.batch_requirement_version的一条内部 `RI_ConstraintTrigger_c_*`，仅执行 `ALTER TABLE ... DISABLE TRIGGER <该触发器>`；外键对象及convalidated仍存在，用户revision/append-only trigger未改，probe继续MATCHED/reasons=[]。恢复ENABLE后正常MATCHED。

当前只比较复合FK的定义/validated标记不等于核实FK执行状态。该源profile宣称包含来源复合约束与guard资格，应拒绝这种已关闭部分来源FK执行的配置，而不能把它当未经实现的并发fence问题。

最小建议：将受支持来源FK对应的内部RI执行态纳入只读资格与固定预期，以constraint/关系/函数/事件等稳定身份规范化，不硬编码每库生成的RI trigger名称或OID；禁用/缺少/未批准执行态失败关闭。仍不绕RLS或读业务数据，不把约束资格当既有数据真实性证明。

## P2观察：未批准函数body原文会进入结果

F用非真实secret哨兵修改wb.allowed body；probe正确UNQUALIFIED，但完整返回facts.prosrc含该哨兵。未证明任何真实凭据泄露，也没有新HTTP接口；它是同角色本已可读的catalog文本。不过“结果绝不含secret”不能对任意未知函数文本无条件保证。建议未批准body输出hash/差异摘要，或明确仅内部敏感审计边界；不要把原始DDL函数体直接对外/入普通日志。此项不与上述两项实际P1混算。

## 可重复命令和F独立失败脚本

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_scope_policy_postgres.py -v
python3 -m unittest discover -s tests -p test_dsh_workbench_scope_profile_artifact.py -v
```

将下列独立审计脚本放临时路径，在固定worktree以相同PG DSN运行。它预期修复后全绿，但在被审f93源实际3条断言均失败；不修改或替换产品测试。

```python
import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path.cwd()));sys.path.insert(0,str(pathlib.Path.cwd()/'tests'))
import test_dsh_workbench_b_scope_policy_postgres as fixture
class QualificationGuard(unittest.TestCase):
 def setUp(self):
  self.case=fixture.ScopeSourcePolicyQualification(methodName='test_migrated_standard_runtime_matches_frozen_profile_without_business_reads');self.case.setUp();self.addCleanup(self.case.doCleanups);self.db=self.case.db
  self.assertEqual(self.case.result()['status'],'MATCHED_AS_OF')
 def test_parameter_set_capability_is_unqualified(self):
  role=fixture.infra.sql.Identifier(self.db.role)
  self.db.admin.execute(fixture.infra.sql.SQL('GRANT SET ON PARAMETER session_replication_role TO {}').format(role))
  try:
   self.assertTrue(self.db.runtime.execute("SELECT has_parameter_privilege(current_user,'session_replication_role','SET')").fetchone()[0])
   self.assertEqual(self.case.result()['status'],'UNQUALIFIED','role may bypass source trigger guards after a match')
  finally:self.db.admin.execute(fixture.infra.sql.SQL('REVOKE SET ON PARAMETER session_replication_role FROM {}').format(role))
 def test_active_replica_bypasses_fk_and_relation_revision_guard(self):
  d=self.db;role=fixture.infra.sql.Identifier(d.role);d.admin.execute(fixture.infra.sql.SQL('GRANT SET ON PARAMETER session_replication_role TO {}').format(role));d.runtime.execute('SET session_replication_role=replica')
  try:
   before=d.owner.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone()[0]
   try:
    with d.runtime.transaction():
     d.runtime.execute("SELECT set_config('wb.principal','alice',true)")
     d.runtime.execute("INSERT INTO wb.batch_requirement_version VALUES('P1','B1','F_NONEXIST_R','F_NONEXIST_V')")
     self.assertEqual(d.runtime.execute("SELECT count(*) FROM wb.batch_requirement_version WHERE requirement_id='F_NONEXIST_R'").fetchone()[0],1)
     self.assertEqual(d.runtime.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone()[0],before)
     raise RuntimeError('F_ROLLBACK')
   except RuntimeError as error:
    if str(error)!='F_ROLLBACK':raise
   self.assertEqual(d.owner.execute("SELECT count(*) FROM wb.batch_requirement_version WHERE requirement_id='F_NONEXIST_R'").fetchone()[0],0)
   self.assertEqual(self.case.result()['status'],'UNQUALIFIED','active replica currently disables O-mode guards')
  finally:d.runtime.execute('SET session_replication_role=origin');d.admin.execute(fixture.infra.sql.SQL('REVOKE SET ON PARAMETER session_replication_role FROM {}').format(role))
 def test_disabled_internal_fk_trigger_is_unqualified(self):
  row=self.db.owner.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='wb.batch_requirement_version'::regclass AND tgisinternal AND tgname LIKE 'RI_ConstraintTrigger_c_%' ORDER BY tgname LIMIT 1").fetchone()
  name=fixture.infra.sql.Identifier(row[0]);self.db.owner.execute(fixture.infra.sql.SQL('ALTER TABLE wb.batch_requirement_version DISABLE TRIGGER {}').format(name))
  try:self.assertEqual(self.case.result()['status'],'UNQUALIFIED','present convalidated FK does not prove its disabled RI trigger enforces it')
  finally:self.db.owner.execute(fixture.infra.sql.SQL('ALTER TABLE wb.batch_requirement_version ENABLE TRIGGER {}').format(name))
if __name__=='__main__':unittest.main(verbosity=2)

```

## 未验与门禁

只实际验PG17.6；其他PG major/patch、OS、Python版本、连接池认证方式及真实Host不沿用。profile即使修复后匹配也只是as-of catalog/role观察，仍无DDL/role fence、业务来源真实性、Host身份/创建权限或正式admission。最终锁定端口仍须新精确审查，真实DSH/Windows继续FIELD_NEEDS_BANK_TRANSFER，最终发布未批准。
