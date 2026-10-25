import unittest

from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector


class FakeLedger:
    def __init__(self, events):
        self._events = list(events)

    def runtime_events(self, node_id=None):
        if node_id is None:
            return list(self._events)
        return [event for event in self._events if event.get("node_id") == node_id]


class RuntimeInvalidationReceiptIdentityTest(unittest.TestCase):
    def source(self):
        return {
            "event_id": "invalidate-1",
            "event_type": "INVALIDATION_RECORDED",
            "test_run_id": "run-1",
            "work_item_id": "work-1",
            "case_id": "case-1",
            "attempt_id": "attempt-2",
        }

    def receipt(self, **overrides):
        event = {
            "event_id": "receipt-1",
            "event_type": "N5_N6_INVALIDATION_PROJECTED",
            "node_id": "center-runtime-invalidation-projector",
            "test_run_id": "run-1",
            "work_item_id": "work-1",
            "case_id": "case-1",
            "attempt_id": "attempt-2",
            "refs": ["invalidate-1"],
            "data": {"source_event_id": "invalidate-1", "reason": "AUTH_BINDING_CHANGED"},
        }
        event.update(overrides)
        return event

    def restore(self, receipt):
        projector = CenterRuntimeInvalidationProjector(FakeLedger([self.source(), receipt]), coordinator=object())
        return projector.receipts

    def test_exact_source_identity_restores_durable_receipt(self):
        self.assertIn("invalidate-1", self.restore(self.receipt()))

    def test_wrong_attempt_receipt_cannot_suppress_pending_invalidation(self):
        self.assertNotIn("invalidate-1", self.restore(self.receipt(attempt_id="attempt-old")))

    def test_receipt_must_reference_source_event(self):
        self.assertNotIn("invalidate-1", self.restore(self.receipt(refs=["other-event"])))

    def test_unknown_source_event_cannot_restore_receipt(self):
        receipt = self.receipt()
        receipt["data"] = dict(receipt["data"], source_event_id="missing-source")
        self.assertNotIn("missing-source", self.restore(receipt))


if __name__ == "__main__":
    unittest.main()
