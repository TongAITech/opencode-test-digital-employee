from __future__ import annotations
import argparse, json
from pathlib import Path

def load_request():
    p=argparse.ArgumentParser(); p.add_argument('--request',required=True); a=p.parse_args()
    return json.loads(Path(a.request).read_text(encoding='utf-8'))

def emit(value):
    print(json.dumps(value,ensure_ascii=False))

def main():
    req=load_request()
    if req.get("mock_result") is not None:
        return emit({"ok":True,"status":"BROWSER_ACTION_OK","result":req.get("mock_result")})
    emit({"ok":False,"status":"NOT_CONFIGURED","required":"controlled browser adapter or HumanTask"})
if __name__=='__main__': main()
