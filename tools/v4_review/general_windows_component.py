"""Actual Windows product file-broker/R1 tests; not process confinement or L4."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if os.name!='nt': raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
    repo=Path(__file__).resolve().parents[2];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    for k in ('GH_TOKEN','GITHUB_TOKEN'):os.environ.pop(k,None)
    sys.dont_write_bytecode=True
    suite=unittest.TestSuite()
    for name in ('test_general_execution.py','test_interaction_admission.py','test_interaction_receipts.py','test_general_worker_entry.py','test_primary_sessions.py'):
        suite.addTests(unittest.TestLoader().discover(str(repo/'tests/v4'),pattern=name))
    suite.addTests(unittest.TestLoader().discover(str(repo/'workspace-template/.pfc-internal-field-validation/tests'),pattern='test_v4_typed_roots.py'))
    with (out/'general-windows-tests.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    identity={'classification':'ACTUAL_WINDOWS_FILE_BROKER_R1_COMPONENT_NOT_L4','source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'platform':platform.platform(),'python':sys.version,'run_id':os.environ.get('GITHUB_RUN_ID'),
        'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':[(str(t),why) for t,why in result.skipped],
        'status':'PASS' if result.wasSuccessful() else 'FAIL','process_confinement':'NOT_QUALIFIED','bank_field':'NOT_RUN',
        'log_sha256':hashlib.sha256((out/'general-windows-tests.log').read_bytes()).hexdigest()}
    (out/'general-windows-result.json').write_text(json.dumps(identity,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(identity,indent=2));return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
