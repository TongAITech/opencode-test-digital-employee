from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from rc8_center.artifacts import FileArtifactStore, MemoryArtifactRepository
from rc8_center.executable_bundle import (
    EXECUTABLE_BUNDLE_FORMAT,
    EXECUTABLE_BUNDLE_KIND,
    ExecutableBundleError,
    materialize_executable_bundle,
    validate_executable_bundle,
)
from rc8_runtime import RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest


class ExecutableBundleContractTest(unittest.TestCase):
    def _store_bundle(self, root: Path, *, artifact_id: str = "bundle-1", unsafe_member: str = ""):
        zip_path = root / (artifact_id + ".zip")
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project/pom.xml", "<project><modelVersion>4.0.0</modelVersion></project>")
            archive.writestr("project/src/test/java/ExampleTest.java", "class ExampleTest {}")
            if unsafe_member:
                archive.writestr(unsafe_member, "escape")
        raw = zip_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        repository = MemoryArtifactRepository()
        store = FileArtifactStore(str(root / (artifact_id + "-store")), repository)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            test_run_id="run-1",
            work_item_id="work-n6-1",
            node_id="node-n6-1",
            kind=EXECUTABLE_BUNDLE_KIND,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="N6ExecutableSpecWorker",
            file_name=artifact_id + ".zip",
            sha256=digest,
            size_bytes=len(raw),
            case_id="CASE-1",
            attempt_id="lease-n6-1",
            metadata={
                "bundle_format": EXECUTABLE_BUNDLE_FORMAT,
                "execution_driver": "maven-junit",
                "project_subdir": "project",
            },
        )
        store.begin(manifest)
        store.upload_chunk(artifact_id, offset=0, data=raw)
        store.complete(artifact_id)
        return store, zip_path, digest

    def test_available_hash_verified_bundle_validates_and_materializes(self):
        with tempfile.TemporaryDirectory(prefix="rc8-bundle-") as temp_dir:
            root = Path(temp_dir)
            store, _, digest = self._store_bundle(root)
            authority = validate_executable_bundle(
                store,
                "artifact:bundle-1",
                test_run_id="run-1",
                work_item_id="work-n6-1",
                node_id="node-n6-1",
                case_id="CASE-1",
                attempt_id="lease-n6-1",
            )
            self.assertEqual(authority.project_subdir, "project")
            self.assertEqual(authority.sha256, digest)
            content_path = store.content_path(authority.artifact_id)
            project_dir = materialize_executable_bundle(
                str(content_path),
                str(root / "attempt-workspace"),
                expected_sha256=authority.sha256,
                project_subdir=authority.project_subdir,
            )
            self.assertTrue((project_dir / "pom.xml").is_file())
            self.assertTrue((project_dir / "src/test/java/ExampleTest.java").is_file())

    def test_bundle_identity_is_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="rc8-bundle-identity-") as temp_dir:
            root = Path(temp_dir)
            store, _, _ = self._store_bundle(root)
            with self.assertRaisesRegex(ExecutableBundleError, "EXECUTABLE_BUNDLE_CASE_MISMATCH"):
                validate_executable_bundle(store, "artifact:bundle-1", case_id="CASE-OTHER")
            with self.assertRaisesRegex(ExecutableBundleError, "EXECUTABLE_BUNDLE_ATTEMPT_MISMATCH"):
                validate_executable_bundle(store, "artifact:bundle-1", attempt_id="lease-other")

    def test_zip_slip_member_is_rejected_before_materialization(self):
        with tempfile.TemporaryDirectory(prefix="rc8-bundle-slip-") as temp_dir:
            root = Path(temp_dir)
            store, _, _ = self._store_bundle(root, artifact_id="bundle-slip", unsafe_member="../escape.txt")
            with self.assertRaisesRegex(ExecutableBundleError, "EXECUTABLE_BUNDLE_MEMBER_UNSAFE"):
                validate_executable_bundle(store, "artifact:bundle-slip")

    def test_downloaded_bytes_are_rehashed_before_extract(self):
        with tempfile.TemporaryDirectory(prefix="rc8-bundle-hash-") as temp_dir:
            root = Path(temp_dir)
            store, _, digest = self._store_bundle(root)
            content_path = store.content_path("bundle-1")
            tampered = root / "tampered.zip"
            tampered.write_bytes(content_path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ExecutableBundleError, "EXECUTABLE_BUNDLE_HASH_MISMATCH"):
                materialize_executable_bundle(
                    str(tampered),
                    str(root / "attempt-workspace"),
                    expected_sha256=digest,
                    project_subdir="project",
                )


if __name__ == "__main__":
    unittest.main()
