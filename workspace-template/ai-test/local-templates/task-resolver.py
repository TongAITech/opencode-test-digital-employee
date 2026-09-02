from __future__ import annotations
import argparse, json, os

def main():
    p=argparse.ArgumentParser(); p.add_argument('--self-test',action='store_true'); p.add_argument('--request'); a=p.parse_args()
    configured=bool(os.environ.get('KYB_TASK_RESOLVER_ENDPOINT'))
    if a.self_test:
        print(json.dumps({'ok':configured,'status':'READY' if configured else 'NOT_CONFIGURED','rule':'resolve by business key, never list-first'})); return 0 if configured else 3
    print(json.dumps({'ok':False,'status':'ADAPTER_IMPLEMENTATION_REQUIRED'})); return 3
if __name__=='__main__': raise SystemExit(main())
