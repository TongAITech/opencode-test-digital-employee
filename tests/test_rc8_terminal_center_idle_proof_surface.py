from rc8_node.single_node_full_loop_proof import SingleNodeFullLoopProof


def _proof(**overrides):
    values = dict(
        test_run_id="run-1",
        stages=("SCOPE_INTAKE",),
        work_item_ids=("wi-1",),
        lease_ids=("attempt-1",),
        stage_instance_ids=("si-1",),
        attempt_ids=("attempt-1",),
        evidence_refs=("artifact:a-1",),
    )
    values.update(overrides)
    return SingleNodeFullLoopProof(**values)


def test_terminal_center_idle_is_fail_closed_by_default():
    assert _proof().terminal_center_idle is False


def test_terminal_center_idle_can_only_be_retained_as_explicit_proof_fact():
    assert _proof(terminal_center_idle=True).terminal_center_idle is True
