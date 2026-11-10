# E02 canonical R1 graph read component

Baseline 0b22bb80. GET /api/workbench/v1/missions/{mission_id}/graph and /workitems require project_id,batch_id,release_date query, trusted server HostIdentity, real B06 all-page authorization. No client principal or write routes.

E02 reuses E01 authorization and immutable R1 snapshot admission, verifies the second snapshot matches truth_revision, performs unique Mission project/batch identity query before graph details, and rechecks PG authorization/revisions after reads. Raw canonical RC72 mission_node/delivery/gate/transition/back_edge or task/ETU/binding records retain their formal states. Missing nodes/gates return explicit gaps; human approval remains UNKNOWN_NOT_QUERIED and release_decision HOLD. No prompt/overlay/draft can create a formal PASS. Unknown canonical node state causes replay failure503, never invented success. Original R1 is not modified.

PostgreSQL17.6 loopback HTTP and persistent synthetic R1 tests cover actual canonical N1 record, missing remaining nodes/gates, workitems, untrusted identity, wrong batch, revoked permission, unknown state503/recovery and original bytes unchanged. Inherited E01 tests cover legacy binding denial, cold recovery, immutable bytes and identity-only rejection. No bank Host/Windows/field claim. F independent review remains required.

Initial local test rejected fixture node_type=N1, correctly requiring canonical N1_REALITY; fixed test and missing-node calculation to use RC72_CANONICAL_NODE_ORDER. No runtime contract modified.
