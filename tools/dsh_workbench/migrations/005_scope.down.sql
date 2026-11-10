-- Controlled operator rollback only after stopping Scope traffic, retiring every
-- key that signed old cursors, recording the retirement receipt and backing up.
-- Automated downgrade() fails closed because key retirement is external to PG.
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['batch_requirement','batch_version','batch_requirement_version','batch_requirement_version_sst'] LOOP EXECUTE format('DROP TRIGGER relation_row_changed ON wb.%I',t); END LOOP; END $$;
DROP FUNCTION wb.relation_row_changed();
DROP TRIGGER acl_revision_changed ON wb.project_acl;
DROP FUNCTION wb.acl_revision_changed();
ALTER TABLE wb.project DROP COLUMN access_scope_revision;
