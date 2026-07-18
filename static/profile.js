const PROFILE_USER_KEY = 'pylearn_user_id_v1';
const PROFILE_STATE_KEY = 'pylearn_latest_learning_state_v1';
const PROFILE_COURSE_KEY = 'pylearn_course_id_v1';
const $ = selector => document.querySelector(selector);

let currentProfileCourseId = localStorage.getItem(PROFILE_COURSE_KEY) || 'programming_python';
let currentSnapshot = null;

const SOURCE_LABELS = {conversation:'学生对话', practice:'练习记录', behavior:'学习行为', user_correction:'用户修正', none:'暂无来源'};
const STATUS_LABELS = {confirmed:'已确认', conflict:'存在冲突', insufficient:'等待信息'};
const PROFILE_FIELDS = ['current_identity','current_course','mastered','unmastered','common_errors','learning_goal','daily_time','learning_preference','learning_state'];

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
}

function displayValue(value, fallback = '尚未确认'){
  if(Array.isArray(value)) return value.length ? value.join('、') : fallback;
  if(value === null || value === undefined || String(value).trim() === '') return fallback;
  return String(value);
}

function displayTime(value){
  if(!value) return '尚未更新';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
}

function getRecord(field){
  return currentSnapshot?.record_map?.[field] || null;
}

function confirmedValue(field, fallback = '尚未确认'){
  const record = getRecord(field);
  if(!record || record.status === 'insufficient') return fallback;
  return displayValue(record.value, fallback);
}

function settingsProfile(){
  return window.CampusStore?.getSettings?.().profile || {};
}

function factCard({label, value, detail, field, source = '账户设置', editable = false}){
  const waiting = !value || value === '尚未确认' || value === '等待学习记录' || value === '暂无信息';
  const action = editable
    ? `<button class="profile-fact-edit" data-profile-field="${escapeHtml(field)}" type="button">修正</button>`
    : `<a class="profile-fact-edit" href="/settings">修改</a>`;
  return `<article class="profile-fact${waiting ? ' waiting' : ''}"><div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || '尚未确认')}</strong><small>${escapeHtml(detail || source)}</small></div>${action}</article>`;
}

function renderGlobalProfile(){
  const profile = settingsProfile();
  const identity = confirmedValue('current_identity', '尚未确认');
  const name = profile.name || profile.nickname || '尚未填写';
  const majorGrade = [profile.major, profile.grade].filter(Boolean).join(' · ') || identity;
  const preference = confirmedValue('learning_preference', '尚未确认');
  const orientationLabels = {balanced:'均衡', theory:'偏理论', practice_questions:'偏做题', hands_on:'偏实践'};
  const orientation = orientationLabels[window.CampusStore?.getSettings?.().ai?.orientation] || '尚未确认';
  const cards = [
    {label:'姓名', value:name, detail:profile.nickname ? `昵称：${profile.nickname}` : '来自账户设置'},
    {label:'专业与年级', value:majorGrade, detail:profile.major || profile.grade ? '来自账户设置' : '身份对话尚未提供完整信息'},
    {label:'每天可投入时间', value:confirmedValue('daily_time'), detail:getRecord('daily_time')?.evidence || '等待直接证据', field:'daily_time', editable:true},
    {label:'学习目标', value:confirmedValue('learning_goal'), detail:getRecord('learning_goal')?.evidence || '等待直接证据', field:'learning_goal', editable:true},
    {label:'讲解偏好', value:preference, detail:getRecord('learning_preference')?.evidence || '等待直接证据', field:'learning_preference', editable:true},
    {label:'学习取向', value:orientation, detail:'来自账户设置中的回答偏好'}
  ];
  $('#globalProfileGrid').innerHTML = cards.map(factCard).join('');
}

function renderCourseProfile(){
  const courseName = $('#profileCourseSelect')?.selectedOptions?.[0]?.textContent || confirmedValue('current_course');
  const state = getRecord('learning_state');
  const cards = [
    {label:'当前课程与章节', value:confirmedValue('current_course', courseName || '尚未确认'), detail:getRecord('current_course')?.evidence || '当前课程空间', field:'current_course', editable:true},
    {label:'已掌握内容', value:confirmedValue('mastered', '等待学习记录'), detail:getRecord('mastered')?.evidence || '尚无练习或对话证据', field:'mastered', editable:true},
    {label:'待加强内容', value:confirmedValue('unmastered', '等待学习记录'), detail:getRecord('unmastered')?.evidence || '尚无诊断证据', field:'unmastered', editable:true},
    {label:'常见错误', value:confirmedValue('common_errors', '等待学习记录'), detail:getRecord('common_errors')?.evidence || '尚无练习错误记录', field:'common_errors', editable:true},
    {label:'最近练习表现', value:state?.source_type === 'practice' ? displayValue(state.value) : '暂无练习记录', detail:state?.source_type === 'practice' ? state.evidence : '后端尚未提供独立练习表现字段'},
    {label:'当前学习状态', value:confirmedValue('learning_state', '等待学习记录'), detail:state?.evidence || '等待真实学习行为', field:'learning_state', editable:true}
  ];
  $('#courseProfileGrid').innerHTML = cards.map(factCard).join('');
}

function renderRecords(records){
  $('#profileRecords').innerHTML = records.length ? records.map(record => {
    const confidence = Math.round(Number(record.confidence || 0) * 100);
    const statusClass = ['confirmed','conflict'].includes(record.status) ? record.status : 'insufficient';
    return `<details class="profile-record ${statusClass}"${record.status === 'conflict' ? ' open' : ''}><summary><span><strong>${escapeHtml(record.label)}</strong><small>${escapeHtml(displayValue(record.value))}</small></span><b>${escapeHtml(STATUS_LABELS[record.status] || record.status)}</b></summary><dl><div><dt>证据</dt><dd>${escapeHtml(record.evidence || '暂无直接证据')}</dd></div><div><dt>来源</dt><dd>${escapeHtml(SOURCE_LABELS[record.source_type] || record.source_type || '暂无来源')}</dd></div><div><dt>置信度</dt><dd>${record.status === 'insufficient' ? '尚未确认' : `${confidence}%`}</dd></div><div><dt>更新时间</dt><dd>${escapeHtml(displayTime(record.updated_at))}</dd></div><div><dt>确认状态</dt><dd>${escapeHtml(STATUS_LABELS[record.status] || record.status)}</dd></div></dl><button class="profile-record-edit" data-profile-field="${escapeHtml(record.field)}" type="button">修正这条画像</button></details>`;
  }).join('') : '<div class="content-empty"><strong>暂无画像证据</strong><p>完成一次有明确个人信息或学习表现的对话后，这里会出现可追溯记录。</p></div>';
}

function renderChanges(changes, labels){
  $('#profileChanges').innerHTML = changes.length ? changes.slice(0, 8).map(change => `<div class="profile-change"><span></span><p><strong>${escapeHtml(labels[change.field] || change.field)}</strong><b>${escapeHtml(change.old_record ? displayValue(change.old_record.value) : '首次记录')} → ${escapeHtml(displayValue(change.new_record?.value))}</b><small>${escapeHtml(displayTime(change.created_at))} · ${escapeHtml(change.reason || '画像更新')}</small></p></div>`).join('') : '<p class="empty">暂无画像变化。</p>';
}

function renderMissing(missingFields, labels){
  $('#profileMissing').innerHTML = missingFields.length ? missingFields.map(field => `<span>${escapeHtml(labels[field] || field)}<small>尚未确认</small></span>`).join('') : '<p class="empty">当前字段均已有直接证据。</p>';
}

function renderStrategies(){
  const preference = confirmedValue('learning_preference');
  const errors = confirmedValue('common_errors', '等待学习记录');
  const course = confirmedValue('current_course', $('#profileCourseSelect')?.selectedOptions?.[0]?.textContent || '当前课程');
  $('#answerStrategy').textContent = preference === '尚未确认' ? '简单问题先直接回答，不推测表达偏好。' : `遵循已确认偏好：${preference}。`;
  $('#resourceStrategy').textContent = errors === '等待学习记录' ? '先补充练习证据，再决定强化资源。' : `围绕已记录易错点提供练习：${errors}。`;
  $('#contextStrategy').textContent = `对话与画像限定在“${course}”课程空间内。`;
}

function bindEditButtons(){
  document.querySelectorAll('[data-profile-field]').forEach(button => button.addEventListener('click', () => openEditModal(button.dataset.profileField)));
}

function renderProfile(snapshot){
  currentSnapshot = snapshot;
  const records = (snapshot.records || []).filter(record => PROFILE_FIELDS.includes(record.field));
  const labels = Object.fromEntries(records.map(record => [record.field, record.label]));
  const confirmed = records.filter(record => record.status === 'confirmed').length;
  const conflict = records.filter(record => record.status === 'conflict').length;
  $('#profileSummary').innerHTML = `<strong>${confirmed} 项已有证据</strong><span>${conflict ? `${conflict} 项存在冲突 · ` : ''}${snapshot.missing_fields?.length || 0} 项等待信息</span>`;
  renderGlobalProfile();
  renderCourseProfile();
  renderRecords(records);
  renderChanges(snapshot.changes || [], labels);
  renderMissing(snapshot.missing_fields || [], labels);
  renderStrategies();
  const showVisual = confirmed >= 4;
  $('#profileVisualPanel').hidden = !showVisual;
  $('#profileVisualEmpty').hidden = showVisual;
  bindEditButtons();
}

function openEditModal(field){
  const record = getRecord(field);
  const form = $('#profileEditForm');
  form.elements.field.value = field;
  form.elements.value.value = record?.status === 'insufficient' ? '' : displayValue(record?.value, '');
  form.elements.evidence.value = '';
  $('#profileEditTitle').textContent = `修正${record?.label || '画像信息'}`;
  $('#profileEditModal').hidden = false;
  form.elements.value.focus();
}

function closeEditModal(){
  $('#profileEditModal').hidden = true;
  $('#profileEditForm').reset();
}

async function saveCorrection(event){
  event.preventDefault();
  const form = event.currentTarget;
  const field = form.elements.field.value;
  const original = String(form.elements.value.value || '').trim();
  const current = getRecord(field);
  const value = Array.isArray(current?.value) ? original.split(/[，,、\n]/).map(item => item.trim()).filter(Boolean) : original;
  const response = await fetch('/api/profile/update', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:localStorage.getItem(PROFILE_USER_KEY) || 'demo_student', field, value, evidence:String(form.elements.evidence.value || '').trim(), course_id:currentProfileCourseId})});
  const data = await response.json().catch(() => ({}));
  if(!response.ok){
    form.elements.evidence.setCustomValidity(data.detail || `保存失败（${response.status}）`);
    form.elements.evidence.reportValidity();
    form.elements.evidence.setCustomValidity('');
    return;
  }
  closeEditModal();
  localStorage.setItem(PROFILE_STATE_KEY, JSON.stringify({profile:data, updatedAt:Date.now()}));
  renderProfile(data);
}

async function loadProfile(){
  try{
    const response = await fetch('/api/profile', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:localStorage.getItem(PROFILE_USER_KEY) || 'demo_student', course_id:currentProfileCourseId})});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    localStorage.setItem(PROFILE_STATE_KEY, JSON.stringify({profile:snapshot, updatedAt:Date.now()}));
    renderProfile(snapshot);
  }catch(error){
    $('#profileSummary').innerHTML = '<strong>画像加载失败</strong><span>请确认本地服务已启动。</span>';
    $('#globalProfileGrid').innerHTML = '<div class="content-error"><strong>无法读取画像</strong><p>当前没有使用模拟数据。</p></div>';
    $('#courseProfileGrid').innerHTML = '<div class="content-error"><strong>课程画像不可用</strong><p>请稍后重试。</p></div>';
    $('#profileRecords').innerHTML = '<p class="empty">暂无数据。</p>';
  }
}

async function loadProfileCourses(){
  const select = $('#profileCourseSelect');
  try{
    const response = await fetch('/api/courses');
    const data = await response.json();
    const courses = (data.courses || []).filter(course => course.is_public);
    select.innerHTML = courses.map(course => `<option value="${escapeHtml(course.course_id)}">${escapeHtml(course.name)}</option>`).join('');
    if(courses.some(course => course.course_id === currentProfileCourseId)) select.value = currentProfileCourseId;
    else if(select.options.length) currentProfileCourseId = select.value;
  }catch(error){
    select.innerHTML = '<option value="programming_python">Python 程序设计</option>';
  }
  select.addEventListener('change', () => {currentProfileCourseId = select.value; localStorage.setItem(PROFILE_COURSE_KEY, currentProfileCourseId); loadProfile();});
}

$('#profileEditClose').addEventListener('click', closeEditModal);
$('#profileEditCancel').addEventListener('click', closeEditModal);
$('#profileEditModal').addEventListener('click', event => {if(event.target.id === 'profileEditModal') closeEditModal();});
$('#profileEditForm').addEventListener('submit', saveCorrection);
document.addEventListener('keydown', event => {if(event.key === 'Escape' && !$('#profileEditModal').hidden) closeEditModal();});
loadProfileCourses().then(loadProfile);
