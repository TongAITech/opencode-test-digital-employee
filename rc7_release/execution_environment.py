"""Strict loader for field ExecutionEnvironmentAdapter implementations.

The qualification CLI accepts a Python module name, not a JSON object claiming
success and not an arbitrary file path.  The module must export the fixed
factory `create_execution_environment()` and return the RC7 runtime adapter
contract.  Configuration/secrets remain the adapter's concern (normally via
field-local environment/config); they are never serialized by this loader.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from types import ModuleType

from rc7_runtime.execution_environment import ExecutionEnvironmentAdapter


class ExecutionEnvironmentLoadError(RuntimeError):
    pass


_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FACTORY = "create_execution_environment"


@dataclass(frozen=True)
class LoadedExecutionEnvironment:
    module_name: str
    factory_name: str
    adapter: ExecutionEnvironmentAdapter


class ExecutionEnvironmentLoader:
    @staticmethod
    def load(module_name: str) -> LoadedExecutionEnvironment:
        if not isinstance(module_name, str) or not module_name.strip():
            raise ExecutionEnvironmentLoadError("EXECUTION_ENVIRONMENT_MODULE_REQUIRED")
        name = module_name.strip()
        if not _MODULE.match(name):
            raise ExecutionEnvironmentLoadError("EXECUTION_ENVIRONMENT_MODULE_NAME_INVALID")
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            raise ExecutionEnvironmentLoadError(
                "EXECUTION_ENVIRONMENT_MODULE_IMPORT_FAILED:%s" % type(exc).__name__
            ) from exc
        return ExecutionEnvironmentLoader.from_module(name, module)

    @staticmethod
    def from_module(module_name: str, module: ModuleType) -> LoadedExecutionEnvironment:
        factory = getattr(module, _FACTORY, None)
        if not callable(factory):
            raise ExecutionEnvironmentLoadError("EXECUTION_ENVIRONMENT_FACTORY_REQUIRED")
        try:
            adapter = factory()
        except Exception as exc:
            raise ExecutionEnvironmentLoadError(
                "EXECUTION_ENVIRONMENT_FACTORY_FAILED:%s" % type(exc).__name__
            ) from exc
        if not isinstance(adapter, ExecutionEnvironmentAdapter):
            raise ExecutionEnvironmentLoadError("EXECUTION_ENVIRONMENT_FACTORY_RETURN_INVALID")
        adapter_id = str(adapter.adapter_id or "").strip()
        if not adapter_id:
            raise ExecutionEnvironmentLoadError("EXECUTION_ENVIRONMENT_ADAPTER_ID_REQUIRED")
        return LoadedExecutionEnvironment(
            module_name=module_name,
            factory_name=_FACTORY,
            adapter=adapter,
        )
