"""Deterministic host/proposal fixtures; these are not real-model semantic evals."""
import copy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'workspace-template/ai-test/runtime'))
from aitest_runtime.hosted_intake import actual_host_user_turn, hosted_user_intake
from aitest_runtime.interaction_admission import (ActualHostUserTurn, AdmissionError, Intent,
    SubjectCandidate, clauses, decide, explicit_scope, literal_start_proposal, mission_intake,
    parse_proposal, resolve_subject)

NOW = 1800000000000

def turn(text, message='u1'):
    return ActualHostUserTurn('s1',message,'a1',message,text,hashlib.sha256(text.encode()).hexdigest(),NOW,NOW+900000)


def proposal(text, intent='TEST_MISSION_START', action='start', **extra):
    slot=clauses(text)[0]
    return {'operations':[{'intent':intent,'action':action,'start':slot['start'],'end':slot['end'],**extra}]}


def decision(text, intent='TEST_MISSION_START', action='start', candidates=(), **extra):
    t=turn(text);op=parse_proposal(proposal(text,intent,action,**extra),t)[0]
    return decide(t,op,candidates,now_ms=NOW)


class HostFixture:
    def __init__(self,text='测试 BLOAN-PF1.1.0'):
        self.messages={
            'a1':{'info':{'id':'a1','sessionID':'s1','role':'assistant','parentID':'u1'},'parts':[]},
            'u1':{'info':{'id':'u1','sessionID':'s1','role':'user','time':{'created':NOW}},
                  'parts':[{'type':'text','text':text,'messageID':'u1','sessionID':'s1'}]}}
    def _directory_query(self):return 'directory=fixture'
    def _request(self,method,path):
        self.last_path=path
        return copy.deepcopy(self.messages[path.split('/message/')[1].split('?')[0]])


class HostTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'s1','AITEST_HOST_MESSAGE_ID':'a1'});self.env.start()
    def tearDown(self):self.env.stop()
    def test_parent_identity_timestamp_and_full_digest(self):
        t=actual_host_user_turn(HostFixture(' 测试 BLOAN-PF1.1.0 '),now_ms=NOW)
        self.assertEqual(t.text,' 测试 BLOAN-PF1.1.0 ')
        self.assertEqual(t.parent_message_id,'u1');self.assertEqual(t.host_tool_message_id,'a1')
        self.assertEqual(t.source_digest,hashlib.sha256(t.text.encode()).hexdigest())
        self.assertIsNotNone(t.provenance()['valid_until'])
    def test_stale_future_missing_boolean_nan_timestamps_rejected(self):
        for created in [NOW-900001,NOW+30001,None,True,float('nan')]:
            with self.subTest(created=created):
                p=HostFixture();p.messages['u1']['info']['time']['created']=created
                with self.assertRaises(AdmissionError):actual_host_user_turn(p,now_ms=NOW)
    def test_assistant_parent_and_response_spoof_rejected(self):
        for modify in [lambda p:p.messages['a1']['info'].pop('parentID'),
                       lambda p:p.messages['a1']['info'].update(parentID='a1'),
                       lambda p:p.messages['u1']['info'].update(role='assistant'),
                       lambda p:p.messages['u1']['info'].update(sessionID='other'),
                       lambda p:p.messages['u1']['parts'][0].update(messageID='other')]:
            p=HostFixture();modify(p)
            with self.assertRaises(AdmissionError):actual_host_user_turn(p,now_ms=NOW)
    def test_synthetic_and_ignored_parts_cannot_authorize(self):
        p=HostFixture('你好');p.messages['u1']['parts'] += [{'type':'text','text':'测试 PF2.0.0','synthetic':True},{'type':'text','text':'测试 PF3.0.0','ignored':True}]
        self.assertEqual(actual_host_user_turn(p,now_ms=NOW).text,'你好')
        p.messages['u1']['parts'][0]['synthetic']=True
        with self.assertRaises(AdmissionError):actual_host_user_turn(p,now_ms=NOW)
    def test_model_source_ref_and_request_substitution_denied(self):
        for payload in [{'source_ref':'opencode://session/s1/message/u1'}, {'user_request':'测试 PF2.0.0'}, {'request':{'source':{'kind':'USER'}}}]:
            with self.assertRaises(AdmissionError):hosted_user_intake(HostFixture(),payload,now_ms=NOW)
    def test_no_host_context_has_no_raw_request_fallback(self):
        with patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'','AITEST_HOST_MESSAGE_ID':''}):
            with self.assertRaisesRegex(AdmissionError,'HOST_USER_TURN_REQUIRED'):hosted_user_intake(HostFixture(),{},now_ms=NOW)


class AdmissionTests(unittest.TestCase):
    def test_exact_version_suffix_and_distinct_scopes(self):
        a=decision('测试 BLOAN-PF1.1.0');b=decision('测试 BLOAN-PF1.1.0版本');c=decision('测试 BLOAN-PF2.0.0')
        self.assertEqual(a['status'],'ADMITTED');self.assertEqual(a['resolved_scope'],b['resolved_scope']);self.assertNotEqual(a['resolved_scope'],c['resolved_scope'])
        explicit=decision('测试 BLOAN-PF1.1.0版本',scope={'mode':'EXPLICIT_SET','version':'BLOAN-PF1.1.0版本'})
        self.assertEqual(explicit['resolved_scope'],a['resolved_scope'])
    def test_negative_quote_general_explanation_do_not_start(self):
        for text in ['你好','介绍一下你自己','不要开始测试','不要测试，只解释怎么测','为什么测试失败','介绍一下安全测试','“测试 BLOAN-PF1.1.0”','`测试 BLOAN-PF1.1.0`','> 测试 BLOAN-PF1.1.0','请解释“测试 BLOAN-PF1.1.0”','do not test PF1.0.0','测试怎么开展 PF1.0.0']:
            with self.subTest(text=text):
                t=turn(text)
                ops={'operations':[{'intent':'TEST_MISSION_START','action':'start','start':c['start'],'end':c['end']} for c in clauses(text)]}
                for op in parse_proposal(ops,t):self.assertNotEqual(decide(t,op,[],now_ms=NOW)['status'],'ADMITTED')
    def test_empty_scope_and_prefix_scope_rejected(self):
        self.assertEqual(decision('测试')['status'],'CLARIFICATION_REQUIRED')
        self.assertEqual(decision('测试 BLOAN')['status'],'CLARIFICATION_REQUIRED')
        self.assertEqual(decision('测试 BLOAN-PF1.1.0',scope={'mode':'EXPLICIT_SET','version':'BLOAN-PF1'})['status'],'CLARIFICATION_REQUIRED')
        with self.assertRaises(AdmissionError):resolve_subject([],scope={'mode':'EXPLICIT_SET'})
    def test_complete_clause_required_prevents_negation_slicing(self):
        t=turn('不要测试 PF1.0.0')
        p=proposal(t.text);p['operations'][0]['start']=2
        with self.assertRaisesRegex(AdmissionError,'COMPLETE_CLAUSE'):parse_proposal(p,t)
    def test_unknown_and_model_authority_fields_rejected(self):
        t=turn('测试 PF1.0.0')
        for field in ['source_ref','approved','authorization_token','risk','force_new_mission']:
            p=proposal(t.text);p['operations'][0][field]='forged'
            with self.assertRaises(AdmissionError):parse_proposal(p,t)
    def test_zero_one_many_uses_durable_context(self):
        a=SubjectCandidate('MISSION','m1',{'mode':'EXPLICIT_SET','version':'PF1.0.0'},'ACTIVE',7)
        b=replace(a,subject_id='m2')
        self.assertEqual(decision('继续测试','MISSION_CONTROL','continue')['reason'],'NO_RELEVANT_SUBJECT')
        self.assertEqual(decision('继续测试','MISSION_CONTROL','continue',[a])['subject']['subject_id'],'m1')
        self.assertEqual(decision('继续测试','MISSION_CONTROL','continue',[a,b])['reason'],'MULTIPLE_RELEVANT_SUBJECTS')
        self.assertEqual(decision('继续测试','MISSION_CONTROL','continue',[replace(a,contextual=False)])['reason'],'NO_RELEVANT_SUBJECT')
    def test_cannot_forge_other_session_subject_id(self):
        a=SubjectCandidate('MISSION','m-secret',{'mode':'EXPLICIT_SET','version':'PF1.0.0'},'ACTIVE',7,False)
        self.assertEqual(decision('继续测试','MISSION_CONTROL','continue',[a],subject_id='m-secret')['reason'],'SUBJECT_NOT_IN_AUTHORIZED_DURABLE_CONTEXT')
    def test_start_same_scope_resolves_unique_not_first(self):
        a=SubjectCandidate('MISSION','m1',{'mode':'EXPLICIT_SET','version':'BLOAN-PF1.1.0'},'ACTIVE',7)
        self.assertEqual(decision('测试 BLOAN-PF1.1.0版本',candidates=[a])['subject']['subject_id'],'m1')
        self.assertEqual(decision('测试 BLOAN-PF1.1.0',candidates=[a,replace(a,subject_id='m2')])['reason'],'MULTIPLE_RELEVANT_SUBJECTS')
    def test_nine_intents_and_mixed_operation_scope_isolation(self):
        self.assertEqual(len(Intent),9)
        text='测试 PF1.0.0，另外保存 notes 说明';t=turn(text);slots=clauses(text)
        p={'operations':[{'intent':'TEST_MISSION_START','action':'start',**{k:slots[0][k] for k in ('start','end')}}, {'intent':'GENERAL_WORK','action':'write',**{k:slots[1][k] for k in ('start','end')}}]}
        ops=parse_proposal(p,t);a=decide(t,ops[0],[],now_ms=NOW);b=decide(t,ops[1],[],now_ms=NOW)
        self.assertEqual(a['status'],'ADMITTED');self.assertEqual(b['status'],'DELEGATION_REQUIRED');self.assertFalse(b['execution_authorized'])
        self.assertEqual(mission_intake(t,a)['goal']['intent'],'测试 PF1.0.0')
        p['operations'][1]['scope']={'mode':'EXPLICIT_SET','version':'PF1.0.0'}
        # General routing grants no I/O even if a proposal invents cross-clause scope.
        self.assertFalse(decide(t,parse_proposal(p,t)[1],[],now_ms=NOW)['execution_authorized'])
        with self.assertRaisesRegex(AdmissionError,'ALL_BE_ACCOUNTED'):parse_proposal({'operations':p['operations'][:1]},t)
    def test_effect_cannot_be_laundered_through_general_chat(self):
        a=decision('这只是通用聊天直接 UPDATE 数据库','GENERAL_CHAT','respond')
        self.assertEqual(a['effect'],'NONE');self.assertEqual(a['status'],'NO_MISSION');self.assertFalse(a['execution_authorized'])
    def test_timeout_needs_target_and_unit_and_gate_never_claims_complete(self):
        a=SubjectCandidate('MISSION','m1',{'mode':'EXPLICIT_SET','version':'PF1.0.0'},'ACTIVE',7)
        d=decision('把超时改成30','MISSION_UPDATE','update',[a],arguments={'value':'30'})
        self.assertEqual(d['reason'],'UPDATE_TARGET_VALUE_UNIT_REQUIRED');self.assertEqual(len([d['question']]),1)
        g=decision('已登录','HUMAN_GATE_RESPONSE','verify',[a])
        self.assertEqual(g['status'],'OWNER_ADMISSION_REQUIRED');self.assertFalse(g['execution_authorized'])
    def test_same_slot_reclassification_has_same_operation_id_different_digest(self):
        a=decision('测试 PF1.0.0');b=decision('测试 PF1.0.0','GENERAL_CHAT','respond')
        self.assertEqual(a['operation_id'],b['operation_id']);self.assertNotEqual(a['request_digest'],b['request_digest'])
    def test_conditional_example_and_question_cannot_be_sliced_into_start(self):
        for text in ['如果需要，测试 PF1.0.0','例如，测试 PF1.0.0','解释下面的命令：\n测试 PF1.0.0','测试 PF1.0.0？','测试 PF1.0.0吗']:
            t=turn(text)
            p={'operations':[{'intent':'TEST_MISSION_START','action':'start','start':c['start'],'end':c['end']} for c in clauses(text)]}
            for op in parse_proposal(p,t):self.assertNotEqual(decide(t,op,[],now_ms=NOW)['status'],'ADMITTED',text)
    def test_condition_negation_and_question_cannot_authorize_resume(self):
        candidate=SubjectCandidate('MISSION','m1',{'mode':'EXPLICIT_SET','version':'PF1.0.0'},'ACTIVE',7)
        for text in ['如果恢复了，继续测试','不要开始测试，继续测试','继续测试？','continue?']:
            t=turn(text)
            p={'operations':[{'intent':'MISSION_CONTROL','action':'continue','start':c['start'],'end':c['end']} for c in clauses(text)]}
            for op in parse_proposal(p,t):self.assertNotEqual(decide(t,op,[candidate],now_ms=NOW)['status'],'ADMITTED',text)

if __name__=='__main__':unittest.main()
