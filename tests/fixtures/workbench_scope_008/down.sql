-- Requires isolated fixture owner with full visibility, under the same migration lock.
LOCK TABLE wb.mission_create_journal, wb.mission_create_receipt,
    wb.mission_create_intent, wb.scope_snapshot IN ACCESS EXCLUSIVE MODE;
SET LOCAL row_security = off;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM wb.mission_create_journal)
        OR EXISTS (SELECT 1 FROM wb.mission_create_receipt)
        OR EXISTS (SELECT 1 FROM wb.mission_create_intent)
        OR EXISTS (SELECT 1 FROM wb.scope_snapshot) THEN
        RAISE EXCEPTION 'SCOPE_008_NONEMPTY' USING ERRCODE = '55000';
    END IF;
END;
$$;
DROP TABLE wb.mission_create_journal, wb.mission_create_receipt,
    wb.mission_create_intent, wb.scope_snapshot;
DROP FUNCTION wb.scope008_reject_mutation();
DROP FUNCTION wb.scope008_require_prepare_journal();
DROP DOMAIN wb.scope008_digest, wb.scope008_id;
