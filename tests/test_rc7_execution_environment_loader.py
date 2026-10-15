from __future__ import annotations

import sys
from types import ModuleType

import pytest

from rc7_release.execution_environment import (
    ExecutionEnvironmentLoadError,
    ExecutionEnvironmentLoader,
)
from rc7_runtime.execution_environment import ExecutionEnvironmentAdapter, ToolProbeResult


class _Adapter(ExecutionEnvironmentAdapter):
    @property
    def adapter_id(self):
        return "loader-test-adapter"

    def probe_tool(self, *, tool_id, target_id, layer):
        return ToolProbeResult(
            tool_id=tool_id,
            success=True,
            locator_ref="locator://%s" % tool_id,
            executable_ref="executable://%s" % tool_id,
            registration_ref="registration://%s" % tool_id,
            tool_call_ref="call://%s" % tool_id,
            evidence_ref="evidence://%s" % tool_id,
            target_readiness_ref="ready://%s/%s" % (tool_id, target_id),
        )

    def resolve_precondition(self, spec, context):
        return {"success": True, "evidence_ref": "evidence://pre"}

    def prepare_data(self, requirement, context, *, strategy):
        return {
            "success": True,
            "binding": {"strategy": strategy},
            "tool_call_ref": "call://data",
            "evidence_ref": "evidence://data",
        }

    def verify_data(self, requirement, binding, context):
        return {"success": True, "evidence_ref": "evidence://verify"}


def _install(name, factory=None):
    module = ModuleType(name)
    if factory is not None:
        module.create_execution_environment = factory
    sys.modules[name] = module
    return module


def test_loader_accepts_only_fixed_factory_returning_runtime_adapter():
    name = "rc7_loader_fixture_good"
    _install(name, lambda: _Adapter())
    try:
        loaded = ExecutionEnvironmentLoader.load(name)
        assert loaded.module_name == name
        assert loaded.factory_name == "create_execution_environment"
        assert loaded.adapter.adapter_id == "loader-test-adapter"
    finally:
        sys.modules.pop(name, None)


def test_loader_rejects_file_paths_and_non_module_names():
    for value in ("./adapter.py", "C:\\adapter.py", "adapter.py/other", "adapter-module"):
        with pytest.raises(ExecutionEnvironmentLoadError, match="MODULE_NAME_INVALID"):
            ExecutionEnvironmentLoader.load(value)


def test_loader_rejects_module_without_fixed_factory():
    name = "rc7_loader_fixture_no_factory"
    _install(name)
    try:
        with pytest.raises(ExecutionEnvironmentLoadError, match="FACTORY_REQUIRED"):
            ExecutionEnvironmentLoader.load(name)
    finally:
        sys.modules.pop(name, None)


def test_loader_rejects_factory_returning_static_dict_claim():
    name = "rc7_loader_fixture_fake_json"
    _install(name, lambda: {"success": True, "database": "ready"})
    try:
        with pytest.raises(ExecutionEnvironmentLoadError, match="FACTORY_RETURN_INVALID"):
            ExecutionEnvironmentLoader.load(name)
    finally:
        sys.modules.pop(name, None)
