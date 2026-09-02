#!/usr/bin/env python3
"""Apply the OpenCode provider PoC as a narrow overlay to a Yuxi checkout.

This script is intentionally anchored to the reviewed Yuxi baseline.  It fails
closed if upstream edits move the integration seams, instead of guessing where
to inject code.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

YUXI_REVIEWED_BASELINE = "bd07ab4ac4faa2e5452507580b1c841543bbec61"


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one integration anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply(yuxi_root: Path) -> None:
    yuxi_root = yuxi_root.resolve()
    script_root = Path(__file__).resolve().parents[1]
    source_pkg = script_root / "src" / "yuxi_opencode_provider"

    models_py = yuxi_root / "backend/package/yuxi/agents/models.py"
    service_py = yuxi_root / "backend/package/yuxi/models/providers/service.py"
    ui_vue = yuxi_root / "web/src/components/model-management/ModelProviderManagePanel.vue"
    for required in (models_py, service_py, ui_vue):
        if not required.exists():
            raise RuntimeError(f"Not a compatible Yuxi checkout: missing {required}")

    target_pkg = yuxi_root / "backend/package/yuxi/models/opencode"
    target_pkg.mkdir(parents=True, exist_ok=True)
    for name in ("client.py", "chat_model.py", "__init__.py"):
        shutil.copyfile(source_pkg / name, target_pkg / name)

    _replace_once(
        models_py,
        "from yuxi.models.providers.cache import model_cache\nfrom yuxi.utils import get_docker_safe_url\n",
        "from yuxi.models.opencode import OpenCodeChatModel\n"
        "from yuxi.models.providers.cache import model_cache\n"
        "from yuxi.utils import get_docker_safe_url\n",
    )

    loader_anchor = """    logger.debug(f\"Loading model {fully_specified_name} with provider_type={info.provider_type}\")\n\n    if info.provider_type == \"anthropic\":\n"""
    loader_replacement = """    logger.debug(f\"Loading model {fully_specified_name} with provider_type={info.provider_type}\")\n\n    if info.provider_type == \"opencode\":\n        opencode_config = dict(info.extra or {})\n        opencode_provider_id = str(opencode_config.get(\"opencode_provider_id\") or \"\").strip()\n        if not opencode_provider_id:\n            raise ValueError(\n                f\"OpenCode provider {info.provider_id} requires extra_json.opencode_provider_id\"\n            )\n\n        metadata = kwargs.pop(\"metadata\", None)\n        if kwargs:\n            unsupported = \", \".join(sorted(kwargs))\n            raise ValueError(\n                \"OpenCode Session gateway cannot guarantee raw model invocation parameters: \" + unsupported\n            )\n\n        return OpenCodeChatModel(\n            base_url=base_url,\n            opencode_provider_id=opencode_provider_id,\n            model_id=info.model_id,\n            agent=str(opencode_config.get(\"opencode_agent\") or \"yuxi-model-provider-proxy\"),\n            directory=opencode_config.get(\"opencode_directory\"),\n            headers=dict(info.headers or {}),\n            metadata=metadata,\n        )\n\n    if info.provider_type == \"anthropic\":\n"""
    _replace_once(models_py, loader_anchor, loader_replacement)

    _replace_once(
        service_py,
        'VALID_PROVIDER_TYPES = {"openai", "anthropic", "gemini", "openrouter"}\n',
        'VALID_PROVIDER_TYPES = {"openai", "anthropic", "gemini", "openrouter", "opencode"}\n',
    )

    credential_anchor = """def check_credential_status(provider: ModelProvider) -> str:\n    \"\"\"检查 provider 的凭证配置状态。仅对启用的 provider 做校验。\"\"\"\n    if not provider.is_enabled:\n        return \"ok\"\n"""
    credential_replacement = """def check_credential_status(provider: ModelProvider) -> str:\n    \"\"\"检查 provider 的凭证配置状态。仅对启用的 provider 做校验。\"\"\"\n    if not provider.is_enabled:\n        return \"ok\"\n    if provider.provider_type == \"opencode\":\n        # The bank LLM credential is owned by OpenCode, not duplicated into Yuxi.\n        return \"ok\"\n"""
    _replace_once(service_py, credential_anchor, credential_replacement)

    remote_anchor = """async def fetch_remote_models(provider: ModelProvider) -> list[dict[str, Any]]:\n    \"\"\"按 provider 配置实时拉取远端模型列表，不落库。\n\n    Chat 模型默认走 /models；embedding 只有 provider 声明能力时才走\n    /embeddings/models；rerank 供应商没有稳定通用端点，配置了 endpoint 才拉取。\n    \"\"\"\n    headers = dict(provider.headers_json or {})\n"""
    remote_replacement = """async def fetch_remote_models(provider: ModelProvider) -> list[dict[str, Any]]:\n    \"\"\"按 provider 配置实时拉取远端模型列表，不落库。\n\n    Chat 模型默认走 /models；embedding 只有 provider 声明能力时才走\n    /embeddings/models；rerank 供应商没有稳定通用端点，配置了 endpoint 才拉取。\n    \"\"\"\n    if provider.provider_type == \"opencode\":\n        # Public OpenCode Session API is not an OpenAI /models API.  The PoC uses\n        # explicit manual model IDs until the bank OpenCode /provider shape is\n        # verified against the exact deployed version.\n        return []\n\n    headers = dict(provider.headers_json or {})\n"""
    _replace_once(service_py, remote_anchor, remote_replacement)

    ui_anchor = """const PROVIDER_TYPE_OPTIONS = [\n  { value: 'openai', label: 'OpenAI Completions API' },\n  { value: 'anthropic', label: 'Anthropic Messages API' }\n]\n"""
    ui_replacement = """const PROVIDER_TYPE_OPTIONS = [\n  { value: 'openai', label: 'OpenAI Completions API' },\n  { value: 'anthropic', label: 'Anthropic Messages API' },\n  { value: 'opencode', label: 'OpenCode Session Gateway' }\n]\n"""
    _replace_once(ui_vue, ui_anchor, ui_replacement)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yuxi-root", required=True, type=Path)
    args = parser.parse_args()
    apply(args.yuxi_root)
