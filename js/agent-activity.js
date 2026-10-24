/* Actual execution milestones, plus owner-scoped research collections. */
(() => {
  'use strict';
  const api=window.CrawlerServer, e=value=>esc(String(value ?? ''));
  let busy=false, nextAt=0, boardId='', failures=0, feed=null, personal=null, personalAt=0, organizationAt=0;
  const taskName=kind=>({'topic-research':'Topic research','recommendation-review':'Recommendation assessment','network-index':'Evidence mapping','network-research':'Branch investigation','agent-organize':'Research organization'}[kind] || kind.replaceAll('-',' '));
  const running=task=>!['Complete','Failed','Cancelled','Paused'].includes(task.status);
  const time=at=>at?new Date(at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
  function progress(value, label='Task progress') {
    const measured=Number(value?.percent);const percent=Number.isFinite(measured)?Math.min(100,Math.max(0,measured)):0;
    return `<div class="agent-progress"><div><span>${e(value?.stage || 'Waiting for a worker')}</span><strong>${percent}%</strong></div><progress max="100" value="${percent}" aria-label="${e(label)}"></progress><small>Completed research stages · not a time estimate or confidence score</small></div>`;
  }
  function render() {
    const host=document.getElementById('agent-activity');if(!host)return;
    const open=new Set([...host.querySelectorAll('details[open]')].map(el=>el.dataset.task));
    const tasks=feed?.tasks || [], active=tasks.filter(running), completed=tasks.filter(t=>!running(t));
    host.innerHTML=`<header><div><span class="network-kicker">LIVE RESEARCH LOG</span><h2>At work on your topic</h2></div><span class="agent-live ${active.length?'working':''}">${!api.connected?'Offline':active.length?'Working':'Monitoring'}</span></header><p class="agent-explainer">Source checks, calculations and saved results from the research workers.</p><div class="agent-task-list">${[...active.slice(0,4),...completed.slice(0,3)].map(task=>`<details class="agent-task" data-task="${e(task.id)}"${open.has(task.id)||active[0]?.id===task.id?' open':''}><summary><span>${e(taskName(task.kind))}</span><small>${e(task.status)} · ${task.percent}%</small></summary>${progress(task)}<ol>${task.events.slice(-8).map(event=>`<li><time>${time(event.at)}</time><span>${e(event.message)}${event.detail?`<small>${e(event.detail)}</small>`:''}${event.totalItems!=null?`<small>${event.completedItems} of ${event.totalItems} assets assessed</small>`:''}</span></li>`).join('')}</ol>${task.status==='Complete'?'<p class="agent-completion">✓ Research step finished. Review its results and evidence status.</p>':''}</details>`).join('') || '<p class="agent-idle">No active task. The board is ready for you to choose a research direction. Scheduled collection continues on the server.</p>'}</div><div class="agent-controls"><button data-agent-organize>Organize research</button><button data-agent-policy="${feed?.organizationPolicy?.enabled===false?'true':'false'}">${feed?.organizationPolicy?.enabled===false?'Enable':'Pause'} organization</button></div><p id="agent-feedback" class="agent-note" role="status">${!api.connected?'Connection interrupted. Last reported progress is retained.':feed?.organizationPolicy?.enabled===false?'Automatic watchlists, monitors and tags are paused.':'Agents can organize cited articles and verified assets. Every change has an audit entry and undo.'}</p>`;
  }
  async function poll(force=false) {
    const id=window.CrawlerNetwork?.detail?.board?.id;
    if(!id||document.body.dataset.experience!=='topic'||document.hidden||busy||!api.connected||api.busy)return;
    if(id!==boardId){boardId=id;feed=null;nextAt=0;render();}
    if(!force&&Date.now()<nextAt)return;
    busy=true;
    try {
      const value=await api.request('research-activity?boardId='+encodeURIComponent(id));
      if(window.CrawlerNetwork?.detail?.board?.id!==id)return;
      feed=value;failures=0;nextAt=Date.now()+(value.tasks.some(running)?4000:15000);render();
      const organized=value.tasks.find(task=>task.kind==='agent-organize'&&task.status==='Complete');
      if(organized?.updatedAt>organizationAt){organizationAt=organized.updatedAt;loadPersonal(true);}
      const recommendation=value.tasks.find(task=>task.kind==='recommendation-review');
      const target=document.getElementById('recommendation-progress');if(target&&recommendation)target.innerHTML=progress(recommendation,'Recommendation assessment progress');
    }catch(error){failures++;nextAt=Date.now()+Math.max(error.retryAfterMs||0,Math.min(60000,5000*2**failures));const target=document.getElementById('agent-feedback');if(target)target.textContent='Activity updates delayed. Last reported progress is retained; retrying automatically.';}
    finally{busy=false;}
  }
  function tags(documentId, version) {
    return (personal?.articleTags||[]).filter(t=>t.documentId===documentId && (!version || t.version===version)).map(t=>`<span class="tag agent-article-tag" title="${e(t.topic)}">${e(t.tag)}</span>`).join('');
  }
  function renderCollections() {
    let host=document.getElementById('agent-collections');
    if(!host&&document.getElementById('server-watchlist')){host=document.createElement('section');host.id='agent-collections';host.className='research-box';document.getElementById('server-watchlist').before(host);}
    if(!host||!personal)return;
    host.innerHTML=`<div class="hub-section-heading"><div><span class="eyebrow">ORGANIZED BY YOUR RESEARCH AGENTS</span><h2>Reading lists & evidence monitors</h2></div></div><p class="dim sm">Created from collected source records and your watch portfolios. Asset favorites are research interests; holdings and trades are not inferred.</p><div class="agent-collection-grid">${(personal.watchlists||[]).map(list=>`<details class="agent-reading-list"><summary>${e(list.title)} <span>${list.articles.length} saved articles${list.matchedCount>list.articles.length?' / '+list.matchedCount+' matches':''}</span></summary>${list.articles.map(doc=>`<article><a href="${e(safeURL(doc.url))}" target="_blank" rel="noopener noreferrer">${e(doc.title)}</a><small>${e(doc.source)} · ${e(doc.reason)} · source v${doc.version}</small></article>`).join('')||'<p>No current source matches.</p>'}</details>`).join('')||'<p class="dim sm">Use “Organize research” beside an observation board to create a sourced reading list.</p>'}</div><details class="agent-monitor-list"><summary>Agent evidence monitors · ${(personal.monitors||[]).length}</summary>${(personal.monitors||[]).map(m=>`<div><b>${e(m.query)}</b><span>${(m.effectiveEnabled ?? m.enabled)?'Active':'Paused'} · ${m.matches.length} source matches · ${m.assetIds.length} assets</span><p>${e(m.rule)}</p><button data-agent-board="${e(m.boardId)}">Open board & controls ↗</button></div>`).join('')}</details><details class="agent-audit"><summary>Agent action audit · latest ${(personal.agentActions||[]).length}</summary>${(personal.agentActions||[]).map(a=>`<article><div><b>${e(a.reason)}</b><small>${new Date(a.at).toLocaleString()} · ${a.evidence.length} cited source versions</small><small>Audit ${e(a.auditHash.slice(0,16))}…</small></div><button data-agent-undo="${e(a.id)}"${a.undone?' disabled':''}>${a.undone?'Undone':'Undo'}</button></article>`).join('')||'<p>No agent changes yet.</p>'}</details><p id="agent-collection-feedback" role="status"></p>`;
  }
  async function loadPersonal(force=false) {
    if(!api.connected||api.busy||document.hidden||(!force&&Date.now()-personalAt<60000))return;
    personalAt=Date.now();
    try {personal=await api.request('my-research');window.CrawlerNetwork?.setPersonal(personal);renderCollections();if(document.body.dataset.destination==='reporting')renderNews(true);if(document.body.dataset.destination==='activity')renderStream();}
    catch(error){personalAt=0;}
  }
  window.addEventListener('crawler:board-ready',()=>{render();poll();});
  window.addEventListener('crawler:personal-data',event=>{personal=event.detail;personalAt=Date.now();renderCollections();});
  window.addEventListener('crawler:server-state',()=>{if(!api.connected){render();return;}poll();if(['watchlist','reporting','activity'].includes(document.body.dataset.destination))loadPersonal();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();loadPersonal();}});
  document.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(['watchlist','reporting','activity'].includes(button.dataset.destination)){loadPersonal();return;}
    if(button.dataset.agentBoard){window.CrawlerNetwork.openBoard(button.dataset.agentBoard);return;}
    if(!button.matches('[data-agent-organize],[data-agent-policy],[data-agent-undo]'))return;
    button.disabled=true;
    try {
      if(button.hasAttribute('data-agent-organize')){const value=await api.request('agent/organize',{boardId});if(!value.queued)throw new Error(value.message);nextAt=0;await poll(true);}
      if(button.hasAttribute('data-agent-policy')){await api.request('agent/policy',{boardId,enabled:button.dataset.agentPolicy==='true'});nextAt=0;await poll(true);}
      if(button.dataset.agentUndo){await api.request('agent/undo',{actionId:button.dataset.agentUndo});await loadPersonal(true);}
    }catch(error){const target=document.getElementById(button.dataset.agentUndo?'agent-collection-feedback':'agent-feedback');if(target)target.textContent=error.message;}
    finally{if(button.isConnected)button.disabled=false;}
  });
  setInterval(()=>{poll();if(['watchlist','reporting','activity'].includes(document.body.dataset.destination))loadPersonal();},4000);
  window.CrawlerActivity={progress,tags,refresh:poll};
})();
