from __future__ import annotations
import argparse, json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
POLICY = WORKSPACE / 'ai-test' / 'config' / 'policies' / 'network.json'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def resolve(value):
    if isinstance(value, str) and value.startswith('env:'):
        name = value.split(':', 1)[1]
        if not os.environ.get(name):
            raise RuntimeError(f'MISSING_SECRET_BINDING:{name}')
        return os.environ[name]
    if isinstance(value, dict):
        return {k: resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v) for v in value]
    return value


def allowed(url):
    cfg = load(POLICY)
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    denied = [p.lower() for p in cfg.get('denied_host_patterns', [])]
    if any(p and p in host for p in denied):
        return False, 'HOST_MATCHES_DENIED_PATTERN'
    hosts = [str(x).lower() for x in cfg.get('allowed_hosts', [])]
    if not hosts:
        return False, 'NETWORK_ALLOWLIST_EMPTY'
    if host in hosts or any(item.startswith('*.') and host.endswith(item[1:]) for item in hosts):
        return True, 'ALLOWLISTED'
    return False, 'HOST_NOT_ALLOWLISTED'


def run(request):
    url = str(request['url'])
    ok, reason = allowed(url)
    if not ok:
        return {'ok': False, 'status': 'POLICY_BLOCKED', 'reason': reason, 'host': urllib.parse.urlparse(url).hostname}
    query = request.get('query') or {}
    if query:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(query, doseq=True)
    method = str(request.get('method') or 'GET').upper()
    headers = resolve(request.get('headers') or {})
    body = None
    if 'json' in request:
        body = json.dumps(resolve(request.get('json')), ensure_ascii=False).encode('utf-8')
        headers.setdefault('Content-Type', 'application/json')
    elif 'body' in request:
        body = str(resolve(request.get('body'))).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    timeout = int(request.get('timeout_seconds') or 30)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
            raw = response.read()
            content_type = response.headers.get('Content-Type', '')
            text = raw.decode('utf-8', errors='replace')
            try:
                parsed = json.loads(text) if 'json' in content_type or text.lstrip().startswith(('{', '[')) else text
            except json.JSONDecodeError:
                parsed = text
            return {'ok': True, 'status': response.status, 'headers': {k: v for k, v in response.headers.items() if k.lower() not in {'set-cookie', 'authorization'}}, 'body': parsed}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode('utf-8', errors='replace')
        try: body_out = json.loads(text)
        except json.JSONDecodeError: body_out = text
        return {'ok': False, 'status': exc.code, 'body': body_out, 'error': 'HTTP_ERROR'}
    except Exception as exc:
        return {'ok': False, 'status': 'TRANSPORT_ERROR', 'error': type(exc).__name__, 'message': str(exc)}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--self-test', action='store_true'); p.add_argument('--request'); a = p.parse_args()
    if a.self_test:
        print(json.dumps({'ok': True, 'status': 'READY', 'capability': 'HTTP with network allowlist and env secret bindings'})); return 0
    if not a.request: p.error('--request required')
    result = run(load(a.request)); print(json.dumps(result, ensure_ascii=False)); return 0 if result.get('ok') else 2
if __name__ == '__main__': raise SystemExit(main())
