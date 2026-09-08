"""Reassemble the current exact Git HEAD using only hash-locked carrier payloads.

The carrier ZIP supplies offline dependencies, never source or qualification.
Runs on the construction runner with the carrier's portable Python.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_package import build, sha256


def reassemble(repo: Path, carrier: Path, output: Path) -> dict:
    registry = json.loads((repo / 'OFFLINE_PAYLOAD_REGISTRY.json').read_text(encoding='utf-8'))
    expected = {}
    for artifact in registry['staged_artifacts']:
        entries = artifact.get('tree_manifest') or []
        if artifact.get('hash_kind') == 'file':
            entries = [{'path': artifact['relative_target'], 'sha256': artifact['sha256']}]
        for entry in entries:
            relative = entry['path']
            if relative in expected and expected[relative] != entry['sha256']:
                raise RuntimeError('Conflicting payload digest: ' + relative)
            expected[relative] = entry['sha256']
    if not expected:
        raise RuntimeError('Offline registry is empty')
    stage = output / 'payload-stage'
    stage.mkdir(parents=True, exist_ok=False)
    for relative, digest in expected.items():
        source = (carrier / relative).resolve()
        target = (stage / relative).resolve()
        if not source.is_relative_to(carrier.resolve()) or not target.is_relative_to(stage.resolve()):
            raise RuntimeError('Unsafe payload path')
        if not source.is_file() or sha256(source) != digest:
            raise RuntimeError('Carrier payload does not match current lock: ' + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    result = build(repo, stage, output / 'assembled', '1.12.0', store_only=True)
    result['carrier_scope'] = 'HASH_LOCKED_OFFLINE_PAYLOAD_ONLY; NO_SOURCE_OR_QUALIFICATION_REUSE'
    (output / 'REASSEMBLY_RESULT.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--carrier', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reassemble(args.repo.resolve(), args.carrier.resolve(), args.output.resolve()), indent=2))
