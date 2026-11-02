"""Process-held serialization for RC7.2 resource and capability decisions.

The lock is acquired before refreshing R1 and held through the reservation
write. An OS-released handle, not a durable marker, owns the critical section.
This does not claim to fence external tools or serialize legacy R1 writers.
"""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path

from .models import ContractError


def ledger_lock_path(truth):
    event_path = Path(truth.store.path).resolve()
    return event_path.parent / ('.' + event_path.name + '.rc72-ledger.lock')


@contextmanager
def ledger_lock(truth, *, busy='RC72_RESOURCE_LEDGER_BUSY', conflict=ContractError):
    path = ledger_lock_path(truth)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        # Lock the range before reading or writing it. Windows denies even
        # this process's second handle access to an exclusively locked byte.
        # CRT _locking permits a range beyond EOF, so no sentinel is needed:
        # https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise conflict(busy) from exc
        try:
            truth.rebuild_projection()
            # Each JsonlEventStore caches its next sequence in-process. Refresh
            # that cursor under the same OS lock before any participating write.
            truth.store._next_seq = truth.store._scan_next_seq()
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resource_guard(*, busy, conflict=ContractError):
    def decorate(method):
        @wraps(method)
        def guarded(self, *args, **kwargs):
            with ledger_lock(self.truth, busy=busy, conflict=conflict):
                return method(self, *args, **kwargs)
        return guarded
    return decorate
