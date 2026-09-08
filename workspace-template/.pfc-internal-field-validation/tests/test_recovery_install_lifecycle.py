"""Installer adversarial contracts. Real portable execution is Windows qualification."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('recovery_installer', REPO / 'tools/recovery/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n', encoding='utf-8')


class InstallLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recovery-install-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'transport'
        self.source.mkdir()
        self.target = self.root / 'installed'
        for relative in installer.REQUIRED_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('sealed fixture bytes\n', encoding='utf-8')
        (self.source / 'workspace-template/runtime/tools/zap').mkdir()
        (self.source / 'workspace-template/runtime/tools/zap/zap-2.17.0.jar').write_bytes(b'fixture-jar')
        python_sha = installer.sha256(self.source / installer.PYTHON_RELATIVE)
        write(self.source / 'INSTALL_MANIFEST.json', {'schema_version': installer.SCHEMA, 'status': 'NOT_INSTALLED'})
        registry = {'staged_artifacts': [{'hash_kind': 'file', 'relative_target': installer.PYTHON_RELATIVE, 'sha256': python_sha}]}
        write(self.source / 'OFFLINE_PAYLOAD_REGISTRY.json', registry)
        write(self.source / 'PAYLOAD_SHA256SUMS.json', {installer.PYTHON_RELATIVE: python_sha})
        write(self.source / 'runtime-lock.json', {'payloads': {'python': {'relative_target': installer.PYTHON_RELATIVE, 'sha256': python_sha, 'version': '3.12.10'}}})
        write(self.source / 'BUILD_PROVENANCE.json', {'source_head': 'a' * 40, 'registry_sha256': installer.sha256(self.source / 'OFFLINE_PAYLOAD_REGISTRY.json')})
        self.reseal()

    def reseal(self):
        write(self.source / 'FILE_SHA256.json', {p.relative_to(self.source).as_posix(): installer.sha256(p)
              for p in self.source.rglob('*') if p.is_file() and p.name != 'FILE_SHA256.json'})

    def install(self):
        with patch.object(installer, 'run_installed_self_check', return_value={'status': 'PASS', 'fixture_boundary': 'CONTRACT_ONLY'}):
            return installer.install(self.source, self.target)

    def test_install_copies_sealed_payload_initializes_identity_and_never_starts_opencode(self):
        source_manifest = (self.source / 'FILE_SHA256.json').read_bytes()
        (self.source / 'unlisted-host-token.txt').write_text('do not copy this secret')
        with patch.object(installer.subprocess, 'Popen', side_effect=AssertionError('service startup forbidden')):
            identity = self.install()
        self.assertEqual(identity['status'], 'INSTALLED')
        self.assertEqual(identity['processes_started'], [])
        self.assertFalse(identity['network_install_performed'])
        self.assertFalse(identity['host_credentials_read_or_copied'])
        self.assertFalse((self.target / 'unlisted-host-token.txt').exists())
        self.assertFalse((self.target / '.AITEST_INSTALLING').exists())
        self.assertEqual((self.target / 'FILE_SHA256.json').read_bytes(), source_manifest)
        for directory in installer.DATA_DIRECTORIES:
            self.assertTrue((self.target / 'data' / directory).is_dir())
        self.assertTrue((self.target / 'workspace-template/bindings/installation.json').is_file())
        self.assertEqual(installer.verify_install_identity(self.target), [])
        self.assertEqual(installer.verify_package(self.target, installed=True)['status'], 'PASS')

    def test_existing_runtime_and_data_are_never_overwritten(self):
        self.target.mkdir()
        durable = self.target / 'runtime-spine.db'
        durable.write_bytes(b'user runtime truth')
        with self.assertRaisesRegex(installer.InstallError, 'INSTALL_TARGET_EXISTS'):
            self.install()
        self.assertEqual(durable.read_bytes(), b'user runtime truth')
        self.assertEqual(list(self.target.iterdir()), [durable])

    def test_existing_empty_directory_is_also_refused(self):
        self.target.mkdir()
        with self.assertRaisesRegex(installer.InstallError, 'INSTALL_TARGET_EXISTS'):
            self.install()

    def test_existing_dangling_link_is_refused(self):
        try:
            self.target.symlink_to(self.root / 'absent')
        except OSError:
            self.skipTest('This Windows host does not permit symlink creation')
        with self.assertRaisesRegex(installer.InstallError, 'INSTALL_TARGET_EXISTS'):
            self.install()

    def test_source_corruption_is_refused_before_creating_target(self):
        (self.source / 'workspace-template/runtime/opencode/opencode.exe').write_bytes(b'tampered')
        with self.assertRaisesRegex(installer.InstallError, 'PACKAGE_SHA256_MISMATCH'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_missing_payload_inventory_member_is_rejected(self):
        checksums = installer.read_json(self.source / 'FILE_SHA256.json')
        checksums.pop('workspace-template/runtime/tools/k6/k6.exe')
        write(self.source / 'FILE_SHA256.json', checksums)
        with self.assertRaisesRegex(installer.InstallError, 'REQUIRED_PAYLOAD_NOT_SEALED'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_inventory_traversal_and_case_collision_are_rejected(self):
        checksums = installer.read_json(self.source / 'FILE_SHA256.json')
        checksums['../outside'] = 'f' * 64
        write(self.source / 'FILE_SHA256.json', checksums)
        with self.assertRaisesRegex(installer.InstallError, 'UNSAFE_INVENTORY_PATH'):
            self.install()
        checksums.pop('../outside')
        checksums['aitest.sh'] = checksums['AITEST.sh']
        write(self.source / 'FILE_SHA256.json', checksums)
        with self.assertRaisesRegex(installer.InstallError, 'INVALID_CHECKSUM_INVENTORY'):
            self.install()

    def test_offline_registry_disagreement_is_rejected(self):
        write(self.source / 'PAYLOAD_SHA256SUMS.json', {installer.PYTHON_RELATIVE: 'f' * 64})
        self.reseal()
        with self.assertRaisesRegex(installer.InstallError, 'OFFLINE_REGISTRY_INVENTORY_MISMATCH'):
            self.install()

    def test_build_registry_identity_disagreement_is_rejected(self):
        write(self.source / 'BUILD_PROVENANCE.json', {'source_head': 'a' * 40, 'registry_sha256': 'f' * 64})
        self.reseal()
        with self.assertRaisesRegex(installer.InstallError, 'BUILD_REGISTRY_IDENTITY_MISMATCH'):
            self.install()

    def test_source_contained_target_is_rejected(self):
        with self.assertRaisesRegex(installer.InstallError, 'INSTALL_TARGET_OVERLAPS_TRANSPORT'):
            installer.install(self.source, self.source / 'installed')

    def test_copy_corruption_cannot_produce_ready_installation(self):
        original_copy = installer.shutil.copy2
        def corrupt(src, dest):
            original_copy(src, dest)
            if dest.name == 'python.exe':
                dest.write_bytes(b'copy corruption')
        with patch.object(installer.shutil, 'copy2', side_effect=corrupt):
            with self.assertRaisesRegex(installer.InstallError, 'PACKAGE_SHA256_MISMATCH'):
                self.install()
        self.assertTrue((self.target / '.AITEST_INSTALLING').exists())
        self.assertTrue(installer.verify_install_identity(self.target))

    def test_self_check_failure_retains_explicit_incomplete_marker(self):
        with patch.object(installer, 'run_installed_self_check', side_effect=installer.InstallError('portable import failed')):
            with self.assertRaisesRegex(installer.InstallError, 'portable import failed'):
                installer.install(self.source, self.target)
        self.assertEqual(installer.read_json(self.target / '.AITEST_INSTALLING')['status'], 'FAILED')
        self.assertTrue(installer.verify_install_identity(self.target))
        with self.assertRaisesRegex(installer.InstallError, 'INSTALL_TARGET_EXISTS'):
            self.install()

    def test_daily_identity_rejects_transport_and_moved_installation(self):
        self.assertTrue(installer.verify_install_identity(self.source))
        self.install()
        moved = self.root / 'moved'
        self.target.rename(moved)
        self.assertTrue(any('INSTALL_LOCATION_MISMATCH' in item for item in installer.verify_install_identity(moved)))

    def test_daily_integrity_allows_only_generated_install_manifest_overlay(self):
        self.install()
        (self.target / 'workspace-template/runtime/opencode/opencode.exe').write_bytes(b'modified installed executable')
        with self.assertRaisesRegex(installer.InstallError, 'PACKAGE_SHA256_MISMATCH'):
            installer.verify_package(self.target, installed=True)

    def test_daily_identity_detects_checksum_authority_replacement(self):
        self.install()
        checksums = installer.read_json(self.target / 'FILE_SHA256.json')
        checksums['AITEST.sh'] = 'e' * 64
        write(self.target / 'FILE_SHA256.json', checksums)
        self.assertIn('INSTALL_SOURCE_CHECKSUM_IDENTITY_MISMATCH', installer.verify_install_identity(self.target))

    def test_installed_probe_uses_only_installed_python_and_strips_host_secrets(self):
        captured = {}
        def run(argv, **kwargs):
            captured.update(argv=argv, **kwargs)
            return subprocess.CompletedProcess(argv, 0, '{"status":"PASS"}', '')
        with patch.dict(os.environ, {'AITEST_MODEL_KEY': 'never-forward', 'OPENAI_API_KEY': 'never-forward',
                                    'PYTHONPATH': '/host/python', 'XDG_CONFIG_HOME': '/host/opencode'}), \
             patch.object(installer.subprocess, 'run', side_effect=run):
            self.assertEqual(installer.run_installed_self_check(self.target)['status'], 'PASS')
        self.assertEqual(captured['argv'][0], str(self.target / installer.PYTHON_RELATIVE))
        self.assertIn('--self-check', captured['argv'])
        self.assertNotIn('AITEST_MODEL_KEY', captured['env'])
        self.assertNotIn('OPENAI_API_KEY', captured['env'])
        self.assertNotIn('PYTHONPATH', captured['env'])
        self.assertEqual(captured['env']['XDG_CONFIG_HOME'], str(self.target / 'data/opencode-config'))
        self.assertFalse(any('opencode.exe' in item or 'pip' == item or 'npm' == item for item in captured['argv']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
