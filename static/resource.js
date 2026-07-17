const $ = (selector) => document.querySelector(selector);

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function codeBlock(code){
  return `<pre><code>${escapeHtml(code)}</code></pre>`;
}

function renderContent(resource){
  const content = resource.content || {};
  if(resource.type === 'explanation') return `<article class="generated-document">${content.html || codeBlock(content.markdown || '')}</article>`;
  if(resource.type === 'mindmap') return `
    <div id="mermaidCanvas" class="mermaid-canvas"><pre class="mermaid">${escapeHtml(content.mermaid || '')}</pre></div>
    <details><summary>查看 Mermaid 源码</summary>${codeBlock(content.mermaid || '')}</details>`;
  if(resource.type === 'quiz') return `<div class="quiz-list">${(content.questions || []).map((item, index) => `
    <article class="quiz-item">
      <span>${escapeHtml(item.difficulty)} · ${escapeHtml(item.knowledge_point)}</span>
      <h3>${index + 1}. ${escapeHtml(item.question)}</h3>
      <details><summary>查看答案与解析</summary><strong>${escapeHtml(item.answer)}</strong><p>${escapeHtml(item.explanation)}</p></details>
    </article>`).join('')}</div>`;
  if(resource.type === 'code_case') return `
    <article class="code-case">
      <h2>初始代码</h2>${codeBlock(content.initial_code)}
      <h2>任务</h2><p>${escapeHtml(content.task)}</p>
      <h2>测试</h2>${codeBlock(content.tests)}
      <details><summary>查看参考答案</summary>${codeBlock(content.reference_answer)}</details>
    </article>`;
  if(resource.type === 'further_reading') return `<div class="reading-list">${(content.items || []).map(item => `
    <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">
      <strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.reason)}</span>
    </a>`).join('')}</div>`;
  return codeBlock(JSON.stringify(content, null, 2));
}

async function renderMermaid(){
  const element = document.querySelector('.mermaid');
  if(!element) return;
  try{
    const module = await import('https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs');
    module.default.initialize({startOnLoad:false, securityLevel:'strict', theme:'neutral'});
    await module.default.run({nodes:[element]});
  }catch(error){
    $('#mermaidCanvas').classList.add('render-failed');
  }
}

function renderResource(resource){
  $('#resourceHeader').innerHTML = `
    <div><span class="badge">${escapeHtml(resource.type)}</span><h1>${escapeHtml(resource.title)}</h1></div>
    <div class="review-badge ${escapeHtml(resource.review_status)}">${escapeHtml(resource.review_status)}</div>`;
  $('#resourceContent').innerHTML = renderContent(resource);
  $('#profileBasis').innerHTML = resource.profile_basis?.length
    ? `<ul>${resource.profile_basis.map(item => `<li><strong>${escapeHtml(item.label)}</strong>：${escapeHtml(Array.isArray(item.value) ? item.value.join('、') : item.value)}<small>证据：${escapeHtml(item.evidence)}</small></li>`).join('')}</ul>`
    : '<p class="empty">画像证据不足，本资源按当前问题使用通用难度生成。</p>';
  $('#citationList').innerHTML = resource.citations?.length
    ? resource.citations.map(item => `<a class="citation-item" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.publisher)}</span></a>`).join('')
    : '<p class="empty">知识库暂无可靠依据。</p>';
  const issues = resource.review?.issues || [];
  $('#reviewResult').innerHTML = `<p class="review-line"><strong>审核状态：</strong>${escapeHtml(resource.review_status)}</p>${issues.length ? `<ul>${issues.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}`;
  renderMermaid();
}

async function hydrate(){
  const resourceId = location.pathname.split('/').filter(Boolean).pop();
  try{
    const response = await fetch(`/api/resources/${encodeURIComponent(resourceId)}`);
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    renderResource(data);
  }catch(error){
    $('#resourceHeader').innerHTML = `<h1>资源无法打开</h1><p>${escapeHtml(error.message)}</p>`;
    $('#resourceContent').innerHTML = '';
  }
}

hydrate();
