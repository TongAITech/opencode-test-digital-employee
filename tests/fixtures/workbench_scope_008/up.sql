-- Isolated PostgreSQL candidate. Deliberately outside both migration runners.
CREATE DOMAIN wb.scope008_id AS text COLLATE "C"
    CHECK (octet_length(VALUE) BETWEEN 1 AND 384);
CREATE DOMAIN wb.scope008_digest AS text COLLATE "C"
    CHECK (octet_length(VALUE) = 64 AND VALUE ~ '^[0-9a-f]{64}$');

CREATE TABLE wb.scope_snapshot (
    project_id text NOT NULL CHECK (octet_length(project_id) BETWEEN 1 AND 384),
    batch_id text NOT NULL CHECK (octet_length(batch_id) BETWEEN 1 AND 384),
    snapshot_ref wb.scope008_id NOT NULL,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    canonical_bytes bytea NOT NULL CHECK (octet_length(canonical_bytes) BETWEEN 1 AND 4194304),
    scope_digest wb.scope008_digest NOT NULL,
    release_date date NOT NULL CHECK (release_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    date_revision bigint NOT NULL CHECK (date_revision > 0),
    relation_revision bigint NOT NULL CHECK (relation_revision > 0),
    access_scope_revision bigint NOT NULL CHECK (access_scope_revision > 0),
    edge_count integer NOT NULL CHECK (edge_count BETWEEN 1 AND 10000),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    PRIMARY KEY (project_id, batch_id, snapshot_ref),
    UNIQUE (project_id, batch_id, scope_digest),
    UNIQUE (project_id, batch_id, snapshot_ref, scope_digest),
    FOREIGN KEY (project_id, batch_id) REFERENCES wb.release_batch,
    CHECK (scope_digest = encode(sha256(convert_to('dsh.scope-snapshot.v1' || chr(10), 'UTF8') || canonical_bytes), 'hex'))
);

CREATE TABLE wb.mission_create_intent (
    formal_authority_ref wb.scope008_id NOT NULL,
    actor_ref wb.scope008_id NOT NULL,
    project_id text NOT NULL,
    creation_key wb.scope008_id NOT NULL,
    batch_id text NOT NULL,
    snapshot_ref wb.scope008_id NOT NULL,
    scope_digest wb.scope008_digest NOT NULL,
    selection_bytes bytea NOT NULL CHECK (octet_length(selection_bytes) BETWEEN 1 AND 65536),
    selection_digest wb.scope008_digest NOT NULL,
    request_schema_version smallint NOT NULL CHECK (request_schema_version = 1),
    request_bytes bytea NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 65536),
    request_digest wb.scope008_digest NOT NULL,
    original_context_ref wb.scope008_id NOT NULL,
    mapping_schema_version smallint NOT NULL CHECK (mapping_schema_version = 1),
    mapping_policy text COLLATE "C" NOT NULL CHECK (mapping_policy = 'ALLOCATE_NEW_RELEASE_V1'),
    mapping_ref wb.scope008_id NOT NULL,
    runtime_release_id wb.scope008_id NOT NULL,
    runtime_release_batch_id wb.scope008_id NOT NULL,
    mission_id wb.scope008_id NOT NULL,
    binding_ref wb.scope008_id NOT NULL,
    creation_operation_ref wb.scope008_id NOT NULL,
    prepared_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(prepared_at)),
    PRIMARY KEY (formal_authority_ref, actor_ref, project_id, creation_key),
    FOREIGN KEY (project_id, batch_id, snapshot_ref, scope_digest)
        REFERENCES wb.scope_snapshot (project_id, batch_id, snapshot_ref, scope_digest),
    UNIQUE (formal_authority_ref, mapping_ref),
    UNIQUE (formal_authority_ref, runtime_release_id),
    UNIQUE (formal_authority_ref, runtime_release_batch_id),
    UNIQUE (formal_authority_ref, mission_id),
    UNIQUE (formal_authority_ref, binding_ref),
    UNIQUE (formal_authority_ref, creation_operation_ref),
    CHECK (selection_digest = encode(sha256(convert_to('dsh.mission-prepare-selection.v1' || chr(10), 'UTF8') || selection_bytes), 'hex'))
);

CREATE TABLE wb.mission_create_receipt (
    formal_authority_ref wb.scope008_id NOT NULL,
    actor_ref wb.scope008_id NOT NULL,
    project_id text NOT NULL,
    creation_key wb.scope008_id NOT NULL,
    receipt_ref wb.scope008_id NOT NULL,
    event_ref wb.scope008_id NOT NULL,
    receipt_hash wb.scope008_digest NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(verified_at)),
    PRIMARY KEY (formal_authority_ref, actor_ref, project_id, creation_key),
    FOREIGN KEY (formal_authority_ref, actor_ref, project_id, creation_key)
        REFERENCES wb.mission_create_intent,
    UNIQUE (formal_authority_ref, receipt_ref),
    UNIQUE (formal_authority_ref, event_ref),
    UNIQUE (formal_authority_ref, actor_ref, project_id, creation_key, receipt_ref)
);

CREATE TABLE wb.mission_create_journal (
    formal_authority_ref wb.scope008_id NOT NULL,
    actor_ref wb.scope008_id NOT NULL,
    project_id text NOT NULL,
    creation_key wb.scope008_id NOT NULL,
    journal_seq bigint GENERATED ALWAYS AS IDENTITY,
    journal_event_ref wb.scope008_id NOT NULL,
    phase text COLLATE "C" NOT NULL,
    observed_result text COLLATE "C" NOT NULL,
    attempt_ref wb.scope008_id,
    receipt_ref wb.scope008_id,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(observed_at)),
    PRIMARY KEY (formal_authority_ref, actor_ref, project_id, creation_key, journal_seq),
    FOREIGN KEY (formal_authority_ref, actor_ref, project_id, creation_key)
        REFERENCES wb.mission_create_intent,
    FOREIGN KEY (formal_authority_ref, actor_ref, project_id, creation_key, receipt_ref)
        REFERENCES wb.mission_create_receipt (formal_authority_ref, actor_ref, project_id, creation_key, receipt_ref),
    UNIQUE (formal_authority_ref, actor_ref, project_id, creation_key, journal_event_ref),
    CHECK ((phase, observed_result) IN (
        ('PREPARE', 'PERSISTED'), ('SUBMIT', 'PROVED_PRE_APPEND_REFUSAL'),
        ('SUBMIT', 'UNKNOWN'), ('LOOKUP', 'UNKNOWN'), ('LOOKUP', 'PROVED_NOT_FOUND'),
        ('RECONCILE', 'RECEIPT_CONFLICT'), ('RECONCILE', 'RECEIPT_LINKED'),
        ('INITIALIZATION', 'HOLD_OBSERVED'))),
    CHECK ((receipt_ref IS NOT NULL) = ((phase, observed_result) = ('RECONCILE', 'RECEIPT_LINKED')))
);

CREATE FUNCTION wb.scope008_reject_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'SCOPE_008_APPEND_ONLY' USING ERRCODE = '55000';
END;
$$;
REVOKE ALL ON FUNCTION wb.scope008_reject_mutation() FROM PUBLIC;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['scope_snapshot', 'mission_create_intent',
            'mission_create_receipt', 'mission_create_journal'] LOOP
        EXECUTE format('ALTER TABLE wb.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE wb.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('CREATE TRIGGER scope008_no_mutation BEFORE UPDATE OR DELETE OR TRUNCATE ON wb.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION wb.scope008_reject_mutation()', table_name);
    END LOOP;
END;
$$;

CREATE POLICY scope008_prepare_snapshot ON wb.scope_snapshot
    USING (wb.allowed(project_id, true)) WITH CHECK (wb.allowed(project_id, true));
CREATE POLICY scope008_prepare_intent ON wb.mission_create_intent
    USING (actor_ref = current_setting('wb.principal', true) AND wb.allowed(project_id, true))
    WITH CHECK (actor_ref = current_setting('wb.principal', true) AND wb.allowed(project_id, true));
CREATE POLICY scope008_prepare_journal ON wb.mission_create_journal FOR INSERT
    WITH CHECK (actor_ref = current_setting('wb.principal', true) AND wb.allowed(project_id, true)
        AND phase = 'PREPARE' AND observed_result = 'PERSISTED' AND attempt_ref IS NULL);

CREATE POLICY scope008_prepare_journal_read ON wb.mission_create_journal FOR SELECT
    USING (actor_ref = current_setting('wb.principal', true) AND wb.allowed(project_id, true)
        AND phase = 'PREPARE');
CREATE UNIQUE INDEX scope008_one_prepare_journal ON wb.mission_create_journal
    (formal_authority_ref, actor_ref, project_id, creation_key)
    WHERE phase = 'PREPARE';

CREATE FUNCTION wb.scope008_require_prepare_journal() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM wb.mission_create_journal j
        WHERE (j.formal_authority_ref, j.actor_ref, j.project_id, j.creation_key) =
              (NEW.formal_authority_ref, NEW.actor_ref, NEW.project_id, NEW.creation_key)
          AND j.phase = 'PREPARE'
    ) THEN
        RAISE EXCEPTION 'SCOPE_008_PREPARE_JOURNAL_REQUIRED' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION wb.scope008_require_prepare_journal() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER scope008_require_prepare_journal AFTER INSERT ON wb.mission_create_intent
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION wb.scope008_require_prepare_journal();
