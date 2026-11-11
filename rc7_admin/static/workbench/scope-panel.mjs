import {ScopeClient,httpScopePort} from './scope-client.mjs';
export function mountScopePanel(root,{fetcher=fetch,locale=()=>document.documentElement.lang}={}){
 const client=new ScopeClient(httpScopePort(fetcher));let generation=0;let selected={requirement:[],version:[],sst:[]};
 const text={ 'zh-CN':['项目ID','批次ID','投产日期','加载合法范围','需求','系统版本','SST','未就绪：等待宿主授权的业务范围','正在加载','范围已加载','来源不可用或无权限，请重新加载'], 'en-US':['Project ID','Batch ID','Release date','Load verified scope','Requirements','System versions','SST','Not ready: waiting for Host-authorized business scope','Loading','Scope loaded','Source unavailable or access denied. Reload required']};
 root.innerHTML='<form><div id="scope-inputs"></div><button type="submit"></button></form><div id="scope-selects"></div><p role="status" id="scope-result"></p>';
 const fields=['project_id','batch_id','release_date'].map((key,i)=>{const label=document.createElement('label'),span=document.createElement('span'),input=document.createElement('input');input.name=key;input.required=true;input.type=i===2?'date':'text';label.append(span,input);root.querySelector('#scope-inputs').append(label);input.oninput=()=>{generation++;client.clear();selected={requirement:[],version:[],sst:[]};render();};return {span,input};});
 const controls=['requirement','version','sst'].map((key,i)=>{const label=document.createElement('label'),span=document.createElement('span'),select=document.createElement('select');select.multiple=true;select.dataset.scope=key;label.append(span,select);root.querySelector('#scope-selects').append(label);select.onchange=()=>{selected[key]=[...select.selectedOptions].map(o=>o.value);for(const next of ['requirement','version','sst'].slice(i+1))selected[next]=[];render();};return {span,select};});
 function render(){const t=text[locale()]||text['zh-CN'];fields.forEach((f,i)=>f.span.textContent=t[i]);root.querySelector('button').textContent=t[3];const ready=client.state.status==='READY';let rows=ready?client.state.records:[];controls.forEach(({span,select},i)=>{const key=['requirement','version','sst'][i],column=['requirement_id','system_version_id','sst_id'][i];span.textContent=t[4+i];select.disabled=!ready;select.replaceChildren(...[...new Set(rows.map(r=>r[column]).filter(Boolean))].sort().map(value=>{const option=new Option(value,value);option.selected=selected[key].includes(value);return option;}));if(selected[key].length)rows=rows.filter(r=>selected[key].includes(r[column]));});root.querySelector('#scope-result').textContent=client.state.status==='LOADING'?t[8]:ready?t[9]:client.state.status==='ERROR'?t[10]+' ('+client.state.error+')':t[7];root.dataset.scopeStatus=client.state.status;document.dispatchEvent(new Event('workbench-scope-changed'));}
 async function load(expectedAccess=null){
  const current=++generation;
  const previous=expectedAccess===null?null:selected;
  selected={requirement:[],version:[],sst:[]};
  const promise=client.load(Object.fromEntries(fields.map((f,i)=>[['project_id','batch_id','release_date'][i],f.input.value])));
  render();
  const loaded=await promise;
  if(current!==generation)return null;
  if(loaded&&previous){
   if(String(client.state.access_scope_revision)!==expectedAccess)client.clear();
   else {
    let rows=client.state.records;
    for(const [key,column] of [['requirement','requirement_id'],['version','system_version_id'],['sst','sst_id']]){
     const allowed=new Set(rows.map(row=>row[column]));
     selected[key]=previous[key].filter(value=>allowed.has(value));
     if(selected[key].length)rows=rows.filter(row=>selected[key].includes(row[column]));
    }
   }
  }
  render();
  return client.state.status==='READY';
 }
 function revalidate(target,expectedAccess){
  if(fields[0].input.value!==target)return false;
  if(client.state.status!=='READY')return true;
  return load(expectedAccess);
 }
 root.querySelector('form').onsubmit=event=>{event.preventDefault();load();};
 new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});render();return {client,load,revalidate,get context(){return Object.fromEntries(fields.map((f,i)=>[['project_id','batch_id','release_date'][i],f.input.value]));},setContext(value){generation++;client.clear();selected={requirement:[],version:[],sst:[]};fields.forEach((f,i)=>f.input.value=value[['project_id','batch_id','release_date'][i]]||'');render();},get selection(){return structuredClone(selected);}};
}
