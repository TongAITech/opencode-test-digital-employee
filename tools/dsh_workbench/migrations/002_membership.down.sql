DROP TRIGGER date_relation_revision ON wb.release_batch;
DROP FUNCTION wb.date_relation_revision();
DROP TRIGGER require_date_audit ON wb.release_batch;
CREATE CONSTRAINT TRIGGER require_date_audit AFTER UPDATE ON wb.release_batch DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.check_date_audit();
DROP TABLE wb.batch_version,wb.batch_requirement,wb.requirement;
ALTER TABLE wb.release_batch DROP COLUMN relation_revision;
