async function loadHomeMode(){
  const el = document.getElementById('homeMode');
  if(!el) return;
  try{
    const res = await fetch('/api/health');
    const data = await res.json();
    if(data.astron_configured){
      el.textContent = `星辰 Workflow 已配置 · ${data.model}`;
    }else if(data.mode === 'spark'){
      el.textContent = `Spark X fallback · ${data.model}`;
    }else{
      el.textContent = '本地模式 · 星辰未配置';
    }
  }catch(e){
    el.textContent = '本地预览';
  }
}

loadHomeMode();
