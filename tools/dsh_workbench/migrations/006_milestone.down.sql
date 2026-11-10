-- Only after the asset tables are proven empty, or a separately approved restore.
DROP TABLE wb.asset_request_result,wb.asset_outbox,wb.asset_brvs_link,wb.asset_brv_link;
ALTER TABLE wb.asset_root DROP CONSTRAINT asset_root_project_id_batch_id_asset_id_current_revision_fkey;
DROP TABLE wb.asset_revision,wb.asset_root;
DROP FUNCTION wb.asset_version_complete(),wb.asset_root_changed(),wb.asset_links_complete();
ALTER TABLE wb.release_batch DROP COLUMN assets_revision;
