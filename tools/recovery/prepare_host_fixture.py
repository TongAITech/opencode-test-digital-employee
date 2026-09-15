"""CI construction only: pre-existing host fixture, outside both installations.

Copies existing hash-verified construction bytes, never downloads. This is not
product provider projection; installation and launcher never run this script.
"""
import argparse
import json
from pathlib import Path
import shutil

p=argparse.ArgumentParser();p.add_argument('--carrier',type=Path,required=True);p.add_argument('--host',type=Path,required=True)
p.add_argument('--host-opencode',type=Path,help='External host sample for CI qualification; never copied into the product package')
a=p.parse_args();host=a.host.resolve();host.mkdir(parents=True,exist_ok=False)
bin=host/'bin';bin.mkdir()
host_source=(a.host_opencode.resolve() if a.host_opencode else (a.carrier/'workspace-template/runtime/opencode/opencode.exe').resolve())
if not host_source.is_file(): raise RuntimeError('CI_HOST_OPENCODE_SAMPLE_REQUIRED')
shutil.copy2(host_source,bin/'opencode.exe')
config=host/'config/opencode';config.mkdir(parents=True)
shutil.copytree(a.carrier/'workspace-template/.opencode/node_modules',config/'node_modules')
for name in ('package.json','package-lock.json'):shutil.copy2(a.carrier/'workspace-template/.opencode'/name,config/name)
# Model an already initialized host configuration. OpenCode itself inserts this
# schema marker on the first ever read; that unrelated initialization must not
# be mistaken for launcher mutation. Startup tests still require byte-identical
# host config and auth after the complete installed launcher lifecycle.
(config/'opencode.json').write_text(json.dumps({'$schema':'https://opencode.ai/config.json','enabled_providers':[],'model':'fixture/unconfigured','autoupdate':False,'share':'disabled'}),encoding='utf-8')
auth=host/'data/opencode';auth.mkdir(parents=True);(auth/'auth.json').write_text('{}',encoding='utf-8')
print(json.dumps({'host':str(host),'scope':'CI_SYNTHETIC_PREEXISTING_HOST_ONLY','host_source':str(host_source),
                  'compatibility_policy':'CAPABILITY_BASED_NO_EXACT_VERSION_PIN','bank_evidence':False}))
