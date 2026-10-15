from pathlib import Path


STRICT = "rc7_release.real_mission_qualification_strict"
BASE_ONLY = "rc7_release.real_mission_qualification "


def test_final_entrypoints_must_use_strict_real_mission_qualification():
    repo = Path(__file__).resolve().parents[1]
    for name in ("QUALIFY-FINAL.sh", "QUALIFY-FINAL.cmd"):
        text = (repo / "packaging" / "rc7" / name).read_text(encoding="utf-8")
        assert STRICT in text
        assert BASE_ONLY not in text
