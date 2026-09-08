"""Audited Playwright actions over the existing G4 lease and StandardCase truth."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from .durable_core import RuntimeError, canonical_sha256
from .recovery_api import template

ACTIONS=frozenset({'navigate','click','fill','select','check','uncheck','hover','keyboard','wait_for',
 'frame','popup','assert_visible','assert_text','assert_value','assert_url','assert_state','assert_network','screenshot'})


def locator(page, spec):
    if not isinstance(spec,dict): raise RuntimeError('UI_LOCATOR_REQUIRED','Semantic locator required')
    target=page
    if spec.get('frame'): target=page.frame_locator(spec['frame'])
    if spec.get('testid'): found=target.get_by_test_id(spec['testid'])
    elif spec.get('role'): found=target.get_by_role(spec['role'],name=spec.get('name'),exact=True)
    elif spec.get('label'): found=target.get_by_label(spec['label'],exact=True)
    elif spec.get('css') and ':nth' not in spec['css']: found=target.locator(spec['css'])
    else: raise RuntimeError('UI_STABLE_LOCATOR_REQUIRED','role, label, testid or unique non-positional CSS')
    if found.count()!=1: raise RuntimeError('UI_LOCATOR_AMBIGUOUS','Expected exactly one target')
    return found


def perform(page, action, variables, network, evidence_root):
    kind=action.get('action')
    if kind not in ACTIONS: raise RuntimeError('UI_ACTION_UNSUPPORTED',str(kind))
    value=template(action.get('value'),variables)
    spec=action.get('locator')
    element=locator(page,spec) if spec else None
    check=True
    if kind=='navigate': page.goto(template(action['url'],variables,url=True),wait_until='domcontentloaded',timeout=15000)
    elif kind=='click': element.click(timeout=5000)
    elif kind=='fill': element.fill(str(value),timeout=5000)
    elif kind=='select': element.select_option(str(value),timeout=5000)
    elif kind=='check': element.check(timeout=5000)
    elif kind=='uncheck': element.uncheck(timeout=5000)
    elif kind=='hover': element.hover(timeout=5000)
    elif kind=='keyboard': element.press(str(value),timeout=5000)
    elif kind=='wait_for': element.wait_for(state=action.get('state','visible'),timeout=5000)
    elif kind=='frame': check=page.frame_locator(action['frame']).locator('body').is_visible()
    elif kind=='popup':
        with page.expect_popup(timeout=5000) as event: element.click(timeout=5000)
        page=event.value
        page.wait_for_url(lambda url: bool(url) and url != 'about:blank',wait_until='domcontentloaded',timeout=10000)
    elif kind=='assert_visible': check=element.is_visible()
    elif kind=='assert_text': check=element.inner_text(timeout=5000)==str(value)
    elif kind=='assert_value': check=element.input_value(timeout=5000)==str(value)
    elif kind=='assert_url': check=page.url==template(action['url'],variables,url=True)
    elif kind=='assert_state':
        operations={'enabled':element.is_enabled,'disabled':element.is_disabled,'checked':element.is_checked,'visible':element.is_visible,'hidden':element.is_hidden}
        if action.get('state') not in operations: raise RuntimeError('UI_STATE_ORACLE_INVALID','Unsupported state')
        check=operations[action['state']]()
    elif kind=='assert_network': check=any(x['path']==action['path'] and x['status']==action['status'] for x in network)
    elif kind=='screenshot':
        evidence_root.mkdir(parents=True,exist_ok=True)
        path=evidence_root/(str(time.time_ns())+'.png')
        page.screenshot(path=str(path),mask=[page.locator('input,textarea,select,iframe,[contenteditable],[data-sensitive]')],timeout=10000)
        return page,True,{'artifact_ref':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'masked':True}
    return page,check,{}


def run_action(executor, case, index, request, prior_network=(), page_digest=None):
    from playwright.sync_api import sync_playwright
    from .r3_3.contracts import StandardTestCase
    from .recovery_executors import allowed_url
    from .recovery_browser import CDPBrowserProvider
    from .r3_e2.contracts import BrowserContextRef
    standard=StandardTestCase.from_dict(case);standard.validate_for_execution()
    journey=standard.execution_profile['ui_journey'];steps=journey['steps']
    if not 1<=len(steps)<=64 or not isinstance(index,int) or not 0<=index<len(steps): raise RuntimeError('UI_STEP_BUDGET','Invalid frozen step index')
    action=steps[index]
    provider=CDPBrowserProvider(executor.root)
    ref=BrowserContextRef.from_dict(request['browser_context_ref'])
    provider.inspect_context(ref)
    if provider.inspect_lease(ref)!='AI': raise RuntimeError('UI_HUMAN_LEASE_ACTIVE','Wait for verified HumanGate completion')
    with sync_playwright() as driver:
        browser=driver.chromium.connect_over_cdp(provider.endpoint,timeout=5000)
        context=browser.contexts[0]
        pages=[p for p in context.pages if provider.allowed(p.url)]
        if not pages: raise RuntimeError('UI_APPROVED_PAGE_REQUIRED','Persistent page unavailable')
        page=next((p for p in pages if canonical_sha256({'url':p.url})==page_digest),None)
        if page is None:
            page=next((p for p in pages if p.url==request.get('url')),pages[-1])
        network=list({(n['path'],n['status']):n for n in prior_network}.values())[-48:]
        def response(r):
            if len(network)<64 and provider.allowed(r.url): network.append({'path':urlsplit(r.url).path,'status':r.status})
        def route(r):
            try:
                allowed_url(r.request.url,executor.config,request)
                if r.request.method not in executor.config.get('allowed_methods',['GET','HEAD']): raise ValueError()
            except Exception:r.abort();return
            r.continue_()
        context.route('**/*',route);context.on('response',response)
        try:
            if action.get('url'): allowed_url(template(action['url'],journey.get('variables',{}),url=True),executor.config,request)
            page,passed,artifact=perform(page,action,journey.get('variables',{}),network,executor.evidence/'screenshots')
            provider.inspect_context(ref)
            if provider.inspect_lease(ref)!='AI': raise RuntimeError('UI_LEASE_CHANGED','Human control superseded action')
            observed={'runner':journey.get('mode','PLAYWRIGHT_SCRIPTED_AUTOMATION'),'action':action['action'],
                      'index':index,'case_version_id':standard.case_version_id,'case_digest':canonical_sha256(case),
                      'context_binding_digest':ref.context_binding_digest,'page_digest':canonical_sha256({'url':page.url}),
                      'network':network,'assertion_passed':passed,**artifact}
            return observed,passed
        finally:
            context.unroute('**/*',route);context.remove_listener('response',response)
            # Disconnecting Playwright never closes the user's persistent browser.


def execute_governed(service, mission_id, request, case, base_execute):
    """G4 owns cursor progression in both modes; no model-selected shell/script."""
    from .r3_3.contracts import StandardTestCase
    StandardTestCase.from_dict(case).validate_for_execution()
    journey=case['execution_profile']['ui_journey'];steps=journey.get('steps')
    mode=journey.get('mode','PLAYWRIGHT_SCRIPTED_AUTOMATION')
    if mode not in {'PLAYWRIGHT_SCRIPTED_AUTOMATION','AI_BROWSER_INTERACTIVE_EXECUTION'} or not isinstance(steps,(list,tuple)) or not 1<=len(steps)<=64:
        raise RuntimeError('UI_JOURNEY_INVALID','Frozen mode and 1..64 actions required')
    attempt=service._canonical_attempt(mission_id,request['attempt_id'],request['task_id'])
    results=[f for f in service.state(mission_id).by_kind('EXECUTION_STEP_RESULT') if f.payload.get('root_attempt_id')==attempt.root_attempt_id and f.payload.get('case_version')==case['case_version_id']]
    completed={f.payload['step_id'] for f in results if f.payload.get('oracle_result')=='PASS'}
    reports=[]
    for index,action in enumerate(steps):
        step_id='ui:'+str(index)
        if step_id in completed: continue
        cursor_request={**request,'current_step_index':index,'pending_step_id':step_id,'completed_step_ids':sorted(completed)}
        # Durable continuation only carries approved identifiers/scope, no body,
        # credentials, copied provider configuration or raw trace.
        resume={k:request[k] for k in ('task_id','attempt_id','case_id','case_version','execution_batch_id','goal_id') if k in request}
        resume['capability_id']='BROWSER_UI'
        er=request.get('executor_request') or {}
        resume['executor_request']={k:er[k] for k in ('url','authorized_scope','browser_context_ref','target_environment') if k in er}
        cursor_request['last_safe_checkpoint']={'ui_journey_resume':resume}
        service.record_cursor(mission_id,cursor_request)
        if action.get('action')=='human_gate':
            gate_id='ui-human:'+canonical_sha256({'root':attempt.root_attempt_id,'case':case['case_version_id'],'step':index})[:24]
            takeover=service.state(mission_id).latest('HUMAN_TAKEOVER_REQUEST',lambda f:f.payload.get('human_gate_id')==gate_id)
            if takeover and takeover.payload.get('status')=='RESUME_SAFE':
                completed.add(step_id);continue
            if takeover:return {'status':'WAITING_HUMAN','human_gate_id':gate_id,'task_id':attempt.task_id,'step_index':index}
            return service.request_human_takeover(mission_id,{**request,'human_gate_id':gate_id,
              'browser_context_ref':er.get('browser_context_ref'),'required_action':action.get('description','Complete approved browser operation'),
              'resume_mode':'AUTO_OR_EXPLICIT','resume_condition':dict(action.get('resume_condition') or {})})
        data={**request,'step':{'step_id':step_id,'expected':case['expected_results'][min(index,len(case['expected_results'])-1)],
                              'standard_case':case,'ui_action_index':index,
                              'prior_network':[n for f in service.state(mission_id).by_kind('EXECUTION_STEP_RESULT')
                                 if f.payload.get('root_attempt_id')==attempt.root_attempt_id
                                 for n in (f.payload.get('actual') or {}).get('network',[])][-48:]}}
        previous = service.state(mission_id).latest('EXECUTION_STEP_RESULT',lambda f:f.payload.get('root_attempt_id')==attempt.root_attempt_id and f.payload.get('case_version')==case['case_version_id'])
        if previous:
            data['step']['page_digest']=(previous.payload.get('actual') or {}).get('page_digest')
        result=base_execute(data);reports.append(result)
        result_fact=result.get('result') or result.get('step_result') or {}
        # Read canonical result truth rather than inferring success from provider return shape.
        actual=service.state(mission_id).latest('EXECUTION_STEP_RESULT',lambda f:f.payload.get('root_attempt_id')==attempt.root_attempt_id and f.payload.get('step_id')==step_id)
        if actual is None or actual.payload.get('oracle_result')!='PASS': return {'status':'FAIL','step_index':index,'result':result}
        completed.add(step_id)
        service.record_cursor(mission_id,{**cursor_request,'current_step_index':index+1,'pending_step_id':None,'completed_step_ids':sorted(completed)})
        if mode=='AI_BROWSER_INTERACTIVE_EXECUTION':
            return {'status':'PASS','step_index':index,'next_step_index':index+1,'complete':index+1==len(steps),'result':result}
    return {'status':'PASS','complete':True,'step_count':len(steps),'case_version_id':case['case_version_id'],
            'evidence_result_count':len(reports),'context_policy':'BOUNDED_G4_RESULTS'}
