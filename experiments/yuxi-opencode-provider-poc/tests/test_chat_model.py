from __future__ import annotations

import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from yuxi_opencode_provider.chat_model import OpenCodeChatModel, OpenCodeToolProtocolError


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/session":
            return httpx.Response(200, json={"id": "ses-model"})
        if request.method == "GET" and path == "/experimental/tool/ids":
            return httpx.Response(200, json=["read", "bash", "task"])
        if request.method == "POST" and path == "/session/ses-model/message":
            return httpx.Response(
                200,
                json={"info": {"role": "assistant"}, "parts": [{"type": "text", "text": self.response_text}]},
            )
        if request.method == "DELETE" and path == "/session/ses-model":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


def new_model(transport: httpx.AsyncBaseTransport) -> OpenCodeChatModel:
    return OpenCodeChatModel(
        base_url="http://opencode.test",
        opencode_provider_id="bank-provider",
        model_id="deepseek-v4-flash",
        transport=transport,
    )


@pytest.mark.asyncio
async def test_langchain_messages_are_serialized_as_stateless_full_transcript():
    transport = RecordingTransport("next answer")
    model = new_model(transport)

    response = await model.ainvoke(
        [
            SystemMessage(content="system truth"),
            HumanMessage(content="first question"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "legacy_tool", "args": {"x": 1}, "type": "tool_call"}],
            ),
            ToolMessage(content="tool result", tool_call_id="call-1"),
            HumanMessage(content="continue"),
        ]
    )

    assert response.content == "next answer"
    message_request = next(
        request for request in transport.requests if request.method == "POST" and request.url.path.endswith("/message")
    )
    body = body_of(message_request)
    assert "system truth" in body["system"]
    assert body["tools"] == {"read": False, "bash": False, "task": False}

    prompt_text = body["parts"][0]["text"]
    transcript = json.loads(prompt_text.split("\n", 1)[1])
    assert [item["role"] for item in transcript] == ["user", "assistant", "tool", "user"]
    assert transcript[1]["tool_calls"][0] == {"id": "call-1", "name": "legacy_tool", "args": {"x": 1}}
    assert transcript[2]["tool_call_id"] == "call-1"


@pytest.mark.asyncio
async def test_bind_tools_converts_strict_envelope_to_native_langchain_tool_call():
    transport = RecordingTransport(
        json.dumps(
            {
                "kind": "tool_calls",
                "tool_calls": [{"id": "call-weather", "name": "weather_lookup", "args": {"city": "Shenzhen"}}],
            }
        )
    )
    model = new_model(transport)

    @tool
    def weather_lookup(city: str) -> str:
        """Look up weather for one city."""
        return city

    bound = model.bind_tools([weather_lookup])
    response = await bound.ainvoke([HumanMessage(content="weather?")])

    assert response.content == ""
    assert response.tool_calls == [
        {
            "id": "call-weather",
            "name": "weather_lookup",
            "args": {"city": "Shenzhen"},
            "type": "tool_call",
        }
    ]

    message_request = next(
        request for request in transport.requests if request.method == "POST" and request.url.path.endswith("/message")
    )
    system = body_of(message_request)["system"]
    assert "YUXI_TOOL_SCHEMAS" in system
    assert "weather_lookup" in system


@pytest.mark.asyncio
async def test_bound_tool_model_accepts_final_answer_envelope():
    transport = RecordingTransport(json.dumps({"kind": "final", "content": "no tool needed"}))
    model = new_model(transport)

    @tool
    def lookup(value: str) -> str:
        """Look up one value."""
        return value

    response = await model.bind_tools([lookup]).ainvoke([HumanMessage(content="answer directly")])
    assert response.content == "no tool needed"
    assert response.tool_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_payload, expected",
    [
        ("not-json", "valid JSON"),
        ("```json\n{}\n```", "must not be wrapped"),
        (json.dumps({"kind": "tool_calls", "tool_calls": [{"id": "1", "name": "unknown", "args": {}}]}), "unknown tool"),
        (json.dumps({"kind": "tool_calls", "tool_calls": [{"id": "1", "name": "lookup", "args": []}]}), "args must be an object"),
    ],
)
async def test_tool_protocol_fails_closed(bad_payload: str, expected: str):
    transport = RecordingTransport(bad_payload)
    model = new_model(transport)

    @tool
    def lookup(value: str) -> str:
        """Look up one value."""
        return value

    with pytest.raises(OpenCodeToolProtocolError, match=expected):
        await model.bind_tools([lookup]).ainvoke([HumanMessage(content="use tool")])

    assert transport.requests[-1].method == "DELETE"


def test_bind_tools_rejects_unimplemented_adapter_options():
    model = new_model(RecordingTransport("unused"))

    @tool
    def lookup(value: str) -> str:
        """Look up one value."""
        return value

    with pytest.raises(ValueError, match="Unsupported bind_tools options"):
        model.bind_tools([lookup], parallel_tool_calls=False)
