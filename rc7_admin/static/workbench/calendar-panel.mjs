import {parseDate,formatDate,shiftDate,monthCells,visibleMilestones} from './calendar-model.mjs';

const words = {
  'zh-CN': {heading:'里程碑日历',year:'年',month:'月',day:'日',view:'日历视图',previous:'上一期',next:'下一期',jump:'跳转日期',count:'项里程碑',empty:'本期没有已加载的里程碑',notLoaded:'先刷新资料以读取当前合法范围的里程碑',invalid:'请选择有效的业务日期',weekdays:['一','二','三','四','五','六','日']},
  'en-US': {heading:'Milestone calendar',year:'Year',month:'Month',day:'Day',view:'Calendar view',previous:'Previous period',next:'Next period',jump:'Go to date',count:'milestones',empty:'No loaded milestones in this period',notLoaded:'Refresh records to load milestones in the verified scope',invalid:'Choose a valid business date',weekdays:['Mon','Tue','Wed','Thu','Fri','Sat','Sun']}
};

// Stateless projection of the same authorized assets used in project details.
export function renderCalendar(root, {date,mode,records,locale,enabled,loaded,onNavigate,onMode,onSelectDate}) {
  const t = words[locale] || words['zh-CN'];
  const focusKey = root.contains(document.activeElement) ? document.activeElement.dataset.calendarControl : null;
  root.replaceChildren();
  const node = (tag, text) => {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  const heading=node('h4',t.heading),controls=node('div');controls.className='calendar-controls';
  const viewLabel=node('label',t.view),select=node('select');select.dataset.calendarControl='view';select.setAttribute('aria-label',t.view);
  for(const value of ['year','month','day']){const option=node('option',t[value]);option.value=value;select.append(option);}
  select.value=mode;select.disabled=!date||!enabled;select.onchange=()=>onMode(select.value);viewLabel.append(select);controls.append(viewLabel);
  for(const [key,step] of [['previous',-1],['next',1]]){const button=node('button',t[key]);button.type='button';button.dataset.calendarControl=key;const target=date?shiftDate(date,mode,step):null;button.disabled=!enabled||!target;button.onclick=()=>onNavigate(target);controls.append(button);}
  const jumpLabel=node('label',t.jump),jump=node('input');jump.type='date';jump.min='0001-01-01';jump.max='9999-12-31';jump.value=date||'';jump.disabled=!enabled;jump.dataset.calendarControl='jump';jump.setAttribute('aria-label',t.jump);
  jump.onchange=()=>{try{parseDate(jump.value);jump.setCustomValidity('');onSelectDate(jump.value,mode);}catch{jump.setCustomValidity(t.invalid);jump.reportValidity();}};
  jumpLabel.append(jump);controls.append(jumpLabel);root.append(heading,controls);
  if(!date)return;
  const {year,month}=parseDate(date),period=date.slice(0,{year:4,month:7,day:10}[mode]),title=node('p',period);title.dataset.calendarPeriod='';title.setAttribute('aria-live','polite');root.append(title);
  const visible=visibleMilestones(records,date,mode);
  const summary=node('p',!loaded?t.notLoaded:visible.length?`${visible.length} ${t.count}`:t.empty);summary.dataset.calendarSummary='';root.append(summary);
  function dateButton(value,text,nextMode,count){const button=node('button',`${text} · ${loaded?count:'—'}`);button.type='button';button.dataset.calendarDate=value;button.dataset.calendarControl='date:'+value;button.setAttribute('aria-label',`${value} · ${loaded?count:'—'} ${t.count}`);button.setAttribute('aria-pressed',String(date===value));button.disabled=!enabled;button.onclick=()=>onSelectDate(value,nextMode);return button;}
  if(mode==='year'){
    const months=node('div');months.className='calendar-months';
    for(let m=1;m<=12;m++){const value=formatDate(year,m,1),count=visible.filter(r=>r.payload.due_date.slice(0,7)===value.slice(0,7)).length;months.append(dateButton(value,locale==='en-US'?new Intl.DateTimeFormat('en-US',{month:'long',timeZone:'UTC'}).format(new Date(Date.UTC(2000,m-1,1))):`${m}月`,'month',count));}
    root.append(months);
  } else if(mode==='month') {
    const table=node('table');table.className='calendar-month';const caption=node('caption',`${year}-${String(month).padStart(2,'0')}`),head=node('thead'),headRow=node('tr'),body=node('tbody');
    for(const day of t.weekdays){const th=node('th',day);th.scope='col';headRow.append(th);}head.append(headRow);
    let row;monthCells(date).forEach((value,index)=>{if(index%7===0){row=node('tr');body.append(row);}const cell=node('td');if(value){const count=visible.filter(r=>r.payload.due_date===value).length;cell.append(dateButton(value,String(parseDate(value).day),'day',count));}row.append(cell);});table.append(caption,head,body);root.append(table);
  }
  if(focusKey){const target=[...root.querySelectorAll('[data-calendar-control]')].find(el=>el.dataset.calendarControl===focusKey);if(target&&!target.disabled)target.focus();else select.focus();}
}
