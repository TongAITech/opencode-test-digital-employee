ALTER TABLE wb.asset_revision DROP CONSTRAINT asset_revision_kind_check;
ALTER TABLE wb.asset_revision ADD CHECK(kind IN('milestone','case_draft','obligation_draft','defect_note','report_draft','knowledge','meeting_minutes'));
ALTER TABLE wb.asset_revision ALTER COLUMN due_date DROP NOT NULL;
ALTER TABLE wb.asset_revision ADD CONSTRAINT asset_revision_kind_date_check CHECK((kind='milestone' AND due_date IS NOT NULL) OR (kind<>'milestone' AND due_date IS NULL));
-- Additive immutable payloads avoid rewriting accepted milestone history.
CREATE TABLE wb.asset_payload(project_id text NOT NULL,batch_id text NOT NULL,asset_id text NOT NULL,revision bigint NOT NULL,kind text NOT NULL CHECK(kind IN('case_draft','obligation_draft','defect_note','report_draft','knowledge','meeting_minutes')),payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),PRIMARY KEY(project_id,batch_id,asset_id,revision),FOREIGN KEY(project_id,batch_id,asset_id,revision) REFERENCES wb.asset_revision);
ALTER TABLE wb.asset_payload ENABLE ROW LEVEL SECURITY;
CREATE POLICY read_scope ON wb.asset_payload FOR SELECT USING(wb.allowed(project_id,false));
CREATE POLICY insert_scope ON wb.asset_payload FOR INSERT WITH CHECK(wb.allowed(project_id,true));
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON wb.asset_payload FOR EACH ROW EXECUTE FUNCTION wb.reject_history_change();
CREATE FUNCTION wb.draft_payload_valid(k text,p jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,wb AS $$ DECLARE allowed text[]; required text[]; arrays text[]; field text; val jsonb; member jsonb; BEGIN
 CASE k
 WHEN 'case_draft' THEN allowed=ARRAY['preconditions','steps','expected_results','oracle_notes']; required=ARRAY['steps','expected_results']; arrays=ARRAY['preconditions','steps','expected_results'];
 WHEN 'obligation_draft' THEN allowed=ARRAY['business_rule','scenario','oracle_notes']; required=ARRAY['business_rule','scenario']; arrays=ARRAY[]::text[];
 WHEN 'defect_note' THEN allowed=ARRAY['reproduction_notes','expected_notes','actual_notes']; required=allowed; arrays=ARRAY[]::text[];
 WHEN 'report_draft','knowledge','meeting_minutes' THEN allowed=ARRAY['body','tags']; required=ARRAY['body']; arrays=ARRAY['tags'];
 ELSE RETURN false; END CASE;
 IF jsonb_typeof(p)<>'object' OR octet_length(p::text)>49152 THEN RETURN false; END IF;
 FOREACH field IN ARRAY required LOOP IF NOT p ? field THEN RETURN false; END IF; END LOOP;
 FOR field,val IN SELECT * FROM jsonb_each(p) LOOP
 IF NOT field=ANY(allowed) THEN RETURN false; END IF;
 IF field=ANY(arrays) THEN
 IF jsonb_typeof(val)<>'array' THEN RETURN false; END IF;
 IF jsonb_array_length(val)>(CASE WHEN field='tags' THEN 30 ELSE 100 END) OR (field=ANY(required) AND jsonb_array_length(val)=0) THEN RETURN false; END IF;
 FOR member IN SELECT * FROM jsonb_array_elements(val) LOOP IF jsonb_typeof(member)<>'string' OR btrim(member#>>'{}')='' OR length(member#>>'{}')>(CASE WHEN field='tags' THEN 128 ELSE 8192 END) THEN RETURN false; END IF; END LOOP;
 ELSE
 IF jsonb_typeof(val)<>'string' OR length(val#>>'{}')>8192 OR (field=ANY(required) AND btrim(val#>>'{}')='') THEN RETURN false; END IF;
 END IF; END LOOP; RETURN true; END $$;
ALTER TABLE wb.asset_payload ADD CHECK(wb.draft_payload_valid(kind,payload));
CREATE FUNCTION wb.asset_payload_complete() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$ DECLARE k text; BEGIN SELECT kind INTO k FROM wb.asset_revision WHERE project_id=NEW.project_id AND batch_id=NEW.batch_id AND asset_id=NEW.asset_id AND revision=NEW.revision; IF k='milestone' THEN IF EXISTS(SELECT 1 FROM wb.asset_payload WHERE project_id=NEW.project_id AND batch_id=NEW.batch_id AND asset_id=NEW.asset_id AND revision=NEW.revision) THEN RAISE EXCEPTION 'MILESTONE_PAYLOAD_IS_LEGACY_TYPED' USING ERRCODE='23514'; END IF; ELSE IF NOT EXISTS(SELECT 1 FROM wb.asset_payload WHERE project_id=NEW.project_id AND batch_id=NEW.batch_id AND asset_id=NEW.asset_id AND revision=NEW.revision AND kind=k) THEN RAISE EXCEPTION 'TYPED_DRAFT_PAYLOAD_REQUIRED' USING ERRCODE='23514'; END IF; END IF; RETURN NEW; END $$;
CREATE CONSTRAINT TRIGGER asset_payload_complete AFTER INSERT ON wb.asset_revision DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.asset_payload_complete();
CREATE CONSTRAINT TRIGGER asset_payload_complete AFTER INSERT ON wb.asset_payload DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.asset_payload_complete();
