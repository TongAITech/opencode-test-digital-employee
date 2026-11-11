DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM wb.project_metadata_result) OR EXISTS(SELECT 1 FROM wb.project_metadata_history)
 OR EXISTS(SELECT 1 FROM wb.project_metadata_outbox) OR EXISTS(SELECT 1 FROM wb.project_namespace)
 OR EXISTS(SELECT 1 FROM wb.project_name_binding) OR EXISTS(SELECT 1 FROM wb.project_namespace_population) THEN
 RAISE EXCEPTION 'ROLLBACK_REQUIRES_BACKUP_AND_RECONCILIATION'; END IF;
END $$;
-- Remove every existing-object privilege added for this dedicated executor.
REVOKE UPDATE(name,metadata_revision) ON wb.project FROM __M1_EXECUTOR__;
REVOKE SELECT ON wb.project FROM __M1_EXECUTOR__;
REVOKE SELECT,INSERT ON wb.request_log,wb.audit FROM __M1_EXECUTOR__;
REVOKE USAGE ON SEQUENCE wb.audit_audit_id_seq FROM __M1_EXECUTOR__;
REVOKE EXECUTE ON FUNCTION wb.allowed(text,boolean) FROM __M1_EXECUTOR__;
REVOKE USAGE ON SCHEMA wb FROM __M1_EXECUTOR__;
DROP FUNCTION wb.get_project_metadata(text);
DROP FUNCTION wb.rename_project_metadata(text,text,text,text,text,bytea,bytea);
DROP TRIGGER metadata_change_proof ON wb.project;
DROP TRIGGER metadata_new_project ON wb.project;
DROP TRIGGER metadata_integrity ON wb.project;
DROP TABLE wb.project_metadata_outbox,wb.project_metadata_history,wb.project_metadata_result;
ALTER TABLE wb.request_log DROP CONSTRAINT metadata_claim_identity;
ALTER TABLE wb.audit DROP CONSTRAINT metadata_audit_identity;
DROP TABLE wb.project_namespace_population,wb.project_name_binding,wb.project_namespace;
DROP FUNCTION wb.metadata_change_proof(),wb.metadata_project_insert(),wb.metadata_integrity(),wb.metadata_name_valid(text),wb.metadata_quote_utf8(bytea);
DROP POLICY metadata_project_update ON wb.project;
ALTER TABLE wb.project DROP COLUMN metadata_revision;
