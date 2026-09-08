"""Small synthetic qualification-seal guards; never evidence of Windows execution.

Run with the construction Python. The fixtures contain no runtime payload or model
result: they exercise provenance admission and closure decisions in the qualifier.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


QUALIFIER = Path(__file__).resolve().with_name('qualify_package.py')
SOURCE_HEAD = 'a' * 40
OTHER_HEAD = 'b' * 40
GATES = (
    'INSTALL_START_LIFECYCLE', 'OPENCODE_START_WITH_MODEL_AUTH_PENDING',
    'CONTROL_LOOP_START', 'HOST_PROVIDER_DISCOVERY', 'NATURAL_LANGUAGE_START_TEST',
    'MISSION_INTAKE', 'PLANNER_SESSION', 'AUTONOMOUS_PLAN', 'SCHEDULER_AUTO_ADVANCE',
    'SESSION_ROUTER', 'AUTO_ROTATION', 'SUCCESSOR_RESUME', 'CONTEXT_STRESS',
    'WINDOWS_FULL_QUALIFICATION',
)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class QualificationSealGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-qualification-guard-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.counter = 0

    def fixture(self):
        self.counter += 1
        folder = self.root / str(self.counter)
        bundle = folder / 'SYNTHETIC-QUALIFIER-GUARD-NOT-WINDOWS-PROOF'
        bundle.mkdir(parents=True)
        write(bundle / 'BUILD_PROVENANCE.json', {'source_head': SOURCE_HEAD,
              'scope': 'SYNTHETIC_QUALIFICATION_GUARD_ONLY'})
        write(bundle / 'PACKAGE_MANIFEST.json', {'candidate_commit': SOURCE_HEAD})
        write(bundle / 'MACHINE_VALIDATION_RESULT.json', {
            'source_head': OTHER_HEAD, 'LOCAL_VALIDATION_PASS': True, 'WINDOWS_CI_PASS': True,
            'local_construction_validation': {'source_head': OTHER_HEAD, 'LOCAL_VALIDATION_PASS': True},
            'windows_ci': {'run_id': 'HISTORICAL_MUST_NOT_BE_REUSED'},
            'scope': 'HISTORICAL_SYNTHETIC_REPORT_MUST_NOT_BECOME_CURRENT_EVIDENCE'})
        write(bundle / 'INSTALL_MANIFEST.json', {'status': 'NOT_INSTALLED'})
        write(bundle / 'OFFLINE_PAYLOAD_REGISTRY.json', {'scope': 'NO_PAYLOAD_IN_THIS_SYNTHETIC_TEST'})
        for name in ('VALIDATION_README.md', 'CAPABILITY_PARITY_MATRIX.md', 'immutable-source.py'):
            (bundle / name).write_text('SYNTHETIC GUARD ONLY\n', encoding='utf-8')
        write(bundle / 'FILE_SHA256.json', {p.name: sha(p) for p in bundle.iterdir() if p.is_file()})
        machine = {'source_head': SOURCE_HEAD, 'status': 'PASS', 'WINDOWS_CI_PASS': True,
                   'LOCAL_VALIDATION_PASS': True, 'BANK_FIELD_VALIDATION_REQUIRED': True,
                   'fixture_boundary': 'SYNTHETIC_QUALIFIER_GUARD_ONLY_NOT_WINDOWS_PROOF',
                   'gates': {**dict.fromkeys(GATES, 'PASS'), 'FINAL_ZIP_SEALED': 'PENDING'}}
        write(bundle / 'windows-validation.json', machine)
        write(bundle / 'windows-install-manifest.json', {'status': 'INSTALLED', 'source_head': SOURCE_HEAD,
              'scope': 'SYNTHETIC_QUALIFIER_GUARD_ONLY'})
        for name in ('windows-install.txt', 'windows-doctor.txt', 'windows-self-check.txt'):
            (bundle / name).write_text('SYNTHETIC GUARD ONLY\n', encoding='utf-8')
        return bundle

    def seal(self, bundle, *, env_updates=None, local=None):
        env = dict(os.environ)
        env.update(GITHUB_SHA=SOURCE_HEAD, GITHUB_RUN_ID='123456789',
                   GITHUB_REPOSITORY='synthetic-fixture/no-external-operation',
                   AITEST_INPUT_SHA256='c' * 64, AITEST_CARRIER_SHA256='d' * 64)
        env.update(env_updates or {})
        output = bundle.parent / 'qualified'
        command = [sys.executable, '-I', '-B', str(QUALIFIER), '--bundle', str(bundle), '--output', str(output)]
        if local is not None:
            path = bundle.parent / 'local.json'
            write(path, local)
            command += ['--local-report', str(path)]
        result = subprocess.run(command, cwd=bundle.parent, env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=20)
        return result, output

    def assert_rejected(self, bundle, *, message, **kwargs):
        before = (bundle / 'MACHINE_VALIDATION_RESULT.json').read_bytes()
        result, output = self.seal(bundle, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse(list(output.glob('*.zip')))
        self.assertEqual((bundle / 'MACHINE_VALIDATION_RESULT.json').read_bytes(), before)

    def test_matching_current_identity_seals_reports_but_never_imports_runtime_data(self):
        bundle = self.fixture()
        (bundle / 'data').mkdir()
        (bundle / 'data/runtime.db').write_bytes(b'unsealed mutable data')
        original_source = (bundle / 'immutable-source.py').read_bytes()
        result, output = self.seal(bundle)
        self.assertEqual(result.returncode, 0, result.stderr)
        machine = read(bundle / 'MACHINE_VALIDATION_RESULT.json')
        self.assertEqual(machine['closure'], 'PASS')
        self.assertEqual(machine['source_head'], SOURCE_HEAD)
        self.assertEqual(machine['local_construction_validation']['source_head'], SOURCE_HEAD)
        self.assertEqual(machine['windows_ci']['run_id'], '123456789')
        self.assertEqual(machine['gates']['FINAL_ZIP_SEALED'], 'PASS')
        self.assertEqual(read(bundle / 'INSTALL_MANIFEST.json')['status'], 'NOT_INSTALLED')
        self.assertEqual((bundle / 'immutable-source.py').read_bytes(), original_source)
        final = next(output.glob('*.zip'))
        self.assertEqual((output / (final.name + '.sha256')).read_text().split()[0], sha(final))
        with zipfile.ZipFile(final) as archive:
            names = {Path(name).relative_to(bundle.name).as_posix() for name in archive.namelist()}
            for name in ('windows-install.txt', 'windows-install-manifest.json', 'windows-validation.json',
                         'windows-doctor.txt', 'windows-self-check.txt', 'INSTALL_MANIFEST.json'):
                self.assertIn(name, names)
            self.assertNotIn('data/runtime.db', names)
            checksums = json.loads(archive.read(bundle.name + '/FILE_SHA256.json'))
            for relative, expected in checksums.items():
                self.assertEqual(hashlib.sha256(archive.read(bundle.name + '/' + relative)).hexdigest(), expected)
        self.assertTrue((output / 'windows-install-manifest.json').is_file())

    def test_report_source_head_mismatch_rejected(self):
        bundle = self.fixture()
        machine = read(bundle / 'windows-validation.json'); machine['source_head'] = OTHER_HEAD
        write(bundle / 'windows-validation.json', machine)
        self.assert_rejected(bundle, message='Validation source HEAD differs')

    def test_workflow_source_head_mismatch_and_missing_identity_rejected(self):
        for source in (OTHER_HEAD, ''):
            with self.subTest(source=source):
                self.assert_rejected(self.fixture(), message='Fresh exact-source Windows workflow is required',
                                     env_updates={'GITHUB_SHA': source})

    def test_report_and_workflow_agreement_cannot_override_different_provenance(self):
        bundle = self.fixture()
        machine = read(bundle / 'windows-validation.json'); machine['source_head'] = OTHER_HEAD
        write(bundle / 'windows-validation.json', machine)
        self.assert_rejected(bundle, message='Validation source HEAD differs', env_updates={'GITHUB_SHA': OTHER_HEAD})

    def test_stale_local_report_rejected(self):
        self.assert_rejected(self.fixture(), message='Local evidence does not match',
                             local={'source_head': OTHER_HEAD, 'LOCAL_VALIDATION_PASS': True})

    def test_failed_or_absent_windows_execution_cannot_seal(self):
        for field, value in (('WINDOWS_CI_PASS', False), ('WINDOWS_CI_PASS', None), ('status', 'FAIL')):
            with self.subTest(field=field, value=value):
                bundle = self.fixture()
                machine = read(bundle / 'windows-validation.json'); machine[field] = value
                write(bundle / 'windows-validation.json', machine)
                self.assert_rejected(bundle, message='Successful Windows payload execution is required')

    def test_any_changed_sealed_source_is_rejected(self):
        bundle = self.fixture()
        (bundle / 'immutable-source.py').write_text('modified during validation')
        self.assert_rejected(bundle, message='Source/payload changed during validation')

    def test_each_missing_named_gate_prevents_closure_pass(self):
        for gate in GATES:
            with self.subTest(gate=gate):
                bundle = self.fixture()
                machine = read(bundle / 'windows-validation.json'); del machine['gates'][gate]
                write(bundle / 'windows-validation.json', machine)
                result, _ = self.seal(bundle)
                self.assertEqual(result.returncode, 0, result.stderr)
                sealed = read(bundle / 'MACHINE_VALIDATION_RESULT.json')
                self.assertEqual(sealed['closure'], 'HOLD')
                self.assertEqual(sealed['unproven_closure_gates'][gate], 'NOT_PROVEN')
                self.assertEqual(read(bundle / 'PACKAGE_MANIFEST.json')['closure'], 'HOLD')

    def test_empty_named_gate_evidence_is_rejected(self):
        bundle = self.fixture()
        machine = read(bundle / 'windows-validation.json'); machine['gates'] = {}
        write(bundle / 'windows-validation.json', machine)
        self.assert_rejected(bundle, message='named gate evidence is missing')

    def test_only_host_provider_partial_binding_is_permitted_for_closure(self):
        for gate, expected in (('HOST_PROVIDER_DISCOVERY', 'PASS'), ('AUTONOMOUS_PLAN', 'HOLD')):
            with self.subTest(gate=gate):
                bundle = self.fixture()
                machine = read(bundle / 'windows-validation.json'); machine['gates'][gate] = 'PARTIAL_BANK_BINDING'
                write(bundle / 'windows-validation.json', machine)
                result, _ = self.seal(bundle)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(read(bundle / 'MACHINE_VALIDATION_RESULT.json')['closure'], expected)

    def test_fresh_local_failure_cannot_inherit_historical_pass_or_claim_closure(self):
        bundle = self.fixture()
        machine = read(bundle / 'windows-validation.json'); machine['LOCAL_VALIDATION_PASS'] = False
        write(bundle / 'windows-validation.json', machine)
        result, _ = self.seal(bundle)
        self.assertEqual(result.returncode, 0, result.stderr)
        sealed = read(bundle / 'MACHINE_VALIDATION_RESULT.json')
        self.assertFalse(sealed['LOCAL_VALIDATION_PASS'])
        self.assertEqual(sealed['local_construction_validation']['source_head'], SOURCE_HEAD)
        self.assertNotEqual(sealed['status'], 'PASS')
        self.assertEqual(sealed['closure'], 'HOLD')


if __name__ == '__main__':
    unittest.main(verbosity=2)
