# F：SST筛选额外UNSPLIT旧源失败

PR：[195](https://github.com/TongAITech/opencode-test-digital-employee/pull/195)。被测完整源：`a9758687cae73f49d9b62e44f49e85625f0eea7c`。独立worktree`f-scope-codec-fix`固定该源；没有修改被测功能/测试、08/09/10或正式R1。本提交仅保留F历史失败报告。

结论：**COMPONENT_NOT_ACCEPTED_AT_A9758687 / P1_FILTERED_UNSPLIT**。旧c4的非hashable错误已经在本源消除，但以下新不变量失败仍阻断本源接受，不能用10项已有测试或Python版本CI覆盖它。后续修复须新完整SHA独立复验。

## 新P1及独立数据oracle

V3第1节明确“过滤SST时不得补虚拟UNSPLIT行”。当filters.sst_ids=['SST1']时，codec接受edges同时包含R1/V1/SST1和R2/V1/UNSPLIT；canonical_scope_bytes与parse_snapshot_json均成功返回，而额外UNSPLIT行不属于筛选。根因是过滤检查先用`if edge[column] is not None`从actual集合丢弃None，再只比较所选ID覆盖，没有逐边检查筛选成员。

这是结构/筛选一致性缺口，不是要求纯DTO替代数据库验证来源或授权。没有生产调用或正式R1写入；F不修被测代码。

最小复现：

```sh
PYTHONPATH=tests python3 - <<'PY'
import copy,json
from test_dsh_workbench_scope_snapshot_codec import snapshot
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes,parse_snapshot_json
value=snapshot();first=value['edges'][0]
first['sst_id']='SST1'
first['sst_source']=dict(first['requirement_source'],kind='SST_IDENTITY',source_object_id='sst1')
first['brvs_source']={'kind':'VERIFIED_SST_LINK','source_link_ref':'ref:sst1','verified_source_revision':'r1'}
other=copy.deepcopy(snapshot()['edges'][0]);other['requirement_id']='R2'
other['requirement_source']['source_object_id']='r2';other['requirement_source']['source_ref']='ref:r2'
other['brv_source']['source_link_ref']='ref:rv2'
value['edges'].append(other);value['filters']['sst_ids']=['SST1']
print(len(canonical_scope_bytes(value)))
print([(row['requirement_id'],row['sst_id']) for row in parse_snapshot_json(json.dumps(value))['edges']])
PY
```

实际：DTO返回1469字节；JSON入口仍返回[('R','SST1'),('R2',None)]。两入口均应拒绝这份筛选声明不一致的结构。

F另以真实PostgreSQL17.6既有Scope fixture读取完整来源字段，构造两边R1/V1/SST1、R2/V1/UNSPLIT：无筛选规范往返与输入不变通过；B06真实sst_ids=['SST1']查询仅返回R1/SST1。将同一实际二边输入声明sst_ids=['SST1']，本源DTO/JSON仍保留R2/None，实际负例拒绝0/2；人工保留合法一边后正向规范化通过。这证明错误位于pure筛选不变量，不是虚构数据库关系。该兼容性审计不是正式LockedScopeAdmissionTransaction或verified权限签署。

## 本源其他实测（不改变失败结论）

- 既有codec 10/10，0.163秒；41d2→a975仅证据两行，但F仍在a975精确新worktree实际重跑，没有转签。
- F独立逐字段矩阵：UNSPLIT/SPLIT两fixture，非hashable[]/{}共288次；扩展None/bool/float共492次，全部稳定ScopeStructureError(INVALID_SCOPE_STRUCTURE)，0原生异常、0非法接受，输入未变。原c4报告#197的失败在本源已消除。
- 完整黄金字节/固定摘要、跨进程（既有测试），以及F额外禁止open/os.open/socket调用、K/HOLD无回调、指数/负零/前导零/越界/bool、转义同名重复键、Unicode不归一化/合法emoji surrogate pair、DEL/U+2028/2029原字节等审计通过。
- 这些通过不能抵消新的SST筛选P1，也不证明纯codec具备Host、DB来源或生产创建权威。旧c4和本a975失败分别保留，后续新SHA另出独立结论。正式SQL/Host/writer/typed模型与发布门禁不变。
