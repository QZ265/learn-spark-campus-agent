const TYPE_NAMES={explanation:'讲解文档',mindmap:'思维导图',quiz:'练习题',code_case:'代码案例',further_reading:'拓展阅读'};
const MODE_NAMES={astron:'星辰 Workflow',spark_fallback:'Spark X fallback',failed:'生成失败'};
const FAVORITES_KEY='campus_resource_favorites_v1';
let resources=[],courses=[];
const $=selector=>document.querySelector(selector);
function escapeHtml(value){return String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function readFavorites(){try{return new Set(JSON.parse(localStorage.getItem(FAVORITES_KEY)||'[]'));}catch(error){return new Set();}}
function saveFavorites(values){localStorage.setItem(FAVORITES_KEY,JSON.stringify([...values]));}
function formatTime(value){if(!value)return '未知时间';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString('zh-CN');}
function courseName(id){return courses.find(course=>course.course_id===id)?.name||id||'未关联课程';}

function render(){
  const course=$('#resourceCourseFilter').value,mode=$('#resourceAgentFilter').value,type=$('#resourceTypeFilter').value,query=$('#resourceSearch').value.trim().toLowerCase(),favorites=readFavorites();
  const filtered=resources.filter(item=>(!course||item.course_id===course)&&(!mode||item.agent_mode===mode)&&(!type||item.type===type)&&(!query||String(item.title).toLowerCase().includes(query)));
  $('#resourceCount').textContent=`${filtered.length} 项资源`;
  const state=$('#resourceCenterState');
  if(!filtered.length){state.className='resource-center-grid';state.innerHTML='<div class="content-empty resource-empty"><span>▤</span><strong>暂无符合条件的资源</strong><p>资源需要在智能 Agent 对话中真实生成并通过审核后才会出现在这里。</p><a href="/chat">进入智能 Agent</a></div>';return;}
  state.className='resource-center-grid';state.innerHTML=filtered.map(item=>`<article class="resource-center-card"><div class="resource-card-top"><span class="resource-type-icon type-${escapeHtml(item.type)}">${escapeHtml((TYPE_NAMES[item.type]||'资源').slice(0,2))}</span><button class="favorite-button${favorites.has(item.id)?' active':''}" data-favorite="${escapeHtml(item.id)}" type="button" title="${favorites.has(item.id)?'取消收藏':'收藏'}">☆</button></div><div class="resource-card-body"><span>${escapeHtml(courseName(item.course_id))} · ${escapeHtml(TYPE_NAMES[item.type]||item.type)}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(MODE_NAMES[item.agent_mode]||item.agent_mode||'生成方式未知')} · ${escapeHtml(formatTime(item.created_at))}</p></div><div class="resource-card-meta"><span class="review-state ${escapeHtml(item.review_status)}">${escapeHtml(item.review_status||'未审核')}</span><span>${Array.isArray(item.citations)?item.citations.length:0} 条引用</span></div><div class="resource-card-actions"><a href="/resources/${encodeURIComponent(item.id)}">打开资源</a><button type="button" disabled title="等待后端提供资源删除接口">删除</button></div></article>`).join('');
  state.querySelectorAll('[data-favorite]').forEach(button=>button.addEventListener('click',()=>{const values=readFavorites();values.has(button.dataset.favorite)?values.delete(button.dataset.favorite):values.add(button.dataset.favorite);saveFavorites(values);render();}));
}

async function hydrate(){
  try{
    const userId=window.CampusStore.getUserId();
    const [courseResponse,resourceResponse]=await Promise.all([fetch(`/api/courses?user_id=${encodeURIComponent(userId)}`),fetch(`/api/resources?user_id=${encodeURIComponent(userId)}`)]);
    if(!courseResponse.ok||!resourceResponse.ok)throw new Error('资源接口请求失败');
    const courseData=await courseResponse.json(),resourceData=await resourceResponse.json();courses=courseData.courses||[];resources=resourceData.resources||[];
    $('#resourceCourseFilter').innerHTML='<option value="">全部课程</option>'+courses.map(item=>`<option value="${escapeHtml(item.course_id)}">${escapeHtml(item.name)}</option>`).join('');render();
  }catch(error){$('#resourceCount').textContent='加载失败';$('#resourceCenterState').innerHTML=`<div class="content-error"><strong>资源读取失败</strong><p>${escapeHtml(error.message)}</p><button type="button" id="resourceRetry">重新加载</button></div>`;$('#resourceRetry').addEventListener('click',hydrate);}
}
['resourceCourseFilter','resourceAgentFilter','resourceTypeFilter'].forEach(id=>document.getElementById(id).addEventListener('change',render));$('#resourceSearch').addEventListener('input',render);hydrate();
