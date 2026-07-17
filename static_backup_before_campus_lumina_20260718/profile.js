const PROFILE_USER_KEY = 'pylearn_user_id_v1';
const PROFILE_STATE_KEY = 'pylearn_latest_learning_state_v1';

const $ = (selector) => document.querySelector(selector);

const SOURCE_LABELS = {
  conversation: '学生对话',
  practice: '练习记录',
  behavior: '学习行为',
  user_correction: '用户修正',
  none: '暂无来源'
};

const STATUS_LABELS = {
  confirmed: '已确认',
  conflict: '存在冲突',
  insufficient: '等待信息'
};

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
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

function renderRecords(records){
  $('#profileRecords').innerHTML = records.map(record => {
    const confidence = Math.round(Number(record.confidence || 0) * 100);
    const statusClass = record.status === 'conflict' ? 'conflict' : record.status === 'confirmed' ? 'confirmed' : 'insufficient';
    return `
      <article class="profile-record ${statusClass}">
        <div class="profile-record-head">
          <strong>${escapeHtml(record.label)}</strong>
          <span>${escapeHtml(STATUS_LABELS[record.status] || record.status)}</span>
        </div>
        <div class="profile-record-value">${escapeHtml(displayValue(record.value))}</div>
        <dl>
          <div><dt>证据</dt><dd>${escapeHtml(record.evidence || '暂无直接证据')}</dd></div>
          <div><dt>来源</dt><dd>${escapeHtml(SOURCE_LABELS[record.source_type] || record.source_type)}</dd></div>
          <div><dt>置信度</dt><dd>${record.status === 'insufficient' ? '尚未确认' : `${confidence}%`}</dd></div>
          <div><dt>更新时间</dt><dd>${escapeHtml(displayTime(record.updated_at))}</dd></div>
        </dl>
      </article>
    `;
  }).join('');
}

function renderChanges(changes, labels){
  $('#profileChanges').innerHTML = changes.length ? changes.map(change => {
    const oldValue = change.old_record ? displayValue(change.old_record.value) : '首次记录';
    const newValue = displayValue(change.new_record.value);
    return `
      <div class="profile-change">
        <strong>${escapeHtml(labels[change.field] || change.field)}</strong>
        <span>${escapeHtml(oldValue)} → ${escapeHtml(newValue)}</span>
        <small>${escapeHtml(displayTime(change.created_at))} · ${escapeHtml(change.reason)}</small>
      </div>
    `;
  }).join('') : '<p class="empty">暂无画像变化。</p>';
}

function renderMissing(missingFields, labels){
  $('#profileMissing').innerHTML = missingFields.length
    ? missingFields.map(field => `<span>${escapeHtml(labels[field] || field)} · 尚未确认</span>`).join('')
    : '<p class="empty">当前字段均已有证据。</p>';
}

function renderProfile(snapshot){
  const records = snapshot.records || [];
  const labels = Object.fromEntries(records.map(record => [record.field, record.label]));
  const confirmed = records.filter(record => record.status === 'confirmed').length;
  const conflict = records.filter(record => record.status === 'conflict').length;
  $('#profileSummary').innerHTML = `
    <strong>${confirmed} 项已有证据</strong>
    <span>${conflict ? `${conflict} 项存在冲突 · ` : ''}${snapshot.missing_fields?.length || 0} 项等待学习记录</span>
  `;
  renderRecords(records);
  renderChanges(snapshot.changes || [], labels);
  renderMissing(snapshot.missing_fields || [], labels);
}

async function hydrate(){
  const userId = localStorage.getItem(PROFILE_USER_KEY) || 'demo_student';
  try{
    const response = await fetch('/api/profile', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({user_id:userId})
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

hydrate();
