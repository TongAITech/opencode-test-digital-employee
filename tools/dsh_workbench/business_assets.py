"""B07 typed business drafts. Never writes canonical R1 or execution results."""
import datetime
import json
import uuid
from .business_scope import ScopeStore
from .business_store import BusinessError
from .draft_payloads import SCHEMAS, validate_payload


class AssetStore(ScopeStore):
    @staticmethod
    def _integer(value):
        if type(value) is not int or value<1:raise BusinessError(400,'INVALID_REVISION')
        return value

    def _batch(self,project,batch,lock=False):
        row=self.db.execute('SELECT release_date,relation_revision,assets_revision FROM wb.release_batch WHERE project_id=%s AND batch_id=%s'+(' FOR UPDATE' if lock else ''),(project,batch)).fetchone()
        if row is None:raise BusinessError(404,'RESOURCE_NOT_FOUND')
        access=self.db.execute('SELECT access_scope_revision FROM wb.project WHERE project_id=%s',(project,)).fetchone()[0]
        return {'project_id':project,'batch_id':batch,'release_date':str(row[0]),'relation_revision':row[1],'assets_revision':row[2],'access_scope_revision':access,'warnings':[],'gap_indicators':[]}

    def _record(self,project,batch,asset,revision=None,include_retired=False):
        row=self.db.execute('''SELECT v.asset_id,v.revision,v.kind,v.title,v.due_date,v.description,v.owner_display,v.state,v.scope_level,v.created_release_date FROM wb.asset_root r JOIN wb.asset_revision v ON v.project_id=r.project_id AND v.batch_id=r.batch_id AND v.asset_id=r.asset_id AND v.revision=COALESCE(%s,r.current_revision) WHERE r.project_id=%s AND r.batch_id=%s AND r.asset_id=%s''',(revision,project,batch,asset)).fetchone()
        if row is None or (row[7]=='RETIRED' and not include_retired):raise BusinessError(404,'RESOURCE_NOT_FOUND')
        record=dict(zip(['asset_id','revision','kind','title','due_date','description','owner_display','state','scope_level','created_release_date'],row))
        legacy={'due_date':str(record.pop('due_date')),'description':record.pop('description'),'owner_display':record.pop('owner_display')}
        if record['kind']=='milestone':record['payload']=legacy
        else:
            content=self.db.execute('SELECT kind,payload FROM wb.asset_payload WHERE project_id=%s AND batch_id=%s AND asset_id=%s AND revision=%s',(project,batch,asset,row[1])).fetchone()
            if content is None or content[0]!=record['kind']:raise BusinessError(503,'ASSET_PAYLOAD_UNAVAILABLE')
            record['payload']=content[1]
        record['created_release_date']=str(record['created_release_date'])
        for key,table,columns in [('brv_links','asset_brv_link',['requirement_id','version_id']),('brvs_links','asset_brvs_link',['requirement_id','version_id','sst_id'])]:
            rows=self.db.execute('SELECT '+','.join(columns)+' FROM wb.'+table+' WHERE project_id=%s AND batch_id=%s AND asset_id=%s AND revision=%s ORDER BY '+','.join(columns),(project,batch,asset,row[1])).fetchall()
            record[key]=[dict(zip(['system_version_id' if c=='version_id' else c for c in columns],values)) for values in rows]
        record['r1_reference_state']='NOT_LINKED' if record['kind']=='milestone' else 'UNRESOLVED'
        return record

    def _validate(self,record):
        if record.get('kind') not in SCHEMAS:raise BusinessError(400,'UNSUPPORTED_ASSET_KIND')
        if record['kind']!='milestone' and self.db.execute("SELECT to_regclass('wb.asset_payload')").fetchone()[0] is None:raise BusinessError(400,'UNSUPPORTED_ASSET_KIND')
        title=record.get('title')
        if not isinstance(title,str) or not title.strip() or '\x00' in title or len(title)>500:raise BusinessError(400,'INVALID_TITLE')
        validate_payload(record['kind'],record.get('payload'),self._date)
        level=record.get('scope_level')
        if level not in ('BATCH_WIDE','EXACT_RELATIONS'):raise BusinessError(400,'INVALID_ASSET_SCOPE')
        total=0
        for key,fields in [('brv_links',{'requirement_id','system_version_id'}),('brvs_links',{'requirement_id','system_version_id','sst_id'})]:
            values=record.get(key,[])
            if not isinstance(values,list) or len(values)>100:raise BusinessError(400,'INVALID_ASSET_SCOPE')
            seen=set()
            for link in values:
                if not isinstance(link,dict) or set(link)!=fields or any(not isinstance(v,str) or not v.strip() or '\x00' in v or len(v)>256 for v in link.values()):raise BusinessError(400,'INVALID_ASSET_SCOPE')
                identity=tuple(sorted(link.items()))
                if identity in seen:raise BusinessError(400,'DUPLICATE_ASSET_SCOPE')
                seen.add(identity)
            total+=len(values)
        if (level=='BATCH_WIDE' and total) or (level=='EXACT_RELATIONS' and not total):raise BusinessError(422,'ILLEGAL_ASSOCIATION')

    def mutate(self,principal,project,batch,action,body,asset=None):
        if action not in ('create','update','retire','restore') or not isinstance(body,dict):raise BusinessError(400,'INVALID_ASSET_REQUEST')
        allowed={'request_id','expected_relation_revision'}
        if action=='create':allowed|={'kind','title','payload','scope_level','brv_links','brvs_links'}
        else:
            allowed|={'expected_asset_revision','reason'}
            if action=='update':allowed|={'title','payload','scope_level','brv_links','brvs_links'}
        if set(body)-allowed:raise BusinessError(400,'INVALID_ASSET_REQUEST')
        if not isinstance(body.get('request_id'),str) or not body['request_id'].strip() or '\x00' in body['request_id'] or len(body['request_id'])>256:raise BusinessError(400,'REQUEST_ID_REQUIRED')
        self._integer(body.get('expected_relation_revision'))
        if action!='create':
            self._integer(body.get('expected_asset_revision'))
            if not isinstance(body.get('reason'),str) or not body['reason'].strip() or '\x00' in body['reason'] or len(body['reason'])>2048:raise BusinessError(400,'AUDIT_REASON_REQUIRED')
        with self._scope(principal,project):
            if self._claim(project,principal,body.get('request_id'),['asset',batch,asset,action,body]):
                row=self.db.execute('SELECT result FROM wb.asset_request_result WHERE project_id=%s AND actor=%s AND request_id=%s',(project,principal,body['request_id'])).fetchone()
                if row is None:raise BusinessError(409,'REQUEST_RESULT_UNAVAILABLE')
                return row[0]
            context=self._batch(project,batch,True)
            if context['relation_revision']!=body['expected_relation_revision']:raise BusinessError(409,'RELATION_REVISION_CONFLICT')
            if action=='create':
                asset=str(uuid.uuid4());revision=1
                record={key:body.get(key,[] if key.endswith('_links') else None) for key in ('kind','title','payload','scope_level','brv_links','brvs_links')}
                record['state']='ACTIVE'
                self.db.execute('INSERT INTO wb.asset_root VALUES(%s,%s,%s,1)',(project,batch,asset))
            else:
                record=self._record(project,batch,asset,include_retired=True)
                if record['revision']!=body['expected_asset_revision']:raise BusinessError(409,'ASSET_REVISION_CONFLICT')
                if (action=='restore')!=(record['state']=='RETIRED'):raise BusinessError(409,'ASSET_STATE_CONFLICT')
                revision=record['revision']+1
                if action=='update':
                    for key in ('title','scope_level','brv_links','brvs_links'):
                        if key in body:record[key]=body[key]
                    if 'payload' in body:
                        if not isinstance(body['payload'],dict):raise BusinessError(400,'INVALID_PAYLOAD')
                        record['payload']=dict(record['payload'],**body['payload'])
                record['state']='RETIRED' if action=='retire' else 'ACTIVE'
                self.db.execute('UPDATE wb.asset_root SET current_revision=%s WHERE project_id=%s AND batch_id=%s AND asset_id=%s AND current_revision=%s',(revision,project,batch,asset,body['expected_asset_revision']))
            self._validate(record)
            payload=record['payload']
            columns='project_id,batch_id,asset_id,revision,kind,title,due_date,description,owner_display,state,scope_level,created_release_date,scope_link_count,actor,reason'
            values=(project,batch,asset,revision,record['kind'],record['title'],payload['due_date'] if record['kind']=='milestone' else None,payload.get('description',''),payload.get('owner_display',''),record['state'],record['scope_level'],context['release_date'],len(record.get('brv_links',[]))+len(record.get('brvs_links',[])),principal,body.get('reason','created'))
            self.db.execute('INSERT INTO wb.asset_revision('+columns+') VALUES('+','.join(['%s']*len(values))+')',values)
            if record['kind']!='milestone':
                self.db.execute('INSERT INTO wb.asset_payload VALUES(%s,%s,%s,%s,%s,%s::jsonb)',(project,batch,asset,revision,record['kind'],json.dumps(payload)))
            for key,table,columns in [('brv_links','asset_brv_link',['requirement_id','system_version_id']),('brvs_links','asset_brvs_link',['requirement_id','system_version_id','sst_id'])]:
                for link in record.get(key,[]):
                    values=[project,batch,asset,revision]+[link[c] for c in columns]
                    self.db.execute('INSERT INTO wb.'+table+' VALUES('+','.join(['%s']*len(values))+')',values)
            audit=self._audit(project,principal,body['request_id'],'asset.'+action,asset,{'revision':revision,'state':record['state'],'batch_id':batch})
            event='workbench.asset.'+{'create':'created','update':'updated','retire':'retired','restore':'restored'}[action]
            self.db.execute('INSERT INTO wb.asset_outbox VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(str(uuid.uuid4()),project,batch,asset,revision,event,body['request_id'],audit))
            result=dict(self._batch(project,batch),record=self._record(project,batch,asset,include_retired=True))
            self.db.execute('INSERT INTO wb.asset_request_result VALUES(%s,%s,%s,%s::jsonb)',(project,principal,body['request_id'],json.dumps(result)))
            return result

    def get(self,principal,project,batch,asset,revision=None,include_retired=False):
        if revision is not None:self._integer(revision)
        with self._scope(principal,project,False,isolation='repeatable read'):
            return dict(self._batch(project,batch),record=self._record(project,batch,asset,revision,include_retired))

    def list(self,principal,project,batch,kind=None,requirement_ids=None,system_version_ids=None,sst_ids=None,due_from=None,due_to=None,include_retired=False,page_size=100,page_cursor=None):
        if kind is not None and kind not in SCHEMAS:raise BusinessError(400,'UNSUPPORTED_ASSET_KIND')
        if due_from is not None or due_to is not None:
            if kind is None:kind='milestone'
            if kind!='milestone':raise BusinessError(400,'INVALID_ASSET_QUERY')
        if type(include_retired) is not bool or type(page_size) is not int or not 1<=page_size<=100:raise BusinessError(400,'INVALID_ASSET_QUERY')
        filters=[self._ids(x) for x in (requirement_ids,system_version_ids,sst_ids)]
        dates=[str(self._date(x)) if x is not None else None for x in (due_from,due_to)]
        if all(dates) and dates[0]>dates[1]:raise BusinessError(400,'INVALID_DATE_RANGE')
        with self._scope(principal,project,False,isolation='repeatable read'):
            context=self._batch(project,batch)
            if any(filters):
                sql=' FROM wb.batch_requirement_version r LEFT JOIN wb.batch_requirement_version_sst s USING(project_id,batch_id,requirement_id,version_id) WHERE r.project_id=%s AND r.batch_id=%s'
                params=[project,batch]
                for ids,column in zip(filters,['r.requirement_id','r.version_id','s.sst_id']):
                    if ids:sql+=' AND '+column+'=ANY(%s)';params.append(ids)
                counts=self.db.execute('SELECT count(*),count(DISTINCT r.requirement_id),count(DISTINCT r.version_id),count(DISTINCT s.sst_id)'+sql,params).fetchone()
                if not counts[0] or any(ids and len(ids)!=count for ids,count in zip(filters,counts[1:])):raise BusinessError(422,'ILLEGAL_ASSOCIATION')
            binding={key:context[key] for key in ('project_id','batch_id','release_date','relation_revision','assets_revision','access_scope_revision')}
            binding.update({'type':'asset-list-v1','principal':principal,'filters':filters,'dates':dates,'kind':kind,'include_retired':include_retired,'page_size':page_size})
            offset=0
            if page_cursor is not None:
                cursor=self._decode(page_cursor);offset=cursor.pop('offset',None)
                if cursor!=binding or type(offset) is not int or offset<1:raise BusinessError(409,'STALE_CURSOR')
            query=''' FROM wb.asset_root r JOIN wb.asset_revision v ON v.project_id=r.project_id AND v.batch_id=r.batch_id AND v.asset_id=r.asset_id AND v.revision=r.current_revision WHERE r.project_id=%s AND r.batch_id=%s'''
            args=[project,batch]
            if kind is not None:query+=' AND v.kind=%s';args.append(kind)
            if not include_retired:query+=" AND v.state='ACTIVE'"
            for date,op in zip(dates,['>=','<=']):
                if date:query+=' AND v.due_date'+op+'%s';args.append(date)
            if any(filters):
                query+=''' AND EXISTS(SELECT 1 FROM (SELECT project_id,batch_id,asset_id,revision,requirement_id,version_id,NULL::text AS sst_id FROM wb.asset_brv_link UNION ALL SELECT project_id,batch_id,asset_id,revision,requirement_id,version_id,sst_id FROM wb.asset_brvs_link) l WHERE l.project_id=r.project_id AND l.batch_id=r.batch_id AND l.asset_id=r.asset_id AND l.revision=r.current_revision'''
                for ids,column in zip(filters,['l.requirement_id','l.version_id','l.sst_id']):
                    if ids:query+=' AND '+column+'=ANY(%s)';args.append(ids)
                query+=')'
            ids=self.db.execute('SELECT r.asset_id'+query+' ORDER BY r.asset_id LIMIT %s OFFSET %s',args+[page_size+1,offset]).fetchall()
            if page_cursor is not None and not ids:raise BusinessError(409,'STALE_CURSOR')
            records=[self._record(project,batch,row[0],include_retired=include_retired) for row in ids[:page_size]]
            cursor=self._encode(dict(binding,offset=offset+page_size)) if len(ids)>page_size else None
            return dict(context,records=records,next_page_cursor=cursor)
