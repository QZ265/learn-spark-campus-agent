const PROFILE_USER_KEY = 'pylearn_user_id_v1';
const PROFILE_STATE_KEY = 'pylearn_latest_learning_state_v1';
const PROFILE_COURSE_KEY = 'pylearn_course_id_v1';

const $ = selector => document.querySelector(selector);
let currentProfileCourseId = localStorage.getItem(PROFILE_COURSE_KEY) || 'programming_python';

const SOURCE_LABELS = {
  conversation:'学生对话', practice:'练习记录', behavior:'学习行为',
  user_correction:'用户修正', none:'暂无来源'
};

const STATUS_LABELS = {confirmed:'已确认', conflict:'存在冲突', insufficient:'等待信息'};

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
}

function displayValue(value){
  if(Array.isArray(value)) return value.length ? value.join('、') : '等待学习记录';
  return value || '暂无信息';
}

function displayTime(value){
  if(!value) return '尚未更新';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}

function recordValue(record, fallback = '尚未确认'){
  if(!record || record.status === 'insufficient') return fallback;
  return displayValue(record.value);
}

function renderDimensions(snapshot){
  const records = snapshot.record_map || {};
  const mastered = recordValue(records.mastered, '等待学习记录');
  const unmastered = recordValue(records.unmastered, '');
  const foundation = mastered === '等待学习记录'
    ? mastered
    : `${mastered}${unmastered ? `；待巩固：${unmastered}` : ''}`;
  const goal = recordValue(records.learning_goal, '尚未确认');
  const dailyTime = recordValue(records.daily_time, '');
  const preference = recordValue(records.learning_preference, '尚未确认');
  const errors = recordValue(records.common_errors, '等待练习记录');
  const course = recordValue(records.current_course, '课程章节尚未确认');
  const state = recordValue(records.learning_state, '等待学习记录');
  const dimensions = [
    ['01','知识基础',foundation],
    ['02','学习目标',`${goal}${dailyTime ? `；可投入：${dailyTime}` : ''}`],
    ['03','认知风格',preference === '尚未确认' ? '尚未确认，需学生明确说明理解方式' : `明确学习偏好：${preference}`],
    ['04','易错点',errors],
    ['05','资源偏好',preference],
    ['06','学习记录',`${course}；${state}`]
  ];
  $('#profileDimensions').innerHTML = dimensions.map(([number, label, value]) => `
    <article class="profile-dimension-card${value.includes('尚未确认') || value.includes('等待') ? ' waiting' : ''}">
      <span>${number}</span><div><strong>${escapeHtml(label)}</strong><p>${escapeHtml(value)}</p></div>
    </article>
  `).join('');

  $('#answerStrategy').textContent = preference === '尚未确认'
    ? '简单问题先直接回答，不推测表达偏好。'
    : `优先遵循已确认偏好：${preference}。`;
  $('#resourceStrategy').textContent = errors === '等待练习记录'
    ? '先补充练习证据，再决定强化资源。'
    : `围绕易错点生成针对性资源：${errors}。`;
  $('#contextStrategy').textContent = `${course}范围内保留最近对话与学习记录。`;
}

function renderRecords(records){
  $('#profileRecords').innerHTML = records.map(record => {
    const confidence = Math.round(Number(record.confidence || 0) * 100);
    const statusClass = record.status === 'conflict' ? 'conflict' : record.status === 'confirmed' ? 'confirmed' : 'insufficient';
    return `
      <details class="profile-record ${statusClass}"${record.status === 'conflict' ? ' open' : ''}>
        <summary>
          <span><strong>${escapeHtml(record.label)}</strong><small>${escapeHtml(displayValue(record.value))}</small></span>
          <b>${escapeHtml(STATUS_LABELS[record.status] || record.status)}</b>
        </summary>
        <dl>
          <div><dt>证据</dt><dd>${escapeHtml(record.evidence || '暂无直接证据')}</dd></div>
          <div><dt>来源</dt><dd>${escapeHtml(SOURCE_LABELS[record.source_type] || record.source_type)}</dd></div>
          <div><dt>抽取置信度</dt><dd>${record.status === 'insufficient' ? '尚未确认' : `${confidence}%`}</dd></div>
          <div><dt>更新时间</dt><dd>${escapeHtml(displayTime(record.updated_at))}</dd></div>
        </dl>
      </details>
    `;
  }).join('');
}

function renderChanges(changes, labels){
  $('#profileChanges').innerHTML = changes.length ? changes.map(change => {
    const oldValue = change.old_record ? displayValue(change.old_record.value) : '首次记录';
    const newValue = displayValue(change.new_record.value);
    return `<div class="profile-change"><span></span><p><strong>${escapeHtml(labels[change.field] || change.field)}</strong><b>${escapeHtml(oldValue)} → ${escapeHtml(newValue)}</b><small>${escapeHtml(displayTime(change.created_at))} · ${escapeHtml(change.reason)}</small></p></div>`;
  }).join('') : '<p class="empty">暂无画像变化。</p>';
}

function renderMissing(missingFields, labels){
  $('#profileMissing').innerHTML = missingFields.length
    ? missingFields.map(field => `<span>${escapeHtml(labels[field] || field)}<small>尚未确认</small></span>`).join('')
    : '<p class="empty">当前字段均已有直接证据。</p>';
}

function renderProfile(snapshot){
  const records = snapshot.records || [];
  const labels = Object.fromEntries(records.map(record => [record.field, record.label]));
  const confirmed = records.filter(record => record.status === 'confirmed').length;
  const conflict = records.filter(record => record.status === 'conflict').length;
  $('#profileSummary').innerHTML = `<strong>${confirmed} 项已有证据</strong><span>${conflict ? `${conflict} 项存在冲突 · ` : ''}${snapshot.missing_fields?.length || 0} 项等待学习记录</span>`;
  renderDimensions(snapshot);
  renderRecords(records);
  renderChanges(snapshot.changes || [], labels);
  renderMissing(snapshot.missing_fields || [], labels);
}

async function loadProfile(){
  const userId = localStorage.getItem(PROFILE_USER_KEY) || 'demo_student';
  try{
    const response = await fetch('/api/profile', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:userId, course_id:currentProfileCourseId})
    });
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot = await response.json();
    localStorage.setItem(PROFILE_STATE_KEY, JSON.stringify({profile:snapshot, updatedAt:Date.now()}));
    renderProfile(snapshot);
  }catch(error){
    $('#profileSummary').innerHTML = '<strong>画像加载失败</strong><span>请确认后端服务已启动。</span>';
    $('#profileRecords').innerHTML = '<p class="empty">暂时无法读取画像。</p>';
    $('#profileChanges').innerHTML = '<p class="empty">暂无数据。</p>';
    $('#profileMissing').innerHTML = '<p class="empty">暂无数据。</p>';
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
    select.addEventListener('change', () => {
      currentProfileCourseId = select.value;
      localStorage.setItem(PROFILE_COURSE_KEY, currentProfileCourseId);
      loadProfile();
    });
  }catch(error){
    select.innerHTML = '<option value="programming_python">Python 程序设计</option>';
  }
}

loadProfileCourses().then(loadProfile);
