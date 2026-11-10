# F：紧凑Mission binding纯实现精确独立验收

被测PR：[209](https://github.com/TongAITech/opencode-test-digital-employee/pull/209)。完整实现源：`968430ed354bed17a9a726ea73617ac194082a7e`；批准设计源3266cb2d。F在独立`f-mission-binding-exact`核验，未参与实现/修复，没有修改被测代码/测试、08/09/10、正式model/reader/writer或R1；本提交仅F报告及审计复现脚本。

结论：**PURE_COMPACT_BINDING_COMPONENT_QA_ACCEPTED_EXACT_968430ED**。未发现阻断这个独立纯组件集成的问题。仅接受parse_scope、parse_mission_json、serialize_scope、require_unchanged的结构/片段/比较功能；设计#208不是本实现结果的替代，A集成后须在新联合HEAD回归。正式生产绑定、reader、factory/writer/PG/Host资格仍HOLD。

## 代码及范围核查

模块只用stdlib，不import正式models/overlay/control/reader/PG或Host，不分配运行身份、不打开/写R1。DTO只核受管域，ScopeIdentity保存canonical bytes而非调用者原dict引用；raw输出为新MappingProxy/tuple深不可变结构；serializer是新detached可修改片段而非整个Mission，legacy严格{}；compare是结构相等，不是CAS或写许可。

严格15/4/7字段、date/三revision/bool/digest、K/mapping/内外mission/release/project/batch镜像一致；null、partial、flat-only、缺镜像/冲突均拒绝，不能parse自动补镜像。公开NamedTuple构造不授权：serializer重新parse所携bytes并核内外身份，非法伪造拒绝；**自造的完整合法结构仍可成为结构片段，这不表示获得正式来源/Host/创建权威**。原operation_ref/零一digest只是结构值，不证明PREPARE或事件已发生。

数值域与3266设计一致：unknown outer有限float/exponent不入Scope比较/片段，raw全局重复key/非finite/非法Unicode策略只属于新helper，不修改旧正式reader；plain DTO不校验未知outer语义。当前正式模型/恢复链没有接入本模块，原绑定缺口并未因本验收解除。

## 本轮实际执行

本地Python3.9.6；没有用SQLite/模型答案/截图或旧设计签署替代实现oracle。

| 范围 | 实际结果 |
|---|---|
| 新binding标准测试 | 9/9，0.153秒，包含大量每字段subTest，不是只跑正向例 |
| 已签Scope codec回归 | 11/11，0.149秒；本地当前HEAD实际重跑 |
| F独立负向结构/状态检查 | **609次**预期拒绝均稳定BindingStructureError，无原生类型异常/非法接受；这些是数据检查次数，不伪装成609个unittest |
| F独立正向/不变性 | 完整709字节固定黄金向量、17个结构自洽却改变不可变域的拒绝、外层有限0.5/1e3/1e308及嵌套数据不入Scope、深不可变/脱离输入、serializer片段隔离通过 |
| F三个新进程 | 显式PYTHONHASHSEED=0/1/98765，compact canonical bytes逐字等于709字节固定黄金 |
| 现有正式validator兼容 | 对正式validate_rc7_mission生成/保留的完整legacy payload，未知outer0.5与1e3分别仍被新codec判LEGACY_UNBOUND、serializer{}，未知值与原输入保留；不是新生产创建 |
| 真实Python3.8/3.11 | [run42877117380](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42877117380)两job SUCCESS；实际Python3.8.18/3.11.18各9/9，0.071/0.043秒 |

该run虽是pull_request事件，workflow显式ref=head.sha；F核checkout日志及git rev-parse HEAD，**两个job均为完整968430ed354bed17a9a726ea73617ac194082a7e**，不是默认merge ref，也没有用旧源/AST语法检查转签版本资格。

### 609个独立预期拒绝检查的分母

受管字段错型312；缺/未知key58；镜像12；flat-only3；显式null1；公开tuple形状伪造40；有效JSON bytes内每个binding/K/mapping成员错型伪造130；tuple外层身份伪造2；结构自洽但变更不可变域17；legacy身份2和绑定转换2；raw全局7；严格数值21；Unicode身份1；禁I/O错误分支1。成功/失败输入均不被修改。

独立原子变化包括同时正确修改所有镜像的mission/release/project/batch/authority，确保不是仅因内部不一致才拒绝；actor/key/ref/历史date/三revision/两digest/map/op变化也必须在strict parse后触发IMMUTABLE_CONFLICT。legacy→legacy不能换outer身份，legacy↔bound不能以空绑定或结构完整绕过历史不变性。

raw额外反例包括未知outer嵌套对象重复key、NaN/±Infinity、指数溢出±1e309、非法surrogate键/值；合法emoji surrogate pair和全32控制字符规范编码、DEL/U+2028/U+2029/中文/斜杠原UTF8行为单独核验。组合/分解Unicode绑定ref不同而不被归一化。NamedTuple完全合法bytes可序列化为结构片段，恰好验证它是非权威DTO而不是安全能力令牌。

## 无副作用与未完成门禁

F在禁止builtins.open/os.open/socket.socket/socket.create_connection的条件下核成功和错误路径；独立纯审计进程没有加载rc6_runtime/rc7_runtime/psycopg。兼容探针另进程显式调用旧validator，仅内存数据，无R1/PG写入。未改变NodeGate/Human Gate/租约、旧legacy运行或现有reader，未删除历史B205/F204范围修订记录。

本轮无被测失败或需要F修复的实现问题。仅纯结构资格，不代表完整Scope来自真实PG、operation_ref有正式事件、原主体拥有Host动作权限或整条创建/恢复路径完成。正式typed模型接入、冻结增量、008、Host fence、单writer/CAS、真实factory/R1/HTTP链需后续独立签署与实测；真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER，最终发布NOT_APPROVED，不生成最终交付包。

## 重复执行

```sh
python3 -m unittest discover -s tests -p test_dsh_workbench_mission_scope_binding_codec.py -v
python3 -m unittest discover -s tests -p test_dsh_workbench_scope_snapshot_codec.py -v
```

下面为F独立审计脚本，从被测仓库根目录保存至临时文件运行；只用纯数据、标准库和被测module，不是产品功能实现。

## 附录：F独立结构/状态/黄金/纯度审计

```python
import copy,inspect,json,os,pathlib,socket,subprocess,sys
from unittest.mock import patch
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
from test_dsh_workbench_mission_scope_binding_codec import bound
from tools.dsh_workbench.mission_scope_binding_codec import BindingStructureError,ScopeIdentity,parse_scope,parse_mission_json,serialize_scope,require_unchanged

counts={}
def check(name,call,code=None):
 counts[name]=counts.get(name,0)+1
 try:call()
 except BindingStructureError as error:
  assert isinstance(error.code,str) and error.code==str(error)
  if code:assert error.code==code,(name,code,error.code)
 else:raise AssertionError((name,'unexpected acceptance'))
def walk(value,path=()):
 yield path,value
 if type(value) is dict:
  for key,item in value.items():yield from walk(item,path+(key,))
 elif type(value) is list:
  for key,item in enumerate(value):yield from walk(item,path+(key,))
def at(value,path):
 for key in path:value=value[key]
 return value

original=bound();before=copy.deepcopy(original)
golden=(b'{"access_scope_revision":3,"batch_id":"B1","binding_ref":"bind:1","creation_key_scope":{"actor_ref":"alice","creation_key":"k1","formal_authority_ref":"a1","project_id":"P1"},"creation_operation_ref":"op:1","date_revision":1,"mapping":{"batch_id":"B1","formal_authority_ref":"a1","mapping_policy":"ALLOCATE_NEW_RELEASE_V1","mapping_ref":"map:1","project_id":"P1","runtime_release_id":"RT1","schema_version":1},"mission_id":"M1","project_id":"P1","relation_revision":2,"release_date":"2026-11-11","request_digest":"'+b'1'*64+b'","schema_version":1,"scope_digest":"'+b'0'*64+b'","snapshot_ref":"snapshot:1"}')
scope=parse_scope(original);assert scope.binding_bytes==golden
assert serialize_scope(scope)=={key:original[key] for key in ['scope_binding','project_id','batch_id']}

# Every managed leaf/container: invalid nonhashables and numeric/null shapes on DTO and raw ports.
for path,value in list(walk(original)):
 for wrong in [[],{},None,True,1.25]:
  if type(wrong) is type(value):continue
  changed=copy.deepcopy(original)
  if path:at(changed,path[:-1])[path[-1]]=wrong
  else:changed=wrong
  unchanged=copy.deepcopy(changed)
  check('managed_wrong_type',lambda:parse_scope(changed))
  check('managed_wrong_type',lambda:parse_mission_json(json.dumps(changed)))
  assert changed==unchanged

# Missing/unknown object members are structural; bad mirrors are not silently filled.
for path,value in walk(original['scope_binding'],('scope_binding',)):
 if type(value) is not dict:continue
 for key in list(value)+['F_unknown']:
  changed=copy.deepcopy(original)
  if key=='F_unknown':at(changed,path)[key]='value'
  else:del at(changed,path)[key]
  check('strict_keys',lambda:parse_scope(changed))
  check('strict_keys',lambda:parse_mission_json(json.dumps(changed)))
for field in ['project_id','batch_id']:
 for wrong in [None,[],{},True,'foreign']:
  changed=bound();changed[field]=wrong;check('mirror',lambda:parse_scope(changed),'BINDING_MIRROR_CONFLICT')
 changed=bound();del changed[field];check('mirror',lambda:parse_scope(changed),'BINDING_MIRROR_CONFLICT')
for fields in [{'project_id':None},{'batch_id':'B1'},{'project_id':'P1','batch_id':'B1'}]:
 check('flat_only',lambda:parse_scope(dict(mission_id='M1',release_id='RT1',**fields)),'BINDING_FLAT_ONLY_UNQUALIFIED')
check('explicit_null',lambda:parse_scope(dict(mission_id='M1',release_id='RT1',scope_binding=None)),'BINDING_EXPLICIT_NULL')

# Valid but different immutable domains must reach conflict, not be accepted merely through self-consistency.
mutations=[]
def add(change):
 changed=bound();change(changed);mutations.append(changed)
add(lambda v:(v.update(mission_id='M2'),v['scope_binding'].update(mission_id='M2')))
add(lambda v:(v.update(release_id='RT2'),v['scope_binding']['mapping'].update(runtime_release_id='RT2')))
add(lambda v:(v.update(project_id='P2'),v['scope_binding'].update(project_id='P2'),v['scope_binding']['mapping'].update(project_id='P2'),v['scope_binding']['creation_key_scope'].update(project_id='P2')))
add(lambda v:(v.update(batch_id='B2'),v['scope_binding'].update(batch_id='B2'),v['scope_binding']['mapping'].update(batch_id='B2')))
add(lambda v:(v['scope_binding']['mapping'].update(formal_authority_ref='a2'),v['scope_binding']['creation_key_scope'].update(formal_authority_ref='a2')))
for field in ['binding_ref','snapshot_ref','creation_operation_ref']:
 add(lambda v,field=field:v['scope_binding'].update({field:'other'}))
for field in ['scope_digest','request_digest']:
 add(lambda v,field=field:v['scope_binding'].update({field:'f'*64}))
for field in ['date_revision','relation_revision','access_scope_revision']:
 add(lambda v,field=field:v['scope_binding'].update({field:99}))
add(lambda v:v['scope_binding'].update(release_date='2024-02-29'))
add(lambda v:v['scope_binding']['mapping'].update(mapping_ref='map:2'))
for field in ['actor_ref','creation_key']:
 add(lambda v,field=field:v['scope_binding']['creation_key_scope'].update({field:'other'}))
for changed in mutations:
 parse_scope(changed);check('immutable_valid_change',lambda:require_unchanged(original,changed),'BINDING_IMMUTABLE_CONFLICT')
legacy={'mission_id':'M1','release_id':'RT1'}
assert require_unchanged(legacy,dict(legacy,diagnostic_score=0.5))
for field in ['mission_id','release_id']:
 check('legacy_identity',lambda:require_unchanged(legacy,dict(legacy,**{field:'other'})),'BINDING_IMMUTABLE_CONFLICT')
check('legacy_transition',lambda:require_unchanged(legacy,original),'BINDING_IMMUTABLE_CONFLICT')
check('legacy_transition',lambda:require_unchanged(original,legacy),'BINDING_IMMUTABLE_CONFLICT')

# The public tuple is not authority and cannot bypass bytes/identity/structure validation.
for field,index in [('classification',0),('mission_id',1),('release_id',2),('binding_bytes',3)]:
 for wrong in [[],{},None,True,1.0,'unknown',b'null',b'[]',b'{',b'\xff']:
  values=['BOUND_STRUCTURAL_ONLY','M1','RT1',golden];values[index]=wrong
  check('forged_tuple',lambda:serialize_scope(ScopeIdentity(*values)))
for mission,release in [('other','RT1'),('M1','other')]:
 check('forged_identity',lambda:serialize_scope(ScopeIdentity('BOUND_STRUCTURAL_ONLY',mission,release,golden)),'BINDING_IDENTITY_CONFLICT')
assert serialize_scope(ScopeIdentity('BOUND_STRUCTURAL_ONLY','M1','RT1',golden))==serialize_scope(scope)
assert serialize_scope(ScopeIdentity('LEGACY_UNBOUND','M1','RT1',None))=={}
for path,object_value in walk(original['scope_binding']):
 if type(object_value) is not dict:continue
 for field in object_value:
  for wrong in [None,[],{},True,1.0]:
   inner=copy.deepcopy(original['scope_binding']);at(inner,path)[field]=wrong
   forged=ScopeIdentity('BOUND_STRUCTURAL_ONLY','M1','RT1',json.dumps(inner).encode())
   check('forged_valid_json',lambda:serialize_scope(forged))


# Numeric scope is strict; unknown outer finite numbers and nested values stay outside scope equality.
for token in ['0.5','1e3','1e308']:
 for value in [legacy,original]:
  raw=json.dumps(value)[:-1]+',"F_score":'+token+',"F_nested":{"items":['+token+']}}'
  parsed=parse_mission_json(raw);dto=json.loads(raw);saved=copy.deepcopy(dto)
  assert parsed.scope==parse_scope(value) and parsed.envelope['F_score']==float(token)
  assert parsed.envelope['F_nested']['items']==(float(token),)
  assert require_unchanged(value,dto);assert serialize_scope(parsed.scope)==serialize_scope(parse_scope(value));assert dto==saved
for raw in ['{"mission_id":"M","release_id":"R","F":1e309}','{"mission_id":"M","release_id":"R","F":-1e309}','{"F":NaN}','{"F":Infinity}','{"F":-Infinity}','{"mission_id":"M","release_id":"R","F":[{"x":1,"x":2}]}','{"mission_id":"M","release_id":"R","\\ud800":1}']:
 check('raw_global',lambda:parse_mission_json(raw),'MISSION_JSON_INVALID')
for token in ['1e0','1.0','true','false','0','-1','9223372036854775808']:
 for field in ['date_revision','relation_revision','access_scope_revision']:
  value=bound();old=json.dumps(value['scope_binding'][field]);raw=json.dumps(value).replace('"'+field+'": '+old,'"'+field+'": '+token)
  check('strict_numeric',lambda:parse_mission_json(raw),'BINDING_STRUCTURE_INVALID')
value=bound();value['scope_binding']['binding_ref']=' 中文 /\x7f\u2028\u2029😀\\"\x01\n '
assert json.loads(parse_scope(value).binding_bytes)['binding_ref']==value['scope_binding']['binding_ref']
composed=bound();decomposed=bound();composed['scope_binding']['binding_ref']='é';decomposed['scope_binding']['binding_ref']='e\u0301';check('unicode_identity',lambda:require_unchanged(composed,decomposed),'BINDING_IMMUTABLE_CONFLICT')
parsed=parse_mission_json(json.dumps(dict(original,F_nested={'items':[{'v':0.5}]})))
try:parsed.envelope['F_nested']['items'][0]['v']=3
except TypeError:pass
else:raise AssertionError('mutable raw output')
fragment=serialize_scope(scope);fragment['scope_binding']['mapping']['mapping_ref']='mutated';assert serialize_scope(scope)['scope_binding']['mapping']['mapping_ref']=='map:1'

# No runtime imports or side-effect primitives are needed for either success or structural failures.
def forbidden(*args,**kwargs):raise AssertionError('SIDE_EFFECT')
with patch('builtins.open',side_effect=forbidden),patch('os.open',side_effect=forbidden),patch('socket.socket',side_effect=forbidden),patch('socket.create_connection',side_effect=forbidden):
 parsed=parse_mission_json(json.dumps(original));serialize_scope(parsed.scope);require_unchanged(original,original)
 check('no_io_error',lambda:parse_scope({'mission_id':[],'release_id':'R'}),'MISSION_ENVELOPE_INVALID')
assert not any(name.startswith(('rc7_runtime','rc6_runtime','psycopg')) for name in sys.modules)
script='import sys;from tools.dsh_workbench.mission_scope_binding_codec import *;print(parse_mission_json(sys.stdin.buffer.read()).scope.binding_bytes.hex())'
outputs=[subprocess.check_output([sys.executable,'-c',script],input=json.dumps(original).encode(),env=dict(os.environ,PYTHONHASHSEED=seed)) for seed in ['0','1','98765']]
assert len(set(outputs))==1 and bytes.fromhex(outputs[0].decode())==golden
assert original==before
print('F independent compact-binding audit PASS',json.dumps(counts,sort_keys=True),'golden bytes',len(golden),'valid immutable changes',len(mutations),'hash-seed processes',len(outputs))
```
