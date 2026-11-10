# F：纯Scope codec精确修复复验

被测PR：[195](https://github.com/TongAITech/opencode-test-digital-employee/pull/195)。完整被测源：`8618676ef83dd166c1c93ea483d1e2fd739578d5`；独立worktree`f-scope-codec-filter-fix`。F未参与实现或修复，没有修改被测代码/测试、08/09/10、正式R1或冻结合同；本提交仅独立报告及内嵌审计复现脚本。

结论：**PURE_SCOPE_CODEC_COMPONENT_QA_ACCEPTED_EXACT_8618676E**。接受范围仅V3允许的纯Scope结构codec/规范字节和Scope摘要、不可变K工厂、默认无能力HOLD。A应在集成后验证新的联合HEAD；本结论不转签其他源码，不批准正式创建请求wire摘要、008、最终锁定PG端口、Host权限、writer或typed Mission/factory/R1事实变更。

## 历史失败保留及本源修复

- c4facd2c：非hashable sst_id先进入seen导致DTO/JSON原生TypeError，独立失败报告[PR #197](https://github.com/TongAITech/opencode-test-digital-employee/pull/197)，源仍保留COMPONENT_NOT_ACCEPTED。
- a9758687：SST筛选仍接受额外UNSPLIT，独立失败报告[PR #200](https://github.com/TongAITech/opencode-test-digital-employee/pull/200)，源仍保留COMPONENT_NOT_ACCEPTED；其已有10项/旧Python CI通过不消除该P1。
- 8618676e：sst_id非null先做文本验证；非空筛选除完整ID覆盖外，逐边都必须属于所选集合，因此SST的None也必须拒绝。F在新worktree从完整新HEAD重新执行，不把c4、a975或41d2结果转签。

## 本轮F实际执行

本地Python3.9.6；来源形状审计使用真实PostgreSQL17.6/Psycopg3.2.13和隔离业务fixture，不是SQLite。下表分母保持独立，数据检查次数不伪装成unittest用例数。

| 验证 | 实际结果 |
|---|---|
| test_dsh_workbench_scope_snapshot_codec.py | 11/11，0.170秒，含完整黄金向量、两个旧缺口回归、跨进程与失败输入不变 |
| F独立逐字段类型替换 | 非hashable[]/{} 288次；扩展None/bool/float 492次；DTO/JSON全部稳定ScopeStructureError(INVALID_SCOPE_STRUCTURE)，0原生异常/0非法接受，输入均未变 |
| F独立筛选/来源/边关系 | 28组合×DTO/JSON=56检查全部符合oracle；合法/非法情况见下节和附录 |
| F独立黄金/纯度/K/Unicode | 完整固定字节及digest；禁止open/os.open/socket调用时所有纯函数成功；K四槽32个非法值拒绝；HOLD不接参数/回调；数值词法、转义重复key、Unicode原样/emoji/不归一化通过 |
| F三个新进程 | 显式PYTHONHASHSEED=0/1/123456，完整规范字节及固定摘要逐字一致 |
| 真实PG来源形状/筛选对照 | 实际来源列构造2边R1/V1/SST1及R2/V1/UNSPLIT；未筛选规范往返成功且输入不变；B06实际SST筛选仅一边，codec拒绝仍含UNSPLIT的DTO/JSON 2/2，合法纯SPLIT一边通过 |
| 最终HEAD直接Python矩阵 | [workflow_dispatch run42873392914](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42873392914)，head=8618676e，实际Python3.8.18/3.11.18两job SUCCESS、各11/11（0.066/0.037秒），checkout日志完整SHA匹配；不是AST检查或旧源转签 |

远端PR merge预检不被当作最终源直接checkout证据。F另触发workflow_dispatch固定8618676e；实际head和解释器证据以该run为准，未引用旧a975的10项结果替代。

### 独立组合oracle

28组合覆盖：UNSPLIT未筛选、不同BRV混合未筛选、同BRV多个SST、不同需求共享版本但SST不同、经结构允许的两需求共享同SST、不同版本同raw来源但不同内部SST ID；需求/版本/SST完整筛选、缺ID/额外未选边；显式SST筛选额外UNSPLIT拒绝；同需求/版本/BRV/SST身份来源矛盾、版本对应系统冲突、跨版本复用内部SST ID、同BRV SPLIT与UNSPLIT并存、重复边、自报verified键均拒绝。只核结构不变量，不把tag或普通DTO当成真实来源/Host授权。

纯度审计额外验证：全黄金固定摘要`86048f9023f4d38a02b0a90c748630d78aa3aae33af78895d3e00874ce6e0e99`；指数、负零/前导零/正号、bool、NaN/Infinity和超bigint拒绝；转义为同名的重复JSON键拒绝；保留前后空格、斜杠、DEL/U+2028/U+2029/emoji原字节，组合/分解Unicode产生不同摘要；合法JSON surrogate pair解为emoji，非法surrogate拒绝。模块不导入psycopg或R1，未定义未冻结的创建请求wire摘要，K与HOLD都不授任何创建权限。

## 范围限制及接续

实际PG字段shape兼容只是读取已有fixture列后构造普通DTO，不是最终LockedScopeAdmissionTransaction、权威verifier或真实生产Scope绑定。没有008、Host fence、writer或正式typed模型改动；没有以SQL/Host现场作为纯函数先决条件，也没有因pure通过解除正式合同门禁。原正式创建/refresh绑定缺口仍未修复。

本轮11项和独立审计均通过，无新阻断发现；两个旧失败没有删除/改称通过。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER，最终产品/发布NOT_APPROVED，不生成最终交付包。以下附录为F可重复审计脚本，只作隔离验证，不是产品实现。

## 重复执行

```sh
python3 -m unittest discover -s tests -p test_dsh_workbench_scope_snapshot_codec.py -v
```

附录脚本保存至临时文件后从被测仓库根目录运行；真实PG脚本另需WB_PG_TEST_DSN与Psycopg环境，fixture结束清理其隔离schema。

## 附录A：逐字段类型拒绝矩阵

```python
import copy,json,os,sys
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
from test_dsh_workbench_scope_snapshot_codec import snapshot
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes,parse_snapshot_json,ScopeStructureError
values=[snapshot(),snapshot()];edge=values[1]['edges'][0];edge['sst_id']='T';edge['sst_source']=dict(edge['requirement_source'],kind='SST_IDENTITY');edge['brvs_source']={'kind':'VERIFIED_SST_LINK','source_link_ref':'link','verified_source_revision':'r'}
def walk(value,path=()):
 yield path,value
 if type(value) is dict:
  for key,item in value.items():yield from walk(item,path+(key,))
 elif type(value) is list:
  for key,item in enumerate(value):yield from walk(item,path+(key,))
counts={'nonhashable':0,'extended':0}
for group,replacements in [('nonhashable',[[],{}]),('extended',[None,True,1.25])]:
 for index,base in enumerate(values):
  for path,original in walk(base):
   for bad in replacements:
    if type(original) is type(bad):continue
    value=copy.deepcopy(base)
    if path:
     target=value
     for part in path[:-1]:target=target[part]
     target[path[-1]]=bad
    else:value=bad
    before=copy.deepcopy(value)
    for name,call in [('DTO',lambda:canonical_scope_bytes(value)),('JSON',lambda:parse_snapshot_json(json.dumps(value)))]:
     counts[group]+=1
     try:call()
     except ScopeStructureError as error:assert str(error)=='INVALID_SCOPE_STRUCTURE'
     else:raise AssertionError((group,index,path,name,'unexpected accept'))
    assert value==before
print('F field matrix stable rejection/input unchanged PASS',counts)
```

## 附录B：筛选/来源/边关系组合

```python
import copy,json,os,sys
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
from test_dsh_workbench_scope_snapshot_codec import snapshot
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes,parse_snapshot_json,ScopeStructureError
def split(edge,sst='T1'):
 edge=copy.deepcopy(edge);edge['sst_id']=sst;edge['sst_source']=dict(edge['requirement_source'],kind='SST_IDENTITY',source_object_id='raw-sst',source_ref='ref:sst');edge['brvs_source']={'kind':'VERIFIED_SST_LINK','source_link_ref':'ref:'+sst,'verified_source_revision':'r1'};return edge
def requirement(edge,identity):
 edge=copy.deepcopy(edge);edge['requirement_id']=identity;edge['requirement_source']['source_object_id']=identity;edge['requirement_source']['source_ref']='ref:'+identity;edge['brv_source']['source_link_ref']='ref:brv:'+identity;return edge
base=snapshot();mixed=snapshot();mixed['edges']=[split(base['edges'][0]),requirement(base['edges'][0],'R2')]
two_sst=snapshot();two_sst['edges']=[split(base['edges'][0],'T1'),split(base['edges'][0],'T2')];two_sst['edges'][1]['sst_source']['source_object_id']='raw-sst2'
two_req=snapshot();two_req['edges']=[split(base['edges'][0]),requirement(split(base['edges'][0],'T2'),'R2')];two_req['edges'][1]['sst_source']['source_object_id']='raw-sst2'
shared_sst=snapshot();shared_sst['edges']=[split(base['edges'][0]),requirement(split(base['edges'][0]),'R2')]
two_version=copy.deepcopy(two_sst);two_version['edges'][1]['version_id']='V2';two_version['edges'][1]['version_source']['source_object_id']='raw-version2';two_version['edges'][1]['sst_source']['source_object_id']='raw-sst'
cases=[('UNSPLIT unfiltered',base,True),('mixed BRVs unfiltered',mixed,True),('one BRV multiple SST',two_sst,True),('shared version different SST',two_req,True),('verified shared SST across requirements',shared_sst,True),('same raw SST origin across versions with distinct internal IDs',two_version,True)]
for field,selected in [('requirement_ids',['R','R2']),('version_ids',['V']),('sst_ids',['T1'])]:
 value=copy.deepcopy(mixed);value['filters'][field]=selected;cases.append(('mixed filter '+field,value,field!='sst_ids'))
for field,selected in [('requirement_ids',['R']),('version_ids',['V']),('sst_ids',['T1','T2'])]:
 value=copy.deepcopy(two_sst);value['filters'][field]=selected;cases.append(('complete split filter '+field,value,True))
for field,selected in [('requirement_ids',['MISSING']),('version_ids',['MISSING']),('sst_ids',['MISSING']),('sst_ids',['T1','MISSING'])]:
 value=copy.deepcopy(two_sst);value['filters'][field]=selected;cases.append(('missing filter coverage '+field+str(selected),value,False))
value=copy.deepcopy(two_req);value['filters']['requirement_ids']=['R'];cases.append(('extra unselected requirement',value,False))
value=copy.deepcopy(two_version);value['filters']['version_ids']=['V'];cases.append(('extra unselected version',value,False))
value=copy.deepcopy(two_sst);value['filters']['sst_ids']=['T1'];cases.append(('extra unselected SST',value,False))
for model,field in [(two_version,'requirement_source'),(two_req,'version_source'),(two_sst,'brv_source'),(shared_sst,'sst_source')]:
 value=copy.deepcopy(model);value['edges'][1][field]['source_revision']='changed';cases.append(('same identity conflicting '+field,value,False))
value=copy.deepcopy(two_sst);value['edges'][1]['system_id']='different';cases.append(('version system conflict',value,False))
value=copy.deepcopy(two_version);value['edges'][1]['sst_id']='T1';cases.append(('project SST internal ID reused in other version',value,False))
value=copy.deepcopy(mixed);value['edges'][1]=copy.deepcopy(base['edges'][0]);cases.append(('same BRV split plus UNSPLIT',value,False))
value=copy.deepcopy(two_req);value['edges'].append(copy.deepcopy(value['edges'][0]));cases.append(('duplicate exact edge',value,False))
value=copy.deepcopy(base);value['edges'][0]['verified']=True;cases.append(('self asserted verified authority key',value,False))
count=0
for name,value,want in cases:
 before=copy.deepcopy(value)
 for port,call in [('DTO',lambda:canonical_scope_bytes(value)),('JSON',lambda:parse_snapshot_json(json.dumps(value)))]:
  try:call();accepted=True
  except ScopeStructureError:accepted=False
  assert accepted==want,(name,port,want,accepted)
  count+=1
 assert value==before
print('F filter/source/relation matrix PASS',len(cases),'cases',count,'DTO/JSON checks; input unchanged')
```

## 附录C：纯度/K/Unicode反例

```python
import copy,inspect,json,os,socket,sys
from unittest.mock import patch
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
from test_dsh_workbench_scope_snapshot_codec import snapshot,GOLDEN
from tools.dsh_workbench.scope_snapshot_codec import *
base=snapshot();original=copy.deepcopy(base)
def forbidden(*args,**kwargs):raise AssertionError('SIDE_EFFECT')
with patch('builtins.open',side_effect=forbidden),patch('os.open',side_effect=forbidden),patch('socket.socket',side_effect=forbidden),patch('socket.create_connection',side_effect=forbidden):
 assert canonical_scope_bytes(base)==GOLDEN
 assert canonical_scope_bytes(parse_snapshot_json(GOLDEN))==GOLDEN
 assert scope_digest(base)=='86048f9023f4d38a02b0a90c748630d78aa3aae33af78895d3e00874ce6e0e99'
 assert tuple(creation_key('A','alice','P','K'))==('A','alice','P','K')
 hold=unavailable_host_admission();assert tuple(hold)==('HOLD','HOST_CAPABILITY_UNAVAILABLE');assert not inspect.signature(unavailable_host_admission).parameters
assert base==original
for token in [b'1E+0',b'-0',b'01',b'+1',b'true',b'false',b'-Infinity',b'NaN',b'9223372036854775808']:
 raw=GOLDEN.replace(b'"date_revision":1',b'"date_revision":'+token)
 try:parse_snapshot_json(raw)
 except ScopeStructureError:pass
 else:raise AssertionError(token)
raw=GOLDEN.replace(b'"project_id":',b'"\\u0070roject_id":"P","project_id":')
try:parse_snapshot_json(raw)
except ScopeStructureError:pass
else:raise AssertionError('escaped duplicate')
value=snapshot();value['project_id']=' P /\x7f\u2028\u2029😀';encoded=canonical_scope_bytes(value);assert b'/' in encoded and '\x7f\u2028\u2029😀'.encode() in encoded;assert json.loads(encoded)['project_id']==value['project_id']
a=snapshot();b=snapshot();a['project_id']='é';b['project_id']='e\u0301';assert scope_digest(a)!=scope_digest(b)
emoji=GOLDEN.replace(b'"project_id":"P"',b'"project_id":"\\ud83d\\ude00"');assert parse_snapshot_json(emoji)['project_id']=='😀'
assert not {'psycopg','rc6_runtime.truth'}&set(sys.modules)
for index in range(4):
 for bad in [[],{},None,True,1,1.25,'','\ud800']:
  values=['A','alice','P','K'];values[index]=bad
  try:creation_key(*values)
  except ScopeStructureError:pass
  else:raise AssertionError((index,type(bad).__name__))
print('F independent golden/digest/no-I/O/K/HOLD/numeric/Unicode/escaped-duplicate audit PASS; K bad fields 32/32')
```

## 附录D：真实PG来源字段与SST筛选对照

```python
import copy,json,os,sys
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes,parse_snapshot_json,scope_digest,ScopeStructureError
case=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors');case.setUp()
try:
 case.scope_seed()
 rows=case.owner.execute('''SELECT jsonb_build_object(
 'requirement_id',brv.requirement_id,'system_id',v.system_id,'version_id',brv.version_id,'sst_id',b.sst_id,
 'requirement_source',jsonb_build_object('kind','REQUIREMENT_IDENTITY','source_system',r.source_system,'source_namespace',r.source_namespace,'source_object_id',r.source_object_id,'source_revision',r.source_revision,'source_ref',r.source_ref),
 'version_source',jsonb_build_object('kind','SYSTEM_VERSION_IDENTITY','source_system',v.source_system,'source_namespace',v.source_namespace,'source_object_id',v.source_object_id,'source_revision',v.source_revision),
 'brv_source',jsonb_build_object('kind','VERIFIED_REQUIREMENT_VERSION','source_link_ref',rv.source_link_ref,'source_revision',rv.source_revision),
 'sst_source',CASE WHEN b.sst_id IS NULL THEN NULL ELSE jsonb_build_object('kind','SST_IDENTITY','source_system',s.source_system,'source_namespace',s.source_namespace,'source_object_id',s.source_object_id,'source_revision',s.source_revision,'source_ref',s.source_ref) END,
 'brvs_source',CASE WHEN b.sst_id IS NULL THEN NULL ELSE jsonb_build_object('kind','VERIFIED_SST_LINK','source_link_ref',sl.source_link_ref,'verified_source_revision',sl.verified_source_revision) END)
 FROM wb.batch_requirement_version brv
 JOIN wb.verified_requirement_version rv USING(project_id,batch_id,requirement_id,version_id)
 JOIN wb.batch_requirement br USING(project_id,batch_id,requirement_id)
 JOIN wb.batch_version bv USING(project_id,batch_id,version_id)
 JOIN wb.requirement r USING(project_id,requirement_id)
 JOIN wb.system_version v USING(project_id,version_id)
 LEFT JOIN wb.batch_requirement_version_sst b USING(project_id,batch_id,requirement_id,version_id)
 LEFT JOIN wb.verified_sst_link sl USING(project_id,batch_id,requirement_id,version_id,sst_id)
 LEFT JOIN wb.sst_identity s ON s.project_id=brv.project_id AND s.version_id=brv.version_id AND s.sst_id=b.sst_id
 WHERE brv.project_id='P1' AND brv.batch_id='B1' ORDER BY brv.requirement_id''').fetchall()
 date,revision,relation=case.owner.execute("SELECT release_date,revision,relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone();access=case.owner.execute("SELECT access_scope_revision FROM wb.project WHERE project_id='P1'").fetchone()[0]
 value={'schema_version':1,'project_id':'P1','batch_id':'B1','release_date':str(date),'date_revision':revision,'relation_revision':relation,'access_scope_revision':access,'filters':{'requirement_ids':[],'version_ids':[],'sst_ids':[]},'edges':[row[0] for row in rows]};before=copy.deepcopy(value)
 encoded=canonical_scope_bytes(value);assert canonical_scope_bytes(parse_snapshot_json(encoded))==encoded;assert value==before
 assert {(r['requirement_id'],r['version_id'],r['sst_id']) for r in value['edges']}=={('R1','V1','SST1'),('R2','V1',None)}
 assert len(scope_digest(value))==64
 print('PG source-shape unfiltered PASS',len(rows),'actual edges')
 oracle=case.scope.scope('alice','P1','B1',sst_ids=['SST1'])['records'];assert [(r['requirement_id'],r['sst_id']) for r in oracle]==[('R1','SST1')]
 bad=copy.deepcopy(value);bad['filters']['sst_ids']=['SST1'];rejections=0
 for name,call in [('DTO',lambda:canonical_scope_bytes(bad)),('JSON',lambda:parse_snapshot_json(json.dumps(bad)))]:
  try:call()
  except ScopeStructureError:rejections+=1;print('PG filtered extra UNSPLIT correctly rejected',name)
  else:print('BUG PG filtered extra UNSPLIT accepted',name)
 good=copy.deepcopy(bad);good['edges']=[r for r in good['edges'] if r['sst_id']=='SST1'];canonical_scope_bytes(good)
 assert rejections==2
 print('PG positive filtered one-edge PASS; negative rejections',rejections,'of 2')
finally:case.doCleanups()
```
