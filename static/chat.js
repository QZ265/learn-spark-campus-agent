const HISTORY_KEY = 'pylearn_chat_history_v2';
const USER_KEY = 'pylearn_user_id_v1';
const MODE_KEY = 'pylearn_answer_mode_v1';
const SIDEBAR_COLLAPSED_KEY = 'pylearn_sidebar_collapsed_v1';
const LATEST_STATE_KEY = 'pylearn_latest_learning_state_v1';
const COURSE_KEY = 'pylearn_course_id_v1';

let chatUserId = localStorage.getItem(USER_KEY);
if(!chatUserId){
  chatUserId = `student_${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(USER_KEY, chatUserId);
}

let currentConversationId = null;
let currentMode = localStorage.getItem(MODE_KEY) || 'flash';
let currentCourseId = localStorage.getItem(COURSE_KEY) || 'programming_python';
if(currentMode === 'agent') currentMode = 'flash';
let healthState = null;
let lastQuestion = '';
let isSending = false;
let promptPage = 0;
let voiceState = {
  recording: false,
  recognizing: false,
  stream: null,
  audioContext: null,
  source: null,
  processor: null,
  chunks: [],
  stopTimer: null
};
const MAX_VOICE_SECONDS = 60;

const QUICK_PROMPTS = [
  {label:'变量入门', prompt:'Python变量是什么？用一个生活类比和一段最小代码说明。'},
  {label:'if 判断', prompt:'Python的if判断怎么用？请只讲核心用法，给一个例子。'},
  {label:'项目实操', prompt:'怎么用Python做一个简单的成绩判断小项目？先给我核心思路和最小代码。'},
  {label:'输入输出', prompt:'input和print分别是什么？请用最小代码解释。'},
  {label:'循环入门', prompt:'Python的for循环怎么用？给我一个从1加到5的例子。'},
  {label:'函数参数', prompt:'函数里的参数和返回值有什么区别？用大白话解释。'},
  {label:'列表下标', prompt:'Python列表为什么从0开始？给一个简单例子。'},
  {label:'报错调试', prompt:'我看不懂Python报错，应该先看哪里？'},
  {label:'类型转换', prompt:'input得到的内容为什么要用int转换？'},
  {label:'生成路径', prompt:'请给我生成Python变量到条件判断的学习路径和练习题。'},
  {label:'复习计划', prompt:'我每天只有30分钟，请给我一个Python入门复习计划。'},
  {label:'错题本', prompt:'怎么用Python做一个简单错题本？先讲核心思路。'}
];

const COURSE_PROMPTS = {
  math_probability_statistics: [
    {label:'随机变量', prompt:'随机变量是什么？请给出严格定义和一个简单例子。'},
    {label:'正态分布', prompt:'正态分布随机变量如何标准化？请结合当前教材回答。'},
    {label:'条件概率', prompt:'条件概率和独立事件有什么区别？'},
    {label:'期望方差', prompt:'数学期望和方差分别描述什么？'},
    {label:'练习题', prompt:'根据当前课程资料给我出一道概率论基础题。'}
  ],
  politics_maogai: [
    {label:'总路线', prompt:'新民主主义革命总路线的内容是什么？请依据当前课程资料回答。'},
    {label:'核心概念', prompt:'请解释当前章节最重要的三个概念。'},
    {label:'材料题', prompt:'根据当前课程资料给我一道材料分析题。'},
    {label:'知识脉络', prompt:'帮我梳理当前课程的核心知识脉络。'},
    {label:'复习要点', prompt:'根据当前教材列出本章复习要点。'}
  ]
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value){
  return String(value || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function formatAnswer(text){
  const safe = escapeHtml(text);
  return safe
    .replace(/\[(.+?)\]\((\/resources\/[a-zA-Z0-9-]+)\)/g, '<a class="resource-link" href="$2">$1</a>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

function uid(){
  return `${Date.now().toString(36)}_${Math.random().toString(16).slice(2)}`;
}

function readHistory(){
  try{
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  }catch(e){
    return [];
  }
}

function writeHistory(list){
  localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 30)));
}

function getConversation(id){
  return readHistory().find(item => item.id === id) || null;
}

function upsertConversation(conversation){
  const list = readHistory().filter(item => item.id !== conversation.id);
  list.unshift(conversation);
  writeHistory(list);
  renderHistoryList();
}

function ensureConversation(firstMessage){
  if(currentConversationId){
    const existing = getConversation(currentConversationId);
    if(existing) return existing;
  }
  const title = firstMessage ? firstMessage.replace(/\s+/g, ' ').slice(0, 24) : '新对话';
  const conversation = {
    id: uid(),
    title,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
    profile: null,
    plan: null,
    knowledge: null
  };
  currentConversationId = conversation.id;
  upsertConversation(conversation);
  return conversation;
}

function saveLearningState(profile, plan, knowledge){
  const previous = safeJson(localStorage.getItem(LATEST_STATE_KEY), {});
  const next = {
    profile: profile || previous.profile || null,
    plan: plan || previous.plan || null,
    knowledge: knowledge || previous.knowledge || null,
    updatedAt: Date.now()
  };
  localStorage.setItem(LATEST_STATE_KEY, JSON.stringify(next));
}

function safeJson(text, fallback){
  try{
    return JSON.parse(text || '');
  }catch(e){
    return fallback;
  }
}

function saveMessage(role, text, extra = {}){
  const conversation = ensureConversation(role === 'user' ? text : lastQuestion);
  conversation.messages.push({
    role,
    text,
    mode: extra.mode || currentMode,
    citations: extra.citations || [],
    review: extra.review || null,
    createdAt: Date.now()
  });
  if(extra.profile) conversation.profile = extra.profile;
  if(extra.plan) conversation.plan = extra.plan;
  if(extra.knowledge) conversation.knowledge = extra.knowledge;
  conversation.updatedAt = Date.now();
  if(role === 'user' && conversation.messages.filter(m => m.role === 'user').length === 1){
    conversation.title = text.replace(/\s+/g, ' ').slice(0, 24) || '新对话';
  }
  upsertConversation(conversation);
}

function requestHistory(){
  const conversation = currentConversationId ? getConversation(currentConversationId) : null;
  if(!conversation || !conversation.messages) return [];
  return conversation.messages.slice(-8).map(message => ({
    role: message.role,
    content: message.text
  }));
}

function welcomeHtml(){
  return `
    <article class="message assistant">
      <div class="avatar">AI</div>
      <div class="bubble">
        <strong>你好，我是你的课程学习助手。</strong>
        <p>直接告诉我你正在学习什么，或者把遇到的问题发给我。</p>
      </div>
    </article>
  `;
}

function resetChatView(){
  $('#chatMessages').innerHTML = welcomeHtml();
}

function renderHistoryList(){
  const list = readHistory();
  const el = $('#historyList');
  if(!el) return;
  if(!list.length){
    el.classList.add('empty');
    el.textContent = '暂无历史。';
    return;
  }
  el.classList.remove('empty');
  el.innerHTML = list.map(item => {
    const active = item.id === currentConversationId ? ' active' : '';
    const time = new Date(item.updatedAt).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' });
    return `
      <button class="history-item${active}" data-id="${escapeHtml(item.id)}" type="button">
        <strong>${escapeHtml(item.title || '未命名对话')}</strong>
        <span>${escapeHtml(time)}</span>
      </button>
    `;
  }).join('');
  el.querySelectorAll('.history-item').forEach(button => {
    button.addEventListener('click', () => loadConversation(button.dataset.id));
  });
}

function renderQuickPrompts(){
  const wrap = $('#quickPrompts');
  if(!wrap) return;
  const promptSource = COURSE_PROMPTS[currentCourseId] || QUICK_PROMPTS;
  const pageSize = 5;
  const start = (promptPage * pageSize) % promptSource.length;
  const items = Array.from({length: Math.min(pageSize, promptSource.length)}).map((_, index) => promptSource[(start + index) % promptSource.length]);
  wrap.innerHTML = items.map(item => `
    <button data-prompt="${escapeHtml(item.prompt)}" type="button">${escapeHtml(item.label)}</button>
  `).join('') + '<button id="promptRefresh" class="prompt-refresh" type="button">换一组</button>';
  wrap.querySelectorAll('[data-prompt]').forEach(button => {
    button.addEventListener('click', () => sendQuestion(button.dataset.prompt));
  });
  $('#promptRefresh').addEventListener('click', () => {
    promptPage += 1;
    renderQuickPrompts();
  });
}

function loadConversation(id){
  const conversation = getConversation(id);
  if(!conversation) return;
  currentConversationId = id;
  const messages = $('#chatMessages');
  messages.innerHTML = welcomeHtml();
  conversation.messages.forEach(message => {
    if(message.role === 'user'){
      addMessage('user', `<p>${escapeHtml(message.text)}</p>`, {scroll:false});
      lastQuestion = message.text;
    }else{
      addMessage('assistant', `
        <div class="answer-meta">${escapeHtml(executionLabel({mode:message.mode}))}${message.review?.status ? ` · 审核 ${escapeHtml(message.review.status)}` : ''}</div>
        <div class="answer-content">${formatAnswer(message.text)}</div>
        ${citationDetails(message.citations)}
      `, {scroll:false});
    }
  });
  if(conversation.profile || conversation.plan || conversation.knowledge){
    saveLearningState(conversation.profile, conversation.plan, conversation.knowledge);
  }
  renderHistoryList();
  messages.scrollTo({ top: 0 });
}

function applySidebarCollapsed(){
  const collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true';
  $('#chatApp').classList.toggle('sidebar-collapsed', collapsed);
  $('#sidebarToggle').textContent = collapsed ? '›' : '‹';
  $('#sidebarToggle').title = collapsed ? '展开侧栏' : '收起侧栏';
}

function setMode(mode){
  currentMode = mode === 'spark' ? 'spark' : 'flash';
  localStorage.setItem(MODE_KEY, currentMode);
  updateModeUI();
}

function updateModeUI(){
  const configured = healthState ? healthState.mode === 'spark' : true;
  const model = healthState && healthState.model ? healthState.model : 'Spark X';
  if(currentMode === 'spark'){
    $('#chatMode').textContent = configured ? `Spark X大模型 · ${model}` : 'Spark X大模型 · 未配置';
    $('#modeHelp').textContent = '答疑由 Spark X 生成；画像、资源和审核会优先调用已发布的讯飞星辰 Workflow，失败时明确标记 fallback。';
  }else{
    $('#chatMode').textContent = 'Flash 快速模式';
    $('#modeHelp').textContent = '答疑使用本地知识库；动态画像与资源审核仍按服务配置调用真实星辰 Workflow 或明确的 fallback。';
  }
  document.querySelectorAll('.mode-option').forEach(button => {
    button.classList.toggle('active', button.dataset.mode === currentMode);
  });
  document.querySelectorAll('[data-direct-mode]').forEach(button => {
    button.classList.toggle('active', button.dataset.directMode === currentMode);
  });
}

function setSendButton(busy){
  const button = $('#chatSend');
  button.disabled = busy;
  button.innerHTML = busy ? '<span>生成中</span><b>…</b>' : '<span>发送</span><b>↑</b>';
}

function syncActiveAgent(){
  const options = Array.from(document.querySelectorAll('.agent-option[data-course]'));
  const active = options.find(option => option.dataset.course === currentCourseId);
  options.forEach(option => option.classList.toggle('active', option === active));
  const fallbackName = $('#courseSelect')?.selectedOptions?.[0]?.textContent || '课程学习 Agent';
  const name = active?.dataset.agentName || `${fallbackName} Agent`;
  const mark = active?.querySelector('.agent-avatar')?.textContent || 'AI';
  if($('#activeAgentName')) $('#activeAgentName').textContent = name;
  if(document.querySelector('.active-agent-mark')) document.querySelector('.active-agent-mark').textContent = mark;
}

function selectAgentCourse(courseId){
  const select = $('#courseSelect');
  if(!select || !Array.from(select.options).some(option => option.value === courseId)) return;
  currentCourseId = courseId;
  select.value = courseId;
  localStorage.setItem(COURSE_KEY, currentCourseId);
  currentConversationId = null;
  promptPage = 0;
  resetChatView();
  renderQuickPrompts();
  syncActiveAgent();
}

function setVoiceStatus(text, type = ''){
  const el = $('#voiceStatus');
  if(!el) return;
  el.textContent = text || '';
  el.className = `voice-status ${type}`.trim();
}

function setVoiceButton(recording, busy = false){
  const button = $('#voiceButton');
  if(!button) return;
  button.disabled = busy;
  button.classList.toggle('recording', recording);
  button.classList.toggle('recognizing', busy);
  const label = busy ? '正在识别' : (recording ? '停止录音并识别' : '语音输入');
  button.title = label;
  button.setAttribute('aria-label', label);
}

function concatAudioChunks(chunks){
  const total = chunks.reduce((sum, item) => sum + item.byteLength, 0);
  const bytes = new Uint8Array(total);
  let offset = 0;
  chunks.forEach(item => {
    bytes.set(new Uint8Array(item), offset);
    offset += item.byteLength;
  });
  return bytes.buffer;
}

function downsampleTo16k(input, sampleRate){
  const targetRate = 16000;
  const ratio = sampleRate / targetRate;
  const length = Math.max(1, Math.round(input.length / Math.max(ratio, 1)));
  const output = new Int16Array(length);
  for(let i = 0; i < length; i += 1){
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for(let j = start; j < end; j += 1){
      sum += input[j];
    }
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function stopVoiceHardware(){
  if(voiceState.stopTimer) clearTimeout(voiceState.stopTimer);
  if(voiceState.processor){
    voiceState.processor.onaudioprocess = null;
    try{ voiceState.processor.disconnect(); }catch(e){}
  }
  if(voiceState.source){
    try{ voiceState.source.disconnect(); }catch(e){}
  }
  if(voiceState.stream){
    voiceState.stream.getTracks().forEach(track => track.stop());
  }
  if(voiceState.audioContext && voiceState.audioContext.state !== 'closed'){
    voiceState.audioContext.close().catch(() => {});
  }
  voiceState.stream = null;
  voiceState.audioContext = null;
  voiceState.source = null;
  voiceState.processor = null;
  voiceState.stopTimer = null;
  voiceState.recording = false;
}

function insertRecognizedText(text){
  const input = $('#chatInput');
  if(!input) return;
  const clean = String(text || '').trim();
  if(!clean) return;
  const value = input.value || '';
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
  const needsSpace = value && start === value.length && !/\s$/.test(value);
  const insert = `${needsSpace ? ' ' : ''}${clean}`;
  input.value = `${value.slice(0, start)}${insert}${value.slice(end)}`;
  const cursor = start + insert.length;
  input.focus();
  input.setSelectionRange(cursor, cursor);
}

async function startVoiceRecording(){
  if(voiceState.recording || voiceState.recognizing) return;
  if(isSending){
    setVoiceStatus('正在生成回答，稍后再录音。', 'warn');
    return;
  }
  if(!healthState){
    await loadHealth();
  }
  if(!healthState){
    setVoiceStatus('无法连接本地服务，请确认页面是从 http://127.0.0.1:8000/chat 打开的。', 'error');
    return;
  }
  if(healthState && healthState.asr_configured === false){
    setVoiceStatus('语音识别还没配置，请先在 config_keys.env 填写讯飞语音识别三项密钥。', 'error');
    return;
  }
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    setVoiceStatus('当前浏览器不支持麦克风录音。', 'error');
    return;
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if(!AudioContextClass){
    setVoiceStatus('当前浏览器不支持音频采集。', 'error');
    return;
  }

  try{
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });
    const audioContext = new AudioContextClass();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    voiceState = {
      recording: true,
      recognizing: false,
      stream,
      audioContext,
      source,
      processor,
      chunks: [],
      stopTimer: null
    };
    processor.onaudioprocess = (event) => {
      const output = event.outputBuffer.getChannelData(0);
      output.fill(0);
      const input = event.inputBuffer.getChannelData(0);
      const pcm = downsampleTo16k(input, audioContext.sampleRate);
      voiceState.chunks.push(pcm.buffer);
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    voiceState.stopTimer = setTimeout(() => stopVoiceRecordingAndRecognize(true), MAX_VOICE_SECONDS * 1000);
    setVoiceButton(true);
    setVoiceStatus('正在录音，再点“停止”开始识别。', 'recording');
  }catch(e){
    stopVoiceHardware();
    setVoiceButton(false);
    setVoiceStatus('无法打开麦克风，请检查浏览器权限。', 'error');
  }
}

async function stopVoiceRecordingAndRecognize(autoStopped = false){
  if(!voiceState.recording || voiceState.recognizing) return;
  const chunks = voiceState.chunks.slice();
  stopVoiceHardware();
  setVoiceButton(false, true);
  voiceState.recognizing = true;

  if(!chunks.length){
    voiceState.recognizing = false;
    setVoiceButton(false);
    setVoiceStatus('没有录到声音，请再试一次。', 'warn');
    return;
  }

  const audioBuffer = concatAudioChunks(chunks);
  if(audioBuffer.byteLength < 800){
    voiceState.recognizing = false;
    setVoiceButton(false);
    setVoiceStatus('录音太短，请至少说一小句。', 'warn');
    return;
  }

  setVoiceStatus(autoStopped ? '已自动停止，正在识别。' : '正在识别。', 'working');
  try{
    const response = await fetch('/api/asr', {
      method: 'POST',
      headers: {'Content-Type': 'application/octet-stream'},
      body: audioBuffer
    });
    const data = await response.json().catch(() => ({}));
    if(!response.ok){
      throw new Error(data.detail || `语音识别失败：${response.status}`);
    }
    const text = String(data.text || '').trim();
    if(!text){
      setVoiceStatus('没有识别到文字，可以换个距离再录一次。', 'warn');
    }else{
      insertRecognizedText(text);
      setVoiceStatus('已填入输入框，你可以修改后再发送。', 'ok');
    }
  }catch(e){
    setVoiceStatus(e.message || '语音识别失败，请稍后再试。', 'error');
  }finally{
    voiceState.recognizing = false;
    setVoiceButton(false);
  }
}

function scrollToBottom(){
  const messages = $('#chatMessages');
  messages.scrollTop = messages.scrollHeight;
}

function scrollToMessageTop(messageEl){
  const messages = $('#chatMessages');
  const top = Math.max(0, messageEl.offsetTop - 18);
  messages.scrollTo({ top, behavior: 'smooth' });
}

function addMessage(role, html, options = {}){
  const messages = $('#chatMessages');
  const article = document.createElement('article');
  article.className = `message ${role}`;
  article.innerHTML = `
    <div class="avatar">${role === 'user' ? '我' : 'AI'}</div>
    <div class="bubble">${html}</div>
  `;
  messages.appendChild(article);
  if(options.scroll !== false) scrollToBottom();
  return article;
}

function createWorkingMessage(useSpark){
  const article = addMessage('assistant', `
    <div class="answer-meta">${useSpark ? 'Spark X大模型模式' : 'Flash 快速模式'}</div>
    <div class="thinking-line"><span>请求已提交，正在等待真实服务返回</span></div>
    <div class="typing-bar"><span></span><span></span><span></span></div>
  `);
  return article;
}

function executionLabel(data){
  if(String(data.mode || '').startsWith('lightrag_')) return 'LightRAG 课程检索';
  if(data.mode === 'astron') return '真实星辰 Workflow';
  if(data.mode === 'spark_fallback') return 'Spark X fallback';
  if(data.mode === 'spark') return 'Spark X 大模型';
  if(data.mode === 'blocked') return '安全拦截';
  return 'Flash 本地回答';
}

function citationDetails(citations){
  const items = Array.isArray(citations) ? citations : [];
  if(!items.length) return '';
  return `
    <details class="answer-citations">
      <summary>查看引用来源（${items.length}）</summary>
      ${items.map(item => `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>`).join('')}
    </details>`;
}

function typeAnswer(article, answer, data){
  const bubble = article.querySelector('.bubble');
  const fallbackHtml = data.mode === 'spark_fallback' ? '<p class="warn">星辰本次调用失败，已明确转为 Spark X 生成。</p>' : '';
  const reviewStatus = data.review?.status || data.verification?.status || '未审核';
  const citationHtml = citationDetails(data.citations);
  bubble.innerHTML = `
    ${fallbackHtml}
    <div class="answer-meta">${escapeHtml(executionLabel(data))} · 审核 ${escapeHtml(reviewStatus)}</div>
    <div class="answer-content">${formatAnswer(answer || '暂无回答')}</div>
    ${citationHtml}
  `;
  scrollToMessageTop(article);
}

async function loadHealth(){
  try{
    const res = await fetch('/api/health');
    healthState = await res.json();
  }catch(e){
    healthState = null;
  }
  updateModeUI();
}

async function loadCourses(){
  const select = $('#courseSelect');
  if(!select) return;
  try{
    const response = await fetch(`/api/courses?user_id=${encodeURIComponent(chatUserId)}`);
    const data = await response.json();
    const courses = Array.isArray(data.courses) ? data.courses : [];
    select.innerHTML = courses.filter(item => item.is_public).map(item =>
      `<option value="${escapeHtml(item.course_id)}">${escapeHtml(item.name)}</option>`
    ).join('');
    if(courses.some(item => item.course_id === currentCourseId && item.is_public)) select.value = currentCourseId;
    else if(select.options.length) currentCourseId = select.value;
    syncActiveAgent();
    renderQuickPrompts();
    select.addEventListener('change', () => {
      currentCourseId = select.value;
      localStorage.setItem(COURSE_KEY, currentCourseId);
      resetChatView();
      currentConversationId = null;
      promptPage = 0;
      syncActiveAgent();
      renderQuickPrompts();
    });
  }catch(e){
    select.innerHTML = '<option value="programming_python">Python 程序设计</option>';
  }
}

async function sendQuestion(message){
  if(isSending || !message.trim()) return;
  isSending = true;
  const useSpark = currentMode === 'spark';
  lastQuestion = message.trim();
  ensureConversation(lastQuestion);
  setSendButton(true);
  $('#chatInput').value = '';

  addMessage('user', `<p>${escapeHtml(lastQuestion)}</p>`);
  saveMessage('user', lastQuestion);
  const working = createWorkingMessage(useSpark);

  try{
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        user_id: chatUserId,
        message: lastQuestion,
        use_spark: useSpark,
        history: requestHistory(),
        course_id: currentCourseId
      })
    });
    if(!res.ok) throw new Error(`服务器返回 ${res.status}`);
    const data = await res.json();
    saveLearningState(data.profile, data.plan, data.knowledge_used);
    typeAnswer(working, data.answer || '暂无回答', data);
    saveMessage('assistant', data.answer || '暂无回答', {
      mode: data.mode,
      profile: data.profile,
      plan: data.plan,
      knowledge: data.knowledge_used,
      citations: data.citations,
      review: data.review
    });
  }catch(e){
    working.querySelector('.bubble').innerHTML = `
      <strong>这次没有成功生成回答。</strong>
      <p>原因：${escapeHtml(e.message || e)}</p>
      <p>请确认本地服务还在运行，或稍后再试。</p>
    `;
    scrollToMessageTop(working);
  }finally{
    isSending = false;
    setSendButton(false);
  }
}

function openModeModal(){
  $('#modeModal').hidden = false;
  updateModeUI();
}

function closeModeModal(){
  $('#modeModal').hidden = true;
}

$('#chatForm').addEventListener('submit', (event) => {
  event.preventDefault();
  sendQuestion($('#chatInput').value);
});

$('#chatInput').addEventListener('keydown', (event) => {
  if(event.key === 'Enter' && !event.shiftKey){
    event.preventDefault();
    sendQuestion($('#chatInput').value);
  }
});

$('#voiceButton').addEventListener('click', () => {
  if(voiceState.recording){
    stopVoiceRecordingAndRecognize();
  }else{
    startVoiceRecording();
  }
});

$('#newChatBtn').addEventListener('click', () => {
  currentConversationId = null;
  lastQuestion = '';
  resetChatView();
  renderHistoryList();
});

$('#sidebarToggle').addEventListener('click', () => {
  const collapsed = !$('#chatApp').classList.contains('sidebar-collapsed');
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  applySidebarCollapsed();
});

$('#modeButton').addEventListener('click', openModeModal);
$('#modeClose').addEventListener('click', closeModeModal);
$('#modeModal').addEventListener('click', (event) => {
  if(event.target.id === 'modeModal') closeModeModal();
});
document.querySelectorAll('.mode-option').forEach(button => {
  button.addEventListener('click', () => {
    setMode(button.dataset.mode);
    closeModeModal();
  });
});
document.querySelectorAll('[data-direct-mode]').forEach(button => {
  button.addEventListener('click', () => setMode(button.dataset.directMode));
});
document.querySelectorAll('.agent-option[data-course]').forEach(button => {
  button.addEventListener('click', () => selectAgentCourse(button.dataset.course));
});
document.addEventListener('keydown', (event) => {
  if(event.key === 'Escape' && !$('#modeModal').hidden) closeModeModal();
});

applySidebarCollapsed();
setMode(currentMode);
loadHealth();
loadCourses();
renderHistoryList();
renderQuickPrompts();
setInterval(() => {
  if(!isSending){
    promptPage += 1;
    renderQuickPrompts();
  }
}, 22000);

const initialQuestion = new URLSearchParams(window.location.search).get('q');
if(initialQuestion && initialQuestion.trim()){
  $('#chatInput').value = initialQuestion.trim();
  window.history.replaceState({}, '', '/chat');
  setTimeout(() => sendQuestion(initialQuestion.trim()), 300);
}
