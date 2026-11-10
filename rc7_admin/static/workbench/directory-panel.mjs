import {DirectoryClient} from './directory-client.mjs';
export function mountDirectory(root,{scopePanel,getView,openDetail,fetcher=fetch}={}){
 const projects=new DirectoryClient(fetcher),dates=new DirectoryClient(fetcher);let project='',batch='';
 root.innerHTML='<h3 data-directory-title></h3><button type="button" data-directory-load></button><label><span data-project-label></span><select data-project-select></select></label><label><span data-date-label></span><select data-date-select></select></label><p role="status" data-directory-status></p><div data-project-cards></div>';
 const $=selector=>root.querySelector(selector);
 const words={'zh-CN':['我的项目','加载/刷新我的项目','项目','投产日期','请选择项目','请选择投产日期','尚未加载项目目录','正在加载','当前没有可访问的项目','项目尚无投产日期','连接失败或权限变化，请重新加载','打开项目'], 'en-US':['My projects','Load / refresh my projects','Project','Release date','Choose a project','Choose a release date','Project directory not loaded','Loading','No accessible projects','No release dates for this project','Connection or permissions changed. Reload required','Open project']};
 function render(){const t=words[document.documentElement.lang]||words['zh-CN'];$('[data-directory-title]').textContent=t[0];$('[data-directory-load]').textContent=t[1];$('[data-project-label]').textContent=t[2];$('[data-date-label]').textContent=t[3];
  const records=projects.state.status==='READY'?projects.state.records:[];const releases=dates.state.status==='READY'?dates.state.records:[];
  $('[data-project-select]').replaceChildren(new Option(t[4],''),...records.map(r=>new Option(r.name,r.project_id)));$('[data-project-select]').value=project;$('[data-project-select]').disabled=projects.state.status!=='READY';
  $('[data-date-select]').replaceChildren(new Option(t[5],''),...releases.map(r=>new Option(r.release_date,r.batch_id)));$('[data-date-select]').value=batch;$('[data-date-select]').disabled=dates.state.status!=='READY';
  const loading=projects.state.status==='LOADING'||dates.state.status==='LOADING';const error=projects.state.status==='ERROR'?projects.state.error:dates.state.status==='ERROR'?dates.state.error:'';
  root.dataset.directoryStatus=error?'ERROR':loading?'LOADING':projects.state.status;
  $('[data-directory-status]').textContent=error?t[10]+' ('+error+')':loading?t[7]:projects.state.status!=='READY'?t[6]:!records.length?t[8]:project&&dates.state.status==='READY'&&!releases.length?t[9]:'';
  $('[data-project-cards]').hidden=getView().page!=='home';$('[data-project-cards]').replaceChildren(...records.map(r=>{const card=document.createElement('article'),name=document.createElement('h4'),button=document.createElement('button');card.dataset.projectId=r.project_id;name.textContent=r.name;button.type='button';button.textContent=t[11];button.onclick=()=>{chooseProject(r.project_id);openDetail();};card.append(name,button);return card;}));
 }
 async function load(){project='';batch='';dates.clear();scopePanel.setContext({});const promise=projects.load();render();await promise;render();}
 async function chooseProject(value){project=value;batch='';dates.clear();scopePanel.setContext({project_id:value});if(!value){render();return;}const promise=dates.load(value);render();await promise;render();}
 $('[data-directory-load]').onclick=load;$('[data-project-select]').onchange=e=>chooseProject(e.target.value);
 $('[data-date-select]').onchange=()=>{batch=$('[data-date-select]').value;const row=dates.state.records.find(r=>r.batch_id===batch);scopePanel.setContext(row?{project_id:project,batch_id:row.batch_id,release_date:row.release_date}:{project_id:project});if(row)scopePanel.load();render();};
 document.addEventListener('workbench-scope-changed',()=>{const value=scopePanel.context;if(project&&value.project_id!==project){project='';batch='';dates.clear();render();}else if(batch){const row=dates.state.records.find(r=>r.batch_id===batch);if(!row||value.batch_id!==batch||value.release_date!==row.release_date){batch='';render();}}});
 new MutationObserver(render).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});document.addEventListener('workbench-view-changed',render);render();return {load};
}
