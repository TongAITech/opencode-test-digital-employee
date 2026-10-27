from __future__ import annotations

from fastapi.testclient import TestClient

from rc8_center.failure_diagnosis import FailureClassification
from rc8_center.formal_app import build_app


def main() -> None:
    app = build_app()
    diagnosis = app.state.failure_diagnosis_service

    observation = diagnosis.observe(
        observation_id="http-obs-1",
        test_run_id="http-run-1",
        source_mission_node_id="http-run-1:scope:N7",
        source_attempt_id="http-attempt-1",
        source_case_id="http-case-1",
        summary="HTTP product mismatch",
        evidence_refs=("artifact:http-failure-evidence",),
    )
    diagnostic = diagnosis.diagnose(
        diagnostic_id="http-diag-1",
        observation_id=observation.observation_id,
        classification=FailureClassification.PRODUCT,
        classifier_ref="center://deterministic-n8",
        reason_code="PRODUCT_SEMANTIC_MISMATCH",
        evidence_refs=("artifact:http-diagnosis-evidence",),
    )
    route = diagnosis.route(
        decision_id="http-route-1",
        diagnostic_id=diagnostic.diagnostic_id,
        gap_id="http-gap-1",
    )

    with TestClient(app) as client:
        forged = client.post(
            "/api/v1/defects/candidates",
            json={
                "defect_case_id": "http-defect-forged",
                "route_decision_id": route.decision_id,
                "evidence_refs": ["artifact:http-candidate"],
                "source_attempt_id": "forged-attempt",
            },
        )
        if forged.status_code != 422:
            raise AssertionError("N9_API_ALLOWED_CALLER_SOURCE_IDENTITY:%s" % forged.text)

        created = client.post(
            "/api/v1/defects/candidates",
            json={
                "defect_case_id": "http-defect-1",
                "route_decision_id": route.decision_id,
                "evidence_refs": ["artifact:http-candidate"],
            },
        )
        if created.status_code != 201:
            raise AssertionError("N9_CANDIDATE_HTTP_CREATE_FAILED:%s" % created.text)
        payload = created.json()
        defect = payload["defect"]
        if defect["test_run_id"] != observation.test_run_id:
            raise AssertionError("N9_HTTP_TEST_RUN_NOT_CENTER_DERIVED")
        if defect["source_case_id"] != observation.source_case_id:
            raise AssertionError("N9_HTTP_CASE_NOT_CENTER_DERIVED")
        if defect["source_attempt_id"] != observation.source_attempt_id:
            raise AssertionError("N9_HTTP_ATTEMPT_NOT_CENTER_DERIVED")
        if defect["state"] != "CANDIDATE":
            raise AssertionError("N9_HTTP_CANDIDATE_STATE_INVALID")

    reconstructed = build_app()
    with TestClient(reconstructed) as client:
        fetched = client.get("/api/v1/defects/http-defect-1")
        if fetched.status_code != 200:
            raise AssertionError("N9_CANDIDATE_HTTP_RECONSTRUCTION_FAILED:%s" % fetched.text)
        persisted = fetched.json()["defect"]
        if persisted != defect:
            raise AssertionError("N9_HTTP_POSTGRES_RECONSTRUCTION_MISMATCH")

    print("N9_PRODUCTION_HTTP_REALITY=PASS")
    print("N8_ROUTE_AUTHORITY=%s" % route.authority)
    print("N9_SOURCE_ATTEMPT=%s" % defect["source_attempt_id"])
    print("N9_CALLER_SOURCE_IDENTITY_INJECTION=REJECTED")
    print("TRUTH_NOTE=REAL_POSTGRESQL_REDIS_FORMAL_APP_HTTP_NOT_BANK_REALITY")


if __name__ == "__main__":
    main()
