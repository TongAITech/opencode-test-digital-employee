import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from rc6_runtime.process_environment import scoped_process_environment
from rc7_runtime.runtime_execution import _EvidenceBackedProcessHarness


def test_real_child_does_not_inherit_parent_credentials_or_pytest_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv('RC72_PARENT_SECRET', 'ambient-secret-not-for-child')
    monkeypatch.setenv('PYTEST_ADDOPTS', '--this-parent-option-must-not-reach-child')
    monkeypatch.setenv('PYTHONPATH', '/parent-path-must-not-reach-child')
    harness = _EvidenceBackedProcessHarness(evidence_root=str(tmp_path), timeout_seconds=10)
    script = "import os,json; print(json.dumps({k:os.environ.get(k) for k in ['RC72_PARENT_SECRET','TASK_SCOPED_VALUE','PYTEST_ADDOPTS','PYTHONPATH','HOME']}))"
    result = harness.run('isolated-child', (sys.executable, '-c', script), str(tmp_path), {'TASK_SCOPED_VALUE': 'explicit-task-value'})
    assert result.passed
    values = json.loads(Path(result.stdout_ref[len('file://'):]).read_text())
    assert values['RC72_PARENT_SECRET'] is None and values['PYTHONPATH'] is None and values['PYTEST_ADDOPTS'] is None
    assert values['TASK_SCOPED_VALUE'] == 'explicit-task-value'
    assert str(tmp_path) in values['HOME']
    assert os.environ['RC72_PARENT_SECRET'] == 'ambient-secret-not-for-child'


@pytest.mark.parametrize('key', ['PYTHONPATH', 'PYTHONHOME', 'PYTEST_PLUGINS', 'BASH_ENV', 'LD_PRELOAD', 'DYLD_INSERT_LIBRARIES'])
def test_explicit_process_injection_controls_are_rejected(tmp_path, key):
    with pytest.raises(ValueError, match='INJECTION_FORBIDDEN'):
        scoped_process_environment({key: 'injected'}, home=tmp_path)


def test_formal_runner_rejects_module_injection_before_qualification(tmp_path):
    from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
    from types import SimpleNamespace
    with pytest.raises(ValueError, match='INJECTION_FORBIDDEN'):
        FormalN7RunnerAdapter(SimpleNamespace(truth=None), evidence_root=tmp_path,
                              execution_env={'PYTHONPATH': '/unapproved-import-root'})
