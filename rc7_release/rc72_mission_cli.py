"""Canonical RC7.2 status and native run/continuation entry."""
import argparse
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_release_driver import release_batch_status


def main(argv=None):
    parser = argparse.ArgumentParser(description='RC7.2 ReleaseBatch mission')
    parser.add_argument('command', choices=['status', 'run'])
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--release-batch', required=True)
    parser.add_argument('--release-id')
    parser.add_argument('--bindings-module')
    parser.add_argument('--package-root')
    parser.add_argument('--evidence-root')
    args = parser.parse_args(argv)
    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        parser.error('existing canonical ledger required')
    truth = TruthRuntime(path)
    if args.command == 'status':
        result = release_batch_status(truth, source_commit=args.source_commit, release_batch_id=args.release_batch)
    else:
        if not all((args.release_id, args.bindings_module, args.package_root, args.evidence_root)):
            parser.error('run requires release-id, bindings-module, package-root and evidence-root')
        root = Path(args.package_root).expanduser().resolve()
        source = root/'SOURCE_COMMIT'
        if not source.is_file() or source.read_text(encoding='utf-8').strip() != args.source_commit:
            parser.error('run requires the exact package source commit')
        # Validate the existing canonical batch before loading any host module.
        snapshot = release_batch_status(truth, source_commit=args.source_commit, release_batch_id=args.release_batch)
        if snapshot['release_id'] != args.release_id:
            parser.error('run release does not match canonical batch')
        from dataclasses import fields
        from rc7_release.rc72_mission_bindings import load_mission_bindings
        from rc7_runtime.rc72_mission_factory import create_mission_driver
        bindings = load_mission_bindings(args.bindings_module, truth=truth,
            release_id=args.release_id, source_commit=args.source_commit)
        driver = create_mission_driver(truth, release_id=args.release_id, source_commit=args.source_commit,
            evidence_root=Path(args.evidence_root).expanduser().resolve(),
            **{f.name: getattr(bindings, f.name) for f in fields(bindings)})
        if driver.bank_pip_mirror.root != root:
            parser.error('native mirror provider must bind the running package')
        result = driver.run(release_batch_id=args.release_batch)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if args.command == 'status' else 37


if __name__ == '__main__':
    raise SystemExit(main())
