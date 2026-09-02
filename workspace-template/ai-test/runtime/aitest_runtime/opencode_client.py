from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any


class OpenCodeClient:
    def __init__(self, base_url: str = "http://127.0.0.1:4096", username: str | None = None, password: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.username = username or os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode"
        self.password = password if password is not None else os.environ.get("OPENCODE_SERVER_PASSWORD")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.password:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenCode HTTP {exc.code}: {raw}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/global/health")

    def create_session(self, title: str, parent_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title}
        if parent_id:
            body["parentID"] = parent_id
        return self._request("POST", "/session", body)

    def session_status(self) -> dict[str, Any]:
        return self._request("GET", "/session/status")

    def messages(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._request("GET", f"/session/{session_id}/message?limit={limit}") or []

    def send_message(self, session_id: str, text: str, *, agent: str, no_reply: bool = False, system: str | None = None) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "agent": agent,
            "noReply": no_reply,
            "parts": [{"type": "text", "text": text}],
        }
        if system:
            body["system"] = system
        return self._request("POST", f"/session/{session_id}/message", body)

    def prompt_async(self, session_id: str, text: str, *, agent: str, system: str | None = None) -> None:
        body: dict[str, Any] = {"agent": agent, "parts": [{"type": "text", "text": text}]}
        if system:
            body["system"] = system
        self._request("POST", f"/session/{session_id}/prompt_async", body)

    def command(self, session_id: str, command: str, arguments: str = "", *, agent: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"command": command, "arguments": arguments}
        if agent:
            body["agent"] = agent
        return self._request("POST", f"/session/{session_id}/command", body)

    def abort(self, session_id: str) -> bool:
        return bool(self._request("POST", f"/session/{session_id}/abort", {}))

    def delete(self, session_id: str) -> bool:
        return bool(self._request("DELETE", f"/session/{session_id}"))
