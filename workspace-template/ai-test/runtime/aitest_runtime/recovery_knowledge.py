"""Task views over the existing R3.E1 projection; R1 remains the only truth.

Product lifecycle labels map to frozen R3.E1 states. There is no new store and
no G6 promotion. Candidate ingestion never grants execution eligibility.
"""
from datetime import datetime, timezone, timedelta
import json
import re
import sqlite3
from .durable_core import RuntimeError, canonical_sha256
from .r3_e1.contracts import KnowledgeScopeIdentity, KnowledgeFact, KnowledgeVersion, KnowledgeSourceRef
from .r3_e1.service import R3E1ApplicationService

TYPES=frozenset({'Requirement','BR','SR','TR','CodeSymbol','CodeImpact','API','Page','Journey',
                 'StandardCase','AutomationAsset','EvidenceSummary','DefectRootCause','HistoricalRegressionSignal'})
LIFECYCLE={'DISCOVERED':'CANDIDATE','CANDIDATE':'CANDIDATE','SOURCE_VERIFIED':'EVIDENCE_BACKED',
 'RUNTIME_VERIFIED':'VERIFIED','USER_VERIFIED':'VERIFIED','STALE':'STALE','CONFLICTED':'STALE',
 'SUPERSEDED':'SUPERSEDED','RETIRED':'REJECTED'}
ROLE_TYPES={
 'aitest-requirement-analyst':{'Requirement','BR','SR','TR','Journey'},
 'aitest-code-analyst':{'BR','SR','TR','CodeSymbol','CodeImpact','API','Page'},
 'aitest-test-strategist':{'TR','Journey','CodeImpact','HistoricalRegressionSignal','DefectRootCause'},
 'aitest-case-designer':{'TR','API','Page','Journey','StandardCase','AutomationAsset'},
 'aitest-executor':{'TR','API','Page','Journey','StandardCase','AutomationAsset'},
 'aitest-evaluator':{'TR','StandardCase','EvidenceSummary','DefectRootCause'},
 'aitest-diagnosis':{'CodeSymbol','CodeImpact','API','EvidenceSummary','DefectRootCause','HistoricalRegressionSignal'},
}


def source_fact(runtime, mission_id, fact_id):
    composed=runtime.replay_composed(mission_id)
    from .g3.contracts import EXTENSION_ID as G3
    from .g4.contracts import EXTENSION_ID as G4
    for name in (G3,G4):
        state=composed.extension_state(name)
        found=state.by_id(fact_id) if state is not None else None
        if found is not None:return found
    # G5 persists its typed diagnosis entities in the frozen R3.6 substrate.
    # The adapter reads that same event/identity; it does not invent a G5 store.
    with sqlite3.connect(str(runtime.db_path)) as conn:
        row=conn.execute("SELECT entity_type,payload_json,seq,created_at FROM events WHERE mission_id=? AND entity_id=? AND entity_type LIKE 'R3_6_%' ORDER BY seq DESC LIMIT 1",(mission_id,fact_id)).fetchone()
    if row:
        from .g5.service import _known_ref
        from types import SimpleNamespace
        identity=_known_ref(runtime,mission_id,fact_id);payload=json.loads(row[1])['entity']
        refs=tuple(str(x.get('ref_id') or x.get('object_id')) for x in payload.get('causal_chain_refs',[]) if isinstance(x,dict) and (x.get('ref_id') or x.get('object_id')))
        return SimpleNamespace(fact_id=fact_id,fact_kind=row[0],payload=payload,digest=identity['digest'],created_seq=row[2],created_at=row[3],provenance_refs=refs)
    return None


def candidate(runtime, mission_id, *, kind, subject, summary, source_fact_id, scope):
    from .g3.service import G3TestingIntelligenceService
    from .g3.contracts import _json
    if kind not in TYPES or not isinstance(summary,str) or not summary.strip() or len(summary.encode())>2048:
        raise RuntimeError('KNOWLEDGE_CANDIDATE_INVALID','Supported type and bounded summary required')
    scope=KnowledgeScopeIdentity.from_dict(scope)
    source=source_fact(runtime,mission_id,source_fact_id)
    if source is None: raise RuntimeError('KNOWLEDGE_SOURCE_FACT_REQUIRED',source_fact_id)
    now=source.created_at
    payload=_json({'kind':kind,'summary':summary,'source_revision':str(source.payload.get('revision') or source.created_seq)})
    identity=canonical_sha256({'scope':scope.to_dict(),'kind':kind,'subject':subject})
    fact_id='knowledge:'+identity[:24]; source_id='knowledge-source:'+source.digest
    with sqlite3.connect(str(runtime.db_path)) as conn:
        existing=conn.execute('SELECT state_json FROM r3e1_versions WHERE scope_key=? AND fact_id=?',(scope.key,fact_id)).fetchall()
    versions=[KnowledgeVersion.from_dict(json.loads(row[0])) for row in existing]
    same=next((v for v in versions if v.payload==payload and source_id in v.source_ref_ids),None)
    if same:return {'fact_id':fact_id,'version_id':same.version_id,'lifecycle':LIFECYCLE[same.status],'execution_eligible':False,'g6':'HOLD'}
    prior=max(versions,key=lambda v:v.version_number) if versions else None
    number=prior.version_number+1 if prior else 1
    version_id=fact_id+':'+str(number)
    fact=KnowledgeFact(fact_id,scope,subject,kind,{'identity':'scope/type/subject'},version_id,(subject,),{'kind':kind})
    version=KnowledgeVersion(version_id,fact_id,number,payload,scope,'CANDIDATE','UNVERIFIED',(source_id,),freshness_id='freshness:'+version_id,supersedes_version_id=prior.version_id if prior else None)
    ref=KnowledgeSourceRef(source_id,'RUNTIME','r1:'+source_fact_id,payload['source_revision'],source.digest,
                           scope,now,now,'BOUNDED_REFERENCE_ONLY',raw_content_ref='r1:'+source_fact_id)
    result=R3E1ApplicationService(runtime).register_version(mission_id=mission_id,fact=fact,version=version,source_refs=(ref,),
        idempotency_key='candidate:'+version_id)
    if not result.ok: raise result.error
    return {'fact_id':fact_id,'version_id':version_id,'lifecycle':'CANDIDATE','execution_eligible':False,'g6':'HOLD'}


def task_view(runtime, *, scope, task_id, query, role, refs=(), source_revisions=None, max_bytes=4096, max_items=12):
    scope=KnowledgeScopeIdentity.from_dict(scope)
    if not task_id or not isinstance(query,str) or not query.strip(): raise RuntimeError('KNOWLEDGE_TASK_REQUIRED','Task and intent are required')
    if not 512<=max_bytes<=8192 or not 1<=max_items<=32: raise RuntimeError('KNOWLEDGE_CONTEXT_BUDGET','512..8192 bytes, 1..32 items')
    kinds=ROLE_TYPES.get(role,set(TYPES)); terms=set(re.findall(r'[\w-]{2,}',query.lower()))
    now=datetime.now(timezone.utc); candidates=[]; excluded=0
    # Read the existing disposable SQL index. All records remain replayable R1
    # events; no query writes or independent vector/database authority exists.
    with sqlite3.connect('file:'+str(runtime.db_path)+'?mode=ro',uri=True) as conn:
        rows=conn.execute('''SELECT f.state_json,v.state_json FROM r3e1_facts f
            JOIN r3e1_versions v ON f.scope_key=v.scope_key AND f.current_version_id=v.version_id
            WHERE f.scope_key=? AND v.status IN ('RUNTIME_VERIFIED','USER_VERIFIED')
            AND length(CAST(f.state_json AS BLOB))<65536 AND length(CAST(v.state_json AS BLOB))<65536
            ORDER BY f.fact_id LIMIT 513''',(scope.key,)).fetchall()
        for raw_fact,raw_version in rows[:512]:
            fact=json.loads(raw_fact); version=json.loads(raw_version)
            kind=fact.get('metadata',{}).get('kind') or fact.get('predicate')
            if kind not in kinds: excluded+=1; continue
            fresh_row=conn.execute('SELECT state_json FROM r3e1_freshness WHERE scope_key=? AND freshness_id=?',
                                   (scope.key,version.get('freshness_id'))).fetchone()
            if not fresh_row: excluded+=1; continue
            fresh=json.loads(fresh_row[0]); valid=fresh.get('result')=='FRESH'
            for key in ('expires_at','next_check_at'):
                if fresh.get(key):
                    try: valid=valid and datetime.fromisoformat(fresh[key].replace('Z','+00:00'))>now
                    except (ValueError,TypeError): valid=False
            conflicts=conn.execute('SELECT state_json FROM r3e1_conflicts WHERE scope_key=?',(scope.key,)).fetchall()
            if any((c:=json.loads(x[0])).get('status')=='OPEN' and fact['fact_id']==c.get('fact_id') for x in conflicts): valid=False
            sources=[]
            for source_id in version.get('source_ref_ids',[]):
                row=conn.execute('SELECT state_json FROM r3e1_source_refs WHERE scope_key=? AND source_ref_id=?',(scope.key,source_id)).fetchone()
                if not row: valid=False; continue
                source=json.loads(row[0]); expected=(source_revisions or {}).get(source['locator'])
                if expected is not None and expected!=source['source_revision']: valid=False
                sources.append({k:source[k] for k in ('source_ref_id','source_revision','source_digest','locator')})
            if not valid or not sources: excluded+=1; continue
            fact_value=fact.get('value') if isinstance(fact.get('value'),dict) else {}
            text=str(version.get('payload',{}).get('summary') or fact_value.get('summary',''))
            anchored=len(set(refs)&set(fact.get('anchor_refs',[])))
            score=20*anchored+sum(t in (fact['subject']+' '+text).lower() for t in terms)
            if score==0: excluded+=1; continue
            candidates.append((score,{'fact_id':fact['fact_id'],'version_id':version['version_id'],'kind':kind,
              'status':'VERIFIED','anchor_refs':fact.get('anchor_refs',[])[:8],'summary':text[:1200],'digest':version['payload_digest'],'sources':sources[:4]}))
    candidates.sort(key=lambda x:(-x[0],x[1]['fact_id']))
    result={'authority':'R1_EVENT_STREAM','index':'R3_E1_SQLITE_PROJECTION','task_id':task_id,'scope':scope.to_dict(),
      'layers':['SourceTruth','DurableKnowledgeAssets','MissionWorkingMemory','SessionContext'],
      'items':[],'relations':[],'excluded_count':excluded,'truncated':len(rows)>512,'max_bytes':max_bytes,'g6':'HOLD'}
    seen=set()
    for _,item in candidates:
        if item['digest'] in seen: continue
        trial={**result,'items':result['items']+[item]}
        if len(result['items'])>=max_items or len(json.dumps(trial,ensure_ascii=False).encode())>max_bytes:
            result['truncated']=True; continue
        result['items'].append(item);seen.add(item['digest'])
    eligible={item['version_id'] for item in result['items']}|{item['fact_id'] for item in result['items']}
    with sqlite3.connect('file:'+str(runtime.db_path)+'?mode=ro',uri=True) as conn:
        relations=conn.execute('SELECT state_json FROM r3e1_relations WHERE scope_key=? AND length(CAST(state_json AS BLOB))<8192 LIMIT 513',(scope.key,)).fetchall()
    for row in relations[:512]:
        rel=json.loads(row[0])
        if rel.get('status') not in {'RUNTIME_VERIFIED','USER_VERIFIED'}:continue
        if not rel.get('freshness_id'):continue
        with sqlite3.connect('file:'+str(runtime.db_path)+'?mode=ro',uri=True) as conn:
            fresh_row=conn.execute('SELECT state_json FROM r3e1_freshness WHERE scope_key=? AND freshness_id=?',(scope.key,rel['freshness_id'])).fetchone()
        if not fresh_row:continue
        freshness=json.loads(fresh_row[0])
        if freshness.get('result')!='FRESH':continue
        try:
            if any(freshness.get(k) and datetime.fromisoformat(freshness[k].replace('Z','+00:00'))<=now for k in ('expires_at','next_check_at')):continue
        except (ValueError,TypeError):continue
        ends=[rel.get(k) or {} for k in ('from_ref','to_ref')]
        # Edges only connect eligible retrieved assets; they never smuggle
        # unverified/stale node content into an execution Context.
        if not all(e.get('version_id') in eligible or e.get('ref_id') in eligible for e in ends):continue
        edge={k:rel[k] for k in ('relation_id','semantic','from_ref','to_ref')}
        trial={**result,'relations':result['relations']+[edge]}
        if len(json.dumps(trial,ensure_ascii=False).encode())>max_bytes:result['truncated']=True;break
        result['relations'].append(edge)
    if len(json.dumps(result,ensure_ascii=False).encode())>max_bytes: raise RuntimeError('KNOWLEDGE_METADATA_BUDGET','Scope exceeds budget')
    return result


def session_view(runtime, mission_id, task_id, role):
    state=runtime.replay_composed(mission_id); mission=state.core_state.mission
    goal=state.core_state.goal(mission.active_goal_id) if mission and mission.active_goal_id else None
    task=state.extension_state('r1_2_work_graph').task(task_id)
    scope=(goal.definition.get('execution_scope') or {}) if goal else {}
    if not all(scope.get(k) for k in ('project_id','environment_id')) or not (scope.get('version_scope') or scope.get('version')):
        return {'authority':'R1_EVENT_STREAM','items':[],'status':'KNOWLEDGE_EXACT_SCOPE_REQUIRED'}
    return task_view(runtime,scope={'project_id':scope['project_id'],'environment_id':scope['environment_id'],
      'version_scope':scope.get('version_scope') or scope['version']},task_id=task_id,
      query=task.intent if task else task_id,role=role,refs=scope.get('requirements',[]))


def review(runtime,root,mission_id,version_id):
    """Human-authored local review plus canonical execution proof, never G6."""
    from pathlib import Path
    from .r3_e1.contracts import KnowledgeFreshness
    path=Path(root)/'bindings/knowledge-reviews.json'
    approvals=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
    entry=next((a for a in approvals if a.get('version_id')==version_id and a.get('approved') is True),None)
    if not entry or not entry.get('reviewer') or not entry.get('approval_ref'):raise RuntimeError('KNOWLEDGE_HUMAN_REVIEW_REQUIRED',version_id)
    with sqlite3.connect(str(runtime.db_path)) as conn:
        rows=conn.execute('SELECT state_json FROM r3e1_versions WHERE version_id=?',(version_id,)).fetchall()
        if len(rows)!=1:raise RuntimeError('KNOWLEDGE_VERSION_REQUIRED',version_id)
        version=KnowledgeVersion.from_dict(json.loads(rows[0][0]));sources=[]
        for sid in version.source_ref_ids:
            row=conn.execute('SELECT state_json FROM r3e1_source_refs WHERE scope_key=? AND source_ref_id=?',(version.scope_identity.key,sid)).fetchone()
            if not row:raise RuntimeError('KNOWLEDGE_SOURCE_REQUIRED',sid)
            sources.append(KnowledgeSourceRef.from_dict(json.loads(row[0])))
    if entry.get('payload_digest')!=version.payload_digest:raise RuntimeError('KNOWLEDGE_REVIEW_DIGEST_MISMATCH',version_id)
    proof=source_fact(runtime,mission_id,entry.get('evidence_ref'))
    if proof is None or proof.fact_kind!='EXECUTION_STEP_RESULT' or proof.payload.get('oracle_result')!='PASS' or not proof.payload.get('evidence_refs'):
        raise RuntimeError('KNOWLEDGE_RUNTIME_EVIDENCE_REQUIRED','Canonical G4 passing execution with Evidence required')
    for source in sources:
        bound=source_fact(runtime,mission_id,source.locator.removeprefix('r1:'))
        if bound is None or bound.digest!=source.source_digest:raise RuntimeError('KNOWLEDGE_SOURCE_REVISION_CHANGED',source.source_ref_id)
    now=datetime.now(timezone.utc);expires=datetime.fromisoformat(entry['expires_at'].replace('Z','+00:00'))
    if not now<expires<=now+timedelta(days=30):raise RuntimeError('KNOWLEDGE_FRESHNESS_WINDOW_REQUIRED','Review expiry within 30 days required')
    app=R3E1ApplicationService(runtime);current=version.status
    transitions={'CANDIDATE':'SOURCE_VERIFIED','SOURCE_VERIFIED':'RUNTIME_VERIFIED','RUNTIME_VERIFIED':'USER_VERIFIED'}
    proof_data={'source_verification_ref':sources[0].locator,'runtime_evidence_ref':proof.fact_id,'user_verification_ref':entry['approval_ref']}
    while current in transitions:
        target=transitions[current]
        result=app.transition_lifecycle(mission_id=mission_id,scope_identity=version.scope_identity,version_id=version_id,
          from_status=current,to_status=target,proof=proof_data,source_refs=sources,actor={'type':'HUMAN','id':entry['reviewer']})
        if not result.ok:raise result.error
        current=target
    if current!='USER_VERIFIED':raise RuntimeError('KNOWLEDGE_LIFECYCLE_REVIEW_REJECTED',current)
    fresh=KnowledgeFreshness(version.freshness_id,version_id,version.scope_identity,'rec3-human-reviewed-v1',now.isoformat(),expires.isoformat(),None,'FRESH',version.source_ref_ids)
    result=app.record_freshness(mission_id=mission_id,freshness=fresh,source_refs=sources,idempotency_key='review:'+entry['approval_ref'])
    if not result.ok:raise result.error
    return {'version_id':version_id,'lifecycle':'VERIFIED','review_ref':entry['approval_ref'],'g6':'HOLD','automatic_promotion':False}


def dispatch(root,action,payload):
    from .canonical_runtime import create_canonical_runtime
    runtime=create_canonical_runtime(root);data=dict(payload)
    if action=='candidate': result=candidate(runtime,**data)
    elif action=='task_view':result=task_view(runtime,**data)
    elif action=='apply_review':result=review(runtime,root,**data)
    elif action=='link':result=link(runtime,**data)
    else:raise RuntimeError('KNOWLEDGE_ACTION_UNSUPPORTED','Candidate, task_view and locally authorized review only; G6 promotion remains HOLD')
    return {'truth_source':'R1_EVENT_STREAM',**result}


def link(runtime,mission_id,from_version_id,to_version_id):
    """Derive a typed dependency only from verified canonical source references."""
    from .r3_e1.contracts import KnowledgeEndpointRef,KnowledgeRelation
    versions=[];sources=[]
    with sqlite3.connect(str(runtime.db_path)) as conn:
        for vid in (from_version_id,to_version_id):
            rows=conn.execute('''SELECT v.state_json FROM r3e1_versions v JOIN r3e1_facts f
                ON v.scope_key=f.scope_key AND v.version_id=f.current_version_id WHERE v.version_id=?''',(vid,)).fetchall()
            if len(rows)!=1:raise RuntimeError('KNOWLEDGE_CURRENT_VERSION_REQUIRED',vid)
            v=KnowledgeVersion.from_dict(json.loads(rows[0][0]))
            if v.status not in {'RUNTIME_VERIFIED','USER_VERIFIED'}:raise RuntimeError('KNOWLEDGE_VERIFIED_ENDPOINT_REQUIRED',vid)
            versions.append(v);refs=[]
            for sid in v.source_ref_ids:
                row=conn.execute('SELECT state_json FROM r3e1_source_refs WHERE scope_key=? AND source_ref_id=?',(v.scope_identity.key,sid)).fetchone()
                if not row:raise RuntimeError('KNOWLEDGE_SOURCE_REQUIRED',sid)
                refs.append(KnowledgeSourceRef.from_dict(json.loads(row[0])))
            sources.append(refs)
    a,b=versions
    if a.scope_identity!=b.scope_identity:raise RuntimeError('KNOWLEDGE_RELATION_SCOPE_MISMATCH','Exact common scope required')
    target_ids={s.locator.removeprefix('r1:') for s in sources[1]}
    referenced=set()
    for source in sources[0]:
        fact=source_fact(runtime,mission_id,source.locator.removeprefix('r1:'))
        if fact is None or fact.digest!=source.source_digest:raise RuntimeError('KNOWLEDGE_SOURCE_REVISION_CHANGED',source.source_ref_id)
        referenced.update(fact.provenance_refs)
        for key in ('source_refs','parent_refs'):
            referenced.update(x for x in fact.payload.get(key,[]) if isinstance(x,str))
    if not referenced&target_ids:raise RuntimeError('KNOWLEDGE_RELATION_PROVENANCE_REQUIRED','Sources do not establish this dependency')
    refs=tuple({s.source_ref_id:s for group in sources for s in group}.values())
    end=lambda v:KnowledgeEndpointRef(v.fact_id,'SYSTEM_TOPOLOGY',v.version_id,v.scope_identity,v.source_ref_ids)
    relation=KnowledgeRelation('knowledge-link:'+canonical_sha256({'from':a.version_id,'to':b.version_id})[:24],end(a),end(b),
        'DEPENDS_ON',a.scope_identity,'RUNTIME_VERIFIED',tuple(s.source_ref_id for s in refs),freshness_id=a.freshness_id)
    result=R3E1ApplicationService(runtime).record_relation(mission_id=mission_id,relation=relation,source_refs=refs)
    if not result.ok:raise result.error
    return {'relation_id':relation.relation_id,'semantic':'DEPENDS_ON','g6':'HOLD','source_derived':True}
