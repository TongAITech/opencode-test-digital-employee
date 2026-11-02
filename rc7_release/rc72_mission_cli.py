"""Read-only canonical RC7.2 ReleaseBatch status entry; no worker configuration."""
import argparse
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_release_driver import release_batch_status


def main(argv=None):
    parser = argparse.ArgumentParser(description='RC7.2 ReleaseBatch mission status')
    parser.add_argument('command', choices=['status'])
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--release-batch', required=True)
    args = parser.parse_args(argv)
    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        parser.error('existing canonical ledger required')
    result = release_batch_status(TruthRuntime(path), source_commit=args.source_commit, release_batch_id=args.release_batch)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
