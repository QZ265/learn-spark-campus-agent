(function(){
  const SETTINGS_KEY = 'campus_lumina_settings_v1';
  const PLAN_KEY = 'campus_lumina_plan_v1';
  const USER_KEY = 'pylearn_user_id_v1';
  const ACCENTS = {indigo:'#5267c9', teal:'#249f91', orange:'#e77d4f'};
  const defaults = {
    profile:{avatar:'',nickname:'',name:'',major:'',grade:'',school:'',bio:''},
    appearance:{mode:'system',accent:'indigo',fontSize:'medium',density:'comfortable'},
    ai:{detail:'concise',explainOrder:'concept',orientation:'balanced',preferCode:false,stepByStep:true,requireCitations:true,customInstruction:''}
  };

  function mergeSettings(value){
    const source = value && typeof value === 'object' ? value : {};
    return {
      profile:{...defaults.profile,...(source.profile || {})},
      appearance:{...defaults.appearance,...(source.appearance || {})},
      ai:{...defaults.ai,...(source.ai || {})}
    };
  }

  function getSettings(){
    try{return mergeSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'));}
    catch(error){return mergeSettings({});}
  }

  function saveSettings(settings){
    const normalized = mergeSettings(settings);
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
    applyAppearance(normalized.appearance);
    hydrateIdentity(normalized.profile);
    window.dispatchEvent(new CustomEvent('campus:settings', {detail:normalized}));
    return normalized;
  }

  function getPlan(){
    try{
      const value = JSON.parse(localStorage.getItem(PLAN_KEY) || '{}');
      return {classes:Array.isArray(value.classes) ? value.classes : [], tasks:Array.isArray(value.tasks) ? value.tasks : []};
    }catch(error){return {classes:[],tasks:[]};}
  }

  function savePlan(plan){
    const normalized = {classes:Array.isArray(plan.classes) ? plan.classes : [],tasks:Array.isArray(plan.tasks) ? plan.tasks : []};
    localStorage.setItem(PLAN_KEY, JSON.stringify(normalized));
    window.dispatchEvent(new CustomEvent('campus:plan', {detail:normalized}));
    return normalized;
  }

  function getUserId(){
    let userId = localStorage.getItem(USER_KEY);
    if(!userId){userId = `student_${Math.random().toString(16).slice(2)}`;localStorage.setItem(USER_KEY,userId);}
    return userId;
  }

  function resolvedTheme(mode){
    if(mode !== 'system') return mode;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyAppearance(appearance){
    const value = {...defaults.appearance,...(appearance || {})};
    document.documentElement.dataset.theme = resolvedTheme(value.mode);
    document.documentElement.dataset.accent = value.accent;
    document.documentElement.dataset.fontSize = value.fontSize;
    document.documentElement.dataset.density = value.density;
    document.documentElement.style.setProperty('--lumina-indigo', ACCENTS[value.accent] || ACCENTS.indigo);
  }

  function hydrateIdentity(profile){
    const displayName = profile.nickname || profile.name || '同学';
    const initial = displayName.trim().slice(0,1) || '学';
    document.querySelectorAll('[data-user-name]').forEach(element => {element.textContent = displayName;});
    document.querySelectorAll('[data-user-initial]').forEach(element => {element.textContent = initial;});
    document.querySelectorAll('[data-user-avatar]').forEach(element => {
      if(profile.avatar){element.style.backgroundImage = `url("${String(profile.avatar).replace(/["\\]/g,'')}")`;element.classList.add('has-image');}
      else{element.style.backgroundImage = '';element.classList.remove('has-image');}
    });
  }

  function initMobileNavigation(){
    const sidebar = document.querySelector('.lumina-sidebar');
    const nav = sidebar?.querySelector('.lumina-nav');
    if(!sidebar || !nav || sidebar.querySelector('.mobile-nav-toggle')) return;
    const button = document.createElement('button');
    button.className = 'mobile-nav-toggle';
    button.type = 'button';
    button.title = '展开导航';
    button.setAttribute('aria-label','展开导航');
    button.setAttribute('aria-expanded','false');
    button.innerHTML = '<span></span><span></span><span></span>';
    button.addEventListener('click', () => {
      const open = sidebar.classList.toggle('nav-open');
      button.setAttribute('aria-expanded', String(open));
      button.title = open ? '收起导航' : '展开导航';
      button.setAttribute('aria-label', open ? '收起导航' : '展开导航');
    });
    sidebar.appendChild(button);
  }

  const api = {SETTINGS_KEY,PLAN_KEY,getSettings,saveSettings,getPlan,savePlan,getUserId,applyAppearance};
  window.CampusStore = api;
  const settings = getSettings();
  applyAppearance(settings.appearance);
  document.addEventListener('DOMContentLoaded', () => {hydrateIdentity(settings.profile);initMobileNavigation();});
  if(window.matchMedia){window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{const current=getSettings();if(current.appearance.mode==='system')applyAppearance(current.appearance);});}
})();
