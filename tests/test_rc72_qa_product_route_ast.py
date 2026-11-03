"""Adversarial QA test of the N8 source gate; never a product acceptance."""
from tools.rc72_qa_product_route_ast import has_real_n8_branch
import pytest


@pytest.mark.parametrize("source", [
    # A bypass branch invoking a different N7 component must not satisfy C03.
    """def run(self):
    if node['node_type'] == 'N8_DIAGNOSIS_RECOVERY':
        self.n7_pipeline.complete(release_batch_id=batch_id)
""",
    # Even if a random completion callback is inside the N8 branch.
    """def run(self):
    if node['node_type'] == 'N8_DIAGNOSIS_RECOVERY':
        result = self.callbacks['approve'].complete()
""",
    # N8 mentioned without a direct current-node comparison is not dispatch.
    """def run(self):
    if feature_enabled('N8_DIAGNOSIS_RECOVERY'):
        self.n8_pipeline.complete(release_batch_id=batch_id)
""",
    # Foreign mock provider is forbidden.
    """def run(self):
    if node_type == 'N8_DIAGNOSIS_RECOVERY':
        fake_n8.complete(release_batch_id=batch_id)
""",
    # A generic use of the same method name is not the owned native service.
    """def run(self):
    if node['node_type'] == 'N8_DIAGNOSIS_RECOVERY':
        self.n9_pipeline.complete(release_batch_id=batch_id)
""",
    # N7 PASS only skips diagnosis without ever entering N8 recovery.
    """def run(self):
    if node['node_type'] == 'N8_DIAGNOSIS_RECOVERY' and self._diagnosis_bypassed():
        continue
""",
])
def test_qa_n8_gate_rejects_fake_or_unrelated_product_dispatch(source):
    assert not has_real_n8_branch(source)


@pytest.mark.parametrize("source", [
    """def run(self):
    if node['node_type'] == 'N8_DIAGNOSIS_RECOVERY' and self.n8_pipeline is not None:
        result = self.n8_pipeline.complete(release_batch_id=batch_id)
""",
    """def run(self):
    if node_type == 'N8_DIAGNOSIS_RECOVERY':
        result = self.n8_pipeline.complete(release_batch_id=batch_id)
""",
])
def test_qa_n8_source_gate_admits_only_owned_native_route_shape(source):
    assert has_real_n8_branch(source)


def test_qa_n8_source_gate_fails_closed_on_bad_source():
    assert not has_real_n8_branch("def run(")
    assert not has_real_n8_branch(None)
