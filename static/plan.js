const DAY_NAMES=['星期一','星期二','星期三','星期四','星期五','星期六','星期日'];
const TASK_TYPES={assignment:'作业',exam:'考试',deadline:'Deadline',review:'复习',reminder:'提醒'};
const STATUS_NAMES={todo:'待开始',in_progress:'进行中',done:'已完成'};
let plan=window.CampusStore.getPlan();
let calendarCursor=new Date();
const $=selector=>document.querySelector(selector);

function escapeHtml(value){return String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function uid(prefix){return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(16).slice(2,8)}`;}
function dateKey(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;}
function save(){plan=window.CampusStore.savePlan(plan);renderAll();}
function openModal(id){document.getElementById(id).hidden=false;}
function closeModal(id){document.getElementById(id).hidden=true;}

function renderSchedule(){
  const grid=$('#scheduleGrid');
  const columns=DAY_NAMES.map((day,index)=>{
    const items=plan.classes.filter(item=>Number(item.weekday)===index+1).sort((a,b)=>String(a.start).localeCompare(String(b.start)));
    return `<section class="schedule-day"><h3>${day}</h3><div>${items.length?items.map(item=>`<button class="schedule-class color-${escapeHtml(item.color||'indigo')}" data-class-id="${escapeHtml(item.id)}" type="button"><strong>${escapeHtml(item.course)}</strong><span>${escapeHtml(item.start)}–${escapeHtml(item.end)}</span><small>${escapeHtml([item.location,item.teacher].filter(Boolean).join(' · ')||'未填写地点和教师')}</small>${item.agent?'<em>已关联 Agent</em>':''}</button>`).join(''):'<p>暂无课程</p>'}</div></section>`;
  }).join('');
  grid.innerHTML=columns;
  grid.querySelectorAll('[data-class-id]').forEach(button=>button.addEventListener('click',()=>editClass(button.dataset.classId)));
}

function renderCalendar(){
  const year=calendarCursor.getFullYear(),month=calendarCursor.getMonth(),today=new Date();
  $('#planCalendarTitle').textContent=`${year}年${month+1}月`;
  const offset=(new Date(year,month,1).getDay()+6)%7,days=new Date(year,month+1,0).getDate(),previous=new Date(year,month,0).getDate();
  const taskCounts={};plan.tasks.forEach(task=>{if(task.date)taskCounts[task.date]=(taskCounts[task.date]||0)+1;});
  const cells=[];for(let i=0;i<42;i+=1){const number=i-offset+1;let display=number,muted=false,cellDate;if(number<=0){display=previous+number;muted=true;cellDate=new Date(year,month-1,display);}else if(number>days){display=number-days;muted=true;cellDate=new Date(year,month+1,display);}else{cellDate=new Date(year,month,number);}const key=dateKey(cellDate),isToday=key===dateKey(today),count=taskCounts[key]||0;cells.push(`<button class="plan-calendar-day${muted?' muted':''}${isToday?' today':''}" data-date="${key}" type="button"><span>${display}</span>${count?`<b>${count}</b>`:''}</button>`);}
  $('#planCalendarGrid').innerHTML=cells.join('');
  $('#planCalendarGrid').querySelectorAll('[data-date]').forEach(button=>button.addEventListener('click',()=>newTask(button.dataset.date)));
}

function renderTasks(){
  const filter=$('#taskStatusFilter').value;
  const tasks=[...plan.tasks].filter(task=>filter==='all'||(filter==='done'?task.status==='done':task.status!=='done')).sort((a,b)=>String(a.date||'9999').localeCompare(String(b.date||'9999')));
  const container=$('#planTaskList');
  if(!tasks.length){container.innerHTML='<div class="content-empty"><span>▦</span><strong>暂无符合条件的任务</strong><p>创建作业、考试、Deadline 或复习提醒。</p><button type="button" data-create-task>新增任务</button></div>';container.querySelector('[data-create-task]').addEventListener('click',()=>newTask());return;}
  container.innerHTML=tasks.map(task=>`<article class="plan-task ${task.status==='done'?'done':''}"><button class="task-check" data-toggle-task="${escapeHtml(task.id)}" type="button" title="切换完成状态">${task.status==='done'?'✓':''}</button><div><span>${escapeHtml(TASK_TYPES[task.type]||task.type)}${task.courseName?` · ${escapeHtml(task.courseName)}`:''}</span><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.date||'未设置日期')}${task.time?` · ${escapeHtml(task.time)}`:''}</p></div><button class="task-edit" data-edit-task="${escapeHtml(task.id)}" type="button">编辑</button></article>`).join('');
  container.querySelectorAll('[data-toggle-task]').forEach(button=>button.addEventListener('click',()=>{const item=plan.tasks.find(task=>task.id===button.dataset.toggleTask);if(item){item.status=item.status==='done'?'todo':'done';save();}}));
  container.querySelectorAll('[data-edit-task]').forEach(button=>button.addEventListener('click',()=>editTask(button.dataset.editTask)));
}
function renderAll(){renderSchedule();renderCalendar();renderTasks();}

function newClass(){const form=$('#classForm');form.reset();form.elements.id.value='';form.elements.repeat.checked=true;$('#classModalTitle').textContent='新增课程';$('#deleteClassButton').hidden=true;openModal('classModal');}
function editClass(id){const item=plan.classes.find(entry=>entry.id===id);if(!item)return;const form=$('#classForm');Object.entries(item).forEach(([key,value])=>{if(form.elements[key])form.elements[key].type==='checkbox'?form.elements[key].checked=Boolean(value):form.elements[key].value=value;});$('#classModalTitle').textContent='编辑课程';$('#deleteClassButton').hidden=false;openModal('classModal');}
function newTask(date=''){const form=$('#taskForm');form.reset();form.elements.id.value='';form.elements.date.value=date||dateKey(new Date());form.elements.reminder.checked=true;$('#taskModalTitle').textContent='新增任务';$('#deleteTaskButton').hidden=true;openModal('taskModal');}
function editTask(id){const item=plan.tasks.find(entry=>entry.id===id);if(!item)return;const form=$('#taskForm');Object.entries(item).forEach(([key,value])=>{if(form.elements[key])form.elements[key].type==='checkbox'?form.elements[key].checked=Boolean(value):form.elements[key].value=value;});$('#taskModalTitle').textContent='编辑任务';$('#deleteTaskButton').hidden=false;openModal('taskModal');}

$('#classForm').addEventListener('submit',event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget).entries());values.repeat=event.currentTarget.elements.repeat.checked;const existing=plan.classes.find(item=>item.id===values.id);if(existing)Object.assign(existing,values);else plan.classes.push({...values,id:uid('class')});closeModal('classModal');save();});
$('#taskForm').addEventListener('submit',event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget).entries());values.reminder=event.currentTarget.elements.reminder.checked;const selected=$('#taskCourseSelect').selectedOptions[0];values.courseName=values.courseId?selected?.textContent||'':'';const existing=plan.tasks.find(item=>item.id===values.id);if(existing)Object.assign(existing,values);else plan.tasks.push({...values,id:uid('task')});closeModal('taskModal');save();});
$('#deleteClassButton').addEventListener('click',()=>{const id=$('#classForm').elements.id.value;if(id){plan.classes=plan.classes.filter(item=>item.id!==id);closeModal('classModal');save();}});
$('#deleteTaskButton').addEventListener('click',()=>{const id=$('#taskForm').elements.id.value;if(id){plan.tasks=plan.tasks.filter(item=>item.id!==id);closeModal('taskModal');save();}});
document.querySelectorAll('[data-close-modal]').forEach(button=>button.addEventListener('click',()=>closeModal(button.dataset.closeModal)));
document.querySelectorAll('.campus-modal').forEach(modal=>modal.addEventListener('click',event=>{if(event.target===modal)closeModal(modal.id);}));
$('#addClassButton').addEventListener('click',newClass);$('#addTaskButton').addEventListener('click',()=>newTask());$('#taskStatusFilter').addEventListener('change',renderTasks);
$('#planCalendarPrev').addEventListener('click',()=>{calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()-1,1);renderCalendar();});$('#planCalendarNext').addEventListener('click',()=>{calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+1,1);renderCalendar();});$('#planCalendarToday').addEventListener('click',()=>{calendarCursor=new Date();renderCalendar();});

fetch(`/api/courses?user_id=${encodeURIComponent(window.CampusStore.getUserId())}`).then(response=>response.json()).then(data=>{$('#taskCourseSelect').innerHTML='<option value="">不关联课程</option>'+(data.courses||[]).map(course=>`<option value="${escapeHtml(course.course_id)}">${escapeHtml(course.name)}</option>`).join('');}).catch(()=>{});
const query=new URLSearchParams(location.search);if(query.get('action')==='new-task')setTimeout(()=>newTask(),0);if(query.get('task'))setTimeout(()=>editTask(query.get('task')),0);renderAll();
