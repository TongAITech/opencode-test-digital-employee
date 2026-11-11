# F：项目metadata纯协议codec精确独立验收

被测 [PR #236](https://github.com/TongAITech/opencode-test-digital-employee/pull/236)，完整源 `63ea53b13e931576955670dd96f2d5a334cd0242`。新独立worktree `f-project-metadata-codec-exact`，测试前后候选HEAD固定且干净；本提交随后只添加F报告，未改被测实现、测试、旧wire、SQL或08/09/10。

结论：**PURE_METADATA_PROTOCOL_COMPONENT_QA_ACCEPTED_EXACT_63EA53B1**。B230精确a21b82fe、A决策9a41b145及其限定设计下的纯语法/规范字节组件，未发现本范围P0/P1。此接受不签项目改名的数据库、命名域完整分母/治理、009 runner、并发锁序、权限/Host或UI产品功能；不将DTO/digest当admission、NO_CHANGE或提交回执。

## 实际读取与边界核查

读取B230完整命名候选、A M1决定、已集成限定设计审查与本组件证据，逐行核module和28项原测试。只有stdlib imports；没有HTTP/SQL/profile/R1/模型/Host接线。公开解析接收raw bytes与route project target；目标ID只入语法摘要，不能代表principal或namespace。body只允许request_id、两个expected revision、changes{name}、reason。未知authority/action字段拒绝。

名称策略固定project-name/utf8-exact-v1：先拒错UTF8/代理/C0/DEL，只trim两端U+0020；1–128 Unicode标量、≤512 UTF8字节，不casefold、不归一化，其余Unicode空白保持精确。128个合法标量最多512 UTF8字节，byte限在此域是防御冗余；不伪造“128标量但513字节”的不可能向量。reason按本协议允许JSON合法控制字符、保持原样且≤2048 UTF8字节，不能误套name控制码规则。

两个revision严格正十进制字符串1..9223372036854775807，既不JSON number也不JS浮点；request ID固定ASCII字符及长度。body16KiB按原始bytes计入JSON空白/转义。重复解码键（含转义等价与未知子树）、错types、数字/NaN/Infinity、坏Unicode/深JSON均稳定拒绝，错误str只含固定code，不反射原请求文本。

输出为仅immutable str字段的frozen/slotted语法DTO；name_key/canonical为不可变bytes。canonical包括固定schema/action/name_policy、route project、request ID、两原revision、规范name与原reason。JSON key顺序/空白/合法转义改变但规范payload相同，bytes/digest相同；project/action/revision/reason/request/name改变分域。公开body不能指定action；F对其它action的检查是独立改变golden canonical域并重算SHA，不是假称有公开任意action API。

## F本轮实际执行（不借B自测分母）

| 验证 | 实际结果 |
|---|---|
| 仓库`test_dsh_workbench_project_metadata_codec.py` | 本机Python3.9.6：**28/28，0.008秒，0跳过** |
| F独立纯函数矩阵（附脚本） | **6/6，0.171秒，0跳过**；无DB/网络业务调用 |
| 精确远端 [42894573262](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42894573262) | 两job SUCCESS。workflow显式PR head，F核checkout和Verify source实际输出均63ea53b1；实际Python **3.8.18：28/28（0.006秒）**、**3.11.18：28/28（0.008秒）**，不是AST检查或默认merge checkout转签 |

F新增覆盖：全部C0/DEL、128个emoji与U10FFFF最大标量/512byte边界、ASCIItrim和其它Unicode空白/大小写/组合字符/全角精确差异；raw16KiB含padding、坏UTF8/过长编码/代理、重复及转义等价key、深JSON；所有顶层字段与name的list/dict/None/bool/数字错误类型、两个bigint字符串及numeric token拒绝；request ID/reason长度、reason控制码原样保留；固定完整golden bytes与`8bb996f25ca9a73b9ea2f64bcebcf87b77afdee6614124ba62a2d5104e01e969`；公开action/namespace/principal拒绝，无NO_CHANGE/权限/committed字段；禁open/os.open/socket/Path.open环境中解析及重放不产生IO；连续错误后原有效DTO/bytes保持；两独立本机进程、不同PYTHONHASHSEED输出完全相同。

F新增6项只在本机Python3.9.6执行；不能把远端原28项说成同样跑过F临时6项。各层不合计成虚假的唯一用例数。本轮没有产品测试失败；未运行任何PG/SQL或现场实验。

## 可重复命令与独立脚本

```sh
python3 -m unittest discover -s tests -p test_dsh_workbench_project_metadata_codec.py -v
python3 /tmp/f_metadata_codec_independent.py
```

独立临时脚本仅用于F测试，本报告保留原文，不修改产品或替换其测试：

```python
import copy,dataclasses,hashlib,json,os,pathlib,socket,subprocess,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path.cwd()))
from tools.dsh_workbench import project_metadata_codec as c

def payload(**changes):
 value={'request_id':'f:rename-1','expected_metadata_revision':'1','expected_access_scope_revision':'2','changes':{'name':' 项目A '},'reason':'人工批准'};value.update(changes);return value

def raw(value):return json.dumps(value,ensure_ascii=True,separators=(',',':')).encode()

class FIndependentMetadataCodec(unittest.TestCase):
 def reject(self,body,project='p1'):
  with self.assertRaises(c.MetadataProtocolError) as error:c.parse_rename_request(body,project)
  self.assertEqual(str(error.exception),error.exception.code);self.assertNotIn('SENTINEL',str(error.exception))
 def test_unicode_policy_full_control_and_scalar_boundaries(self):
  for scalar in list(range(32))+[127]:self.reject(raw(payload(changes={'name':'A'+chr(scalar)})))
  for name in ['a'*128,'😀'*128,chr(0x10ffff)*128,'\u3000','\u00a0','\u200b']:
   parsed=c.parse_rename_request(raw(payload(changes={'name':' '+name+' '})),'p1');self.assertEqual(parsed.name,name);self.assertLessEqual(len(parsed.name_key),512)
  for name in ['', ' '*129,'x'*129,'😀'*129,'\ud800','\udfff','\ud800A','A\udfff']:
   self.reject(raw(payload(changes={'name':name})))
  for left,right in [('Alpha','alpha'),('é','e\u0301'),('A','\u00a0A\u00a0'),('A','Ａ')]:
   a=c.parse_rename_request(raw(payload(changes={'name':left})),'p1');b=c.parse_rename_request(raw(payload(changes={'name':right})),'p1');self.assertNotEqual(a.name_key,b.name_key);self.assertNotEqual(a.payload_digest,b.payload_digest)
 def test_raw_json_budget_duplicates_malformed_bytes_and_escaped_equivalence(self):
  body=raw(payload());self.assertLess(len(body),16384)
  c.parse_rename_request(b' '*(16384-len(body))+body,'p1');self.reject(b' '*(16385-len(body))+body)
  for body in [b'\xff',b'\xc0\x80',b'\xed\xa0\x80',b'\xf4\x90\x80\x80',b'\xef\xbb\xbf{}',b'{}x',b'['*2000+b']'*2000]:self.reject(body)
  body=raw(payload())
  for duplicate in [b',"request_id":"SENTINEL"}',b',"request\\u005fid":"SENTINEL"}',b',"unused":{"a":true,"a":false}}']:
   self.reject(body[:-1]+duplicate)
  self.reject(body.replace(b'"name":',b'"name":"SENTINEL","name":'))
  pair=raw(payload(changes={'name':'x'})).replace(b'"x"',b'"\\ud83d\\ude00"');self.assertEqual(c.parse_rename_request(pair,'p1').name,'😀')
 def test_nonhashable_and_wrong_types_stable_errors_and_revision_strings(self):
  malformed=[None,[],{},True,False,0,1,1.5]
  original=payload();body=raw(original)
  for field in original:
   for value in malformed:self.reject(raw(dict(original,**{field:value})))
  for value in malformed:self.reject(raw(payload(changes={'name':value})));self.reject(body,project=value)
  for value in malformed+['','0','00','01','+1','-1','١','１','1.0','1e0','1\n','1 ',' 1','9223372036854775808','9'*100]:
   for key in ['expected_metadata_revision','expected_access_scope_revision']:self.reject(raw(payload(**{key:value})))
  p=c.parse_rename_request(raw(payload(expected_metadata_revision='9223372036854775807',expected_access_scope_revision='9223372036854775807')),'p1');self.assertEqual(p.expected_metadata_revision,'9223372036854775807')
  for token in [b'1',b'1e1000',b'-1',b'0.0',b'NaN',b'Infinity']:
   self.reject(body.replace(b'"1"',token))
  self.assertEqual(payload(),original);self.assertEqual(raw(original),body)
 def test_request_id_reason_boundaries_and_no_business_decision(self):
  for id in ['a'*128,'.',':','_-.:Az09']:c.parse_rename_request(raw(payload(request_id=id)),'p1')
  for id in ['a'*129,'','x\n','项目','\ud800','A/B','A B']:self.reject(raw(payload(request_id=id)))
  reason='\x00\x01\n\r\t\x7f \u3000';request=c.parse_rename_request(raw(payload(reason=reason)),'p1');self.assertEqual(request.reason,reason)
  request=c.parse_rename_request(raw(payload(reason='😀'*512)),'p1');self.assertEqual(len(request.reason.encode()),2048)
  self.reject(raw(payload(reason='😀'*512+'a')))
  for name in ['principal','namespace_ref','no_change','authorized','committed','action']:self.reject(raw(dict(payload(),**{name:'SENTINEL'})))
  for name in ['principal','namespace','no_change','authorized','committed','admission']:self.assertFalse(hasattr(request,name))
 def test_immutable_golden_digest_replay_and_domain_isolation_with_no_io(self):
  value=payload(request_id='r1',changes={'name':' A '},reason='');original=copy.deepcopy(value)
  expected=b'{"action":"project.metadata.update/v1","changes":{"name":"A"},"expected_access_scope_revision":"2","expected_metadata_revision":"1","name_policy":"project-name/utf8-exact-v1","project_id":"p1","reason":"","request_id":"r1","schema":"dsh-workbench/project-metadata-request/v1"}'
  with patch('builtins.open',side_effect=AssertionError('FILE_IO')),patch('os.open',side_effect=AssertionError('OS_FILE_IO')),patch('socket.socket',side_effect=AssertionError('NETWORK_IO')),patch('pathlib.Path.open',side_effect=AssertionError('PATH_IO')):
   request=c.parse_rename_request(raw(value),'p1');self.assertEqual(request.canonical_bytes,expected);self.assertEqual(request.payload_digest,'8bb996f25ca9a73b9ea2f64bcebcf87b77afdee6614124ba62a2d5104e01e969')
   for field in dataclasses.fields(request):
    with self.assertRaises(dataclasses.FrozenInstanceError):setattr(request,field.name,[])
   self.assertFalse(hasattr(request,'__dict__'))
   for _ in range(10):
    self.reject(raw(dict(value,principal='SENTINEL')));replay=c.parse_rename_request(json.dumps(dict(reversed(list(value.items()))),ensure_ascii=True,indent=2).encode(),'p1');self.assertEqual(replay,request);self.assertEqual(replay.canonical_bytes,expected)
   canonical=json.loads(expected)
   for key,replacement in [('project_id','p2'),('action','other/v1'),('name_policy','other/v1'),('expected_metadata_revision','2'),('expected_access_scope_revision','3'),('reason','x'),('request_id','r2')]:
    changed=dict(canonical,**{key:replacement});encoded=json.dumps(changed,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();self.assertNotEqual(hashlib.sha256(encoded).hexdigest(),request.payload_digest)
   for changes in [dict(expected_metadata_revision='2'),dict(expected_access_scope_revision='3'),dict(reason='x'),dict(request_id='r2'),dict(changes={'name':'B'})]:self.assertNotEqual(c.parse_rename_request(raw(dict(value,**changes)),'p1').payload_digest,request.payload_digest)
   self.assertNotEqual(c.parse_rename_request(raw(value),'p2').payload_digest,request.payload_digest)
  self.assertEqual(value,original)
 def test_two_processes_and_hash_seeds_produce_identical_exact_replay(self):
  body=raw(payload());code="import pathlib,sys;sys.path.insert(0,str(pathlib.Path.cwd()));from tools.dsh_workbench.project_metadata_codec import parse_rename_request;r=parse_rename_request(bytes.fromhex(sys.argv[1]),'p1');print(r.canonical_bytes.hex());print(r.payload_digest)"
  results=[]
  for seed in ['1','231']:
   env=dict(os.environ,PYTHONHASHSEED=seed);results.append(subprocess.run([sys.executable,'-c',code,body.hex()],check=True,capture_output=True,text=True,env=env).stdout)
  self.assertEqual(results[0],results[1]);request=c.parse_rename_request(body,'p1');self.assertEqual(results[0].splitlines(),[request.canonical_bytes.hex(),request.payload_digest])
if __name__=='__main__':unittest.main(verbosity=2)

```

## 尚未实现的承载与实施门禁

此模块不查询当前DB值，故同名也不是NO_CHANGE；重放同canonical仅说明语法身份稳定，不证明已提交、原主体授权或原回执。完整namespace分母、NAMING_ACTIVE治理、不可见重复、RLS/最小DML、CAS/原结果、009依赖runner/回滚、Directory ABA及同K跨动作/FK KEY SHARE锁交错的真实PGOracle仍分别待审待实现；本报告不给SQL功能PASS。

协议允许reason包含NUL等JSON控制字符；未来PG若用text/jsonb必须明确无损承载/编码，不可盲目插入或静默改变已冻结pure wire。128标量的emoji可占JS UTF16 length256；未来C不能只靠maxlength128错误缩小服务端上限。这两点是后续SQL/UI适配条件，不是当前符合合同的codec缺陷。

旧HTTP/DB wire未变，没有项目创建、成员/namespace管理、R1或正式运行副作用。真实DSH/Windows/银行/离线仍FIELD_NEEDS_BANK_TRANSFER；A可正向集成纯组件并另验新联合HEAD，不跨SHA转签、不批准最终交付。
