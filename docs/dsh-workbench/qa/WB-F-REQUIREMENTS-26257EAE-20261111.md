# F：需求关联只读界面精确审查及继承移动布局P2

被测 [PR #225](https://github.com/TongAITech/opencode-test-digital-employee/pull/225) 完整源 `26257eaed8f78857ce9d22b8325a4cffb419b67f`。独立worktree `f-requirements-exact`，测试前后源固定且干净；未修改被测实现/测试或08/09/10，本提交只增加报告。

结论：**READONLY_RELATIONS_FUNCTIONAL_COMPONENT_ACCEPTED_EXACT_26257EAE / INHERITED_P2_MOBILE_LONG_ID_OPEN**。未发现新增关系投影的数据正确性/Scope清理P0/P1，但不能写全量375px资格通过：F使用合法长需求ID在375px浏览者宽度实际得到390px横向内容。该P2定位到既有共用Scope下拉框，离开需求界面仍存在；不因继承关系而隐藏，完整C05/发布仍不得核销。A已要求先保留本精确报告，再由C修复并对新SHA复验。

## 单一Scope来源与边界审查

新requirements-panel只同步读取既有ScopeClient的完整READY结果及全局selection；无fetch、新API、独立业务缓存/持久化、POST或R1写。ScopeClient仍负责真实来源/分页/revision/外Scope/迟到响应校验。需求/版本/SST三个选择逐行求交，不做笛卡尔积；UNSPLIT保持null，BRV/BRVS ref+revision直接从验证过的原行显示。来源明确标注为关系来源，不能称已读需求正文、测试义务或覆盖完成。

每次render先清DOM与Scope/revision metadata；隐藏或非READY均无旧行。全局selection不合法或交集不匹配不返回零需求成功。静态两语文字和所有资料都走textContent；六页面/十个分区未增删。无额外运行命令或Host能力声明。

## F实际测试

环境：本机隔离PostgreSQL17.6/Psycopg3.2.13、真实同源HTTP与原生Chromium，显式fixture Host，不是银行DSH认证。只用本机普通业务fixtures，无新增权限提升/外部目标/额外安全SQL实验。

| 实际范围 | 结果 |
|---|---|
| `node --test tests/test_dsh_workbench*.mjs` | 124/124，0跳过，0.587秒 |
| 现有真实PG浏览器 `tests/browser/test*.py` | 10/10，0跳过，48.666秒；含101行/两页、两需求共享V1但不同SST、99 UNSPLIT、每条ref/revision SQL Oracle、文字HTML、筛选交集、原生fetch、403/503/改期恢复及旧响应清理等现有用例 |
| F独立普通UI/资料组合 | **1例末尾移动宽度断言失败**；首次3.035秒，加入只读布局定位后复跑3.131秒仍同一390>375。未将其算通过，也不将重复执行虚增唯一用例数 |
| 精确远端C产品CI | [42890031077](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42890031077)两个job均SUCCESS；workflow显式checkout PR head，F核实际ref与git log均26257eae，Node124分母可查。不是默认merge checkout转签 |

F组合在最终失败前已经实际执行并通过：普通fixture建立R1/V1/SST1、R2/V1/SST2、R1/V2/UNSPLIT及一个HTML样式合法ID/UNSPLIT；与精确预设tuple逐个相等；多选交集不串SST；BRV ref/revision的HTML样式字符串只作文字，DOM无img/svg/b且无脚本执行；选择UNSPLIT不造SST；两语切换不增加请求；真实B06改为每页1行并暂挂第二页，同Scope重载不显示半页，切section清空且回来仍无半页，交付后四页完整；第二页revision漂移使整个投影及metadata清空，恢复后完整；Scope日期编辑立即清空且只有重新加载恢复；键盘Tab无BODY焦点；全窗口请求只GET且无legacy API；localStorage只有四项UI偏好，无业务ID；fetch前后保持native code。没有用截图或模型回答作业务Oracle。

## P2：长合法ID的既有Scope选择控件溢出

普通fixture需求ID：`REQ <img src=x onerror=window.fInjected=1>`（作为纯业务文本，非HTML）。375px窗口中F只读DOM测得：

- document.documentElement.scrollWidth = **390**；
- 共用`#business-scope` requirement LABEL/SELECT宽356.703px、right382.703px，超过视口；
- 切到overview使新增需求列表DOM完全清空后，scrollWidth仍为**390**；
- 新需求article/p/h4/dd已有overflow-wrap，实际越界元素是原ScopePanel选择器。

这证明是继承的长ID/共用控件响应式P2，不能误归新增article，也不能把正常短ID的375px测试外推为全部合法ID已通过。建议C限制共用选择器/label在容器内的宽度并在新精确SHA复验；F不修被测功能。本报告不提前接受该移动布局门禁。

## 可复用独立失败脚本

本机保留 `/tmp/f_requirements_layout_diagnostic.py`，可在C修复的新隔离worktree用相同PG环境重跑。脚本保持native fetch，无init script包装；网络route仅用于真实B06分页交付与revision故障场景，fixture业务写仅为普通资料准备，不是安全权限实验。完整脚本如下：

```python
import json,pathlib,sys,threading,unittest
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
sys.path.insert(0,str(pathlib.Path.cwd()));sys.path.insert(0,str(pathlib.Path.cwd()/'tests'))
import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.business_relations import import_verified_requirement_version,import_verified_sst_link,import_sst_identity
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from rc7_admin.product_server import WorkbenchPublicApplication,create_server
from playwright.sync_api import sync_playwright
class IndependentRequirements(unittest.TestCase):
 def test_native_window_projection_exact_sources_no_partial_reload_and_literal_ids(self):
  db=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors');db.setUp();server=None
  try:
   db.scope_seed();rev=7
   import_sst_identity(db.owner,'P1','V1','SST2','src','prod','raw2','r2','source:sst2')
   import_verified_sst_link(db.owner,'P1','B1','R2','V1','SST2','source:link2','brvs:r2')
   rev=db.relations.attach_sst('alice','P1','B1','R2','V1','SST2',rev,'f-attach2')
   db.store.create_version('alice','P1','V2','S1','same label','src','prod','v2','rev2','f-v2')
   rev=db.relations.attach_member('alice','P1','B1','version','V2',rev,'f-v2-member')
   rv_ref='source:<svg onload=window.fInjected=1>';rv_revision='<b>actual-rev2</b>'
   import_verified_requirement_version(db.owner,'P1','B1','R1','V2',rv_ref,rv_revision)
   rev=db.relations.attach_requirement_version('alice','P1','B1','R1','V2',rev,'f-r1-v2')
   hostile='REQ <img src=x onerror=window.fInjected=1>'
   db.relations.create_requirement('alice','P1',hostile,'src','prod','hostile-id','rev3','source:req-f','f-req')
   rev=db.relations.attach_member('alice','P1','B1','requirement',hostile,rev,'f-member')
   import_verified_requirement_version(db.owner,'P1','B1',hostile,'V1','source:hostile-id','rev3')
   rev=db.relations.attach_requirement_version('alice','P1','B1',hostile,'V1',rev,'f-rv')
   expected=[['R1','V1','SST1'],['R1','V2',None],['R2','V1','SST2'],[hostile,'V1',None]]
   server=create_server(WorkbenchPublicApplication(),port=0,workbench_handler=scope_handler(lambda:fixture.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,lambda request:HostIdentity('alice') if request.headers.get('Cookie')=='fixture=f-req' else None))
   threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port)
   with sync_playwright() as p:
    browser=p.chromium.launch();context=browser.new_context(viewport={'width':375,'height':812});context.add_cookies([{'name':'fixture','value':'f-req','url':origin}]);page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda req:requests.append((req.method,req.url)))
    page.goto(origin+'/workbench/');self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(fetch)'));page.locator('#project-entry').click();page.locator('#sections [data-id=requirements]').focus();page.keyboard.press('Enter')
    panel=page.locator('#requirement-relations')
    def keys():return [json.loads(k) for k in panel.locator('article').evaluate_all('(rows)=>rows.map(row=>row.dataset.relationKey)')]
    def blank():
     self.assertEqual(keys(),[])
     for attr in ['data-relation-scope','data-relation-revision','data-access-revision']:self.assertIsNone(panel.get_attribute(attr))
    for name,value in [('project_id','P1'),('batch_id','B1'),('release_date','2026-11-12')]:page.locator('[name='+name+']').fill(value)
    def load():page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]')
    load();self.assertEqual(keys(),expected)
    self.assertIn(rv_ref,panel.inner_text());self.assertIn(rv_revision,panel.inner_text());self.assertEqual(panel.locator('svg,img,b').count(),0);self.assertIsNone(page.evaluate('window.fInjected'))
    self.assertEqual(panel.get_attribute('data-relation-revision'),str(rev));self.assertIn('不是需求文档',panel.inner_text())
    page.select_option('[data-scope=requirement]',['R1','R2']);page.select_option('[data-scope=version]',['V1']);page.select_option('[data-scope=sst]',['SST2']);self.assertEqual(keys(),[['R2','V1','SST2']])
    page.select_option('[data-scope=requirement]',['R1']);page.select_option('[data-scope=version]',['V2']);self.assertEqual(keys(),[['R1','V2',None]]);self.assertIn('待拆分',panel.inner_text())
    count=len(requests);page.select_option('#locale','en-US');self.assertEqual(keys(),[['R1','V2',None]]);self.assertEqual(len(requests),count);self.assertIn('not requirement document sources',panel.inner_text())
    page.select_option('[data-scope=requirement]',[hostile]);self.assertEqual(keys(),[[hostile,'V1',None]]);self.assertEqual(panel.locator('img').count(),0)
    page.select_option('[data-scope=requirement]',[])
    mode=['hold'];held=[]
    def route_pages(route):
     parsed=urlsplit(route.request.url);q=dict(parse_qsl(parsed.query));q['page_size']='1';response=route.fetch(url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(q),parsed.fragment)))
     if 'page_cursor' in q and mode[0]=='hold':held.append((route,response));return
     if 'page_cursor' in q and mode[0]=='drift':value=response.json();value['relation_revision']+=1;route.fulfill(response=response,json=value);return
     route.fulfill(response=response)
    page.route('**/scope?*',route_pages);page.locator('#business-scope button').click();page.wait_for_function('document.querySelector("#business-scope").dataset.scopeStatus==="LOADING"')
    for _ in range(100):
     if held:break
     page.wait_for_timeout(20)
    self.assertTrue(held);blank()
    page.locator('#sections [data-id=overview]').click();self.assertEqual(panel.inner_text(),'');page.locator('#sections [data-id=requirements]').click();blank()
    mode[0]='normal'
    for route,response in held:route.fulfill(response=response)
    page.wait_for_selector('#business-scope[data-scope-status=READY]');self.assertEqual(keys(),expected)
    mode[0]='drift';page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');blank();self.assertIn('STALE_SCOPE',page.locator('#scope-result').inner_text())
    page.unroute('**/scope?*',route_pages);load();self.assertEqual(keys(),expected)
    page.locator('[name=release_date]').fill('2026-11-13');blank();page.locator('[name=release_date]').fill('2026-11-12');blank();load();self.assertEqual(keys(),expected)
    page.locator('#sections [data-id=requirements]').focus();page.keyboard.press('Tab');self.assertNotEqual(page.evaluate('document.activeElement.tagName'),'BODY')
    width=page.evaluate('document.documentElement.scrollWidth')
    print('REQUIREMENTS_WIDTH',width)
    print('OVERFLOW_ELEMENTS',page.evaluate("[...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,id:e.id,scope:e.dataset.scope,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,text:(e.textContent||'').slice(0,60)})).filter(e=>e.right>376)"))
    page.locator('#sections [data-id=overview]').click();print('OVERVIEW_WIDTH',page.evaluate('document.documentElement.scrollWidth'));page.locator('#sections [data-id=requirements]').click()

    self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(fetch)'));self.assertTrue(all(method=='GET' for method,url in requests));self.assertFalse(any('/api/' in url and '/api/workbench/v1/' not in url for method,url in requests));self.assertEqual(errors,[])
    settings=page.evaluate('JSON.parse(localStorage.getItem("dsh-workbench-settings"))');self.assertEqual(set(settings),{'locale','page','section','theme'});self.assertNotIn(hostile,json.dumps(settings));print('FUNCTIONAL_AND_STORAGE_CHECKS_PASSED');self.assertLessEqual(width,375);browser.close()
  finally:
   if server:server.shutdown();server.server_close()
   db.doCleanups()
if __name__=='__main__':unittest.main(verbosity=2)

```

## 保留项

只有新增只读关系展示功能审查，不核销需求管理/正文/编辑/测试义务/覆盖、完整C04/C05、正式Mission绑定、Host、Windows或离线交付。真实现场仍FIELD_NEEDS_BANK_TRANSFER；本结论不跨SHA转签。A负责集成与账本，P2必须原样记录并由后续新源复验关闭。
