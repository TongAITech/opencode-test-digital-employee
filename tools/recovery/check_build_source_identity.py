"""Focused construction check: seal committed source identity before payload overlays."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from build_package import build, SOURCE_IDENTITY_FORMULA


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def committed_identity(repo: Path, head: str) -> tuple[str, dict[str, str]]:
    paths = sorted(p.decode('utf-8') for p in git(repo, 'ls-tree', '-r', '--name-only', '-z', head).split(b'\0')
                   if p and p != b'PACKAGE_MANIFEST.json')
    files = {p: hashlib.sha256(git(repo, 'show', head + ':' + p)).hexdigest() for p in paths}
    raw = ('\n'.join(f'{digest}  {path}' for path, digest in files.items()) + '\n').encode('utf-8')
    return hashlib.sha256(raw).hexdigest(), files


class SourceIdentitySealCheck(unittest.TestCase):
    def test_clean_crlf_registry_checkout_cannot_replace_committed_archive_bytes(self):
        with tempfile.TemporaryDirectory(prefix='aitest-build-crlf-identity-') as temporary:
            root = Path(temporary); repo = root / 'source'; repo.mkdir()
            git(repo, 'init', '-q')
            git(repo, 'config', 'core.autocrlf', 'true')
            files = {
                'INSTALL.sh': '#!/bin/sh\n', 'AITEST.sh': '#!/bin/sh\n',
                'INSTALL_MANIFEST.json': '{"status":"NOT_INSTALLED"}\n',
                'tools/recovery/install.py': '# construction fixture\n',
                'tools/recovery/launcher.py': '# construction fixture\n',
                'tools/recovery/validate_package.py': '# construction fixture\n',
                'VALIDATION_README.md': 'fixture\n', 'CAPABILITY_PARITY_MATRIX.md': 'fixture\n',
                'MACHINE_VALIDATION_RESULT.json': '{}\n', 'PACKAGE_MANIFEST.json': '{}\n',
                'OFFLINE_PAYLOAD_REGISTRY.json': '{\n  "staged_artifacts": []\n}\n',
            }
            for relative, content in files.items():
                path = repo / relative; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content.encode('utf-8'))
            git(repo, 'add', '.')
            git(repo, '-c', 'user.name=Construction Check', '-c', 'user.email=construction@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-qm', 'CRLF construction fixture')
            head = git(repo, 'rev-parse', 'HEAD').decode().strip()
            committed_registry = git(repo, 'show', head + ':OFFLINE_PAYLOAD_REGISTRY.json')
            self.assertNotIn(b'\r\n', committed_registry)
            registry = repo / 'OFFLINE_PAYLOAD_REGISTRY.json'
            registry.unlink()
            git(repo, 'checkout', '--', 'OFFLINE_PAYLOAD_REGISTRY.json')
            self.assertIn(b'\r\n', registry.read_bytes())
            self.assertNotEqual(registry.read_bytes(), committed_registry)
            # This is the real Windows failure condition: different physical
            # bytes while Git still reports the exact source checkout as clean.
            self.assertEqual(git(repo, 'status', '--porcelain'), b'')
            stage = root / 'stage'
            for relative in ['python/python.exe', 'python/python312.dll', 'opencode/opencode.exe',
                             'browser/chrome-win64/chrome.exe',
                             'code-intelligence/codegraph/codegraph-server-win32-x64.exe',
                             'code-intelligence/codegraph/onnxruntime.dll']:
                path = stage / 'workspace-template/runtime' / relative
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'construction fixture bytes')
            result = build(repo, stage, root / 'output', '1.12.0', store_only=True)
            bundle = Path(result['bundle'])
            committed_sha = hashlib.sha256(committed_registry).hexdigest()
            delivered = (bundle / 'OFFLINE_PAYLOAD_REGISTRY.json').read_bytes()
            self.assertEqual(delivered, committed_registry)
            checksums = json.loads((bundle / 'FILE_SHA256.json').read_text())
            provenance = json.loads((bundle / 'BUILD_PROVENANCE.json').read_text())
            expected_identity, _ = committed_identity(repo, head)
            self.assertEqual(result['source_content_identity'], expected_identity)
            self.assertEqual(checksums['OFFLINE_PAYLOAD_REGISTRY.json'], committed_sha)
            self.assertEqual(provenance['registry_sha256'], committed_sha)
            source_entries = {entry['path']: entry['sha256'] for entry in provenance['source_identity']['files']}
            self.assertEqual(source_entries['OFFLINE_PAYLOAD_REGISTRY.json'], committed_sha)
            with zipfile.ZipFile(result['zip']) as archive:
                self.assertEqual(archive.read(bundle.name + '/OFFLINE_PAYLOAD_REGISTRY.json'), committed_registry)
            self.assertEqual(git(repo, 'status', '--porcelain'), b'')

    def test_committed_identity_is_refreshed_and_excludes_payload_overlays(self):
        with tempfile.TemporaryDirectory(prefix='aitest-build-identity-') as temporary:
            root = Path(temporary); repo = root / 'source'; repo.mkdir()
            git(repo, 'init', '-q')
            source_files = {
                'AITEST.sh': '#!/bin/sh\n',
                'INSTALL.sh': '#!/bin/sh\n',
                'INSTALL_MANIFEST.json': '{"status":"NOT_INSTALLED"}\n',
                'tools/recovery/install.py': '# construction fixture\n',
                'tools/recovery/launcher.py': '# construction fixture\n',
                'tools/recovery/validate_package.py': '# construction fixture\n',
                'VALIDATION_README.md': 'fixture\n', 'CAPABILITY_PARITY_MATRIX.md': 'fixture\n',
                'MACHINE_VALIDATION_RESULT.json': '{}\n',
                'OFFLINE_PAYLOAD_REGISTRY.json': '{"staged_artifacts": []}\n',
                'workspace-template/.opencode/package-lock.json': '{"source":"committed"}\n',
                'workspace-template/需求 source.txt': '原始源码\n',
                'PACKAGE_MANIFEST.json': json.dumps({'source_identity_formula': SOURCE_IDENTITY_FORMULA,
                    'source_content_identity': 'f' * 64, 'candidate_commit': 'STALE'}) + '\n',
            }
            for relative, content in source_files.items():
                path = repo / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding='utf-8')
            def commit():
                git(repo, 'add', '.')
                git(repo, '-c', 'user.name=Construction Check', '-c', 'user.email=construction@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '-qm', 'construction fixture')
                return git(repo, 'rev-parse', 'HEAD').decode().strip()
            head = commit()
            stage = root / 'stage'
            for relative in ['python/python.exe', 'python/python312.dll', 'opencode/opencode.exe',
                             'browser/chrome-win64/chrome.exe',
                             'code-intelligence/codegraph/codegraph-server-win32-x64.exe',
                             'code-intelligence/codegraph/onnxruntime.dll']:
                path = stage / 'workspace-template/runtime' / relative
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'construction fixture bytes')
            shadow = stage / 'workspace-template/.opencode/package-lock.json'
            shadow.parent.mkdir(parents=True, exist_ok=True); shadow.write_text('{"payload":"first"}\n')
            expected, committed_files = committed_identity(repo, head)
            first = build(repo, stage, root / 'first', '1.12.0', store_only=True)
            bundle = Path(first['bundle'])
            manifest = json.loads((bundle / 'PACKAGE_MANIFEST.json').read_text())
            provenance = json.loads((bundle / 'BUILD_PROVENANCE.json').read_text())
            checksums = json.loads((bundle / 'FILE_SHA256.json').read_text())
            self.assertEqual(manifest['candidate_commit'], head)
            self.assertEqual(manifest['source_content_identity'], expected)
            self.assertEqual(provenance['source_content_identity'], expected)
            self.assertEqual(provenance['source_head'], head)
            self.assertEqual({x['path']: x['sha256'] for x in provenance['source_identity']['files']}, committed_files)
            self.assertEqual(provenance['generated_build_overlays'][0]['source_archive_sha256'],
                             hashlib.sha256(git(repo, 'show', head + ':PACKAGE_MANIFEST.json')).hexdigest())
            self.assertEqual(provenance['generated_build_overlays'][0]['generated_sha256'], checksums['PACKAGE_MANIFEST.json'])
            self.assertEqual(checksums['BUILD_PROVENANCE.json'], hashlib.sha256((bundle / 'BUILD_PROVENANCE.json').read_bytes()).hexdigest())
            self.assertEqual((bundle / 'workspace-template/.opencode/package-lock.json').read_bytes(), shadow.read_bytes())
            self.assertEqual(json.loads((repo / 'PACKAGE_MANIFEST.json').read_text())['candidate_commit'], 'STALE')
            # Derived bytes change without changing the identity of committed source.
            shadow.write_text('{"payload":"second"}\n')
            second = build(repo, stage, root / 'second', '1.12.0', store_only=True)
            self.assertEqual(second['source_content_identity'], expected)
            self.assertNotEqual(first['sha256'], second['sha256'])
            # A new source commit refreshes both the exact commit and source identity.
            (repo / 'workspace-template/需求 source.txt').write_text('修订源码\n', encoding='utf-8')
            new_head = commit(); new_expected, _ = committed_identity(repo, new_head)
            third = build(repo, stage, root / 'third', '1.12.0', store_only=True)
            self.assertNotEqual(new_expected, expected)
            self.assertEqual(third['source_content_identity'], new_expected)
            self.assertEqual(json.loads((Path(third['bundle']) / 'PACKAGE_MANIFEST.json').read_text())['candidate_commit'], new_head)


if __name__ == '__main__':
    unittest.main(verbosity=2)
