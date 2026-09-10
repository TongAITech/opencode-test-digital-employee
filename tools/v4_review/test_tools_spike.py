"""S7: real tools against disposable loopback data; never bank/product qualification."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, secrets, shutil, socket, sqlite3
import subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=pathlib.Path,required=True)
    p.add_argument('--runtime',type=pathlib.Path)
    p.add_argument('--coverage',action='store_true')
    a=p.parse_args(); out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    result={'scope':'S7_ISOLATED_REAL_TOOL_INTEGRATION', 'product_default_adapters':'NOT_PROVEN',
            'bank_field':'NOT_RUN', 'python':sys.version, 'checks':{}, 'started':time.time()}
    checks=result['checks']; env=dict(os.environ)
    for key in list(env):
        if key.lower().endswith('_proxy') or key in ('GH_TOKEN','GITHUB_TOKEN'): env.pop(key,None)
    env.update(PYTHONUTF8='1',NO_PROXY='127.0.0.1,localhost',PIP_NO_INDEX='1')
    def run(name,cmd,cwd=out,timeout=120):
        started=time.time()
        completed=subprocess.run(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        log=out/(name+'.log');log.write_bytes(completed.stdout)
        return {'exit_code':completed.returncode,'elapsed_s':time.time()-started,'log':log.name,'sha256':digest(log)}
    counts={'requests':0,'cat':0,'security':0}; cat_requests=[]; token=secrets.token_hex(12)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def answer(self,code,value,kind='application/json'):
            payload=json.dumps(value).encode() if kind=='application/json' else value.encode()
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(payload)));self.end_headers()
            try: self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError): pass
        def do_GET(self):
            counts['requests']+=1
            if urlparse(self.path).path=='/search':
                counts['security']+=1
                return self.answer(200,'<html><body><form><input name="q"></form>'+parse_qs(urlparse(self.path).query).get('q',[''])[0]+'</body></html>','text/html')
            return self.answer(200,{'status':'READY','business_value':42})
        def do_POST(self):
            counts['requests']+=1
            body=self.rfile.read(min(int(self.headers.get('Content-Length','0')),65536))
            if self.path=='/ShakaMockApi/cat/getAll':
                counts['cat']+=1
                if self.headers.get('authorization')!=token:return self.answer(401,{'error':'AUTH_REQUIRED'})
                query=json.loads(body);cat_requests.append(query)
                return self.answer(200,{'records':[{'correlation':query['caseId'],'message':'SYNTHETIC_EXPECTED_RECORD'}]})
            return self.answer(200,{'id':'synthetic','accepted':True})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    try:
        import httpx
        with httpx.Client(trust_env=False,timeout=5) as client:
            response=client.get(origin+'/health'); assert response.json()['business_value']==42
            checks['HTTPX']={'status':'PASS','version':httpx.__version__,'actual_http':True}
            query={'env':'SYNTHETIC','startTime':'2026-01-01 00:00:00','endTime':'2026-01-01 00:01:00',
                   'appIds':[101],'tags':'review','caseId':'S7-CAT','size':10,'message':'loan',
                   'messageQuery':{'conditions':['trace=S7'],'operators':['AND']}}
            response=client.post(origin+'/ShakaMockApi/cat/getAll',headers={'authorization':token},json=query)
            assert response.json()['records'][0]['correlation']=='S7-CAT' and cat_requests==[query]
            assert client.post(origin+'/ShakaMockApi/cat/getAll',json=query).status_code==401
            checks['CAT_HTTP']={'status':'PASS_COMPONENT_FIXTURE','header':'authorization','query':query,
                               'real_bank_auth':'NOT_RUN','canonical_default_wiring':'NOT_IMPLEMENTED',
                               'legacy_source_semantics':'POST_getAll_ENV_TIMES_APPIDS_TAGS_CASEID_SIZE_MESSAGE_MESSAGEQUERY',
                               'subenv_fallback':'NOT_PROVEN'}
        db=out/'synthetic.db';con=sqlite3.connect(db)
        con.execute('create table loans(id text primary key, amount integer check(amount>0))')
        con.execute('insert into loans values(?,?)',('L1',100));con.commit()
        con.execute('update loans set amount=200 where id=?',('L1',));con.rollback()
        assert con.execute('select amount from loans where id=?',('L1',)).fetchone()==(100,)
        try:con.execute('insert into loans values(?,?)',('BAD',-1));raise AssertionError('DB_CONSTRAINT_NOT_ENFORCED')
        except sqlite3.IntegrityError:con.rollback()
        con.close();con=sqlite3.connect(db);assert con.execute('select count(*) from loans').fetchone()==(1,);con.close()
        checks['DB']={'status':'PASS_SQLITE_ONLY','version':sqlite3.sqlite_version,'commit_rollback_restart_constraint':True,
                      'vendor_mysql_tdsql_oceanbase_tidb':'NOT_PROVEN','sha256':digest(db)}
        unit=out/'unit';unit.mkdir()
        module=unit/'business.py';module.write_text('def eligible(amount):\n    if amount <= 0:\n        raise ValueError("positive amount required")\n    return amount <= 100\n')
        (unit/'test_business.py').write_text('import pytest\nfrom business import eligible\ndef test_allowed(): assert eligible(100) is True\ndef test_rejected(): assert eligible(101) is False\ndef test_invalid():\n    with pytest.raises(ValueError): eligible(0)\n')
        cmd=[sys.executable,'-m','coverage','run','--branch','--source=business','-m','pytest','-q'] if a.coverage else [sys.executable,'-m','pytest','-q']
        good=run('unit-positive',cmd,unit);assert good['exit_code']==0
        unit_result={'status':'PASS','positive':good,'source_sha256':digest(module),'coverage':'NOT_RUN'}
        if a.coverage:
            covrun=run('coverage-json',[sys.executable,'-m','coverage','json','-o',str(out/'coverage.json')],unit)
            assert covrun['exit_code']==0
            cov=json.loads((out/'coverage.json').read_text());assert cov['totals']['percent_covered']==100
            unit_result['coverage']={'version':cov['meta']['version'],'totals':cov['totals'],'report_sha256':digest(out/'coverage.json'),'scope':'SYNTHETIC_THREE_BRANCH_FUNCTION_ONLY'}
        mutant=out/'mutant';shutil.copytree(unit,mutant,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.coverage'))
        mutant_module=mutant/'business.py';mutant_module.write_text(module.read_text().replace('return amount <= 100','return True'))
        bad=run('unit-negative',[sys.executable,'-m','pytest','-q'],mutant);assert bad['exit_code']==1
        unit_result['negative_mutant_rejected']=bad; checks['UNIT']=unit_result
        suffix='.exe' if os.name=='nt' else ''
        k6=a.runtime/'tools/k6'/('k6'+suffix) if a.runtime else pathlib.Path('/UNAVAILABLE')
        if k6.is_file():
            source=out/'load.js'
            source.write_text("import http from 'k6/http'; import {check,sleep} from 'k6';\nexport const options={vus:2,duration:'3s',thresholds:{http_req_failed:['rate==0'],checks:['rate==1']}};\nexport default function(){const r=http.get("+json.dumps(origin+ '/health')+");check(r,{'business':r=>r.status===200&&r.json('business_value')===42});sleep(0.1);}\n")
            perf=run('k6',[str(k6.resolve()),'run','--no-usage-report','--summary-export',str(out/'k6-summary.json'),str(source)])
            summary=json.loads((out/'k6-summary.json').read_text());assert perf['exit_code']==0 and summary['metrics']['http_reqs']['count']>0
            checks['PERFORMANCE']={'status':'PASS_REAL_K6_SYNTHETIC_LOAD','run':perf,'binary_sha256':digest(k6),'summary_sha256':digest(out/'k6-summary.json'),'metrics':summary['metrics']}
        else:checks['PERFORMANCE']={'status':'NOT_RUN_HOST_PAYLOAD_UNAVAILABLE'}
        java=a.runtime/'tools/java/bin'/('java'+suffix) if a.runtime else pathlib.Path('/UNAVAILABLE')
        jars=list((a.runtime/'tools/zap').glob('zap-*.jar')) if a.runtime else []
        if java.is_file() and jars:
            home=out/'zap-home';home.mkdir();zaplog=open(out/'zap-process.log','wb')
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            key=secrets.token_hex(12)
            cmd=[str(java.resolve()),'-Xmx512m','-jar',str(jars[0].resolve()),'-daemon','-host','127.0.0.1','-port',str(port),'-dir',str(home),
                 '-config','api.key='+key,'-config','autoupdate.checkOnStart=false','-config','autoupdate.downloadNewRelease=false','-config','autoupdate.installAddonUpdates=false',
                 '-config','connection.dnsTtlSuccessfulQueries=-1']
            proc=subprocess.Popen(cmd,cwd=jars[0].parent,env=env,stdout=zaplog,stderr=subprocess.STDOUT)
            try:
                with httpx.Client(trust_env=False,timeout=5) as client:
                    def api(component,kind,name,**params):
                        r=client.get(f'http://127.0.0.1:{port}/JSON/{component}/{kind}/{name}/',params={'apikey':key,**params});r.raise_for_status();return r.json()
                    deadline=time.time()+100
                    while True:
                        try: version=api('core','view','version');break
                        except Exception:
                            if proc.poll() is not None or time.time()>deadline:raise
                            time.sleep(1)
                    target=origin+'/search?q=hello';api('core','action','accessUrl',url=target,followRedirects='false')
                    api('ascan','action','setOptionMaxScanDurationInMins',Integer='1')
                    scan=api('ascan','action','scan',url=target,recurse='false',inScopeOnly='false')['scan']
                    deadline=time.time()+100
                    while int(api('ascan','view','status',scanId=scan)['status'])<100:
                        if time.time()>deadline:raise TimeoutError('ZAP active scan timeout')
                        time.sleep(1)
                    messages=api('core','view','numberOfMessages',baseurl=origin)
                    alerts=api('core','view','alerts',baseurl=origin,start='0',count='100')
                    assert int(messages['numberOfMessages'])>1 and counts['security']>1
                    (out/'zap-alerts.json').write_text(json.dumps(alerts,indent=2))
                    checks['SECURITY']={'status':'PASS_REAL_ZAP_ACTIVE_SYNTHETIC_TARGET','version':version,'jar_sha256':digest(jars[0]),'message_count':messages,
                                        'target_requests':counts['security'],'alerts_sha256':digest(out/'zap-alerts.json'),'business_security_coverage':'NOT_PROVEN'}
                    api('core','action','shutdown')
            finally:
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10)
                zaplog.close()
        else:checks['SECURITY']={'status':'NOT_RUN_HOST_PAYLOAD_UNAVAILABLE'}
        result['status']='COMPONENT_SPIKE_COMPLETE'
    except Exception as e:
        import traceback
        result.update(status='FAILED',error=repr(e),traceback=traceback.format_exc())
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
        result.update(request_counts=counts,finished=time.time())
        (out/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
    return 1 if result['status']=='FAILED' else 0

if __name__=='__main__':raise SystemExit(main())
