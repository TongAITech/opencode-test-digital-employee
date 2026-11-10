GRANT SELECT,INSERT ON wb.asset_root,wb.asset_revision,wb.asset_brv_link,wb.asset_brvs_link,wb.asset_outbox,wb.asset_request_result TO wb_runtime;
GRANT UPDATE(current_revision) ON wb.asset_root TO wb_runtime;
