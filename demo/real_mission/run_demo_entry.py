from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import Artifact
from rc7_runtime.truth_overlay import append_entity

from demo.real_mission import run_demo


_original_install = MissionTaskGraphCompiler.install


def _content_hash(ref: str) -> str:
    if ref.startswith("file://"):
        parsed = urlparse(ref)
        path = Path(unquote(parsed.path.lstrip("/") if parsed.netloc else parsed.path))
        # Windows file://D:/... is parsed with path D:/... after lstrip.
        if path.exists() and path.is_file():
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + hashlib.sha256(ref.encode("utf-8")).hexdigest()


def _install_with_durable_external_sources(self, control_plane, mission_id, *, external_inputs=None):
    mapped = {}
    for node, refs in dict(external_inputs or {}).items():
        ids = []
        for index, ref in enumerate(refs):
            artifact_id = "ART-EXT-%s" % hashlib.sha256(
                (mission_id + "\x1f" + node + "\x1f" + str(index) + "\x1f" + ref).encode("utf-8")
            ).hexdigest()[:20]
            source_type = "REQUIREMENT_SOURCE" if node == "REQUIREMENT_ANALYSIS" else "SOURCE_REVISION"
            append_entity(
                control_plane.truth,
                Artifact(
                    artifact_id=artifact_id,
                    mission_id=mission_id,
                    artifact_type=source_type,
                    producer_task_id="EXTERNAL-SOURCE-INGEST",
                    content_ref=ref,
                    parent_refs=[],
                    evidence_refs=[],
                    content_hash=_content_hash(ref),
                ),
                release_id=control_plane.release_id,
                artifact_version=1,
            )
            ids.append(artifact_id)
        mapped[node] = tuple(ids)
    return _original_install(self, control_plane, mission_id, external_inputs=mapped)


MissionTaskGraphCompiler.install = _install_with_durable_external_sources


if __name__ == "__main__":
    raise SystemExit(run_demo.main())
