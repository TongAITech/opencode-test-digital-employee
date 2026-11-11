"""Read-only catalog qualification of one pinned Scope source profile.

No business rows are read, no role/policy/grant is changed, and no admission
capability is issued. A match describes this catalog/role observation only;
DDL or privileges may change immediately afterwards. Formal admission needs
its separately reviewed schema/DDL fence and a recheck under that fence.
"""
import datetime
import hashlib
import json
from pathlib import Path



PROFILE_ID = 'dsh.scope-source.project-only.pg17.001-007.v2'
PROFILE_CONTENT_HASH = '161c779c3fe956364fd381573f356fdc43fef98fbec8edb84e2706f64588d898'
SOURCE_TABLES = (
    'project', 'release_batch', 'system_identity', 'system_version', 'requirement',
    'batch_requirement', 'batch_version', 'verified_requirement_version',
    'batch_requirement_version', 'sst_identity', 'verified_sst_link',
    'batch_requirement_version_sst',
)
TABLES = SOURCE_TABLES + ('project_acl',)
_SUPPORT_FUNCTIONS = ('reject_history_change','acl_revision_changed','relation_row_changed','date_relation_revision','check_date_audit')
_OPTIONAL_INSERT = {'release_batch','system_identity','system_version','requirement','batch_requirement','batch_version','batch_requirement_version','batch_requirement_version_sst'}


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def _rows(connection, query, parameters=None):
    cursor = connection.execute(query, parameters)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _parameter_capabilities(connection):
    # PostgreSQL resolves direct, PUBLIC and inherited effective parameter ACLs.
    return _rows(connection, """SELECT current_setting('session_replication_role') AS mode,
        pg_catalog.has_parameter_privilege(current_user,'session_replication_role','SET') AS can_set,
        pg_catalog.has_parameter_privilege(current_user,'session_replication_role','ALTER SYSTEM') AS can_alter_system""")[0]


def _public_facts(facts):
    # Unknown function text can contain arbitrary literals. Keep only its hash.
    value=json.loads(json.dumps(facts))
    for key in ('allowed_functions','support_functions'):
        for function in value[key]:
            function['body_sha256']=hashlib.sha256(function.pop('prosrc').encode('utf-8')).hexdigest()
    return value


def _catalog(connection, *, tables=TABLES, support_functions=_SUPPORT_FUNCTIONS, all_policies=False):
    """Fixed catalog SELECTs; caller owns a read-only transaction/search_path."""
    facts = {}
    facts['session'] = _rows(connection, '''SELECT current_user::text AS current_role,session_user::text AS session_role,
        (SELECT usename::text FROM pg_catalog.pg_stat_activity WHERE pid=pg_catalog.pg_backend_pid()) AS backend_role,
        current_database() AS database_name,current_setting('server_version_num')::integer AS server_version_num,
        current_setting('row_security') AS row_security,transaction_timestamp()::text AS as_of''')[0]
    facts['parameter_capabilities'] = _parameter_capabilities(connection)
    facts['roles'] = _rows(connection, '''SELECT oid,rolname,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication,rolcanlogin
        FROM pg_catalog.pg_roles WHERE rolname IN(current_user,session_user) ORDER BY rolname''')
    facts['memberships'] = _rows(connection, '''SELECT r.oid,r.rolname,pg_catalog.pg_has_role(current_user,r.oid,'USAGE') AS usable_without_set,
        pg_catalog.pg_has_role(current_user,r.oid,'SET') AS can_set_role,
        pg_catalog.has_parameter_privilege(r.oid,'session_replication_role','SET') AS can_set_replication_mode,
        pg_catalog.has_parameter_privilege(r.oid,'session_replication_role','ALTER SYSTEM') AS can_alter_system_replication_mode
        FROM pg_catalog.pg_roles r WHERE r.rolname<>current_user AND pg_catalog.pg_has_role(current_user,r.oid,'MEMBER') ORDER BY r.rolname''')
    schemas = _rows(connection, '''SELECT oid,nspowner,pg_catalog.pg_get_userbyid(nspowner)::text AS owner,
        pg_catalog.has_schema_privilege(current_user,oid,'USAGE') AS can_use,
        pg_catalog.has_schema_privilege(current_user,oid,'CREATE') AS can_create,
        pg_catalog.pg_has_role(current_user,nspowner,'MEMBER') AS owner_member
        FROM pg_catalog.pg_namespace WHERE nspname='wb' ''')
    facts['schema'] = schemas[0] if schemas else None
    facts['database_create'] = _rows(connection, "SELECT pg_catalog.has_database_privilege(current_user,current_database(),'CREATE') AS allowed")[0]['allowed']
    relations = _rows(connection, '''SELECT c.oid,c.relname,c.relkind::text,c.relpersistence::text,c.relispartition,
        c.relrowsecurity,c.relforcerowsecurity,c.relowner,pg_catalog.pg_get_userbyid(c.relowner)::text AS owner,
        pg_catalog.pg_has_role(current_user,c.relowner,'MEMBER') AS owner_member,
        pg_catalog.row_security_active(c.oid) AS rls_active
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='wb' AND c.relname=ANY(%s) ORDER BY c.relname''', (list(tables),))
    facts['tables'] = relations
    ids = [row['oid'] for row in relations]
    facts['columns'] = _rows(connection, '''SELECT a.attrelid AS table_oid,a.attnum,a.attname,
        pg_catalog.format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull,a.attidentity::text,a.attgenerated::text,
        pg_catalog.pg_get_expr(d.adbin,d.adrelid) AS default_expr
        FROM pg_catalog.pg_attribute a LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attrelid,a.attnum''',(ids,)) if ids else []
    facts['constraints'] = _rows(connection, '''SELECT conrelid AS table_oid,conname,contype::text,convalidated,condeferrable,condeferred,
        pg_catalog.pg_get_constraintdef(oid) AS definition FROM pg_catalog.pg_constraint
        WHERE conrelid=ANY(%s) ORDER BY conrelid,conname''',(ids,)) if ids else []
    facts['policies'] = _rows(connection, '''SELECT p.oid,p.polrelid AS table_oid,p.polname,p.polcmd::text,p.polpermissive,p.polroles,
        pg_catalog.pg_get_expr(p.polqual,p.polrelid) AS using_expr,pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid) AS check_expr,
        EXISTS(SELECT 1 FROM unnest(p.polroles) r WHERE CASE WHEN r=0 THEN true ELSE pg_catalog.pg_has_role(current_user,r,'USAGE') END) AS applies_to_role,
        ARRAY(SELECT d.refobjid::pg_catalog.regprocedure::text FROM pg_catalog.pg_depend d
            WHERE d.classid='pg_catalog.pg_policy'::pg_catalog.regclass AND d.objid=p.oid
            AND d.refclassid='pg_catalog.pg_proc'::pg_catalog.regclass ORDER BY d.refobjid::pg_catalog.regprocedure::text) AS function_dependencies
        FROM pg_catalog.pg_policy p WHERE p.polrelid=ANY(%s) AND (%s OR p.polcmd IN('r','*')) ORDER BY p.polrelid,p.polname''',(ids,all_policies)) if ids else []
    facts['triggers'] = _rows(connection, '''SELECT t.tgrelid AS table_oid,t.tgname,t.tgenabled::text,t.tgtype,
        pg_catalog.pg_get_triggerdef(t.oid,true) AS definition
        FROM pg_catalog.pg_trigger t WHERE t.tgrelid=ANY(%s) AND NOT t.tgisinternal
        ORDER BY t.tgrelid,t.tgname''',(ids,)) if ids else []
    facts['ri_triggers'] = _rows(connection, """SELECT ns.nspname AS source_schema,src.relname AS source_table,
        c.conname AS constraint_name,nt.nspname AS target_schema,tgt.relname AS target_table,
        pg_catalog.pg_get_constraintdef(c.oid) AS constraint_definition,
        ni.nspname AS trigger_schema,ri.relname AS trigger_table,
        no.nspname AS related_schema,other.relname AS related_table,
        t.tgenabled::text,t.tgtype,t.tgdeferrable,t.tginitdeferred,t.tgnargs,t.tgargs,
        nf.nspname AS function_schema,p.proname AS function_name,
        pg_catalog.oidvectortypes(p.proargtypes) AS function_argument_types,l.lanname AS function_language,
        pg_catalog.format_type(p.prorettype,NULL) AS function_return_type
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class src ON src.oid=c.conrelid JOIN pg_catalog.pg_namespace ns ON ns.oid=src.relnamespace
        JOIN pg_catalog.pg_class tgt ON tgt.oid=c.confrelid JOIN pg_catalog.pg_namespace nt ON nt.oid=tgt.relnamespace
        LEFT JOIN pg_catalog.pg_trigger t ON t.tgconstraint=c.oid AND t.tgisinternal
        LEFT JOIN pg_catalog.pg_class ri ON ri.oid=t.tgrelid LEFT JOIN pg_catalog.pg_namespace ni ON ni.oid=ri.relnamespace
        LEFT JOIN pg_catalog.pg_class other ON other.oid=t.tgconstrrelid LEFT JOIN pg_catalog.pg_namespace no ON no.oid=other.relnamespace
        LEFT JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid LEFT JOIN pg_catalog.pg_namespace nf ON nf.oid=p.pronamespace
        LEFT JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE c.contype='f' AND (c.conrelid=ANY(%s) OR c.confrelid=ANY(%s))""",(ids,ids)) if ids else []
    for row in facts['ri_triggers']:
        raw=row.pop('tgargs')
        row['arguments_sha256']=hashlib.sha256(bytes(raw)).hexdigest() if raw is not None else None
    # Deliberately exclude every per-database trigger OID/name; retain duplicates.
    facts['ri_triggers'].sort(key=lambda row:json.dumps(row,sort_keys=True,separators=(',',':')).encode('utf-8'))
    facts['privileges'] = _rows(connection, '''SELECT c.oid AS table_oid,
        pg_catalog.has_table_privilege(current_user,c.oid,'SELECT') AS can_select,
        pg_catalog.has_table_privilege(current_user,c.oid,'INSERT') AS can_insert,
        pg_catalog.has_table_privilege(current_user,c.oid,'UPDATE') AS can_update,
        pg_catalog.has_table_privilege(current_user,c.oid,'DELETE') AS can_delete,
        pg_catalog.has_table_privilege(current_user,c.oid,'TRUNCATE') AS can_truncate,
        pg_catalog.has_table_privilege(current_user,c.oid,'REFERENCES') AS can_reference,
        pg_catalog.has_table_privilege(current_user,c.oid,'TRIGGER') AS can_trigger,
        pg_catalog.has_any_column_privilege(current_user,c.oid,'SELECT') AS column_select,
        pg_catalog.has_any_column_privilege(current_user,c.oid,'INSERT') AS column_insert,
        pg_catalog.has_any_column_privilege(current_user,c.oid,'UPDATE') AS column_update,
        pg_catalog.has_any_column_privilege(current_user,c.oid,'REFERENCES') AS column_reference
        FROM pg_catalog.pg_class c WHERE c.oid=ANY(%s) ORDER BY c.oid''',(ids,)) if ids else []
    function_query = '''SELECT p.oid,p.proname,p.proowner,pg_catalog.pg_get_userbyid(p.proowner)::text AS owner,
        pg_catalog.pg_has_role(current_user,p.proowner,'MEMBER') AS owner_member,
        l.lanname,p.prokind::text,p.prosecdef,p.provolatile::text,p.proparallel::text,p.proleakproof,p.proisstrict,p.proretset,
        pg_catalog.oidvectortypes(p.proargtypes) AS argument_types,p.proargnames,p.pronargdefaults,
        pg_catalog.format_type(p.prorettype,NULL) AS return_type,p.proconfig,p.prosrc,
        pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE') AS can_execute,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE n.nspname='wb' AND p.proname=ANY(%s) ORDER BY p.proname,p.oid'''
    facts['allowed_functions'] = _rows(connection,function_query,(['allowed'],))
    facts['support_functions'] = _rows(connection,function_query,(list(support_functions),))
    return facts


def _definition(facts):
    """Owner/OID-independent pinned definitions, never learned at probe time."""
    def grouped(key, oid, excluded):
        return [{k:v for k,v in row.items() if k not in excluded} for row in facts[key] if row['table_oid']==oid]
    result = {'tables':{},'allowed_functions':[],'support_functions':[],'ri_triggers':facts['ri_triggers']}
    for table in facts['tables']:
        oid=table['oid']
        result['tables'][table['relname']]={
            **{key:table[key] for key in ('relkind','relpersistence','relispartition','relrowsecurity','relforcerowsecurity')},
            'columns':grouped('columns',oid,{'table_oid'}),
            'constraints':grouped('constraints',oid,{'table_oid'}),
            'select_policies':grouped('policies',oid,{'table_oid','oid','applies_to_role'}),
            'triggers':grouped('triggers',oid,{'table_oid'}),
        }
    dynamic={'oid','proowner','owner','owner_member','can_execute','public_execute','prosrc'}
    for key in ('allowed_functions','support_functions'):
        result[key]=[{**{k:v for k,v in row.items() if k not in dynamic},
            'body_sha256':hashlib.sha256(row['prosrc'].encode('utf-8')).hexdigest()} for row in facts[key]]
    return result


class ReadOnlyScopeSourcePolicyQualification:
    """One PG17 source-visibility profile observation, not an authorization token."""

    _profile_id = PROFILE_ID
    _profile_content_hash = PROFILE_CONTENT_HASH
    _profile_filename = 'scope_source_profile_pg17.json'

    def _observe(self):
        return _catalog(self.db)

    def _validate_extension(self, facts, reject):
        pass

    def __init__(self, connection, *, statement_timeout_ms=5000):
        if not connection.autocommit:
            raise ValueError('AUTOCOMMIT_CONNECTION_REQUIRED_FOR_SCOPED_TRANSACTIONS')
        if type(statement_timeout_ms) is not int or not 1<=statement_timeout_ms<=30000:
            raise ValueError('INVALID_SCOPE_POLICY_QUALIFICATION_TIMEOUT')
        self.db,self.timeout=connection,statement_timeout_ms
        # Fixed packaged artifact: callers cannot supply a relaxed profile.
        self._profile=json.loads(Path(__file__).with_name(self._profile_filename).read_text(encoding='utf-8'))
        if not isinstance(self._profile,dict) or self._profile.get('profile_id')!=self._profile_id or _hash(self._profile)!=self._profile_content_hash:
            raise ValueError('SCOPE_SOURCE_PROFILE_ARTIFACT_INVALID')

    def probe(self):
        if self.db.closed:
            return self._failure('CATALOG_CONNECTION_CLOSED')
        if self.db.info.transaction_status!=0:
            raise ValueError('IDLE_CONNECTION_REQUIRED_FOR_SCOPE_POLICY_QUALIFICATION')
        try:
            with self.db.transaction():
                self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self.db.execute("SELECT set_config('statement_timeout',%s,true)",(str(self.timeout),))
                self.db.execute("SELECT set_config('search_path','pg_catalog',true)")
                facts=self._observe()
        except Exception as error:
            state=getattr(error,'sqlstate',None)
            if state=='57014':return self._failure('CATALOG_READ_TIMEOUT')
            if state=='42501':return self._failure('CATALOG_PERMISSION_UNAVAILABLE')
            if state in ('42P01','42703'):return self._failure('CATALOG_PROFILE_SHAPE_UNAVAILABLE')
            if (state and state.startswith('08')) or type(error).__name__ in ('OperationalError','InterfaceError'):
                return self._failure('CATALOG_CONNECTION_UNAVAILABLE')
            if state:return self._failure('CATALOG_READ_UNAVAILABLE')
            raise
        reasons=[]
        def reject(code,subject): reasons.append({'code':code,'subject':subject})
        session=facts['session']
        if session['server_version_num']//10000!=17:reject('UNSUPPORTED_POSTGRESQL_PROFILE_VERSION','server')
        if session['current_role']!=session['session_role']:reject('SESSION_ROLE_SWITCH_NOT_QUALIFIED','role')
        if session['backend_role']!=session['session_role']:reject('AUTHENTICATED_BACKEND_ROLE_MISMATCH','role')
        if session['row_security']!='on':reject('ROW_SECURITY_SETTING_NOT_ON','session')
        parameter=facts['parameter_capabilities']
        if parameter['mode']!='origin':reject('SOURCE_GUARDS_REPLICATION_MODE_NOT_ORIGIN','session')
        if parameter['can_set'] or parameter['can_alter_system']:
            reject('SOURCE_GUARD_PARAMETER_CAPABILITY','session_replication_role')
        for role in facts['memberships']:
            if role['can_set_role'] and (role['can_set_replication_mode'] or role['can_alter_system_replication_mode']):
                reject('SOURCE_GUARD_PARAMETER_CAPABILITY_VIA_SET_ROLE',role['rolname'])
        for role in facts['roles']:
            if any(role[key] for key in ('rolsuper','rolbypassrls','rolcreatedb','rolcreaterole','rolreplication')):
                reject('ELEVATED_ROLE_CAPABILITY',role['rolname'])
        if facts['memberships']:reject('UNAPPROVED_ROLE_MEMBERSHIP','role')
        schema=facts['schema']
        if schema is None:reject('SOURCE_SCHEMA_MISSING','wb')
        else:
            if not schema['can_use']:reject('SOURCE_SCHEMA_USAGE_MISSING','wb')
            if schema['can_create'] or schema['owner_member']:reject('SCHEMA_OWNER_OR_DDL_CAPABILITY','wb')
        if facts['database_create']:reject('DATABASE_DDL_CAPABILITY',session['database_name'])
        definitions=_definition(facts)
        for name in TABLES:
            actual=definitions['tables'].get(name)
            expected=self._profile['definitions']['tables'].get(name)
            if actual is None:reject('SOURCE_RELATION_MISSING','wb.'+name)
            elif actual!=expected:reject('SOURCE_SCHEMA_OR_SELECT_POLICY_DRIFT','wb.'+name)
        privileges={row['table_oid']:row for row in facts['privileges']}
        for table in facts['tables']:
            name=table['relname'];priv=privileges[table['oid']]
            if table['owner_member']:reject('SOURCE_RELATION_OWNER_CAPABILITY','wb.'+name)
            if schema is not None and table['relowner']!=schema['nspowner']:reject('SOURCE_OWNER_PROFILE_DRIFT','wb.'+name)
            if name in SOURCE_TABLES:
                if not table['rls_active']:reject('SOURCE_RLS_NOT_ACTIVE','wb.'+name)
                if not priv['can_select']:reject('SOURCE_SELECT_PRIVILEGE_MISSING','wb.'+name)
                allowed={'can_select','column_select'}
                if name in _OPTIONAL_INSERT:allowed.update({'can_insert','column_insert'})
                if name=='release_batch':allowed.update({'can_update','column_update'})
            else:allowed=set()
            if any(value for key,value in priv.items() if key!='table_oid' and key not in allowed):
                reject('UNAPPROVED_SOURCE_OR_ACL_PRIVILEGE','wb.'+name)
        if definitions['ri_triggers']!=self._profile['definitions']['ri_triggers']:
            reject('SOURCE_RI_TRIGGER_EXECUTION_PROFILE_DRIFT','scope-touching foreign keys')
        if definitions['allowed_functions']!=self._profile['definitions']['allowed_functions']:
            reject('ALLOWED_FUNCTION_DEFINITION_DRIFT','wb.allowed')
        if definitions['support_functions']!=self._profile['definitions']['support_functions']:
            reject('SOURCE_REVISION_OR_IMMUTABILITY_FUNCTION_DRIFT','wb')
        for function in facts['support_functions']:
            if function['owner_member']:reject('SOURCE_SUPPORT_FUNCTION_OWNER_CAPABILITY','wb.'+function['proname'])
            if schema is not None and function['proowner']!=schema['nspowner']:reject('SOURCE_SUPPORT_FUNCTION_OWNER_DRIFT','wb.'+function['proname'])
        for function in facts['allowed_functions']:
            if function['owner_member']:reject('ALLOWED_FUNCTION_OWNER_CAPABILITY','wb.allowed')
            if schema is not None and function['proowner']!=schema['nspowner']:reject('ALLOWED_FUNCTION_OWNER_DRIFT','wb.allowed')
            if not function['can_execute'] or function['public_execute']:reject('ALLOWED_FUNCTION_EXECUTE_GRANT_DRIFT','wb.allowed')
        self._validate_extension(facts,reject)
        # Timestamp does not create an artificial new config fingerprint each call.
        public_facts=_public_facts(facts)
        fingerprint=json.loads(json.dumps(public_facts));fingerprint['session'].pop('as_of',None)
        return {
            'profile_id':self._profile_id,'profile_hash':_hash(self._profile),'as_of':session['as_of'],
            'as_of_source':'DATABASE_TRANSACTION_TIMESTAMP','observation_complete':True,
            'status':'MATCHED_AS_OF' if not reasons else 'UNQUALIFIED','admission_authorized':False,
            'facts_hash':_hash(fingerprint),'reasons':reasons,'facts':public_facts,
            'limitation':'NO_DDL_OR_ROLE_FENCE; RECHECK_UNDER_SEPARATE_FORMAL_ADMISSION_PROTOCOL',
        }

    def _failure(self, code):
        return {
            'profile_id':self._profile_id,'profile_hash':_hash(self._profile),
            'as_of':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'as_of_source':'CLIENT_FAILURE_OBSERVATION','observation_complete':False,
            'status':'UNQUALIFIED','admission_authorized':False,
            'facts_hash':_hash({'failure':code}),'facts':None,'reasons':[{'code':code,'subject':'catalog'}],
            'limitation':'NO_DDL_OR_ROLE_FENCE; RECHECK_UNDER_SEPARATE_FORMAL_ADMISSION_PROTOCOL',
        }
