const HOME_USER_NAME_KEY = 'pylearn_user_name_v1';
let calendarCursor = new Date();

function formatDate(date, withWeekday = false){
  return new Intl.DateTimeFormat('zh-CN', {
    year:'numeric', month:'long', day:'numeric',
    ...(withWeekday ? {weekday:'long'} : {})
  }).format(date);
}

function hydrateIdentity(){
  const name = localStorage.getItem(HOME_USER_NAME_KEY) || '同学';
  document.getElementById('welcomeUser').textContent = name;
  document.getElementById('dashboardUser').textContent = name;
  document.getElementById('dashboardDate').textContent = formatDate(new Date(), true);
}

function hydrateRelativeDates(){
  document.querySelectorAll('[data-date-offset]').forEach(element => {
    const date = new Date();
    date.setDate(date.getDate() + Number(element.dataset.dateOffset || 0));
    element.textContent = new Intl.DateTimeFormat('zh-CN', {month:'2-digit', day:'2-digit'}).format(date);
  });
  document.querySelectorAll('[data-reminder-offset]').forEach(element => {
    const date = new Date();
    date.setDate(date.getDate() + Number(element.dataset.reminderOffset || 0));
    element.textContent = formatDate(date, true);
  });
}

function renderCalendar(){
  const year = calendarCursor.getFullYear();
  const month = calendarCursor.getMonth();
  const today = new Date();
  const firstDay = new Date(year, month, 1);
  const offset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const previousMonthDays = new Date(year, month, 0).getDate();
  const cells = [];
  document.getElementById('calendarTitle').textContent = `${year}年${month + 1}月`;
  for(let index = 0; index < 42; index += 1){
    const dayNumber = index - offset + 1;
    let display = dayNumber;
    let muted = false;
    if(dayNumber <= 0){
      display = previousMonthDays + dayNumber;
      muted = true;
    }else if(dayNumber > daysInMonth){
      display = dayNumber - daysInMonth;
      muted = true;
    }
    const isToday = !muted && year === today.getFullYear() && month === today.getMonth() && dayNumber === today.getDate();
    const hasReminder = !muted && [today.getDate() + 1, today.getDate() + 2, today.getDate() + 4].includes(dayNumber)
      && year === today.getFullYear() && month === today.getMonth();
    cells.push(`<button class="calendar-day${muted ? ' muted' : ''}${isToday ? ' today' : ''}${hasReminder ? ' has-reminder' : ''}" type="button">${display}</button>`);
  }
  document.getElementById('calendarGrid').innerHTML = cells.join('');
}

async function loadHomeMode(){
  const summary = document.getElementById('serviceSummary');
  try{
    const response = await fetch('/api/health');
    const data = await response.json();
    const rag = data.lightrag?.available ? `LightRAG ${data.lightrag.version}` : '课程检索未就绪';
    const astron = data.astron_configured ? '星辰协作已连接' : '星辰协作未配置';
    summary.textContent = `${data.mode === 'spark' ? 'Spark X 在线' : '本地服务可用'} · ${rag} · ${astron}`;
  }catch(error){
    summary.textContent = '等待连接';
  }
}

document.getElementById('calendarPrev').addEventListener('click', () => {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() - 1, 1);
  renderCalendar();
});

document.getElementById('calendarNext').addEventListener('click', () => {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + 1, 1);
  renderCalendar();
});

document.getElementById('dashboardSearch').addEventListener('keydown', event => {
  if(event.key !== 'Enter') return;
  const query = event.currentTarget.value.trim();
  if(query) window.location.href = `/chat?q=${encodeURIComponent(query)}`;
});

hydrateIdentity();
hydrateRelativeDates();
renderCalendar();
loadHomeMode();
