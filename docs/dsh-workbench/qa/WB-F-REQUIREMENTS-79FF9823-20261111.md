# F：需求关联移动长ID修复精确复验

被测 [PR #225](https://github.com/TongAITech/opencode-test-digital-employee/pull/225) 新冻结源 `79ff9823fe8bdc67a1b4cbc0a69d710664ef1840`。独立worktree `f-requirements-fix`，测试前后该源固定且干净；F未改实现、仓库测试或08/09/10，本提交只追加报告。

结论：**READONLY_REQUIREMENT_RELATIONS_COMPONENT_QA_ACCEPTED_EXACT_79FF9823 / F228_LONG_ID_P2_FIXED_FOR_TESTED_CASES**。F228旧26257eae的390px失败保留，不倒写成通过；本次在新SHA实际重新执行旧失败脚本并新增普通长ID访问案例，关闭该P2已复现范围。不是完整C04/C05、需求正文/编辑、测试义务/覆盖、原生DSH/Windows或发布资格。

## 修复范围只读核查

与262相比，需求投影、ScopeClient和ScopePanel业务代码差异为空。修复为main min-width:0、共用Scope label/select宽度约束及option文本换行，另扩现有浏览器回归。没有overflow:hidden掩盖页面、substring截断业务ID或放弃原value；没有新fetch/API/cache/POST/业务storage/R1写。

单一Scope完整READY、三筛选逐行交集、精确UNSPLIT和BRV/BRVS来源及未获取正文/义务/覆盖的边界保持。新CSS影响共用控件，因此F不只看新增需求article，也检查overview中的相同选择器。

## F本轮实际执行

真实本地隔离PostgreSQL17.6/Psycopg3.2.13、同源HTTP、原生Chromium窗口与显式fixture Host；普通自有测试资料，无新权限提升或额外安全SQL实验。

| 实际范围 | 结果 |
|---|---|
| 原F失败脚本原样复跑 | **1/1，3.229秒**。`/tmp/f_requirements_layout_diagnostic.py`未改，SHA256 `d66e700727cd53b3c371c81436479e33e750a30690a9683b52c6679d08b925f1`；原requirements/overview 390均变**375**，OVERFLOW_ELEMENTS=[]。原多版本/精确SST/UNSPLIT/来源文字HTML、同Scope四页暂挂无半页、晚页revision漂移清空/恢复、Scope编辑清空、原生fetch/无POST/legacy/业务storage等断言实际全部完成 |
| 新F普通长ID访问案例 | **1/1，3.011秒**；120连续X加Unicode后缀ID，zh/en × requirements/overview均在375内；完整accessible option name/text/value与键盘End选中原ID、Tab焦点可用，选中后的article原ID及来源ref/revision完全一致；html/body/main没有overflow-x:hidden，h4按anywhere换行，切换/选择不增加请求，fetch仍native，storage只四偏好字段 |
| `node --test tests/test_dsh_workbench*.mjs` | **124/124**，0跳过，0.649秒 |
| 全既有 `tests/browser/test*.py` 真实PG浏览器 | **10/10**，0跳过，48.778秒；含C新增两语言/两section/合法长ID/End/Tab回归，以及原101行分页/403/503/改期/旧响应与其它九页面组件案例 |
| 精确远端产品CI | [42892364517](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42892364517)两job SUCCESS；F核checkout显式ref和实际git log均79ff9823、Node124分母可查，不把默认merge checkout当候选证据 |

各层分母分别记录，不相加伪装唯一覆盖数。完整文本可访问的结论来自option完整名称/text/value、真实键盘选择和选中后正文原文，不用“页面不滚动”一条指标冒充文字保留，也没有用截图替代业务Oracle。

## 可复用命令与独立案例

原失败脚本已完整保存在[F228](https://github.com/TongAITech/opencode-test-digital-employee/pull/228)报告；本次直接原样运行，未删除375断言：

```sh
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 /tmp/f_requirements_layout_diagnostic.py
node --test tests/test_dsh_workbench*.mjs
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py' -v
```

新增F临时普通资料案例（不改产品或仓库既有测试），以相同PG环境在固定worktree运行：

```python
import json,pathlib,sys,threading,unittest
sys.path.insert(0,str(pathlib.Path.cwd()));sys.path.insert(0,str(pathlib.Path.cwd()/'tests'))
import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.business_relations import import_verified_requirement_version
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from rc7_admin.product_server import WorkbenchPublicApplication,create_server
from playwright.sync_api import sync_playwright
class FAccessibleLongIdentifier(unittest.TestCase):
 def test_both_locales_both_sections_unbroken_unicode_identifier_keyboard_and_native_data(self):
  db=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors');db.setUp();server=None
  try:
   db.scope_seed();long_id='ZZ_'+('X'*120)+'/测试ID/完整保留'
   db.relations.create_requirement('alice','P1',long_id,'src','prod','f-long-id','r1','source:long-id','f-long-create')
   rev=db.relations.attach_member('alice','P1','B1','requirement',long_id,7,'f-long-member')
   import_verified_requirement_version(db.owner,'P1','B1',long_id,'V1','source:long-relation','relation-revision-real')
   db.relations.attach_requirement_version('alice','P1','B1',long_id,'V1',rev,'f-long-brv')
   server=create_server(WorkbenchPublicApplication(),port=0,workbench_handler=scope_handler(lambda:fixture.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,lambda request:HostIdentity('alice') if request.headers.get('Cookie')=='fixture=f-long' else None))
   threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port)
   with sync_playwright() as p:
    browser=p.chromium.launch();context=browser.new_context(viewport={'width':375,'height':812});context.add_cookies([{'name':'fixture','value':'f-long','url':origin}]);page=context.new_page();requests=[];errors=[]
    page.on('request',lambda req:requests.append((req.method,req.url)));page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(origin+'/workbench/');self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(fetch)'));page.locator('#project-entry').click();page.locator('#sections [data-id=requirements]').click()
    for name,value in [('project_id','P1'),('batch_id','B1'),('release_date','2026-11-12')]:page.locator('[name='+name+']').fill(value)
    page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');reads=len(requests)
    for locale in ['zh-CN','en-US']:
     page.select_option('#locale',locale)
     for section in ['requirements','overview']:
      page.locator('#sections [data-id='+section+']').click()
      self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
      self.assertTrue(page.locator('#business-scope label,#business-scope select').evaluate_all('(nodes)=>nodes.every(n=>n.getBoundingClientRect().left>=0&&n.getBoundingClientRect().right<=375)'))
      self.assertFalse(page.locator('html,body,main').evaluate_all('(nodes)=>nodes.some(n=>getComputedStyle(n).overflowX==="hidden")'))
      option=page.get_by_role('option',name=long_id,exact=True);self.assertEqual(option.text_content(),long_id);self.assertEqual(option.get_attribute('value'),long_id)
      control=page.locator('[data-scope=requirement]');control.focus();page.keyboard.press('End')
      self.assertEqual(control.evaluate('(el)=>[...el.selectedOptions].map(o=>o.value)'),[long_id])
      page.keyboard.press('Tab');self.assertNotEqual(page.evaluate('document.activeElement.tagName'),'BODY')
      if section=='overview':self.assertEqual(page.locator('#requirement-relations').inner_text(),'')
      page.locator('#sections [data-id=requirements]').click();panel=page.locator('#requirement-relations');self.assertEqual(panel.locator('article').count(),1)
      self.assertIn(long_id,panel.locator('h4').inner_text());self.assertEqual(json.loads(panel.locator('article').get_attribute('data-relation-key')),[long_id,'V1',None]);self.assertIn('source:long-relation / relation-revision-real',panel.inner_text())
      self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
      self.assertEqual(panel.locator('h4').evaluate('(el)=>getComputedStyle(el).overflowWrap'),'anywhere')
      page.select_option('[data-scope=requirement]',[])
    self.assertEqual(len(requests),reads);self.assertTrue(all(method=='GET' for method,url in requests));self.assertEqual(errors,[])
    stored=page.evaluate('JSON.parse(localStorage.getItem("dsh-workbench-settings"))');self.assertEqual(set(stored),{'locale','theme','page','section'});self.assertNotIn(long_id,json.dumps(stored));self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(fetch)'));browser.close()
  finally:
   if server:server.shutdown();server.server_close()
   db.doCleanups()
if __name__=='__main__':unittest.main(verbosity=2)

```

## 保留门禁

这是普通只读关系展示及本次继承布局修复的组件接受，不取得需求文档、不生成正式Obligation/Case、不证明覆盖或NodeGate PASS。未验证所有浏览器/OS/任意长度ID或真实DSH宿主；Windows、银行网络、离线交付仍FIELD_NEEDS_BANK_TRANSFER。由A正向集成并核新联合HEAD，本报告不跨SHA转签、不批准最终发布。
