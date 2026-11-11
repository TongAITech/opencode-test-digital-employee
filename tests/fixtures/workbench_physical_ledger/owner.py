"""Physical-file lock probe. This fixture has no production entry point."""

import errno
import json
import os
from pathlib import Path
import sys


def identity(stat):
    return stat.st_dev, stat.st_ino


def reply(value):
    print(value, flush=True)


def lock(ledger):
    if os.name == "nt":
        import msvcrt

        # Lock a byte outside the fixture payload so a reader can inspect the
        # ledger while a cooperating writer holds the ownership lock.
        ledger.seek(1 << 30)
        msvcrt.locking(ledger.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def run(path, expected_identity, epoch):
    # Open without creating a missing or replacement ledger.
    with path.open("r+b", buffering=0) as ledger:
        if identity(os.fstat(ledger.fileno())) != expected_identity:
            reply("FILE_IDENTITY_CHANGED")
            return
        try:
            lock(ledger)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            reply("LOCK_BUSY")
            return

        reply("LOCK_HELD")
        for raw in sys.stdin:
            command = json.loads(raw)
            if command["epoch"] != epoch:
                reply("STALE_EPOCH")
                continue
            try:
                same_path = identity(path.stat()) == expected_identity
            except FileNotFoundError:
                same_path = False
            if not same_path:
                reply("FILE_IDENTITY_CHANGED")
                continue
            # Only the temporary fixture can supply pre-encoded native rows.
            # The open descriptor, rather than a reopened path, receives them.
            ledger.seek(0, os.SEEK_END)
            row = bytes.fromhex(command["row"])
            if ledger.write(row) != len(row):
                raise OSError("short fixture append")
            os.fsync(ledger.fileno())
            if command.get("exit_after_sync") is True:
                os._exit(79)
            reply("SYNCED")


if __name__ == "__main__":
    path, device, inode, epoch = sys.argv[1:]
    run(Path(path), (int(device), int(inode)), int(epoch))
