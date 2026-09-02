from __future__ import annotations

import json

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.tools import tool

from yuxi_opencode_provider.chat_model import OpenCodeChatModel


class AgentLoopTransport(httpx.AsyncBaseTransport):
    """Two ephemeral model calls: request a Yuxi tool, then return final text."""

    def __init__(self) -> None:
        self.session_counter = 0
        self.model_calls = 0
        self.deleted: list[str] = []
        self.message_bodies: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            self.session_counter += 1
            return httpx.Response(200, json={"id": f"ses-{self.session_counter}"})

        if request.method == "GET" and request.url.path == "/experimental/tool/ids":
            return httpx.Response(200, json=["read", "bash", "task"])

        if request.method == "POST" and request.url.path.endswith("/message"):
            self.model_calls += 1
            body = json.loads(request.content.decode("utf-8"))
            self.message_bodies.append(body)
            assert body["tools"] == {"read": False, "bash": False, "task": False}
            if self.model_calls == 1:
                text = json.dumps(
                    {
                        "kind": "tool_calls",
                        "tool_calls": [
                            {"id": "calc-1", "name": "add_numbers", "args": {"a": 2, "b": 3}}
                        ],
                    }
                )
            elif self.model_calls == 2:
                transcript = json.loads(body["parts"][0]["text"].split("\n", 1)[1])
                assert any(item["role"] == "tool" and item["content"] == "5" for item in transcript)
                text = json.dumps({"kind": "final", "content": "answer is 5"})
            else:
                raise AssertionError("agent loop should converge in exactly two model calls")
            return httpx.Response(200, json={"info": {"role": "assistant"}, "parts": [{"type": "text", "text": text}]})

        if request.method == "DELETE" and request.url.path.startswith("/session/"):
            self.deleted.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=True)

        raise AssertionError(f"unexpected request: {request.method} {request.url}")


@pytest.mark.asyncio
async def test_langchain_create_agent_executes_yuxi_tool_not_opencode_tool():
    transport = AgentLoopTransport()
    model = OpenCodeChatModel(
        base_url="http://opencode.test",
        opencode_provider_id="bank-provider",
        model_id="deepseek-v4-flash",
        transport=transport,
    )

    @tool
    def add_numbers(a: int, b: int) -> str:
        """Add two integers."""
        return str(a + b)

    agent = create_agent(model=model, tools=[add_numbers])
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "What is 2 + 3?"}]})

    assert result["messages"][-1].content == "answer is 5"
    assert transport.model_calls == 2
    assert transport.session_counter == 2
    assert transport.deleted == ["ses-1", "ses-2"]
    assert all("YUXI_TOOL_SCHEMAS" in body["system"] for body in transport.message_bodies)
