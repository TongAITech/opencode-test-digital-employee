#!/usr/bin/env python3
"""Preserve the legacy formal Center control/R1/recovery regression standalone.

The historical integration suite predates the production-date/TestRound entry
contract. It is still valuable because it contains hundreds of assertions for
PostgreSQL/Redis lease truth, R1 ordering, governance projection, evidence gates
and recovery. This adapter changes exactly one historical assumption: its
synthetic TestRun is explicitly non-production, so it must not carry a
production_batch_id and must not be bootstrapped into a TestRound Mission Graph.

Production missions are verified separately by rc8_formal_center_round_entry_test.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient


_ORIGINAL_POST = TestClient.post


def _patched_post(self: TestClient, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
    payload = kwargs.get("json")
    if (
        str(url) == "/api/v1/test-runs"
        and isinstance(payload, dict)
        and payload.get("production_batch_id") == "PB-IT"
        and (payload.get("payload") or {}).get("scope") == "formal-center-integration"
    ):
        rewritten = dict(payload)
        rewritten.pop("production_batch_id", None)
        rewritten["payload"] = dict(rewritten.get("payload") or {})
        rewritten["payload"]["truth_scope"] = "STANDALONE_CONTROL_REGRESSION"
        kwargs = dict(kwargs)
        kwargs["json"] = rewritten
    return _ORIGINAL_POST(self, url, *args, **kwargs)


def main() -> int:
    TestClient.post = _patched_post  # type: ignore[method-assign]
    try:
        from scripts import rc8_formal_center_stack_test as legacy
        return int(legacy.main())
    finally:
        TestClient.post = _ORIGINAL_POST  # type: ignore[method-assign]


if __name__ == "__main__":
    raise SystemExit(main())
