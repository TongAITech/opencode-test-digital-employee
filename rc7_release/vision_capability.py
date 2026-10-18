from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional

from .optional_enhancements import probe as probe_optional

LOCAL_OCR_MARKER = Path("workspace-template/runtime/python/.rc7-capabilities/local_ocr_cv.json")
VISION_PLUGIN = "dsh-vision-router"
POLICY = "LOCAL_FIRST_OPTIONAL_DSH_VISION_APPROVED_BANK_VLM_NO_PUBLIC_UPLOAD"


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def probe(home: Path) -> Dict[str, object]:
    root = Path(home).expanduser().resolve()
    local_marker = root / LOCAL_OCR_MARKER
    local_ready = local_marker.is_file() and local_marker.stat().st_size > 0
    optional = probe_optional(root)
    vision_row = (optional.get("plugins") or {}).get(VISION_PLUGIN) or {}
    vision_plugin_available = bool(vision_row.get("available"))
    router_active = _enabled("PFC_RC7_VISION_ROUTER_ACTIVE")
    bank_vlm_endpoint = os.environ.get("PFC_BANK_VLM_ENDPOINT", "").strip()
    bank_vlm_approved = _enabled("PFC_BANK_VLM_APPROVED")
    bank_vlm_ready = bool(bank_vlm_endpoint and bank_vlm_approved)
    requested = os.environ.get("PFC_RC7_VISION_MODE", "auto").strip().lower() or "auto"
    allowed = {"auto", "local", "dsh", "bank_vlm"}
    if requested not in allowed:
        return {"status": "FAIL", "reason": "VISION_MODE_INVALID", "requested_mode": requested, "allowed": sorted(allowed)}
    selected: Optional[str] = None; blocker: Optional[str] = None
    if requested == "local": selected = "LOCAL_OCR_CV" if local_ready else None; blocker = None if selected else "LOCAL_OCR_CV_UNAVAILABLE"
    elif requested == "dsh": selected = "DSH_VISION_ROUTER" if vision_plugin_available and router_active else None; blocker = None if selected else "DSH_VISION_ROUTER_NOT_ACTIVE"
    elif requested == "bank_vlm": selected = "BANK_VLM" if bank_vlm_ready else None; blocker = None if selected else "BANK_VLM_NOT_APPROVED_OR_NOT_CONFIGURED"
    else:
        if vision_plugin_available and router_active: selected = "DSH_VISION_ROUTER"
        elif local_ready: selected = "LOCAL_OCR_CV"
        elif bank_vlm_ready: selected = "BANK_VLM"
        else: blocker = "NO_APPROVED_VISION_PROVIDER_READY"
    return {
        "status": "PASS" if selected else "HOLD",
        "policy": POLICY,
        "requested_mode": requested,
        "selected_provider": selected,
        "blocking_reason": blocker,
        "public_remote_image_upload": False,
        "local_ocr_cv": {"ready": local_ready, "marker": str(local_marker)},
        "dsh_vision_router": {"available": vision_plugin_available, "active": router_active, "path": vision_row.get("path") or "", "activation_env": "PFC_RC7_VISION_ROUTER_ACTIVE"},
        "bank_vlm": {"configured": bool(bank_vlm_endpoint), "approved": bank_vlm_approved, "ready": bank_vlm_ready, "endpoint_masked": "configured" if bank_vlm_endpoint else ""},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe RC7 local/DSH/bank vision capabilities without public image upload"); parser.add_argument("--home", required=True); parser.add_argument("--output"); args = parser.parse_args(argv); result = probe(Path(args.home)); text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text + "\n", encoding="utf-8")
    print(text); return 0 if result.get("status") in {"PASS", "HOLD"} else 2


if __name__ == "__main__": raise SystemExit(main())
