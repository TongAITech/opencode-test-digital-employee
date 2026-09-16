"""Launch package-owned runtime modules from the current installed workspace.

Windows embedded Python distributions can ignore PYTHONPATH when a ._pth file is
present.  Every package-owned child therefore injects the installed
ai-test/runtime directory inside the child interpreter before importing the
target module.  This prevents a carrier/site-packages copy of aitest_runtime
from becoming a second runtime implementation over the same R1 Event Stream.
"""
from __future__ import annotations

from pathlib import Path
import sys

_BOOTSTRAP = r"""
import importlib.util
import runpy
import sys
from pathlib import Path

runtime_root = Path(sys.argv[1]).resolve()
module = sys.argv[2]
sys.path.insert(0, str(runtime_root))
spec = importlib.util.find_spec(module)
if spec is None or spec.origin is None:
    raise RuntimeError("AITEST_RUNTIME_MODULE_NOT_FOUND:" + module)
origin = Path(spec.origin).resolve()
try:
    origin.relative_to(runtime_root)
except ValueError as exc:
    raise RuntimeError(
        "AITEST_RUNTIME_MODULE_IDENTITY_MISMATCH:"
        + module + ":" + str(origin) + ":" + str(runtime_root)
    ) from exc
sys.argv = [module, *sys.argv[3:]]
runpy.run_module(module, run_name="__main__")
"""


def runtime_module_command(workspace_root: str | Path, module: str, *args: str) -> list[str]:
    root = Path(workspace_root).expanduser().resolve()
    runtime_root = (root / "ai-test" / "runtime").resolve()
    package_root = runtime_root / "aitest_runtime"
    if not package_root.is_dir():
        raise RuntimeError("AITEST_RUNTIME_SOURCE_ROOT_REQUIRED:" + str(runtime_root))
    if not isinstance(module, str) or not module.startswith("aitest_runtime."):
        raise ValueError("AITEST_RUNTIME_MODULE_REQUIRED")
    return [
        sys.executable,
        "-X",
        "utf8",
        "-c",
        _BOOTSTRAP,
        str(runtime_root),
        module,
        *(str(item) for item in args),
    ]


__all__ = ["runtime_module_command"]
