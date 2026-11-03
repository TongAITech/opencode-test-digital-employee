"""Controller authority files are never model-facing source artifacts."""
from pathlib import Path


def is_controller_secret_path(path):
    resolved = Path(path).resolve()
    return (resolved.name.casefold() == 'controller.key'
            and resolved.parent.name.casefold() == 'authority')
