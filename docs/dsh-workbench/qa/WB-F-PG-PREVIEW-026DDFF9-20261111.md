# F：PG 完整来源只读预览精确独立验收

被测 [PR #199](https://github.com/TongAITech/opencode-test-digital-employee/pull/199)，完整源 `026ddff91a7b3177feeced5b597db7132818bcd0`。独立 worktree `f-pg-preview-exact`，测试前后 HEAD 相同且干净；没有修改被测实现/测试、08/09/10、迁移、R1 或权限。仅本报告新增。

结论：**COMPONENT_QA_ACCEPTED_PROJECT_ONLY_APPROVED_SCHEMA_EXACT_026DDFF9**。只接受已批准001–005来源表及001–007适用的 project-wide `wb.allowed(project_id,false)` 策略配置下的**内部只读预览组件**。这不是任意RLS配置、部署/银行资格、最终锁定快照、admission/verifier、008、正式创建或整体产品通过。未知/漂移schema和额外关系级RLS配置尚未资格；最终正式admission之前必须另有schema/策略资格证据及失败关闭，不能把本报告当成替代。

## 审查范围与实际执行

完整读取02业务模型、06 Scope/权限与真相边界及V3 `04ca971676509da9379ed53a29b495d2a32c325c`第1/3/7节；核查 `business_scope_preview.py`、BusinessStore._scope、001–005复合FK/身份来源/ACL和relation revision触发器。端口组合复用空闲autocommit连接保护，自持REPEATABLE READ READ ONLY，只SELECT和SET LOCAL，无HTTP入口、不继承写方法、无新schema/权限、不导入R1、不分配ID、不返回digest或创建许可。principal仍必须来自服务端可信身份，调用者DTO不构成权威。

真实环境：PostgreSQL **17.6**，Psycopg **3.2.13**，本机Python3.9，隔离Unix socket/临时数据库与非owner、NOBYPASSRLS运行角色；非SQLite。实际SELECT version()与库版本已核对。

| F实际范围 | 结果 |
|---|---|
| `test_dsh_workbench_b_scope_preview_postgres.py` | 17/17，5.586秒，0跳过；多需求/多版本/不同SST精确关系、UNSPLIT、筛选全ID覆盖、同业务ID跨项目隔离、ACL撤权恢复、八类来源/成员隐藏、SELECT权限缺失、外层事务拒绝/主体不串、READ ONLY/RR/临时配置归还、精确行/字节预算、真实statement_timeout取消/恢复、并发改期与来源同快照、闭连接恢复、原Unicode与无Python文件访问 |
| F独立组合测试 | 3/3，0.973秒，0跳过；见下面可复现脚本。实际PG→预览→codec四种整批/UNSPLIT/SST/version结构往返、audit未增加；21组不可hash/空/坏类型筛选与伪主体拒绝且同连接恢复；ACL在header后真实撤销，本次保持旧RR as-of、下一次403，重授后新ACL revision可见 |
| F额外RLS漂移故障诊断 | **成功复现不支持配置下的假UNSPLIT风险，不计产品通过**。详细如下 |

前两行共20项实际执行、20通过、0跳过；F未重跑B声称的240项全B回归，不将B自测或远端旧CI转成F分母。远端PR checks的W0与PG成功仅作辅助，F精确源结论来自本地固定HEAD实际执行。没有构建离线包、操作生产数据或真实Host。

组合测试使用的codec仅固定已存在工作区 `8618676ef83dd166c1c93ea483d1e2fd739578d5`；执行前实际核对该HEAD。四种PG来源分别规范化为1531/762/1000/1535字节并严格解析往返相等。它只证明两个DTO结构兼容，不对该codec发独立接受、不证明来源权限/最新修订或正式创建。另一F任务负责codec当前完整SHA验收。

## 必须保留的配置边界：关系行RLS隐藏

F在同一临时数据独立注入：

```sql
CREATE POLICY f_hide_relation ON wb.batch_requirement_version_sst
AS RESTRICTIVE FOR SELECT USING(false);
```

物理owner Oracle仍有 `(R1,V1,SST1)`，正常预览是 `[(R1,V1,SST1),(R2,V1,null)]`。注入后预览**成功**返回 `[(R1,V1,null),(R2,V1,null)]`；撤销该policy立即恢复。额外RESTRICTIVE policy隐藏整个BRV则422，不产生假空成功。代码LEFT JOIN在没有可见BRVS行时推UNSPLIT，无法区分“确实没有”与“被额外策略隐藏”。原17测试的八类来源/成员隐藏不能覆盖这条关系行缺口，不能称所有RLS漂移都失败关闭。

冻结迁移的实际关系表只有project-wide read_scope及写策略，没有逐BRVS读取授权语义。上述注入需要测试owner改DDL，超出当前已支持策略配置；因此本报告不把它夸大成正常默认配置的越权漏洞。A已明确本阶段不扩展额外关系级RLS，接受范围限已批准schema，且最终admission之前增加真实策略资格依赖。F据此保留本窄组件接受，同时**不接受未知/漂移配置的来源完整性或部署资格**。不得为修复此限制偷偷使用BYPASSRLS、owner绕读或新增未审权限。

正式提交仍需独立durable PREPARE、当前创建许可、受控持锁快照、Host撤权/append全序及封闭正式writer；本RR预览在ACL读后被撤销时允许返回旧as-of视图，实测下一次403。这是显式预览语义，绝不能把旧preview当当前创建许可。

## 可重复命令与独立脚本

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_scope_preview_postgres.py -v
```

以下F临时审计脚本可在精确worktree运行；不作为功能实现，不修改原测试。若codec工作区已更新，应先从上述固定8618676源导出模块后调整路径，不借新源转签。

```python
import sys,pathlib,importlib.util,unittest,copy
sys.path.insert(0,str(pathlib.Path.cwd()));sys.path.insert(0,str(pathlib.Path.cwd()/'tests'))
import test_dsh_workbench_b_scope_preview_postgres as fixture
from tools.dsh_workbench.business_scope_preview import ReadOnlyScopeSnapshotPreview
from tools.dsh_workbench.business_store import BusinessError
spec=importlib.util.spec_from_file_location('fcodec',str(pathlib.Path.cwd().parent/'e-scope-codec/tools/dsh_workbench/scope_snapshot_codec.py'));codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
class Independent(unittest.TestCase):
 def setUp(self):
  self.db=fixture.ScopeSnapshotPreview(methodName='test_full_real_source_shape_and_date_revisions_no_authority_or_business_writes');self.db.setUp();self.addCleanup(self.db.doCleanups)
 def test_true_database_sources_roundtrip_and_no_state_write(self):
  d=self.db.db;before=d.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0]
  for filters in [{},{'requirement_ids':['R2']},{'sst_ids':['SST1']},{'version_ids':['V1']}]:
   value=self.db.read(**filters);snap=value['snapshot'];raw=codec.canonical_scope_bytes(snap)
   self.assertEqual(codec.parse_snapshot_json(raw),snap)
   if filters.get('sst_ids'):self.assertTrue(all(e['sst_id']=='SST1' for e in snap['edges']))
   self.assertEqual(value['preview_state'],'READ_ONLY_SNAPSHOT_NOT_ADMISSION');self.assertNotIn('scope_digest',value)
  self.assertEqual(d.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0],before)
  self.assertEqual(d.runtime.info.transaction_status,0)
 def test_malformed_identity_and_filters_fail_recover_and_never_mutate(self):
  d=self.db.db;original=self.db.read();before=d.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0]
  for bad in [[],{},True,1,None,'','\ud800']:
   for key in ['requirement_ids','version_ids','sst_ids']:
    with self.assertRaises(BusinessError) as error:self.db.read(**{key:[bad]})
    self.assertEqual(error.exception.status,400)
    self.assertEqual(d.runtime.info.transaction_status,0)
  for actor in ['unknown',"alice' OR 1=1 --"]:
   with self.assertRaises(BusinessError) as error:self.db.preview.preview(actor,'P1','B1')
   self.assertEqual(error.exception.status,403)
  self.assertEqual(self.db.read(),original);self.assertEqual(d.owner.execute('SELECT count(*) FROM wb.audit').fetchone()[0],before)
 def test_revoke_after_snapshot_is_asof_only_then_fresh_read_denied(self):
  d=self.db.db;original=self.db.read()['snapshot'];raw=d.runtime
  class RevokeAfterHeader:
   fired=False
   def __getattr__(self,name):return getattr(raw,name)
   def execute(self,query,params=None):
    result=raw.execute(query,params)
    if 'SELECT b.release_date,b.revision' in query and not self.fired:
     self.fired=True;d.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
    return result
  value=ReadOnlyScopeSnapshotPreview(RevokeAfterHeader()).preview('alice','P1','B1')['snapshot']
  self.assertEqual(value,original)
  with self.assertRaises(BusinessError) as error:self.db.read()
  self.assertEqual(error.exception.status,403)
  d.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
  self.assertGreater(self.db.read()['snapshot']['access_scope_revision'],original['access_scope_revision'])
if __name__=='__main__':unittest.main(verbosity=2)

```

RLS诊断可使用同一fixture，先记owner物理关系与默认policy，再加入/撤除上面的RESTRICTIVE policy，比较返回身份。CREATE/DROP只用于临时审计数据库；业务audit分母在正常只读测试前后不变。

## 保留门禁

真实DSH/SSO、Windows离线、实际Agent Teams并发/资源恢复继续FIELD_NEEDS_BANK_TRANSFER。生产Mission绑定、正式控制命令及R1事实边界未因本预览解除。当前F组件接受不转签A新联合HEAD、SQL/锁端口或最终发布；由A正向集成并进行相应新联合回归。
