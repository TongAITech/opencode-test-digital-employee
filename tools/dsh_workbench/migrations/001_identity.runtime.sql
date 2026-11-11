-- Execute by migration owner after CREATE ROLE wb_runtime LOGIN NOSUPERUSER
-- NOCREATEDB NOCREATEROLE NOBYPASSRLS; credentials managed outside source.
GRANT USAGE ON SCHEMA wb TO wb_runtime;
GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean) TO wb_runtime;
GRANT SELECT ON wb.project,wb.release_batch,wb.system_identity,wb.system_version,wb.audit,wb.batch_date_history,wb.request_log TO wb_runtime;
GRANT INSERT ON wb.release_batch,wb.system_identity,wb.system_version,wb.audit,wb.batch_date_history,wb.request_log TO wb_runtime;
GRANT UPDATE ON wb.release_batch TO wb_runtime;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA wb TO wb_runtime;
