from __future__ import annotations

# Public compatibility entrypoint. The hardened implementation lives in a
# separate module so the BANK_FINAL proof can evolve without reopening frozen
# Wave modules or leaving an older permissive qualification path callable.
from .agent_qualification_runtime import main, run_real_vertical_slice

__all__ = ["main", "run_real_vertical_slice"]


if __name__ == "__main__":
    raise SystemExit(main())
