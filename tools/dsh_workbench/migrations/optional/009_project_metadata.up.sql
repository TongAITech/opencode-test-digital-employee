-- Explicit optional 009; executor is a checked NOLOGIN non-owner role supplied
-- by administrative runner. Never execute through HTTP or a runtime owner.
ALTER TABLE wb.project ADD COLUMN metadata_revision bigint NOT NULL DEFAULT 1 CHECK(metadata_revision>0);
CREATE TABLE wb.project_namespace(
 namespace_ref text PRIMARY KEY CHECK(namespace_ref<>''),
 state text NOT NULL CHECK(state IN ('GOVERNANCE_HOLD','NAMING_ACTIVE')),
 policy_version text NOT NULL CHECK(policy_version='project-name/utf8-exact-v1'),
 governance_ref text NOT NULL CHECK(governance_ref<>''), governance_revision text NOT NULL CHECK(governance_revision<>''),
 governance_hash text NOT NULL CHECK(governance_hash ~ '^[0-9a-f]{64}$'),
 namespace_revision bigint NOT NULL CHECK(namespace_revision>0), allow_rename boolean NOT NULL DEFAULT false);
CREATE TABLE wb.project_name_binding(
 project_id text PRIMARY KEY REFERENCES wb.project,
 namespace_ref text NOT NULL REFERENCES wb.project_namespace,
 kind text NOT NULL CHECK(kind='PROJECT'),
 name_key bytea NOT NULL, binding_revision bigint NOT NULL CHECK(binding_revision>0),
 governance_ref text NOT NULL CHECK(governance_ref<>''), UNIQUE(namespace_ref,name_key), UNIQUE(namespace_ref,project_id));
CREATE TABLE wb.project_namespace_population(
 namespace_ref text NOT NULL REFERENCES wb.project_namespace,
 project_id text NOT NULL REFERENCES wb.project,
 disposition text NOT NULL CHECK(disposition IN ('MEMBER','EXCLUDED')),
 source_ref text NOT NULL CHECK(source_ref<>''), exclusion_reason text,
 PRIMARY KEY(namespace_ref,project_id), CHECK(disposition='MEMBER' OR (exclusion_reason IS NOT NULL AND btrim(exclusion_reason)<>'')));
ALTER TABLE wb.request_log ADD CONSTRAINT metadata_claim_identity UNIQUE(project_id,actor,request_id,payload_hash);
ALTER TABLE wb.audit ADD CONSTRAINT metadata_audit_identity UNIQUE(project_id,actor,request_id,audit_id);
CREATE TABLE wb.project_metadata_result(
 project_id text NOT NULL, actor text NOT NULL, request_id text NOT NULL,
 payload_hash text NOT NULL, canonical_payload bytea NOT NULL,
 audit_id bigint NOT NULL, outcome text NOT NULL CHECK(outcome IN ('APPLIED','NO_CHANGE')),
 applied_revision bigint NOT NULL CHECK(applied_revision>0), receipt jsonb NOT NULL,
 PRIMARY KEY(project_id,actor,request_id),
 FOREIGN KEY(project_id,actor,request_id,payload_hash) REFERENCES wb.request_log(project_id,actor,request_id,payload_hash),
 FOREIGN KEY(project_id,actor,request_id,audit_id) REFERENCES wb.audit(project_id,actor,request_id,audit_id),
 CHECK(payload_hash=encode(sha256(canonical_payload),'hex')),
 CHECK(receipt @> jsonb_build_object('schema','project-metadata-receipt/v1','project_id',project_id,
  'request_id',request_id,'action','project.metadata.update/v1','outcome',outcome,
  'applied_metadata_revision',applied_revision::text,'audit_id',audit_id::text,
  'history_revision',CASE WHEN outcome='APPLIED' THEN applied_revision::text ELSE NULL END)
  AND receipt ? 'name' AND jsonb_typeof(receipt->'name')='string'),
 UNIQUE(project_id,actor,request_id,audit_id,outcome,applied_revision));
CREATE TABLE wb.project_metadata_history(
 project_id text NOT NULL REFERENCES wb.project, revision bigint NOT NULL CHECK(revision>1),
 old_revision bigint NOT NULL CHECK(revision=old_revision+1), old_name text NOT NULL,new_name text NOT NULL CHECK(convert_to(old_name,'UTF8')<>convert_to(new_name,'UTF8')),
 actor text NOT NULL, request_id text NOT NULL, audit_id bigint NOT NULL,
 outcome text NOT NULL DEFAULT 'APPLIED' CHECK(outcome='APPLIED'), reason_utf8 bytea NOT NULL,
 PRIMARY KEY(project_id,revision),
 FOREIGN KEY(project_id,actor,request_id,audit_id,outcome,revision)
 REFERENCES wb.project_metadata_result(project_id,actor,request_id,audit_id,outcome,applied_revision));
CREATE TABLE wb.project_metadata_outbox(
 project_id text NOT NULL, metadata_revision bigint NOT NULL,
 event_kind text NOT NULL CHECK(event_kind='project.metadata.changed'),
 actor text NOT NULL,request_id text NOT NULL,audit_id bigint NOT NULL,
 outcome text NOT NULL DEFAULT 'APPLIED' CHECK(outcome='APPLIED'),
 PRIMARY KEY(project_id,metadata_revision,event_kind),
 FOREIGN KEY(project_id,metadata_revision) REFERENCES wb.project_metadata_history,
 FOREIGN KEY(project_id,actor,request_id,audit_id,outcome,metadata_revision)
 REFERENCES wb.project_metadata_result(project_id,actor,request_id,audit_id,outcome,applied_revision));

-- Bytewise JSON UTF8 quoting preserves even NUL in a valid reason, which PG text
-- cannot represent. Raw reason is bytea, never silently truncated/replaced.
CREATE FUNCTION wb.metadata_quote_utf8(v bytea) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
DECLARE r bytea=decode('22','hex'); b integer; i integer;
BEGIN
 FOR i IN 0..octet_length(v)-1 LOOP
  b=get_byte(v,i);
  IF b=34 THEN r=r||convert_to('\"','UTF8');
  ELSIF b=92 THEN r=r||convert_to('\\','UTF8');
  ELSIF b=8 THEN r=r||convert_to('\b','UTF8');
  ELSIF b=9 THEN r=r||convert_to('\t','UTF8');
  ELSIF b=10 THEN r=r||convert_to('\n','UTF8');
  ELSIF b=12 THEN r=r||convert_to('\f','UTF8');
  ELSIF b=13 THEN r=r||convert_to('\r','UTF8');
  ELSIF b<32 THEN r=r||convert_to('\u00'||lpad(to_hex(b),2,'0'),'UTF8');
  ELSE r=r||set_byte(decode('00','hex'),0,b); END IF;
 END LOOP;
 RETURN convert_from(r||decode('22','hex'),'UTF8');
END $$;
CREATE FUNCTION wb.metadata_name_valid(n text) RETURNS boolean LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $$
 SELECT convert_to(n,'UTF8')=convert_to(btrim(n,' '),'UTF8') AND char_length(n) BETWEEN 1 AND 128 AND octet_length(convert_to(n,'UTF8'))<=512
 AND NOT EXISTS(SELECT 1 FROM generate_series(1,char_length(n)) i WHERE ascii(substr(n,i,1))<32 OR ascii(substr(n,i,1))=127)
$$;

-- Every administrative denominator mutation begins by writing one common row
-- version before taking namespace row locks, then before its own row writes.
-- This is not just a mutex: RR/SERIALIZABLE writers with old snapshots must
-- fail 40001 on the fence UPDATE, rather than validate an obsolete population.
CREATE TABLE wb.project_metadata_governance_fence(
 singleton boolean PRIMARY KEY CHECK(singleton), epoch bigint NOT NULL CHECK(epoch>0));
INSERT INTO wb.project_metadata_governance_fence VALUES(true,1);
CREATE FUNCTION wb.metadata_governance_advance() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,wb AS $$
BEGIN
 IF TG_OP='TRUNCATE' THEN RAISE EXCEPTION 'GOVERNANCE_TRUNCATE_FORBIDDEN' USING ERRCODE='42501'; END IF;
 UPDATE wb.project_metadata_governance_fence SET epoch=epoch+1 WHERE singleton;
 IF NOT FOUND THEN RAISE EXCEPTION 'GOVERNANCE_FENCE_MISSING' USING ERRCODE='23514'; END IF;
 -- Take the same namespace-before-project/binding order as ordinary rename.
 -- Administration is rare and global; ordinary rename and ACL writes do not
 -- participate in this global version change.
 PERFORM 1 FROM wb.project_namespace ORDER BY convert_to(namespace_ref,'UTF8') FOR UPDATE;
 RETURN NULL;
END $$;
CREATE TRIGGER metadata_governance_advance BEFORE INSERT OR DELETE OR UPDATE OF project_id OR TRUNCATE ON wb.project
 FOR EACH STATEMENT EXECUTE FUNCTION wb.metadata_governance_advance();
CREATE TRIGGER metadata_governance_advance BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON wb.project_namespace
 FOR EACH STATEMENT EXECUTE FUNCTION wb.metadata_governance_advance();
CREATE TRIGGER metadata_governance_advance BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON wb.project_namespace_population
 FOR EACH STATEMENT EXECUTE FUNCTION wb.metadata_governance_advance();
CREATE TRIGGER metadata_governance_advance BEFORE INSERT OR DELETE OR UPDATE OF project_id,namespace_ref,kind,binding_revision,governance_ref OR TRUNCATE ON wb.project_name_binding
 FOR EACH STATEMENT EXECUTE FUNCTION wb.metadata_governance_advance();

-- Commit-time administrative source checks. Full population means all projects,
-- including explicitly excluded legacy rows, not merely visible members.
CREATE FUNCTION wb.metadata_integrity() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM wb.project_name_binding b JOIN wb.project p USING(project_id)
           WHERE NOT wb.metadata_name_valid(p.name) OR b.name_key<>convert_to(p.name,'UTF8')) THEN
  RAISE EXCEPTION 'METADATA_KEY_INCONSISTENT' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM wb.project_namespace n WHERE n.state='NAMING_ACTIVE' AND (
   EXISTS(SELECT 1 FROM wb.project p WHERE NOT EXISTS(SELECT 1 FROM wb.project_namespace_population g WHERE g.namespace_ref=n.namespace_ref AND g.project_id=p.project_id))
   OR EXISTS(SELECT 1 FROM wb.project_namespace_population g WHERE g.namespace_ref=n.namespace_ref AND
     ((g.disposition='MEMBER') IS DISTINCT FROM EXISTS(SELECT 1 FROM wb.project_name_binding b WHERE b.project_id=g.project_id AND b.namespace_ref=g.namespace_ref))))) THEN
  RAISE EXCEPTION 'GOVERNANCE_POPULATION_INCOMPLETE' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
-- All affected transactions run this owner-owned invariant trigger, including
-- a rename through the restricted executor. It is not a public SQL write port.
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['project','project_namespace','project_name_binding','project_namespace_population'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER metadata_integrity AFTER INSERT OR UPDATE OR DELETE ON wb.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.metadata_integrity()',t);
 END LOOP; END $$;
CREATE FUNCTION wb.metadata_project_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$ BEGIN
 UPDATE wb.project_namespace SET state='GOVERNANCE_HOLD',allow_rename=false,namespace_revision=namespace_revision+1 WHERE state='NAMING_ACTIVE'; RETURN NEW;
END $$;
CREATE TRIGGER metadata_new_project AFTER INSERT ON wb.project FOR EACH ROW EXECUTE FUNCTION wb.metadata_project_insert();

-- Mandatory rename receipt/key/history proof, even for direct executor DML.
CREATE FUNCTION wb.metadata_change_proof() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$
BEGIN
 IF convert_to(NEW.name,'UTF8') IS DISTINCT FROM convert_to(OLD.name,'UTF8') OR NEW.metadata_revision IS DISTINCT FROM OLD.metadata_revision THEN
  IF NEW.project_id<>OLD.project_id OR NEW.metadata_revision<>OLD.metadata_revision+1 OR convert_to(NEW.name,'UTF8')=convert_to(OLD.name,'UTF8')
   OR NOT EXISTS(SELECT 1 FROM wb.project_metadata_history h JOIN wb.project_metadata_outbox o ON o.project_id=h.project_id AND o.metadata_revision=h.revision
      WHERE h.project_id=NEW.project_id AND h.revision=NEW.metadata_revision AND h.old_revision=OLD.metadata_revision AND convert_to(h.old_name,'UTF8')=convert_to(OLD.name,'UTF8') AND convert_to(h.new_name,'UTF8')=convert_to(NEW.name,'UTF8')) THEN
   RAISE EXCEPTION 'METADATA_CHANGE_PROOF_REQUIRED' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER metadata_change_proof AFTER UPDATE ON wb.project DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.metadata_change_proof();
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['project_metadata_result','project_metadata_history','project_metadata_outbox'] LOOP
 EXECUTE format('ALTER TABLE wb.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY metadata_read ON wb.%I FOR SELECT USING(wb.allowed(project_id,true) AND actor=current_setting(''wb.principal'',true))',t);
 EXECUTE format('CREATE POLICY metadata_insert ON wb.%I FOR INSERT WITH CHECK(wb.allowed(project_id,true) AND actor=current_setting(''wb.principal'',true))',t);
 EXECUTE format('CREATE TRIGGER metadata_append_only BEFORE UPDATE OR DELETE ON wb.%I FOR EACH ROW EXECUTE FUNCTION wb.reject_history_change()',t);
 END LOOP; END $$;
ALTER TABLE wb.project_name_binding ENABLE ROW LEVEL SECURITY;
CREATE POLICY metadata_binding_read ON wb.project_name_binding FOR SELECT USING(wb.allowed(project_id,false));
CREATE POLICY metadata_binding_update ON wb.project_name_binding FOR UPDATE USING(wb.allowed(project_id,true)) WITH CHECK(wb.allowed(project_id,true));
CREATE POLICY metadata_project_update ON wb.project FOR UPDATE USING(wb.allowed(project_id,true)) WITH CHECK(wb.allowed(project_id,true));

CREATE FUNCTION wb.rename_project_metadata(p text,rid text,em text,ea text,n text,reason bytea,canonical bytea) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$
DECLARE actor_id text=current_setting('wb.principal',true); ns text; locked_ns text; state_now text; enabled boolean;
 old_name text; mr bigint; ar bigint; hash text; original jsonb; ai bigint; result jsonb; outcome_now text; expected bytea; inserted text;
BEGIN
 IF actor_id IS NULL OR actor_id='' OR NOT wb.allowed(p,true) THEN RAISE EXCEPTION 'FORBIDDEN' USING ERRCODE='P0001'; END IF;
 IF rid IS NULL OR char_length(rid) NOT BETWEEN 1 AND 128 OR octet_length(translate(rid,'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-',''))<>0 OR em IS NULL OR ea IS NULL
 OR em COLLATE "C" !~ '^[1-9][0-9]{0,18}$' OR ea COLLATE "C" !~ '^[1-9][0-9]{0,18}$' OR em COLLATE "C" ~ '[^0-9]' OR ea COLLATE "C" ~ '[^0-9]' THEN RAISE EXCEPTION 'INVALID_METADATA_REQUEST' USING ERRCODE='P0001'; END IF;
 IF em::numeric>9223372036854775807 OR ea::numeric>9223372036854775807 OR n IS NULL OR NOT wb.metadata_name_valid(n)
 OR reason IS NULL OR octet_length(reason)>2048 OR canonical IS NULL THEN RAISE EXCEPTION 'INVALID_METADATA_REQUEST' USING ERRCODE='P0001'; END IF;
 expected=convert_to('{"action":"project.metadata.update/v1","changes":{"name":'||wb.metadata_quote_utf8(convert_to(n,'UTF8'))||'},"expected_access_scope_revision":'||to_json(ea)::text||',"expected_metadata_revision":'||to_json(em)::text||',"name_policy":"project-name/utf8-exact-v1","project_id":'||to_json(p)::text||',"reason":'||wb.metadata_quote_utf8(reason)||',"request_id":'||to_json(rid)::text||',"schema":"dsh-workbench/project-metadata-request/v1"}','UTF8');
 IF canonical<>expected THEN RAISE EXCEPTION 'INVALID_METADATA_CANONICAL' USING ERRCODE='P0001'; END IF;
 hash=encode(sha256(canonical),'hex');
 -- Same K may already be committed: reauthorize now but replay before current
 -- CAS/governance. No claim write on this path and no current-state overwrite.
 SELECT q.payload_hash INTO inserted FROM wb.request_log q WHERE q.project_id=p AND q.actor=actor_id AND q.request_id=rid;
 IF FOUND THEN
  IF inserted<>hash THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT' USING ERRCODE='P0001'; END IF;
  SELECT receipt INTO original FROM wb.project_metadata_result q WHERE q.project_id=p AND q.actor=actor_id AND q.request_id=rid AND q.payload_hash=hash;
  IF original IS NULL THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN original;
 END IF;
 SELECT namespace_ref INTO ns FROM wb.project_name_binding WHERE project_id=p;
 IF ns IS NULL THEN RAISE EXCEPTION 'METADATA_NOT_GOVERNED' USING ERRCODE='P0001'; END IF;
 SELECT state,allow_rename INTO state_now,enabled FROM wb.project_namespace WHERE namespace_ref=ns FOR SHARE;
 -- NO KEY UPDATE is compatible with old request_log/project FK KEY SHARE.
 -- Never update referenced unique identity, so old claim-first operations can
 -- complete while this transaction waits for their same K to commit/rollback.
 SELECT name,metadata_revision,access_scope_revision INTO old_name,mr,ar FROM wb.project WHERE project_id=p FOR NO KEY UPDATE;
 SELECT namespace_ref INTO locked_ns FROM wb.project_name_binding WHERE project_id=p FOR NO KEY UPDATE;
 IF locked_ns IS DISTINCT FROM ns THEN RAISE EXCEPTION 'METADATA_RETRY_REQUIRED' USING ERRCODE='P0001'; END IF;
 IF NOT wb.allowed(p,true) THEN RAISE EXCEPTION 'FORBIDDEN' USING ERRCODE='P0001'; END IF;
 INSERT INTO wb.request_log VALUES(p,actor_id,rid,hash) ON CONFLICT DO NOTHING RETURNING request_id INTO inserted;
 IF inserted IS NULL THEN
  SELECT q.payload_hash INTO inserted FROM wb.request_log q WHERE q.project_id=p AND q.actor=actor_id AND q.request_id=rid;
  IF inserted IS DISTINCT FROM hash THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT' USING ERRCODE='P0001'; END IF;
  SELECT receipt INTO original FROM wb.project_metadata_result q WHERE q.project_id=p AND q.actor=actor_id AND q.request_id=rid AND q.payload_hash=hash;
  IF original IS NULL THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN original;
 END IF;
 IF state_now<>'NAMING_ACTIVE' OR NOT enabled THEN RAISE EXCEPTION 'GOVERNANCE_HOLD' USING ERRCODE='P0001'; END IF;
 IF mr<>em::bigint OR ar<>ea::bigint THEN RAISE EXCEPTION 'REVISION_CONFLICT' USING ERRCODE='P0001'; END IF;
 outcome_now=CASE WHEN convert_to(old_name,'UTF8')=convert_to(n,'UTF8') THEN 'NO_CHANGE' ELSE 'APPLIED' END;
 IF outcome_now='APPLIED' AND mr=9223372036854775807 THEN RAISE EXCEPTION 'REVISION_EXHAUSTED' USING ERRCODE='P0001'; END IF;
 INSERT INTO wb.audit(project_id,actor,request_id,action,object_id,detail)
 VALUES(p,actor_id,rid,'project.metadata.update/v1',p,jsonb_build_object('outcome',outcome_now,'old_name',old_name,'new_name',n,'old_revision',mr::text,'reason_utf8_hex',encode(reason,'hex'))) RETURNING audit_id INTO ai;
 IF outcome_now='APPLIED' THEN mr=mr+1; END IF;
 result=jsonb_build_object('schema','project-metadata-receipt/v1','project_id',p,'request_id',rid,'action','project.metadata.update/v1','outcome',outcome_now,'name',n,'applied_metadata_revision',mr::text,'access_scope_revision',ar::text,'audit_id',ai::text,'history_revision',CASE WHEN outcome_now='APPLIED' THEN mr::text ELSE NULL END);
 INSERT INTO wb.project_metadata_result VALUES(p,actor_id,rid,hash,canonical,ai,outcome_now,mr,result);
 IF outcome_now='APPLIED' THEN
  UPDATE wb.project_name_binding SET name_key=convert_to(n,'UTF8') WHERE project_id=p;
  UPDATE wb.project SET name=n,metadata_revision=mr WHERE project_id=p;
  INSERT INTO wb.project_metadata_history VALUES(p,mr,mr-1,old_name,n,actor_id,rid,ai,'APPLIED',reason);
  INSERT INTO wb.project_metadata_outbox VALUES(p,mr,'project.metadata.changed',actor_id,rid,ai,'APPLIED');
 END IF;
 RETURN result;
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION 'NAME_UNAVAILABLE' USING ERRCODE='P0001';
END $$;
REVOKE ALL ON FUNCTION wb.rename_project_metadata(text,text,text,text,text,bytea,bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION wb.metadata_quote_utf8(bytea),wb.metadata_name_valid(text),wb.metadata_integrity(),wb.metadata_project_insert(),wb.metadata_change_proof(),wb.metadata_governance_advance() FROM PUBLIC;
GRANT USAGE ON SCHEMA wb TO __M1_EXECUTOR__;
GRANT EXECUTE ON FUNCTION wb.allowed(text,boolean),wb.metadata_quote_utf8(bytea),wb.metadata_name_valid(text) TO __M1_EXECUTOR__;
GRANT SELECT ON wb.project,wb.project_name_binding,wb.project_namespace,wb.request_log,wb.project_metadata_result,wb.audit TO __M1_EXECUTOR__;
-- PostgreSQL row locks require UPDATE privilege on at least one column.
-- This NOLOGIN non-member executor gets only the revision column, no state/
-- policy/governance writes; no public function updates it.
GRANT UPDATE(namespace_revision) ON wb.project_namespace TO __M1_EXECUTOR__;
GRANT UPDATE(name,metadata_revision) ON wb.project TO __M1_EXECUTOR__;
GRANT UPDATE(name_key) ON wb.project_name_binding TO __M1_EXECUTOR__;
GRANT INSERT ON wb.request_log,wb.audit,wb.project_metadata_result,wb.project_metadata_history,wb.project_metadata_outbox TO __M1_EXECUTOR__;
GRANT USAGE ON SEQUENCE wb.audit_audit_id_seq TO __M1_EXECUTOR__;
-- ALTER OWNER needs temporary CREATE; it is revoked in the same migration tx.
GRANT CREATE ON SCHEMA wb TO __M1_EXECUTOR__;
ALTER FUNCTION wb.rename_project_metadata(text,text,text,text,text,bytea,bytea) OWNER TO __M1_EXECUTOR__;
REVOKE CREATE ON SCHEMA wb FROM __M1_EXECUTOR__;

CREATE FUNCTION wb.get_project_metadata(p text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,wb AS $$
DECLARE result jsonb;
BEGIN
 IF NOT wb.allowed(p,false) THEN RAISE EXCEPTION 'FORBIDDEN' USING ERRCODE='P0001'; END IF;
 SELECT jsonb_build_object('schema','project-metadata/v1','project_id',p,'name',q.name,
 'metadata_revision',q.metadata_revision::text,'access_scope_revision',q.access_scope_revision::text,
 'can_rename',COALESCE(b.project_id IS NOT NULL AND n.state='NAMING_ACTIVE' AND n.allow_rename AND wb.allowed(p,true),false),
 'governance_state',CASE WHEN b.project_id IS NULL THEN 'METADATA_NOT_GOVERNED' WHEN n.state='NAMING_ACTIVE' AND n.allow_rename THEN 'GOVERNED_ROOT_ACTIVE' ELSE 'GOVERNANCE_HOLD' END)
 INTO result FROM wb.project q LEFT JOIN wb.project_name_binding b USING(project_id) LEFT JOIN wb.project_namespace n USING(namespace_ref) WHERE q.project_id=p;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION wb.get_project_metadata(text) FROM PUBLIC;
GRANT CREATE ON SCHEMA wb TO __M1_EXECUTOR__;
ALTER FUNCTION wb.get_project_metadata(text) OWNER TO __M1_EXECUTOR__;
REVOKE CREATE ON SCHEMA wb FROM __M1_EXECUTOR__;
