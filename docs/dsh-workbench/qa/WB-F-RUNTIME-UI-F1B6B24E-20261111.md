# F：只读运行界面精确独立验收

被测PR：[189](https://github.com/TongAITech/opencode-test-digital-employee/pull/189)。完整被测源：`f1b6b24e233bae2adb43d2ae60dc84cfb6523c53`。独立worktree：`f-runtime-ui-exact`。F没有参与被测实现/修复，没有修改被测源、现有测试、08/09/10或正式合同。本提交只增加独立审查报告及内嵌审计复现脚本。

结论：**READONLY_RUNTIME_UI_COMPONENT_QA_ACCEPTED_EXACT_F1B6B24E**。未发现阻断该只读组件集成的问题，由A集成后回归新联合HEAD；不转签当前A HEAD，不核销完整C06、正式Mission创建/执行命令/SSE、生产数据绑定、真实Host/SSO或Windows现场发布。

## 合同与实现检查

已读05/06运行/API边界、E01 B06消费与PG/HTTP/R1组件合同、E02只读图及既有跨Mission lineage修复说明、runtime-client/runtime-panel、同源Host服务路由、E01/E02服务和lineage校验、Scope切换与UI持久化代码，以及本PR差异和测试。

客户端只请求graph/workitems/quality三个同源GET；不传客户端principal、不调用legacy端点、无创建/执行/审批控制。三响应全部成功且project/batch/date/Mission、双revision、R1字节摘要及source_refs集合一致后整组发布；Promise.all失败、Scope/Mission变更、离开视图/Abort后不发布旧组。返回快照深度冻结。非空需求/版本/SST筛选拒绝整批次API，不假装做了子集筛选。服务端E02仍是正式授权与完整lineage检查的所有者，UI结构校验不取代它。

N1–N10缺失节点明确为未记录，不推PASS；NodeGate展示原始决策。Evidence只展示ID/声明哈希/完整性状态，不提供任意file引用打开能力。HASH_VERIFIED_ONLY只表示文件字节哈希匹配；整体投产决定强制HOLD，人工批准UNKNOWN_NOT_QUERIED。没有将快照、Mission ID或凭据写入local/session storage；原应用只持久化界面偏好。

## 本轮F实际结果

本地PostgreSQL17.6/Psycopg3.2.13、真实HTTP和Chromium。R1为持久**synthetic fixture**：Mission的project/batch绑定由测试显式添加，正式typed创建缺口仍未解决；fixture里的Gate/Evidence不是银行实际执行或验收证据。

| 验证 | 实际结果 |
|---|---|
| Node所有test_dsh_workbench*.mjs | 117/117，0跳过，含26项只读运行客户端正反例 |
| 新runtime浏览器独立单跑 | 1/1，5.424秒；真实PG授权/同源三API/持久synthetic R1 |
| tests/browser/test*.py整轮回归 | 8/8，35.963秒，包含上一行runtime用例，不重复算作额外独立功能分母 |
| F独立组合审计（附录） | 1/1，4.886秒；下节列出数据oracle |

首轮F临时组合夹具为Evidence事件漏传release_id，正式R1 validator在任何HTTP/UI测试开始前拒绝MISSING_OR_INVALID_RELEASE_ID（0.325秒）。保留此失败记录，按正式结构仅修正临时fixture后重跑通过；未修改被测实现、正式validator或降低断言。该失败不伪装成产品修复通过。

### 独立组合反例

- 真实PG Scope授权后，R1 fixture含一条实际读取的工作项、N1原始NOT_STARTED、原始NodeGate PASS与受控文件正确sha256的Evidence。浏览器同时展示工作项、Gate记录与HASH_VERIFIED_ONLY，整体仍HOLD/人工未查询。375px文档无横向溢出，英文说明明确not business acceptance。
- 仅暂挂workitems真实HTTP响应交付，另外两腿已成功时无部分/旧表格；释放后整组READY。workitems单腿503、quality单腿source_refs漂移、graph单腿跨Mission Gate行均整体ERROR并清空全部旧集合，恢复正常HTTP后可再读。
- 在临时R1正式append一个M1 Gate指向M2 node/delivery，真实E02返回503，客户端不显示剩余成功腿。只恢复临时fixture原字节后重新读取成功；不是修改生产事实或UI自行修补R1。
- 分别选择非空需求、版本、SST，按钮禁用、旧组清空；即使直接触发表单submit也零运行API请求，不做伪筛选。清空筛选后重新授权读取。
- 暂挂旧M1读成功响应，输入M2触发clear/Abort，再交付旧响应，保持NOT_READY且无旧事实。local/session storage无M1、工作项ID、Evidence ID或哈希；实际所有页面请求为GET，所有API请求均为/api/workbench/v1前缀，无legacy/POST。全过程无页面异常；测试后临时R1与审计前字节一致。

## 重复执行命令

```sh
node --test tests/test_dsh_workbench*.mjs
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p test_runtime_product_browser.py -v
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py'
```

附录是本次F独立审计代码，保存到临时脚本，从被测仓库根目录以相同PYTHONPATH/WB_PG_TEST_DSN运行；只操作隔离fixture，不是正式生产创建入口。本报告未运行全量RC7/RC7.2原生资格，不生成离线交付包。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER，发布NOT_APPROVED。

## 附录：独立真实PG/HTTP/浏览器审计脚本

```python
import hashlib, json, os, pathlib, sys, threading, unittest
from dataclasses import asdict
from urllib.parse import urlsplit
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
import test_dsh_workbench_e01_postgres as fixture
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task,Evidence
from rc7_runtime.rc72_domain import MissionNodeRecord,NodeDelivery,NodeGate
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import HostIdentity,scope_handler
from tools.dsh_workbench.e02_service import E02Service
from playwright.sync_api import sync_playwright

class IndependentRuntime(unittest.TestCase):
 def test_three_leg_group_evidence_lineage_filters_and_no_mutations(self):
  db=fixture.E01(methodName='test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery');db.setUp();self.addCleanup(db.doCleanups);db.scope_seed();db.setup_r1()
  # Explicit synthetic R1 binding/records, not the missing production Mission creation chain.
  truth=TruthRuntime(db.r1)
  append_rc72_entity(truth,MissionNodeRecord(mission_node_id='F_NODE',mission_id='M1',node_type='N1_REALITY',scope_ref='B1'),release_id='B1')
  append_rc72_entity(truth,NodeDelivery(delivery_id='F_DELIVERY',mission_id='M1',mission_node_id='F_NODE',node_type='N1_REALITY',version=1,producer_ref='F-explicit-fixture'),release_id='B1')
  append_rc72_entity(truth,NodeGate(gate_id='F_GATE',mission_id='M1',mission_node_id='F_NODE',node_type='N1_REALITY',delivery_id='F_DELIVERY',decision='PASS',reviewer_worker_id='fixture-reviewer',reviewer_session_id='fixture-session',criteria=['fixture-only']),release_id='B1')
  truth.append_atomic('RC7_TASK_UPSERTED',dict(asdict(Task(task_id='F_TASK',mission_id='M1',node='N1',task_type='fixture',objective='read-only fixture')),release_id='B1'))
  content=db.root/'F-content';content.write_bytes(b'F fixture bytes, not execution acceptance');digest='sha256:'+hashlib.sha256(content.read_bytes()).hexdigest()
  truth.append_atomic('RC7_EVIDENCE_UPSERTED',dict(asdict(Evidence(evidence_id='F_EVIDENCE',mission_id='M1',kind='fixture',source_ref='F:fixture-only',content_ref=content.as_uri(),content_hash=digest)),release_id='B1'))
  before=db.r1.read_bytes();handler=scope_handler(lambda:fixture.prior.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,lambda req:HostIdentity('alice') if req.headers.get('Cookie')=='fixture=f-runtime' else None,lambda store:E02Service(store,db.r1,db.root))
  server=create_server(ProductAdminApplication(str(db.r1)),port=0,workbench_handler=handler);origin='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  with sync_playwright() as p:
   browser=p.chromium.launch();context=browser.new_context(viewport={'width':375,'height':812});context.add_cookies([{'name':'fixture','value':'f-runtime','url':origin}]);page=context.new_page();requests=[];errors=[];page.on('request',lambda req:requests.append((req.method,req.url)));page.on('pageerror',lambda error:errors.append(str(error)))
   page.add_init_script("const original=window.fetch.bind(window);window.fetch=async(...args)=>{const response=await original(...args);if(window.fHold&&String(args[0]).includes('/workitems?')){window.fHeld=true;await new Promise(resolve=>window.fRelease=resolve);}return response;};")
   page.goto(origin+'/workbench/');page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12');page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');page.locator('#project-entry').click();page.locator('#sections [data-id=tasks]').click();panel=page.locator('#runtime-facts')
   def read():
    panel.locator('[name=runtime-mission-id]').fill('M1');panel.locator('[data-runtime-load]').click();page.wait_for_selector('#runtime-facts[data-runtime-status=READY]')
   def failed(code):
    panel.locator('[data-runtime-load]').click();page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]');self.assertIn(code,panel.locator('[data-runtime-status]').inner_text());self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0)
   read();self.assertIn('F_TASK',panel.inner_text());self.assertIn('HASH_VERIFIED_ONLY',panel.inner_text());self.assertIn(digest,panel.inner_text());self.assertIn('PASS',panel.locator('[data-record-id=F_GATE]').inner_text());self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'),'HOLD');self.assertIn('未查询',panel.inner_text());self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
   # Hold only one real API leg: two completed legs cannot publish any partial/old group.
   page.evaluate('window.fHold=true;window.fHeld=false');panel.locator('[data-runtime-load]').click();page.wait_for_function('window.fHeld===true');self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0);page.evaluate('window.fRelease();window.fHold=false');page.wait_for_selector('#runtime-facts[data-runtime-status=READY]')
   def unavailable(route):route.fulfill(status=503,json={'error':{'code':'F_TEST_UNAVAILABLE'}})
   page.route('**/missions/M1/workitems?*',unavailable);failed('HTTP_503');page.unroute('**/missions/M1/workitems?*',unavailable);read()
   def sources(route):
    response=route.fetch();value=response.json();value['source_refs']=['F:unexpected-source'];route.fulfill(response=response,json=value)
   page.route('**/quality?*',sources);failed('RUNTIME_SOURCE_CHANGED');page.unroute('**/quality?*',sources);read()
   def foreign(route):
    response=route.fetch();value=response.json();value['records']['rc72_node_gate'][0]['mission_id']='FOREIGN';route.fulfill(response=response,json=value)
   page.route('**/missions/M1/graph?*',foreign);failed('INVALID_RUNTIME_RECORD');page.unroute('**/missions/M1/graph?*',foreign);read()
   # A genuine invalid persisted Gate points across Mission lineage; E02 rejects, UI discards all three legs.
   append_rc72_entity(truth,MissionNodeRecord(mission_node_id='F_FOREIGN_NODE',mission_id='M2',node_type='N1_REALITY',scope_ref='B1'),release_id='B1')
   append_rc72_entity(truth,NodeDelivery(delivery_id='F_FOREIGN_DELIVERY',mission_id='M2',mission_node_id='F_FOREIGN_NODE',node_type='N1_REALITY',version=1,producer_ref='F-fixture'),release_id='B1')
   append_rc72_entity(truth,NodeGate(gate_id='F_BAD_GATE',mission_id='M1',mission_node_id='F_FOREIGN_NODE',node_type='N1_REALITY',delivery_id='F_FOREIGN_DELIVERY',decision='PASS',reviewer_worker_id='fixture',reviewer_session_id='fixture',criteria=['fixture']),release_id='B1')
   failed('HTTP_503');db.r1.write_bytes(before);read()
   # None of the three nonempty selectors can silently read the whole Mission.
   for key,values in [('requirement',['R2']),('version',['V1']),('sst',['SST1'])]:
    page.select_option('[data-scope='+key+']',values);self.assertTrue(panel.locator('[data-runtime-load]').is_disabled());self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0);count=len(requests);page.evaluate("const form=document.querySelector('#runtime-facts form');form.querySelector('input').value='M1';form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));");self.assertEqual(len(requests),count);self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0);page.select_option('[data-scope='+key+']',[]);read()
   # A new Mission input invalidates a held successful old-Mission group.
   page.evaluate('window.fHold=true;window.fHeld=false');panel.locator('[data-runtime-load]').click();page.wait_for_function('window.fHeld===true');panel.locator('[name=runtime-mission-id]').fill('M2');page.evaluate('window.fRelease();window.fHold=false');self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0);self.assertEqual(panel.get_attribute('data-runtime-status'),'NOT_READY')
   page.select_option('#locale','en-US');read();self.assertIn('not business acceptance',panel.inner_text());self.assertIn('not queried',panel.inner_text());self.assertEqual(panel.locator('button').count(),1)
   stored=page.evaluate('JSON.stringify({local:{...localStorage},session:{...sessionStorage}})');self.assertNotIn('M1',stored);self.assertNotIn('F_TASK',stored);self.assertNotIn('F_EVIDENCE',stored);self.assertNotIn(digest,stored)
   self.assertTrue(all(method=='GET' for method,url in requests));self.assertTrue(all(urlsplit(url).path.startswith('/api/workbench/v1/') for method,url in requests if urlsplit(url).path.startswith('/api/')));self.assertEqual(errors,[]);self.assertEqual(db.r1.read_bytes(),before);browser.close()

unittest.main(verbosity=2)
```
