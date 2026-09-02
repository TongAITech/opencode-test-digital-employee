#!/usr/bin/env python3
"""Live bank probe for the Yuxi -> OpenCode -> bank LLM architecture.

Run this *inside the same environment that can reach the bank OpenCode server*.
The probe is read-only with respect to the workspace and disables every OpenCode
owned tool for model requests.  It creates only ephemeral scratch sessions and
requires them to be deleted before reporting PASS.

The JSON report intentionally omits credentials, headers, prompts, and raw
provider objects.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from yuxi_opencode_provider.chat_model import OpenCodeChatModel


PLAIN_MARKER = "YUXI_OC_PLAIN_7F3A"
SYSTEM_MARKER = "YUXI_OC_SYSTEM_91C2"
STREAM_MARKER = "YUXI_OC_STREAM_4D8E"
PROBE_TOOL = "yuxi_probe_add"
SESSION_TITLE_PREFIX = "yuxi-model-gateway"


@dataclass(frozen=True)
class Selection:
    provider_id: str | None
    model_id: str | None
    reason: str


def _safe_error(exc: BaseException) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    return text[:500]


def _extract_provider_inventory(payload: Any) -> tuple[list[dict[str, Any]], list[str], Any]:
    """Project /provider into a secret-free inventory."""

    if not isinstance(payload, dict):
        return [], [], None
    raw_providers = payload.get("all") or payload.get("providers") or []
    connected = payload.get("connected") or []
    connected_ids = [item for item in connected if isinstance(item, str)] if isinstance(connected, list) else []
    result: list[dict[str, Any]] = []

    if isinstance(raw_providers, list):
        for provider in raw_providers:
            if not isinstance(provider, dict):
                continue
            provider_id = provider.get("id") or provider.get("providerID") or provider.get("provider_id")
            if not isinstance(provider_id, str) or not provider_id:
                continue
            raw_models = provider.get("models") or {}
            model_ids: list[str] = []
            if isinstance(raw_models, dict):
                model_ids = [str(key) for key in raw_models.keys() if str(key)]
            elif isinstance(raw_models, list):
                for model in raw_models:
                    if isinstance(model, str):
                        model_ids.append(model)
                    elif isinstance(model, dict):
                        model_id = model.get("id") or model.get("modelID") or model.get("model_id")
                        if isinstance(model_id, str) and model_id:
                            model_ids.append(model_id)
            result.append(
                {
                    "provider_id": provider_id,
                    "name": provider.get("name") if isinstance(provider.get("name"), str) else None,
                    "connected": provider_id in connected_ids,
                    "model_ids": sorted(set(model_ids)),
                }
            )

    return result, sorted(set(connected_ids)), payload.get("default")


def _choose_model(
    inventory: list[dict[str, Any]],
    connected: list[str],
    requested_provider: str | None,
    requested_model: str | None,
) -> Selection:
    provider_id = requested_provider.strip() if requested_provider and requested_provider.strip() else None
    model_id = requested_model.strip() if requested_model and requested_model.strip() else None

    by_id = {item["provider_id"]: item for item in inventory if isinstance(item.get("provider_id"), str)}

    if provider_id and model_id:
        return Selection(provider_id, model_id, "explicit")

    if not provider_id:
        connected_known = [item for item in inventory if item.get("provider_id") in connected]
        if len(connected_known) == 1:
            provider_id = connected_known[0]["provider_id"]
        elif len(inventory) == 1:
            provider_id = inventory[0]["provider_id"]
        else:
            return Selection(None, model_id, "provider-selection-required")

    provider = by_id.get(provider_id)
    if not provider:
        return Selection(provider_id, model_id, "provider-not-present-in-inventory")

    if model_id:
        return Selection(provider_id, model_id, "explicit-model")

    models = provider.get("model_ids") or []
    if len(models) == 1:
        return Selection(provider_id, models[0], "single-model-auto-selected")
    return Selection(provider_id, None, "model-selection-required")


def _extract_agents(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    agents: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("id")
        if isinstance(name, str) and name:
            agents.append(name)
    return sorted(set(agents))


def _session_snapshot(payload: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(payload, list):
        return result
    for item in payload:
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        title = item.get("title")
        if isinstance(sid, str):
            result[sid] = title if isinstance(title, str) else ""
    return result


def _basic_auth_header(username: str | None, password: str | None) -> dict[str, str]:
    if not password:
        return {}
    user = username or "opencode"
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


async def _get_json(client: httpx.AsyncClient, path: str) -> tuple[int, Any]:
    response = await client.get(path)
    status = response.status_code
    if status >= 400:
        return status, None
    try:
        return status, response.json()
    except Exception:
        return status, None


async def run_probe(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    base_url = args.base_url.rstrip("/")
    password = os.getenv(args.password_env) if args.password_env else None
    headers = _basic_auth_header(args.basic_user, password)
    if args.directory:
        headers["x-opencode-directory"] = args.directory

    report: dict[str, Any] = {
        "probe": "YUXI_OPENCODE_PROVIDER_LIVE_GATE",
        "base_url": base_url,
        "directory_configured": bool(args.directory),
        "auth_configured": bool(password),
        "checks": {},
    }
    checks = report["checks"]

    timeout = httpx.Timeout(args.timeout, connect=min(args.timeout, 10.0))
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers) as http:
            health_status, health = await _get_json(http, "/global/health")
            if health_status == 200 and isinstance(health, dict):
                checks["server_health"] = {
                    "status": "PASS" if health.get("healthy", True) else "FAIL",
                    "version": health.get("version") if isinstance(health.get("version"), str) else None,
                }
            else:
                # 1.14.22 has /global/health, but a session list is a useful safe
                # compatibility fallback for a customized bank build.
                session_status, _ = await _get_json(http, "/session")
                checks["server_health"] = {
                    "status": "PASS" if session_status == 200 else "FAIL",
                    "version": None,
                    "fallback": "GET /session",
                }

            provider_status, provider_payload = await _get_json(http, "/provider")
            inventory, connected, defaults = _extract_provider_inventory(provider_payload)
            checks["provider_inventory"] = {
                "status": "PASS" if provider_status == 200 and inventory else "FAIL",
                "connected_provider_ids": connected,
                "providers": inventory,
                "default_present": defaults is not None,
            }

            tool_status, tool_payload = await _get_json(http, "/experimental/tool/ids")
            tool_ids = tool_payload if isinstance(tool_payload, list) and all(isinstance(x, str) for x in tool_payload) else []
            checks["opencode_tool_enumeration"] = {
                "status": "PASS" if tool_status == 200 and isinstance(tool_payload, list) else "FAIL",
                "tool_count": len(tool_ids),
            }

            agent_status, agent_payload = await _get_json(http, "/agent")
            agents = _extract_agents(agent_payload)
            checks["provider_proxy_agent"] = {
                "status": "PASS" if agent_status == 200 and args.agent in agents else "FAIL",
                "agent": args.agent,
                "available": args.agent in agents,
            }

            before_status, before_payload = await _get_json(http, "/session")
            before = _session_snapshot(before_payload) if before_status == 200 else {}

        selection = _choose_model(inventory, connected, args.provider_id, args.model_id)
        report["selection"] = {
            "provider_id": selection.provider_id,
            "model_id": selection.model_id,
            "reason": selection.reason,
        }

        prereq_checks = (
            checks["server_health"]["status"],
            checks["provider_inventory"]["status"],
            checks["opencode_tool_enumeration"]["status"],
            checks["provider_proxy_agent"]["status"],
        )
        if selection.provider_id is None or selection.model_id is None:
            report["gate"] = "NEEDS_MODEL_SELECTION"
            report["next_action"] = "Re-run with --provider-id and --model-id from the safe inventory above."
            return 2, report
        if "FAIL" in prereq_checks:
            report["gate"] = "FAIL_PRECONDITION"
            return 1, report

        model = OpenCodeChatModel(
            base_url=base_url,
            opencode_provider_id=selection.provider_id,
            model_id=selection.model_id,
            agent=args.agent,
            timeout=args.timeout,
            headers=_basic_auth_header(args.basic_user, password),
            directory=args.directory,
        )

        plain = await model.ainvoke([HumanMessage(content=f"Reply with exactly this token: {PLAIN_MARKER}")])
        plain_text = str(plain.content)
        checks["plain_chat"] = {
            "status": "PASS" if PLAIN_MARKER in plain_text else "FAIL",
            "marker_seen": PLAIN_MARKER in plain_text,
        }

        system = await model.ainvoke(
            [
                SystemMessage(content=f"Your response must contain the exact token {SYSTEM_MARKER}."),
                HumanMessage(content="Return the required token and nothing else."),
            ]
        )
        system_text = str(system.content)
        checks["system_prompt"] = {
            "status": "PASS" if SYSTEM_MARKER in system_text else "FAIL",
            "marker_seen": SYSTEM_MARKER in system_text,
        }

        stream_chunks: list[str] = []
        async for chunk in model.astream([HumanMessage(content=f"Reply with exactly this token: {STREAM_MARKER}")]):
            stream_chunks.append(str(chunk.content))
        stream_text = "".join(stream_chunks)
        checks["streaming"] = {
            "status": "PASS" if STREAM_MARKER in stream_text and len(stream_chunks) > 0 else "FAIL",
            "marker_seen": STREAM_MARKER in stream_text,
            "chunk_count": len(stream_chunks),
        }

        probe_tool_schema = {
            "type": "function",
            "function": {
                "name": PROBE_TOOL,
                "description": "Add two integers. Use this tool when explicitly instructed by the probe.",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                    "additionalProperties": False,
                },
            },
        }
        bound = model.bind_tools([probe_tool_schema])
        tool_request = HumanMessage(
            content=f"Use the {PROBE_TOOL} tool with a=2 and b=3. Do not calculate it yourself; select the tool."
        )
        tool_response = await bound.ainvoke([tool_request])
        matching = [call for call in tool_response.tool_calls if call.get("name") == PROBE_TOOL]
        tool_call_ok = (
            len(matching) == 1
            and matching[0].get("args") == {"a": 2, "b": 3}
            and isinstance(matching[0].get("id"), str)
            and bool(matching[0].get("id"))
        )
        checks["yuxi_tool_selection"] = {
            "status": "PASS" if tool_call_ok else "FAIL",
            "tool_call_count": len(tool_response.tool_calls),
            "expected_tool_seen": bool(matching),
        }

        continuation_ok = False
        if tool_call_ok:
            call_id = matching[0]["id"]
            continued = await bound.ainvoke(
                [
                    tool_request,
                    tool_response,
                    ToolMessage(content="5", tool_call_id=call_id, name=PROBE_TOOL),
                ]
            )
            continuation_ok = not continued.tool_calls and "5" in str(continued.content)
        checks["yuxi_tool_result_continuation"] = {
            "status": "PASS" if continuation_ok else "FAIL",
            "final_answer_mentions_expected_result": continuation_ok,
        }

        async with httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers) as http:
            after_status, after_payload = await _get_json(http, "/session")
        after = _session_snapshot(after_payload) if after_status == 200 else {}
        new_probe_sessions = {
            sid: title
            for sid, title in after.items()
            if sid not in before and isinstance(title, str) and title.startswith(SESSION_TITLE_PREFIX)
        }
        checks["ephemeral_session_cleanup"] = {
            "status": "PASS" if after_status == 200 and not new_probe_sessions else "FAIL",
            "leftover_probe_session_count": len(new_probe_sessions),
        }

        failures = [name for name, item in checks.items() if isinstance(item, dict) and item.get("status") == "FAIL"]
        report["gate"] = "PASS" if not failures else "FAIL"
        if failures:
            report["failed_checks"] = failures
        return (0 if not failures else 1), report

    except BaseException as exc:
        report["gate"] = "ERROR"
        report["error_type"] = type(exc).__name__
        report["error"] = _safe_error(exc)
        return 1, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live Yuxi -> OpenCode provider compatibility probe")
    parser.add_argument("--base-url", default=os.getenv("OPENCODE_SERVER_URL", "http://127.0.0.1:4096"))
    parser.add_argument("--provider-id")
    parser.add_argument("--model-id")
    parser.add_argument("--agent", default="yuxi-model-provider-proxy")
    parser.add_argument("--directory")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--basic-user", default=os.getenv("OPENCODE_SERVER_USERNAME", "opencode"))
    parser.add_argument("--password-env", default="OPENCODE_SERVER_PASSWORD")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    code, report = asyncio.run(run_probe(args))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
