// C02 protocol component. Not wired to UI until B06 HTTP/Host qualification.
export class ScopeError extends Error { constructor(code){super(code);this.code=code;} }
const fail=code=>{throw new ScopeError(code);};
const immutable=value=>{if(value&&typeof value==='object'){for(const child of Object.values(value))immutable(child);Object.freeze(value);}return value;};
const id=v=>typeof v==='string'&&v.trim().length>0;
export function scopeRequest(scope,cursor=null){
  if(!id(scope.project_id)||!id(scope.batch_id)||!/^\d{4}-\d{2}-\d{2}$/.test(scope.release_date))fail('INVALID_SCOPE');
  if(new Date(scope.release_date+'T00:00:00Z').toISOString().slice(0,10)!==scope.release_date)fail('INVALID_SCOPE');
  for(const key of ['requirement_ids','system_version_ids','sst_ids'])if(scope[key]!==undefined&&!Array.isArray(scope[key]))fail('INVALID_SCOPE');
  const q=new URLSearchParams({batch_id:scope.batch_id,page_size:'100'});
  for(const key of ['requirement_ids','system_version_ids','sst_ids'])for(const value of scope[key]||[]){if(!id(value))fail('INVALID_SCOPE');q.append(key,value);}
  if(cursor!==null){if(!id(cursor))fail('INVALID_CURSOR');q.set('page_cursor',cursor);}
  return `/api/workbench/v1/projects/${encodeURIComponent(scope.project_id)}/release-dates/${scope.release_date}/scope?${q}`;
}
export function httpScopePort(fetcher){return async(scope,cursor,signal)=>{
  const response=await fetcher(scopeRequest(scope,cursor),{method:'GET',credentials:'same-origin',redirect:'error',headers:{Accept:'application/json'},signal});
  if(!response.ok)fail(`HTTP_${response.status}`);
  return response.json();
};}
export class ScopeClient {
  #state;
  get state(){return this.#state;}
  #publish(value){this.#state=immutable(structuredClone(value));}
  constructor(port,{maxPages=100,maxRows=10000}={}){this.port=port;this.maxPages=maxPages;this.maxRows=maxRows;this.generation=0;this.#publish({status:'NOT_READY',scope:null,records:[]});}
  clear(){this.generation++;this.controller?.abort();this.#publish({status:'NOT_READY',scope:null,records:[]});}
  async load(input){this.clear();const generation=this.generation;const scope=immutable(structuredClone(input));const controller=new AbortController();this.controller=controller;this.#publish({status:'LOADING',scope,records:[]});
    try{scopeRequest(scope);let cursor=null;const cursors=new Set(),rows=new Set(),parents=new Map(),sourceRefs=new Set(),records=[];let snapshot;
      for(let pageNo=0;pageNo<this.maxPages;pageNo++){
        const page=await this.port(immutable(structuredClone(scope)),cursor,controller.signal);
        if(generation!==this.generation)return false;
        if(!page||page.project_id!==scope.project_id||page.batch_id!==scope.batch_id||page.release_date!==scope.release_date)fail('SCOPE_MISMATCH');
        if(!Number.isSafeInteger(page.relation_revision)||page.relation_revision<1||!Number.isSafeInteger(page.access_scope_revision)||page.access_scope_revision<1)fail('INVALID_REVISION');
        const revision=JSON.stringify([page.relation_revision,page.access_scope_revision]);if(snapshot&&snapshot!==revision)fail('STALE_SCOPE');snapshot=revision;
        if(!Array.isArray(page.records)||!page.records.length||!Array.isArray(page.source_refs)||!page.source_refs.every(id)||new Set(page.source_refs).size!==page.source_refs.length||!Array.isArray(page.warnings)||!Array.isArray(page.gap_indicators))fail('INVALID_PAGE');
        for(const row of page.records){const parent=JSON.stringify([row.requirement_id,row.system_version_id]);if(!id(row.requirement_id)||!id(row.system_version_id))fail('INVALID_RELATION');
          for(const [filter,key] of [['requirement_ids','requirement_id'],['system_version_ids','system_version_id'],['sst_ids','sst_id']])if(scope[filter]?.length&&!scope[filter].includes(row[key]))fail('FILTER_MISMATCH');
          const rv=row.source_verified_requirement_version;const link=row.source_verified_link;
          if(!rv||!id(rv.source_link_ref)||!id(rv.source_revision)||!page.source_refs.includes(rv.source_link_ref))fail('UNVERIFIED_RELATION');
          if(row.split_state==='UNSPLIT'){if(row.sst_id!==null||link!==null)fail('INVALID_UNSPLIT');}
          else if(row.split_state!=='SPLIT'||!id(row.sst_id)||!link||!id(link.source_link_ref)||!id(link.verified_source_revision)||!page.source_refs.includes(link.source_link_ref))fail('UNVERIFIED_RELATION');
          const signature=JSON.stringify([row.split_state,rv]);if(parents.has(parent)&&parents.get(parent)!==signature)fail('SOURCE_DRIFT');parents.set(parent,signature);
          const key=JSON.stringify([row.requirement_id,row.system_version_id,row.sst_id]);if(rows.has(key))fail('DUPLICATE_RELATION');rows.add(key);records.push(structuredClone(row));if(records.length>this.maxRows)fail('ROW_LIMIT');
        }
        page.source_refs.forEach(ref=>sourceRefs.add(ref));
        if(!Object.hasOwn(page,'next_page_cursor'))fail('INCOMPLETE_SCOPE');
        if(page.next_page_cursor===null){this.#publish({status:'READY',scope,records,source_refs:[...sourceRefs],relation_revision:page.relation_revision,access_scope_revision:page.access_scope_revision});return true;}
        cursor=page.next_page_cursor;if(!id(cursor)||cursors.has(cursor))fail('CURSOR_CYCLE');cursors.add(cursor);
      }fail('PAGE_LIMIT');
    }catch(error){if(generation!==this.generation)return false;this.#publish({status:'ERROR',scope:null,records:[],error:error.code||'SOURCE_UNAVAILABLE'});return false;}
  }
}
