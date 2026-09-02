from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "live_probe.py"
SPEC = importlib.util.spec_from_file_location("yuxi_opencode_live_probe", MODULE_PATH)
assert SPEC and SPEC.loader
live_probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live_probe
SPEC.loader.exec_module(live_probe)


def test_provider_inventory_is_secret_free_and_model_selection_is_deterministic():
    raw = {
        "all": [
            {
                "id": "bank-deepseek",
                "name": "Bank DeepSeek",
                "models": {
                    "deepseek-v4-flash": {
                        "id": "deepseek-v4-flash",
                        "apiKey": "MUST_NOT_LEAK",
                    }
                },
                "apiKey": "MUST_NOT_LEAK",
            }
        ],
        "connected": ["bank-deepseek"],
        "default": {"chat": "bank-deepseek/deepseek-v4-flash"},
        "secret": "MUST_NOT_LEAK",
    }

    inventory, connected, defaults = live_probe._extract_provider_inventory(raw)

    assert inventory == [
        {
            "provider_id": "bank-deepseek",
            "name": "Bank DeepSeek",
            "connected": True,
            "model_ids": ["deepseek-v4-flash"],
        }
    ]
    assert connected == ["bank-deepseek"]
    assert defaults == {"chat": "bank-deepseek/deepseek-v4-flash"}
    assert "MUST_NOT_LEAK" not in repr(inventory)

    selection = live_probe._choose_model(inventory, connected, None, None)
    assert selection.provider_id == "bank-deepseek"
    assert selection.model_id == "deepseek-v4-flash"
    assert selection.reason == "single-model-auto-selected"


def test_model_selection_requires_explicit_choice_when_inventory_is_ambiguous():
    inventory = [
        {"provider_id": "p1", "name": "P1", "connected": True, "model_ids": ["m1", "m2"]},
        {"provider_id": "p2", "name": "P2", "connected": True, "model_ids": ["m3"]},
    ]

    missing_provider = live_probe._choose_model(inventory, ["p1", "p2"], None, None)
    assert missing_provider.provider_id is None
    assert missing_provider.reason == "provider-selection-required"

    missing_model = live_probe._choose_model(inventory, ["p1", "p2"], "p1", None)
    assert missing_model.provider_id == "p1"
    assert missing_model.model_id is None
    assert missing_model.reason == "model-selection-required"

    explicit = live_probe._choose_model(inventory, ["p1", "p2"], "p1", "m2")
    assert explicit.reason == "explicit"


def test_basic_auth_header_never_exposes_plain_password():
    header = live_probe._basic_auth_header("opencode", "sensitive-password")
    assert "sensitive-password" not in repr(header)
    encoded = header["Authorization"].split(" ", 1)[1]
    assert base64.b64decode(encoded).decode("utf-8") == "opencode:sensitive-password"


def test_agent_and_session_projection_are_narrow():
    assert live_probe._extract_agents([{"name": "build", "permission": {"bash": "allow"}}, {"id": "proxy"}]) == [
        "build",
        "proxy",
    ]
    sessions = live_probe._session_snapshot(
        [
            {"id": "ses-1", "title": "normal", "messages": ["secret"]},
            {"id": "ses-2", "title": "yuxi-model-gateway"},
        ]
    )
    assert sessions == {"ses-1": "normal", "ses-2": "yuxi-model-gateway"}
