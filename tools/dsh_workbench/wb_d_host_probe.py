"""WB-D01 safe DSH host read-only capability probe.

SOURCE/INTERFACE observation only. Never a bank qualification certificate.
Never creates sessions, writes preferences, sends prompts or accesses secrets.
"""
from __future__ import annotations
import argparse
import json
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


MAX_BYTES = 65536


class HostProbeError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _origin(url):
    if not isinstance(url, str):
        raise HostProbeError("LOOPBACK_URL_REQUIRED")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        raise HostProbeError("LOOPBACK_URL_REQUIRED") from None
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or not port or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise HostProbeError("LOOPBACK_ONLY")
    return url.rstrip("/")


def _session_id(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise HostProbeError("SESSION_ID_INVALID")
    return value


def _read_only_get(opener, url):
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=3) as response:
            if response.status != 200 or response.geturl() != url:
                raise HostProbeError("HTTP_NOT_TRUSTED")
            raw = response.read(MAX_BYTES + 1)
    except HostProbeError:
        raise
    except HTTPError as error:
        if error.code in (401, 403):
            raise HostProbeError("HOST_PERMISSION_DENIED") from None
        if error.code == 404:
            raise HostProbeError("HOST_ROUTE_MISSING") from None
        raise HostProbeError("GET_UNAVAILABLE") from None
    except (URLError, OSError, ValueError):
        raise HostProbeError("GET_UNAVAILABLE") from None
    if len(raw) > MAX_BYTES:
        raise HostProbeError("RESPONSE_TOO_LARGE")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise HostProbeError("INVALID_JSON") from None
    if not isinstance(body, dict):
        raise HostProbeError("RESPONSE_NOT_OBJECT")
    if isinstance(body.get("data"), dict):
        return body["data"]
    return body


def probe(*, base_url, session_id=None, opener=None):
    """Return redacted evidence of two documented GETs, no claimed compatibility PASS."""
    origin = _origin(base_url)
    sid = _session_id(session_id)
    reader = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())
    result = {
        "schema": "dsh-workbench-host-probe/v1",
        "mode": "READ_ONLY",
        "source_contract": "rc7_release/rc72_dsh_agentteams_host.py",
        "bank_dsh_version": "UNVERIFIED",
        "field_verified": False,
        "bank_final": False,
        "session_status": "NOT_OBSERVED",
        "session_identity": "NOT_PROBED" if sid is None else "NOT_OBSERVED",
        "native_panel": "NOT_PROBED",
        "models": "NOT_PROBED",
        "skills": "NOT_PROBED",
        "commands": "NOT_PROBED",
        "attachments": "NOT_PROBED",
        "cancellation": "NOT_PROBED",
        "history": "NOT_PROBED",
        "teams_roster": "NOT_PROBED",
        "teams_active_workers": "NOT_PROBED",
        "resource_leases": "NOT_PROBED",
        "model_quota": "NOT_PROBED",
    }
    try:
        status = _read_only_get(reader, origin + "/session/status")
        if not all(isinstance(v, dict) and isinstance(v.get("type"), str) for v in status.values()):
            raise HostProbeError("SESSION_STATUS_SCHEMA_MISMATCH")
        result["session_status"] = "SCHEMA_OBSERVED"
    except HostProbeError as error:
        result["session_status"] = error.args[0]
        return result
    if sid is not None:
        try:
            session = _read_only_get(reader, origin + "/session/" + quote(sid, safe=""))
            if session.get("id") != sid:
                raise HostProbeError("SESSION_ID_MISMATCH")
            result["session_identity"] = "MATCH_OBSERVED"
            if sid not in status:
                result["session_identity"] = "STATUS_NOT_OBSERVED"
        except HostProbeError as error:
            result["session_identity"] = error.args[0]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="DSH read-only loopback probe; no secrets or live acceptance")
    parser.add_argument("--url", default="http://127.0.0.1:4096")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args(argv)
    try:
        report = probe(base_url=args.url, session_id=args.session_id)
    except HostProbeError as error:
        report = {"schema": "dsh-workbench-host-probe/v1", "mode": "READ_ONLY",
                  "error_code": error.args[0], "field_verified": False, "bank_final": False}
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("session_status") == "SCHEMA_OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
