"""RC6 release engineering helpers."""

from .package import BUILD_STATUS, build_package, verify_package
from .execution_closure_hardening import install_execution_closure_hardening

# Install before rc6_release.mcp_server imports execution_closure_mcp symbols.
# This preserves the frozen/base implementation while enforcing the fail-closed
# Execution Closure control-plane overlay for every package/runtime import.
install_execution_closure_hardening()

__all__ = ["BUILD_STATUS", "build_package", "verify_package", "install_execution_closure_hardening"]
