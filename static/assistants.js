const USER_KEY = 'pylearn_user_id_v1';
let userId = localStorage.getItem(USER_KEY);
if(!userId){ userId = `student_${Math.random().toString(16).slice(2)}`; localStorage.setItem(USER_KEY, userId); }
let assistant = null;
const $ = selector => document.querySelector(selector);
const esc = value => String(value || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function jsonFetch(url, options={}){
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if(!response.ok) throw new Error(data.detail || `请求失败 ${response.status}`);
  return data;
}

async function loadInitial(){
  const [health, courses] = await Promise.all([jsonFetch('/api/health'), jsonFetch(`/api/courses?user_id=${encodeURIComponent(userId)}`)]);
  const rag = health.lightrag || {};
  $('#ragStatus').textContent = rag.available ? `可用 · ${rag.embedding_model}` : 'LightRAG 未安装';
  $('#ragStatus').className = `review-badge ${rag.available ? 'passed' : 'rejected'}`;
  const publicCourses = courses.courses.filter(item => item.is_public);
  $('#publicCourses').innerHTML = publicCourses.length ? publicCourses.map(item => `<div class="assistant-item"><strong>${esc(item.name)}</strong><span>${esc(item.domain)} · 独立课程空间</span><a href="/chat?course=${encodeURIComponent(item.course_id)}">进入答疑</a></div>`).join('') : '<div class="content-empty"><strong>暂无可用课程</strong><p>没有使用静态课程数据替代。</p></div>';
}

$('#assistantForm').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  payload.user_id = userId;
  try{
    assistant = await jsonFetch('/api/custom-assistants', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    $('#createResult').textContent = '助手已创建，请上传第一份课程资料。';
    showAssistant();
  }catch(error){ $('#createResult').textContent = error.message; }
});

function showAssistant(){
  $('#customPanel').hidden = false;
  $('#customTitle').textContent = assistant.name;
  $('#customMeta').textContent = `${assistant.course_name} · ${assistant.workspace}`;
  $('#customStatus').textContent = assistant.status;
}

async function refreshAssistant(){
  assistant = await jsonFetch(`/api/custom-assistants/${assistant.assistant_id}?user_id=${encodeURIComponent(userId)}`);
  showAssistant();
  $('#documentList').innerHTML = assistant.documents.map(item => `<div class="assistant-item"><strong>${esc(item.filename)}</strong><span>${esc(item.index_status)}${item.error_message ? ` · ${esc(item.error_message)}` : ''}</span></div>`).join('');
}

$('#uploadForm').addEventListener('submit', async event => {
  event.preventDefault();
  if(!assistant) return;
  const file = $('#documentFile').files[0];
  if(!file) return;
  const body = new FormData(); body.append('file', file); body.append('user_id', userId);
  try{
    const result = await jsonFetch(`/api/custom-assistants/${assistant.assistant_id}/documents`, {method:'POST', body});
    $('#jobProgress').hidden = false;
    await watchJob(result.job.job_id);
  }catch(error){ $('#jobStage').textContent = error.message; $('#jobProgress').hidden = false; }
});

async function watchJob(jobId){
  for(;;){
    const job = await jsonFetch(`/api/indexing-jobs/${jobId}?user_id=${encodeURIComponent(userId)}`);
    $('#jobStage').textContent = job.stage;
    $('#jobPercent').textContent = `${job.progress}%`;
    $('#jobBar').value = job.progress;
    if(['completed','failed','duplicate'].includes(job.status)){ await refreshAssistant(); return; }
    await new Promise(resolve => setTimeout(resolve, 900));
  }
}

$('#assistantQueryForm').addEventListener('submit', async event => {
  event.preventDefault();
  if(!assistant) return;
  $('#assistantAnswer').hidden = false;
  $('#assistantAnswer').textContent = '正在检索当前课程知识空间并审核引用...';
  try{
    const data = await jsonFetch(`/api/assistants/${assistant.assistant_id}/query`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:userId, assistant_id:assistant.assistant_id, course_id:assistant.course_id, message:$('#assistantQuestion').value})});
    const citations = (data.citations || []).map(item => `<li>${esc(item.material_name)} · ${esc(item.chapter)} · ${item.page_index ? `第 ${item.page_index} 页/节` : '未分页'}<br><small>${esc(item.snippet)}</small></li>`).join('');
    $('#assistantAnswer').innerHTML = `<div class="answer-content">${esc(data.answer)}</div><h3>引用</h3><ol>${citations}</ol>`;
  }catch(error){ $('#assistantAnswer').textContent = error.message; }
});

loadInitial().catch(error => { $('#ragStatus').textContent = error.message; $('#publicCourses').innerHTML = '<div class="content-error"><strong>课程读取失败</strong><p>请确认本地服务已启动。</p></div>'; });

const requestedAction = new URLSearchParams(location.search).get('action');
if(requestedAction === 'create' || requestedAction === 'upload'){
  requestAnimationFrame(() => {
    $('#createAssistantSection').scrollIntoView({behavior:'smooth', block:'start'});
    $('#assistantForm').elements.name.focus();
  });
}
