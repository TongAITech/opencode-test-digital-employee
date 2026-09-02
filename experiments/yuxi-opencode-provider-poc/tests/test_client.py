from __future__ import annotations

import json

import httpx
import pytest

from yuxi_opencode_provider.client import OpenCodeClient, OpenCodeProtocolError


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


@pytest.mark.asyncio
async def test_invoke_is_ephemeral_and_disables_every_opencode_tool():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses-1"})
        if request.method == "GET" and request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=["read", "bash", "task"])
        if request.method == "POST" and request.url.path == "/session/ses-1/message":
            body = json_body(request)
            assert body["model"] == {"providerID": "bank-provider", "modelID": "deepseek-v4-flash"}
            assert body["agent"] == "yuxi-model-provider-proxy"
            assert body["tools"] == {"read": False, "bash": False, "task": False}
            assert body["system"] == "system truth"
            assert body["parts"] == [{"type": "text", "text": "hello"}]
            return httpx.Response(200, json={"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "world"}]})
        if request.method == "DELETE" and request.url.path == "/session/ses-1":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = RecordingTransport(handler)
    client = OpenCodeClient(
        base_url="http://opencode.test",
        directory="C:/bank/pfc",
        transport=transport,
    )

    result = await client.invoke_ephemeral(
        provider_id="bank-provider",
        model_id="deepseek-v4-flash",
        agent="yuxi-model-provider-proxy",
        system="system truth",
        text="hello",
    )

    assert result.text == "world"
    assert result.session_id == "ses-1"
    assert transport.requests[-1].method == "DELETE"
    assert all(request.headers.get("x-opencode-directory") == "C:/bank/pfc" for request in transport.requests)


@pytest.mark.asyncio
async def test_cleanup_runs_when_model_request_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses-fail"})
        if request.method == "GET" and request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path == "/session/ses-fail/message":
            return httpx.Response(503, json={"error": "model unavailable"})
        if request.method == "DELETE" and request.url.path == "/session/ses-fail":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = RecordingTransport(handler)
    client = OpenCodeClient(base_url="http://opencode.test", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await client.invoke_ephemeral(
            provider_id="bank-provider",
            model_id="deepseek-v4-flash",
            agent="yuxi-model-provider-proxy",
            text="hello",
        )

    assert [(request.method, request.url.path) for request in transport.requests][-1] == (
        "DELETE",
        "/session/ses-fail",
    )


@pytest.mark.asyncio
async def test_missing_tool_enumeration_fails_closed_and_cleans_up():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses-no-tools-api"})
        if request.method == "GET" and request.url.path == "/experimental/tool/ids":
            return httpx.Response(404, json={"error": "not found"})
        if request.method == "DELETE" and request.url.path == "/session/ses-no-tools-api":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = RecordingTransport(handler)
    client = OpenCodeClient(base_url="http://opencode.test", transport=transport)

    with pytest.raises(OpenCodeProtocolError, match="cannot prove"):
        await client.invoke_ephemeral(
            provider_id="bank-provider",
            model_id="deepseek-v4-flash",
            agent="yuxi-model-provider-proxy",
            text="hello",
        )

    assert transport.requests[-1].url.path == "/session/ses-no-tools-api"
    assert transport.requests[-1].method == "DELETE"


@pytest.mark.asyncio
async def test_stream_filters_other_sessions_and_stops_on_own_idle():
    sse = """data: {"type":"server.connected","properties":{}}

data: {"type":"message.part.delta","properties":{"sessionID":"foreign","field":"text","delta":"ignore"}}

data: {"type":"message.part.delta","properties":{"sessionID":"ses-stream","messageID":"m1","partID":"p1","field":"text","delta":"hel"}}

data: {"payload":{"type":"message.part.delta","properties":{"sessionID":"ses-stream","messageID":"m1","partID":"p1","field":"text","delta":"lo"}}}

data: {"type":"session.idle","properties":{"sessionID":"ses-stream"}}

"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses-stream"})
        if request.method == "GET" and request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=["read"])
        if request.method == "GET" and request.url.path == "/event":
            return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})
        if request.method == "POST" and request.url.path == "/session/ses-stream/prompt_async":
            assert json_body(request)["tools"] == {"read": False}
            return httpx.Response(204)
        if request.method == "DELETE" and request.url.path == "/session/ses-stream":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = RecordingTransport(handler)
    client = OpenCodeClient(base_url="http://opencode.test", transport=transport)

    chunks = [
        chunk
        async for chunk in client.stream_ephemeral(
            provider_id="bank-provider",
            model_id="deepseek-v4-flash",
            agent="yuxi-model-provider-proxy",
            text="hello",
        )
    ]

    assert chunks == ["hel", "lo"]
    assert transport.requests[-1].method == "DELETE"
