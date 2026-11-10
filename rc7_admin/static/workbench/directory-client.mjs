// Read-only authorized directories. No partial pages or caller-provided identity.
function freeze(value){if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;}
export class DirectoryClient {
 #state; get state(){return this.#state;}
 constructor(fetcher=fetch){this.fetcher=fetcher;this.generation=0;this.#state=freeze({status:'NOT_READY',records:[]});}
 clear(){this.generation++;this.abort?.abort();this.#state=freeze({status:'NOT_READY',records:[]});}
 async load(project=null){
  this.clear();const generation=this.generation;this.abort=new AbortController();this.#state=freeze({status:'LOADING',records:[]});
  try {
   if(project!==null&&(typeof project!=='string'||!project.trim()))throw Error('INVALID_DIRECTORY_PROJECT');
   const path='/api/workbench/v1/projects'+(project===null?'':'/'+encodeURIComponent(project)+'/release-dates');
   const records=[],ids=new Set(),cursors=new Set();let cursor=null,revision=null,access=null;
   for(let page=0;page<100;page++){
    const params=new URLSearchParams({page_size:'100'});if(cursor)params.set('page_cursor',cursor);
    // Native Window.fetch rejects a client object as its receiver.
    const response=await (0,this.fetcher)(path+'?'+params,{credentials:'same-origin',redirect:'error',signal:this.abort.signal,headers:{Accept:'application/json'}});
    if(!response.ok)throw Error('HTTP_'+response.status);
    const value=await response.json();if(generation!==this.generation)return false;
    if(value.schema!=='dsh-workbench/business-directory/v1'||!Array.isArray(value.records)||typeof value.directory_revision!=='string'||!/^[a-f0-9]{64}$/.test(value.directory_revision)||!Object.hasOwn(value,'next_page_cursor'))throw Error('INVALID_DIRECTORY');
    if(revision!==null&&revision!==value.directory_revision)throw Error('STALE_DIRECTORY');revision=value.directory_revision;
    if(project!==null){if(value.project_id!==project||!Number.isSafeInteger(value.access_scope_revision)||value.access_scope_revision<1)throw Error('INVALID_DIRECTORY');if(access!==null&&access!==value.access_scope_revision)throw Error('STALE_DIRECTORY');access=value.access_scope_revision;}
    for(const record of value.records){
     if(typeof record.project_id!=='string'||!record.project_id.trim()||!Number.isSafeInteger(record.access_scope_revision)||record.access_scope_revision<1)throw Error('INVALID_DIRECTORY_RECORD');
     if(project===null){if(typeof record.name!=='string'||!record.name.trim())throw Error('INVALID_DIRECTORY_RECORD');}
     else {if(record.project_id!==project||record.access_scope_revision!==access||typeof record.batch_id!=='string'||!record.batch_id.trim()||!validDate(record.release_date)||!['date_revision','relation_revision'].every(k=>Number.isSafeInteger(record[k])&&record[k]>0))throw Error('INVALID_DIRECTORY_RECORD');}
     const id=project===null?record.project_id:record.batch_id;if(ids.has(id))throw Error('DUPLICATE_DIRECTORY_RECORD');ids.add(id);records.push(structuredClone(record));if(records.length>10000)throw Error('DIRECTORY_LIMIT');
    }
    cursor=value.next_page_cursor;
    if(cursor===null){this.#state=freeze({status:'READY',records,directory_revision:revision,project_id:project,access_scope_revision:access});return true;}
    if(typeof cursor!=='string'||!cursor||cursors.has(cursor))throw Error('INVALID_DIRECTORY_CURSOR');cursors.add(cursor);
   }
   throw Error('DIRECTORY_PAGE_LIMIT');
  }catch(error){if(generation===this.generation)this.#state=freeze({status:'ERROR',error:error.message,records:[]});return false;}
 }
}
function validDate(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||value.startsWith('0000-'))return false;const d=new Date(value+'T00:00:00Z');return !Number.isNaN(d.valueOf())&&d.toISOString().slice(0,10)===value;}
