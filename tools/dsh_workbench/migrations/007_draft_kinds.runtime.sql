GRANT SELECT,INSERT ON wb.asset_payload TO wb_runtime;
GRANT EXECUTE ON FUNCTION wb.draft_payload_valid(text,jsonb) TO wb_runtime;
