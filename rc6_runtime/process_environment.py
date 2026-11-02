"""Explicit child-process environment; ambient credentials are not inherited."""
import os
import re
from pathlib import Path

_BASE = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'TMPDIR',
         'LANG', 'LC_ALL', 'TZ', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
         'JAVA_HOME', 'JDK_HOME', 'MAVEN_HOME', 'M2_HOME', 'GRADLE_HOME'}
_FORBIDDEN = {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'PYTEST_ADDOPTS',
              'PYTEST_PLUGINS', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'BASH_ENV', 'ENV'}


def scoped_process_environment(explicit=None, *, home, allow_explicit_pythonpath=False):
    """Only explicit, task-scoped secrets may enter; no values are persisted.

    This is environment/config isolation, not an OS filesystem sandbox.
    """
    base = {key: value for key, value in os.environ.items() if key.upper() in _BASE}
    local_home = Path(home).resolve()
    local_home.mkdir(parents=True, exist_ok=True)
    base.update(HOME=str(local_home), USERPROFILE=str(local_home),
                APPDATA=str(local_home / 'AppData' / 'Roaming'),
                LOCALAPPDATA=str(local_home / 'AppData' / 'Local'),
                PYTHONNOUSERSITE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    for key, value in dict(explicit or {}).items():
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
                or not isinstance(value, str) or '\x00' in value):
            raise ValueError('PROCESS_ENVIRONMENT_ENTRY_INVALID')
        if ((key.upper() in _FORBIDDEN and not (allow_explicit_pythonpath and key.upper() == 'PYTHONPATH'))
                or key.upper().startswith('DYLD_')):
            raise ValueError('PROCESS_ENVIRONMENT_INJECTION_FORBIDDEN')
        base[key] = value
    # Caller cannot enable ambient user-site/plugin discovery in child Python.
    base['PYTHONNOUSERSITE'], base['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1', '1'
    return base
