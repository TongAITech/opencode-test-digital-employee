// Synchronous view of the existing validated ScopeClient; no fetch, cache or new facts.
export function requirementRelations(state){
 if(state?.status!=='READY')return {status:'NOT_READY',records:[]};
 let rows=state.records;
 for(const [key,column] of [['requirement','requirement_id'],['version','system_version_id'],['sst','sst_id']]){
  const values=state.selection?.[key]??[];
  if(!Array.isArray(values)||values.some(value=>typeof value!=='string'||!value||!state.records.some(row=>row[column]===value)))return {status:'INVALID_SELECTION',records:[]};
  if(values.length)rows=rows.filter(row=>values.includes(row[column]));
 }
 return {status:rows.length?'READY':'NO_MATCH',records:rows};
}
const copy={
 'zh-CN':{heading:'需求 → 版本 → SST 关联',boundary:'仅展示已验证业务关联。关系来源不是需求文档来源；尚未获取需求正文或测试义务，不表示覆盖完成。',pending:'尚无可用的已验证范围；请加载或重新加载授权范围。',empty:'当前筛选没有合法关联，请调整筛选；不表示需求或测试义务为零。',scope:'业务范围',revision:'关联版本 / 权限版本',requirement:'需求 ID',version:'系统版本 ID',sst:'精确 SST ID',split:'拆分状态',rv:'BRV 关系来源 / revision',link:'BRVS 关系来源 / revision',unsplit:'待拆分（UNSPLIT）：尚未建立 SST 关联',splitValue:'已关联（SPLIT）',none:'未建立'},
 'en-US':{heading:'Requirement → version → SST relations',boundary:'Verified business relations only. Relation sources are not requirement document sources. Requirement text and test obligations have not been fetched; coverage completion is not implied.',pending:'No verified scope available. Load or reload an authorized scope.',empty:'No valid relations match this selection. Adjust filters; this does not mean zero requirements or test obligations.',scope:'Business scope',revision:'Relation revision / access revision',requirement:'Requirement ID',version:'System version ID',sst:'Exact SST ID',split:'Split state',rv:'BRV relation source / revision',link:'BRVS relation source / revision',unsplit:'Pending split (UNSPLIT): no SST relation established',splitValue:'Linked (SPLIT)',none:'Not established'}
};
export function mountRequirements(root,{getScope,getView}){
 function render(){
  const view=getView(),visible=view.page==='detail'&&view.section==='requirements';root.hidden=!visible;
  root.replaceChildren();for(const key of ['relationScope','relationRevision','accessRevision'])delete root.dataset[key];
  const state=getScope(),projection=requirementRelations(state);root.dataset.relationsStatus=projection.status;
  if(!visible)return;
  const t=copy[document.documentElement.lang==='en-US'?'en-US':'zh-CN'];
  const node=(tag,value)=>{const element=document.createElement(tag);element.textContent=String(value);return element;};
  root.append(node('h3',t.heading),node('p',t.boundary));
  if(projection.status!=='READY'){const status=node('p',projection.status==='NOT_READY'?t.pending:t.empty);status.setAttribute('role','status');root.append(status);return;}
  root.dataset.relationScope=JSON.stringify([state.scope.project_id,state.scope.batch_id,state.scope.release_date]);root.dataset.relationRevision=state.relation_revision;root.dataset.accessRevision=state.access_scope_revision;
  root.append(node('p',`${t.scope}: ${state.scope.project_id} / ${state.scope.batch_id} / ${state.scope.release_date}`),node('p',`${t.revision}: ${state.relation_revision} / ${state.access_scope_revision}`));
  for(const row of projection.records){
   const article=document.createElement('article');article.dataset.relationKey=JSON.stringify([row.requirement_id,row.system_version_id,row.sst_id]);
   article.append(node('h4',`${row.requirement_id} → ${row.system_version_id} → ${row.sst_id??'UNSPLIT'}`));
   const list=document.createElement('dl');
   const rv=row.source_verified_requirement_version,link=row.source_verified_link;
   for(const [label,value] of [[t.requirement,row.requirement_id],[t.version,row.system_version_id],[t.sst,row.sst_id??t.none],[t.split,row.split_state==='UNSPLIT'?t.unsplit:t.splitValue],[t.rv,`${rv.source_link_ref} / ${rv.source_revision}`],[t.link,link?`${link.source_link_ref} / ${link.verified_source_revision}`:t.none]])list.append(node('dt',label),node('dd',value));
   article.append(list);root.append(article);
  }
 }
 document.addEventListener('workbench-scope-changed',render);document.addEventListener('workbench-view-changed',render);new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});render();
}
