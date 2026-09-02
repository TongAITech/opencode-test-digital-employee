"""Minimal OpenCode HTTP client for the Yuxi provider feasibility PoC.

The client deliberately treats every model invocation as an ephemeral OpenCode
session. Session IDs are transport diagnostics only and MUST NOT be promoted to
Yuxi Mission/Run/Thread truth.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class OpenCodeGatewayError(RuntimeError):
    """Base error for the OpenCode gateway adapter."""


class OpenCodeProtocolError(OpenCodeGatewayError):
    """Raised when OpenCode does not expose the contract required by this PoC."""


@dataclass(frozen=True)
class OpenCodeInvocation:
    """One completed ephemeral invocation.

    ``session_id`` exists only so a caller can correlate transport logs. The
    session is deleted before this object is returned.
    """

    session_id: str
    text: str
    raw: dict[str, Any]


class OpenCodeClient:
    """Small async client around the OpenCode server Session API."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:4096",
        timeout: float = 120.0,
        headers: dict[str, str] | None = None,
        directory: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.directory = directory
        self.transport = transport

    def _http(self) -> httpx.AsyncClient:
        headers = dict(self.headers)
        if self.directory:
            # Match the exact OpenCode v1.14.22 SDK contract: the directory
            # header is URI-encoded before transport. This matters for Windows
            # drive letters, spaces, non-ASCII paths, and other reserved chars.
            headers.setdefault("x-opencode-directory", quote(self.directory, safe=""))
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=headers,
            transport=self.transport,
        )

    @staticmethod
    async def _create_session(http: httpx.AsyncClient, title: str) -> str:
        response = await http.post("/session", json={"title": title})
        response.raise_for_status()
        payload = response.json()
        session_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise OpenCodeProtocolError("OpenCode POST /session did not return a non-empty id")
        return session_id

    @staticmethod
    async def _delete_session(http: httpx.AsyncClient, session_id: str) -> None:
        response = await http.delete(f"/session/{session_id}")
        response.raise_for_status()

    @staticmethod
    async def _tool_ids(http: httpx.AsyncClient) -> list[str]:
        """Return every OpenCode-owned tool id so the adapter can disable it.

        Failing to enumerate tools is a hard failure. Silently continuing would
        allow the OpenCode agent loop to become an unexpected second tool/runtime
        owner, which this PoC explicitly forbids.
        """

        response = await http.get("/experimental/tool/ids")
        if response.status_code == 404:
            raise OpenCodeProtocolError(
                "OpenCode /experimental/tool/ids is unavailable; cannot prove that all OpenCode tools are disabled"
            )
        response.raise_for_status()
        payload = response.json()

        candidates: Any = payload
        if isinstance(payload, dict):
            for key in ("ids", "tools", "data"):
                if key in payload:
                    candidates = payload[key]
                    break

        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            raise OpenCodeProtocolError("Unexpected /experimental/tool/ids response shape")
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _prompt_payload(
        *,
        provider_id: str,
        model_id: str,
        agent: str,
        system: str | None,
        text: str,
        disabled_tools: dict[str, bool],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": {"providerID": provider_id, "modelID": model_id},
            "agent": agent,
            "tools": disabled_tools,
            "parts": [{"type": "text", "text": text}],
        }
        if system:
            payload["system"] = system
        return payload

    @staticmethod
    def _extract_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise OpenCodeProtocolError("OpenCode message response is not an object")
        parts = payload.get("parts")
        if not isinstance(parts, list):
            raise OpenCodeProtocolError("OpenCode message response has no parts array")
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        if not chunks:
            raise OpenCodeProtocolError("OpenCode message response contains no text part")
        return "".join(chunks)

    async def invoke_ephemeral(
        self,
        *,
        provider_id: str,
        model_id: str,
        agent: str,
        text: str,
        system: str | None = None,
    ) -> OpenCodeInvocation:
        """Invoke OpenCode once, then delete the scratch session in ``finally``."""

        async with self._http() as http:
            session_id = await self._create_session(http, title="yuxi-model-gateway")
            primary_error: BaseException | None = None
            try:
                tool_ids = await self._tool_ids(http)
                disabled_tools = {tool_id: False for tool_id in tool_ids}
                payload = self._prompt_payload(
                    provider_id=provider_id,
                    model_id=model_id,
                    agent=agent,
                    system=system,
                    text=text,
                    disabled_tools=disabled_tools,
                )
                response = await http.post(f"/session/{session_id}/message", json=payload)
                response.raise_for_status()
                raw = response.json()
                return OpenCodeInvocation(
                    session_id=session_id,
                    text=self._extract_text(raw),
                    raw=raw,
                )
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                try:
                    await self._delete_session(http, session_id)
                except BaseException:
                    if primary_error is None:
                        raise

    async def stream_ephemeral(
        self,
        *,
        provider_id: str,
        model_id: str,
        agent: str,
        text: str,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas from OpenCode SSE for one ephemeral invocation."""

        async with self._http() as http:
            session_id = await self._create_session(http, title="yuxi-model-gateway-stream")
            primary_error: BaseException | None = None
            try:
                tool_ids = await self._tool_ids(http)
                disabled_tools = {tool_id: False for tool_id in tool_ids}
                payload = self._prompt_payload(
                    provider_id=provider_id,
                    model_id=model_id,
                    agent=agent,
                    system=system,
                    text=text,
                    disabled_tools=disabled_tools,
                )

                async with http.stream("GET", "/event") as event_response:
                    event_response.raise_for_status()
                    submitted = await http.post(f"/session/{session_id}/prompt_async", json=payload)
                    submitted.raise_for_status()

                    async for event in self._iter_sse_json(event_response):
                        event_type, properties = self._event_fields(event)
                        if properties.get("sessionID") != session_id:
                            continue
                        if event_type == "message.part.delta":
                            if properties.get("field") == "text" and isinstance(properties.get("delta"), str):
                                yield properties["delta"]
                            continue
                        if event_type == "session.error":
                            raise OpenCodeGatewayError(
                                f"OpenCode session failed: {properties.get('error') or properties}"
                            )
                        if event_type == "session.idle":
                            break
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                try:
                    await self._delete_session(http, session_id)
                except BaseException:
                    if primary_error is None:
                        raise

    @staticmethod
    async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                if data_lines:
                    raw = "\n".join(data_lines)
                    data_lines.clear()
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise OpenCodeProtocolError(f"Invalid OpenCode SSE JSON: {raw!r}") from exc
                    if isinstance(parsed, dict):
                        yield parsed
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            raw = "\n".join(data_lines)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise OpenCodeProtocolError(f"Invalid OpenCode SSE JSON: {raw!r}") from exc
            if isinstance(parsed, dict):
                yield parsed

    @staticmethod
    def _event_fields(event: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        event_type = payload.get("type") if isinstance(payload, dict) else None
        properties = payload.get("properties", {}) if isinstance(payload, dict) else {}
        if not isinstance(properties, dict):
            properties = {}
        return event_type if isinstance(event_type, str) else None, properties
