"""Host-owned message transport fixture for real F53 product entry tests.

Only host HTTP responses are synthetic. Admission, R1 receipts, scope resolution,
Mission/Session creation and every downstream product operation remain real.
"""
from __future__ import annotations
import time
from unittest.mock import patch


def host_turn(scope, *, session='fixture-host', message='fixture-user', text=None):
    scope={k:v for k,v in scope.items() if k in {'mode','project_id','version','requirements'}}
    if text is None:
        values=[]
        for key,value in scope.items():
            if key=='mode':continue
            values.extend(value if isinstance(value,list) else [value])
        text='测试 '+' '.join(values)
    assistant=message+'-assistant'
    messages={
        f'/session/{session}/message/{assistant}':{'info':{'sessionID':session,'id':assistant,'role':'assistant','parentID':message}},
        f'/session/{session}/message/{message}':{'info':{'sessionID':session,'id':message,'role':'user','time':{'created':int(time.time()*1000)}},
            'parts':[{'type':'text','text':text,'sessionID':session,'messageID':message}]},
    }
    env={'AITEST_HOST_SESSION_ID':session,'AITEST_HOST_MESSAGE_ID':assistant}
    return messages,env,{'scope':scope} if scope else {}


def start_product_mission(service, request, *, fixture_id):
    from aitest_runtime import product_entry
    from aitest_runtime.interaction_receipts import R1InteractionOwner
    from urllib.parse import urlparse
    provider=getattr(service,'raw_session_provider',service.session_provider)
    messages,env,payload=host_turn(request['scope'],session='host-'+fixture_id,message='user-'+fixture_id)
    reads=[]
    def read(method,path):
        assert method=='GET'
        reads.append(path)
        return messages[urlparse(path).path]
    import os
    with patch.dict(os.environ,env),patch.object(provider,'_request',side_effect=read,create=True),patch.object(provider,'_directory_query',return_value='directory=fixture',create=True):
        result=product_entry.orchestration_command('DIRECTOR','start_test',payload)
    operation=result['operations'][0]
    assert operation['status']=='DISPATCHED',operation
    assert len(reads)==2,reads
    receipt=R1InteractionOwner(service.runtime).receipt(operation['operation_id'])
    assert receipt['state']=='COMPLETED' and receipt['bound_subject']==operation['subject'],receipt
    return result
