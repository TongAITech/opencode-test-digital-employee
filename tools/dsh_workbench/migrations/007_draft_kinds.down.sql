-- Downgrade runner refuses any accepted non-milestone payload first.
DROP TRIGGER asset_payload_complete ON wb.asset_revision;
DROP TRIGGER asset_kind_immutable ON wb.asset_revision;
DROP FUNCTION wb.asset_kind_immutable();
DROP TABLE wb.asset_payload;
DROP FUNCTION wb.asset_payload_complete(),wb.draft_payload_valid(text,jsonb);
ALTER TABLE wb.asset_revision DROP CONSTRAINT asset_revision_kind_date_check;
ALTER TABLE wb.asset_revision DROP CONSTRAINT asset_revision_kind_check;
ALTER TABLE wb.asset_revision ADD CHECK(kind='milestone');
ALTER TABLE wb.asset_revision ALTER COLUMN due_date SET NOT NULL;
