"""CI construction only: pre-existing host fixture, outside both installations.

Copies existing hash-verified construction bytes, never downloads. This is not
product provider projection; installation and launcher never run this script.
"""
import argparse
import json
from pathlib import Path
import shutil

p=argparse.ArgumentParser();p.add_argument('--carrier',type=Path,required=True);p.add_argument('--host',type=Path,required=True)
a=p.parse_args();host=a.host.resolve();host.mkdir(parents=True,exist_ok=False)
bin=host/'bin';bin.mkdir();shutil.copy2(a.carrier/'workspace-template/runtime/opencode/opencode.exe',bin/'opencode.exe')
config=host/'config/opencode';config.mkdir(parents=True)
shutil.copytree(a.carrier/'workspace-template/.opencode/node_modules',config/'node_modules')
for name in ('package.json','package-lock.json'):shutil.copy2(a.carrier/'workspace-template/.opencode'/name,config/name)
(config/'opencode.json').write_text(json.dumps({'enabled_providers':[],'model':'fixture/unconfigured','autoupdate':False,'share':'disabled'}),encoding='utf-8')
auth=host/'data/opencode';auth.mkdir(parents=True);(auth/'auth.json').write_text('{}',encoding='utf-8')
print(json.dumps({'host':str(host),'scope':'CI_SYNTHETIC_PREEXISTING_HOST_ONLY','bank_evidence':False}))
