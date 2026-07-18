const HISTORY_KEY = 'pylearn_chat_history_v2';
const COURSE_KEY = 'pylearn_course_id_v1';
const AGENT_NAMES = {
  programming_python:'Python 编程助手',
  math_probability_statistics:'数学学习助手',
  math_calculus:'数学学习助手',
  math_linear_algebra:'数学学习助手',
  politics_maogai:'思政学习助手',
  politics_modern_history:'思政学习助手',
  politics_xi_thought:'思政学习助手'
};
const TASK_TYPES = {assignment:'作业',exam:'考试',deadline:'Deadline',review:'复习',reminder:'提醒'};
let calendarCursor = new Date();
let dashboardPlan = window.CampusStore.getPlan();

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
}

function dateKey(date){
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2,'0');
  const day = String(date.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
}

function formatDate(date, withWeekday = false){
  return new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric',...(withWeekday ? {weekday:'long'} : {})}).format(date);
}

function formatTaskDate(task){
  if(!task.date) return '未设置';
  const value = new Date(`${task.date}T${task.time || '00:00'}`);
  if(Number.isNaN(value.getTime())) return task.date;
  return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:task.time ? '2-digit' : undefined,minute:task.time ? '2-digit' : undefined}).format(value);
}

function loadHistory(){
  try{return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');}
  catch(error){return [];}
}

function hydrateIdentity(){
  const settings = window.CampusStore.getSettings();
  const metadata = [settings.profile.major,settings.profile.grade].filter(Boolean).join(' · ');
  document.getElementById('dashboardUserMeta').textContent = metadata || 'Student';
  document.getElementById('dashboardDate').textContent = formatDate(new Date(),true);
}

function hydrateRecentAgent(){
  const recent = loadHistory()[0];
  const courseId = localStorage.getItem(COURSE_KEY) || 'programming_python';
  const name = AGENT_NAMES[courseId] || '课程学习助手';
  if(!recent){
    document.getElementById('recentAgentName').textContent = '暂无使用记录';
    document.getElementById('recentAgentDetail').textContent = '完成一次对话后会显示在这里。';
    return;
  }
  document.getElementById('recentAgentName').textContent = name;
  document.getElementById('recentAgentDetail').textContent = recent.title || '最近对话';
}

async function hydrateCurrentCourse(){
  const courseId = localStorage.getItem(COURSE_KEY) || 'programming_python';
  try{
    const response = await fetch(`/api/courses?user_id=${encodeURIComponent(window.CampusStore.getUserId())}`);
    const data = await response.json();
    const course = (data.courses || []).find(item => item.course_id === courseId);
    document.getElementById('currentCourseName').textContent = course?.name || '尚未选择课程';
    document.getElementById('currentCourseProgress').textContent = '暂无可计算的学习进度。';
  }catch(error){
    document.getElementById('currentCourseName').textContent = '课程信息加载失败';
    document.getElementById('currentCourseProgress').textContent = '请确认本地服务已启动。';
  }
}

function renderPlanSummary(){
  const now = new Date();
  const today = dateKey(now);
  const weekday = now.getDay() || 7;
  const weekEnd = new Date(now);weekEnd.setDate(now.getDate() + 7);
  const todayClasses = dashboardPlan.classes.filter(item => Number(item.weekday) === weekday);
  const todayTasks = dashboardPlan.tasks.filter(item => item.date === today && item.status !== 'done');
  const unfinished = dashboardPlan.tasks.filter(item => item.status !== 'done');
  const weekDue = unfinished.filter(item => {
    if(!item.date) return false;
    const value = new Date(`${item.date}T23:59:59`);
    return value >= new Date(`${today}T00:00:00`) && value <= weekEnd;
  });
  document.getElementById('todayClassCount').textContent = String(todayClasses.length);
  document.getElementById('todayTaskCount').textContent = String(todayTasks.length);
  document.getElementById('unfinishedTaskCount').textContent = String(unfinished.length);
  document.getElementById('weekDueCount').textContent = String(weekDue.length);
  document.getElementById('todayClassHint').textContent = todayClasses.length ? todayClasses.map(item => item.course).slice(0,2).join('、') : '暂无课表记录';
  document.getElementById('todayTaskHint').textContent = todayTasks.length ? todayTasks.map(item => item.title).slice(0,2).join('、') : '暂无今日任务';
  renderUpcoming(unfinished);
  renderReminders(weekDue);
}

function renderUpcoming(tasks){
  const rows = document.getElementById('dashboardTaskRows');
  const sorted = [...tasks].sort((a,b) => String(a.date || '9999').localeCompare(String(b.date || '9999'))).slice(0,5);
  if(!sorted.length){
    rows.innerHTML = '<tr><td colspan="5"><div class="table-empty-state"><strong>还没有学习计划</strong><span>创建任务后，Dashboard 会同步显示真实日程。</span><a href="/plan?action=new-task">创建第一个任务</a></div></td></tr>';
    return;
  }
  rows.innerHTML = sorted.map(task => `<tr data-task-id="${escapeHtml(task.id)}"><td><a class="task-title-link" href="/plan?task=${encodeURIComponent(task.id)}">${escapeHtml(task.title)}</a></td><td>${escapeHtml(TASK_TYPES[task.type] || task.type || '任务')}</td><td>${escapeHtml(task.courseName || '未关联课程')}</td><td>${escapeHtml(formatTaskDate(task))}</td><td><span class="task-status ${task.status === 'in_progress' ? 'status-progress' : 'status-waiting'}">${task.status === 'in_progress' ? '进行中' : '待开始'}</span></td></tr>`).join('');
}

function renderReminders(tasks){
  const container = document.getElementById('dashboardReminders');
  if(!tasks.length){container.className='dashboard-reminders-empty';container.innerHTML='<strong>本周暂无提醒</strong><span>学习计划中的 Deadline 会显示在这里。</span>';return;}
  container.className = 'dashboard-reminder-list';
  container.innerHTML = tasks.slice(0,4).map((task,index) => `<a class="reminder-item ${['reminder-indigo','reminder-teal','reminder-orange'][index%3]}" href="/plan?task=${encodeURIComponent(task.id)}"><span></span><div><strong>${escapeHtml(task.title)}</strong><time>${escapeHtml(formatTaskDate(task))}</time></div></a>`).join('');
}

function renderCalendar(){
  const year = calendarCursor.getFullYear();
  const month = calendarCursor.getMonth();
  const today = new Date();
  const firstDay = new Date(year,month,1);
  const offset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year,month + 1,0).getDate();
  const previousMonthDays = new Date(year,month,0).getDate();
  const taskDays = new Set(dashboardPlan.tasks.filter(task => task.date?.startsWith(`${year}-${String(month+1).padStart(2,'0')}`)).map(task => Number(task.date.slice(-2))));
  const cells = [];
  document.getElementById('calendarTitle').textContent = `${year}年${month + 1}月`;
  for(let index=0;index<42;index+=1){
    const dayNumber = index-offset+1;let display=dayNumber;let muted=false;
    if(dayNumber<=0){display=previousMonthDays+dayNumber;muted=true;}else if(dayNumber>daysInMonth){display=dayNumber-daysInMonth;muted=true;}
    const isToday=!muted&&year===today.getFullYear()&&month===today.getMonth()&&dayNumber===today.getDate();
    cells.push(`<button class="calendar-day${muted?' muted':''}${isToday?' today':''}${!muted&&taskDays.has(dayNumber)?' has-reminder':''}" type="button">${display}</button>`);
  }
  document.getElementById('calendarGrid').innerHTML=cells.join('');
}

async function loadHomeMode(){
  const summary=document.getElementById('serviceSummary');
  try{
    const response=await fetch('/api/health');const data=await response.json();const rag=data.lightrag?.available?`LightRAG ${data.lightrag.version}`:'课程检索未就绪';
    summary.textContent=`${data.mode==='spark'?'Spark X 在线':'本地服务可用'} · ${rag}`;
  }catch(error){summary.textContent='服务等待连接';}
}

document.getElementById('calendarPrev').addEventListener('click',()=>{calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()-1,1);renderCalendar();});
document.getElementById('calendarNext').addEventListener('click',()=>{calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+1,1);renderCalendar();});
document.getElementById('dashboardSearch').addEventListener('keydown',event=>{if(event.key==='Enter'&&event.currentTarget.value.trim())window.location.href=`/chat?q=${encodeURIComponent(event.currentTarget.value.trim())}`;});
window.addEventListener('campus:plan',event=>{dashboardPlan=event.detail;renderPlanSummary();renderCalendar();});

hydrateIdentity();hydrateRecentAgent();hydrateCurrentCourse();renderPlanSummary();renderCalendar();loadHomeMode();
