from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import List, Optional

from rc7_release.final_manifest_refresh import refresh


PREFIX = "PFC-AITest-RC7-FINAL-UNIFIED-BANK-WIN10"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def seal(home: Path, output: Path, source_commit: str) -> dict:
    refreshed = refresh(home)
    if refreshed.get("status") != "PASS":
        return {"status": "FAIL", "reason": "MANIFEST_REFRESH_FAILED", "refresh": refreshed}
    output.mkdir(parents=True, exist_ok=True)
    target = output / ("%s-%s.zip" % (PREFIX, source_commit[:12]))
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(str(target), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(home.rglob("*")):
            if path.is_file():
                zf.write(str(path), (Path(home.name) / path.relative_to(home)).as_posix())
    digest = sha256_file(target)
    Path(str(target) + ".sha256").write_text("%s  %s\n" % (digest, target.name), encoding="utf-8")
    return {"status": "PASS", "zip": str(target), "sha256": digest, "refresh": refreshed}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--home", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args(argv)
    result = seal(Path(args.home).resolve(), Path(args.output).resolve(), args.source_commit)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
