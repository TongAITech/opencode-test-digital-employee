"""Pending mandatory regression carries across a second actual repair round."""
import pytest
from test_rc72_n8_multi_round import _resume_second_round


@pytest.mark.parametrize('stage', ['planned', 'ready', 'published'])
def test_pending_member_second_round_cold_resume_never_reuses_old_result_or_repeats_projections(tmp_path, monkeypatch, stage):
    _resume_second_round(tmp_path, monkeypatch, stage=stage, repair_completed=True)
