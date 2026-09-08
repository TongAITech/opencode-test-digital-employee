"""Human trace to bounded, source-bound Playwright candidate; G6 stays HOLD."""
import json
import hashlib
from .durable_core import RuntimeError, canonical_sha256
from .g3.service import G3TestingIntelligenceService
from .recovery_ui import ACTIONS, locator, perform


def generate_candidate(runtime, mission_id, teaching_fact_id):
    g3=G3TestingIntelligenceService(runtime);fact=g3.state(mission_id).by_id(teaching_fact_id)
    if fact is None or fact.fact_kind!='TEACHING_ASSET': raise RuntimeError('TEACHING_SOURCE_REQUIRED',teaching_fact_id)
    lineage=fact.payload.get('execution_lineage') or {}
    if not all(lineage.get(k) for k in ('human_gate_id','root_attempt_id','task_id','step_id')):
        raise RuntimeError('TEACHING_EXECUTION_ATTEMPT_REQUIRED','Standalone recordings cannot become execution automation')
    actions=[];unresolved=[]
    for index,event in enumerate(fact.payload.get('observations',[])):
        if event.get('kind')!='ELEMENT':continue
        element=event.get('element') or {};kind=element.get('action')
        if kind not in ACTIONS:unresolved.append(index);continue
        candidates=element.get('locator_candidates') or []
        stable=next((dict(c) for c in candidates if c.get('testid') or c.get('role') and c.get('name') or c.get('label')),None)
        if stable is None:
            stable=next((dict(c) for c in candidates if c.get('css','').startswith('#') and ':nth' not in c['css']),None)
        if stable is None:unresolved.append(index);continue
        if element.get('frame_name'):
            name=element['frame_name']
            if any(x in name for x in ['"','\\','\n']):unresolved.append(index);continue
            stable['frame']='iframe[name="'+name+'"]'
        action={'action':kind,'locator':stable,'trace_index':index,'semantic_page':element.get('semantic_page')}
        if kind in {'fill','select'}:
            field=element.get('test_data_placeholder')
            if not field:unresolved.append(index);continue
            action['value']='${'+field+'}'
        if kind=='keyboard':action['value']=element.get('keyboard')
        actions.append(action)
    if not actions or len(actions)>32 or unresolved:
        raise RuntimeError('TEACHING_LOCATOR_REVIEW_REQUIRED','Recording requires stable locators before replay')
    program=playwright_program(actions)
    payload={'asset_id':'playwright-candidate:'+canonical_sha256({'source':fact.digest,'actions':actions})[:24],
      'mode':'PLAYWRIGHT_CANDIDATE','lifecycle':'CANDIDATE','source_teaching_ref':fact.fact_id,
      'source_teaching_digest':fact.digest,'execution_lineage':lineage,'actions':actions,
      'playwright_program':program,'program_sha256':hashlib.sha256(program.encode("utf-8")).hexdigest(),
      'replay_status':'REPLAY_VALIDATION_REQUIRED','automatic_promotion':False,'g6':'HOLD'}
    return g3._record(mission_id,'TEACHING_ASSET',payload,provenance_refs=(fact.fact_id,))


def playwright_program(actions):
    # Literal JSON plus fixed audited Python; action values never become code.
    return ('import json\nfrom aitest_runtime.recovery_ui import perform, locator\n'
      'from aitest_runtime.durable_core import canonical_sha256\n'
      'ACTIONS = json.loads('+repr(json.dumps(actions,ensure_ascii=False,sort_keys=True))+')\n'
      'def replay(page, variables, network, evidence_root, lease_check):\n'
      '    receipts = []\n'
      '    for action in ACTIONS:\n'
      '        lease_check()\n'
      '        locator(page, action["locator"])\n'
      '        page, passed, artifact = perform(page, action, variables, network, evidence_root)\n'
      '        receipts.append({"action": action["action"], "passed": passed, "locator_digest": canonical_sha256(action["locator"]), **artifact})\n'
      '        if not passed: break\n'
      '    lease_check()\n'
      '    return page, receipts\n')


def validate_replay(runtime, mission_id, candidate_ref, *, page, variables, evidence_root, approval_ref, context_ref):
    """Validate mapping in a G4-controlled AI lease, recording bounded Evidence.

    Caller must hold the current governed browser lease; fresh identity checks
    bracket replay. No promotion to global Skill or automatic Verified Knowledge.
    """
    from .recovery_browser import CDPBrowserProvider
    from .r3_e2.contracts import BrowserContextRef
    g3=G3TestingIntelligenceService(runtime);candidate=g3.state(mission_id).by_id(candidate_ref)
    if candidate is None or candidate.payload.get('mode')!='PLAYWRIGHT_CANDIDATE':raise RuntimeError('PLAYWRIGHT_CANDIDATE_REQUIRED',candidate_ref)
    if not approval_ref:raise RuntimeError('PLAYWRIGHT_REPLAY_APPROVAL_REQUIRED','Use a locally approved replay scope')
    payload=candidate.payload;actions=payload['actions']
    if payload['playwright_program']!=playwright_program(actions) or payload['program_sha256']!=hashlib.sha256(payload['playwright_program'].encode('utf-8')).hexdigest():
        raise RuntimeError('PLAYWRIGHT_CANDIDATE_HASH_MISMATCH',candidate_ref)
    from .g4.contracts import EXTENSION_ID
    state=runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
    lineage=payload['execution_lineage']
    takeover=state.latest('HUMAN_TAKEOVER_REQUEST',lambda f:f.payload.get('human_gate_id')==lineage['human_gate_id'])
    if takeover is None or takeover.payload.get('status')!='RESUME_SAFE':
        raise RuntimeError('PLAYWRIGHT_G4_RESUME_REQUIRED','Replay only after G4 freshly verified the human gate')
    # Use the already-bound browser adapter's exact context and allowed origin.
    # The workspace is explicit on the runtime, supplied by the caller's approved fixture/product context.
    from pathlib import Path
    import os
    root=Path(os.environ["AITEST_WORKSPACE_ROOT"])
    provider=CDPBrowserProvider(root,runtime=runtime);ref=BrowserContextRef.from_dict(context_ref)
    provider.inspect_context(ref)
    if provider.inspect_lease(ref)!='AI' or not provider.allowed(page.url):raise RuntimeError('PLAYWRIGHT_REPLAY_SCOPE_REQUIRED','AI lease and approved page required')
    approvals = provider.config.get('replay_approvals') or []
    if not any(item.get('candidate_ref') == candidate_ref and item.get('approval_ref') == approval_ref
               and item.get('program_sha256') == payload['program_sha256'] and item.get('approved') is True
               for item in approvals):
        raise RuntimeError('PLAYWRIGHT_REPLAY_LOCAL_APPROVAL_REQUIRED','Bind this exact candidate before replay')
    from .recovery_executors import binding, allowed_url
    execution_binding = binding(root)
    authorized = {'authorized_scope': {'origins': provider.config['allowed_origins']}}
    def route(r):
        try:
            allowed_url(r.request.url, execution_binding, authorized)
            if r.request.method not in execution_binding.get('allowed_methods',['GET','HEAD']): raise ValueError()
        except Exception: r.abort(); return
        r.continue_()
    def lease_check():
        provider.inspect_context(ref)
        if provider.inspect_lease(ref) != 'AI': raise RuntimeError('PLAYWRIGHT_REPLAY_LEASE_CHANGED','Human control superseded replay')
    # Execute the actual generated artifact only after fixed-program equality and
    # approval hashes match. No caller Python or shell code is accepted.
    import importlib.util
    import tempfile
    page.context.route('**/*', route)
    try:
        with tempfile.TemporaryDirectory(prefix='aitest-verified-replay-') as folder:
            program_path=Path(folder)/'candidate.py'
            program_path.write_bytes(payload['playwright_program'].encode('utf-8'))
            spec=importlib.util.spec_from_file_location('aitest_verified_replay',program_path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            page,receipts=module.replay(page,variables,[],evidence_root,lease_check)
    finally: page.context.unroute('**/*',route)
    conditions = takeover.payload.get('resume_condition') or {}
    postchecks = {key: bool(conditions.get(key)) and page.locator(conditions[key]).is_visible()
                  for key in ('authenticated_selector','page_selector','business_selector')}
    passed=len(receipts)==len(actions) and all(x['passed'] for x in receipts) and all(postchecks.values())
    result={'asset_id':'playwright-replay:'+canonical_sha256({'candidate':candidate.digest,'receipts':receipts})[:24],
      'mode':'AUTOMATION_ASSET','lifecycle':'EVIDENCE_BACKED' if passed else 'REJECTED',
      'candidate_ref':candidate_ref,'execution_lineage':lineage,'replay_status':'PASS' if passed else 'FAIL',
      'approval_ref':approval_ref,'receipts':receipts,'fresh_postconditions':postchecks,'replay_evidence_digest':canonical_sha256(receipts),
      'context_binding_digest':ref.context_binding_digest,'program_sha256':payload['program_sha256'],
      'g6':'HOLD','automatic_promotion':False}
    return g3._record(mission_id,'TEACHING_ASSET',result,provenance_refs=(candidate_ref,takeover.fact_id,approval_ref))
