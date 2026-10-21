/* On-demand source directory. No feed requests or archive hydration on the landing page. */
(() => {
  'use strict';
  const api = window.CrawlerServer;
  const roles = {reporting:'Reporting',primary:'Official releases',commentary:'Commentary',survey:'Surveys & polls',community:'Public discussions',discovery:'Discovery links',marketdata:'Market data'};
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = value => value ? new Date(value).toLocaleString() : 'Not checked yet';
  let dialog, rows = [], limit = 12, refreshing = null, selected = '', previewToken = 0;
  function state(s) {
    if (!s.enabled) return 'Paused';
    if (!s.health) return 'Awaiting first poll';
    if (!s.health.ok) return 'Unavailable';
    if (s.health.status === 'empty') return 'Connected · no usable entries';
    return s.health.totalItems ? 'Collecting' : 'Connected';
  }
  function mount() {
    if (dialog) return;
    dialog = document.createElement('dialog'); dialog.id = 'source-directory'; dialog.setAttribute('aria-labelledby','source-directory-title');
    dialog.innerHTML = `<header><div><span class="source-eyebrow">RESEARCH INPUTS</span><h2 id="source-directory-title">Your sources</h2></div><button data-source-close aria-label="Close sources">Close</button></header>
      <p>See what each connection contributes. Reporting, opinions, survey findings and public discussion remain clearly attributed.</p>
      <div class="source-directory-tools"><label>Find a source<input type="search" id="source-search" placeholder="Publisher, topic or journalist…"></label><label>Type<select id="source-role"><option value="">All types</option>${Object.entries(roles).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>Connection<select id="source-status"><option value="">All connections</option><option value="working">Collecting / connected</option><option value="unavailable">Unavailable</option><option value="paused">Paused</option></select></label></div>
      <div class="source-directory-actions"><span id="source-summary"></span><button data-source-refresh>Refresh status</button><button data-source-poll-all>Poll enabled sources</button><button data-source-add>Add a feed</button></div>
      <p id="source-directory-feedback" role="status" aria-live="polite"></p>
      <form id="source-quick-add" hidden><h3>Connect a public RSS or Atom feed</h3><label>Name<input name="name" required maxlength="120"></label><label>HTTPS feed address<input name="url" type="url" placeholder="https://publisher.example/feed" required></label><label>Content type<select name="contentRole">${Object.entries(roles).filter(([k])=>k!=='marketdata').map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>Language<input name="language" value="en" maxlength="20"></label><p>Collection uses publisher-supplied feed text. Private chats, login-only forums and subscriber articles require an authorized provider connection.</p><button>Add & poll feed</button><button type="button" data-source-add>Cancel</button></form>
      <div class="source-directory-body"><div><div id="source-cards"></div><button data-source-more hidden>Show more sources</button></div><aside id="source-preview" aria-live="polite"><h3>Inspect a source</h3><p>Select “Collected items” to see its latest contributions, links and publication dates.</p><p>Discovery and community feeds supply research leads. Structured prices and financial observations come from market data connectors.</p></aside></div>`;
    document.body.append(dialog);
    for (const id of ['source-search','source-role','source-status']) dialog.querySelector('#'+id).addEventListener(id==='source-search'?'input':'change',()=>{limit=12;render();});
    dialog.addEventListener('close',()=>{previewToken++; selected='';});
    dialog.addEventListener('click', async event => {
      const b=event.target.closest('button'); if(!b) return;
      try {
        if(b.hasAttribute('data-source-close')) {dialog.close();return;}
        if(b.hasAttribute('data-source-more')) {limit+=12;render();return;}
        if(b.hasAttribute('data-source-add')) {const form=dialog.querySelector('#source-quick-add');form.hidden=!form.hidden;if(!form.hidden)form.querySelector('input').focus();return;}
        if(b.hasAttribute('data-source-refresh')) {await refresh();return;}
        if(b.dataset.sourcePreview) {await preview(b.dataset.sourcePreview);return;}
        if(b.dataset.sourceEdit) {const source=rows.find(s=>s.id===b.dataset.sourceEdit);dialog.close();window.CrawlerHub.editSource(source);return;}
        b.disabled=true;
        if(b.hasAttribute('data-source-poll-all')) {
          const result=await api.request('sources/poll-all',{});
          feedback(`${result.jobIds.length} enabled sources queued. Collection runs in the background and respects provider cooldowns.`);
        }
        if(b.dataset.sourcePoll) {await api.request('sources/poll',{id:b.dataset.sourcePoll});feedback('Poll queued. An existing queued poll or provider cooldown is preserved.');}
        if(b.dataset.sourceToggle) {const source=rows.find(s=>s.id===b.dataset.sourceToggle);await api.request('sources/toggle',{id:source.id,enabled:!source.enabled});await refresh();}
      } catch(error) {feedback(error.message);}
      finally {if(b.isConnected)b.disabled=false;}
    });
    dialog.querySelector('form').addEventListener('submit', async event=>{
      event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;
      try {
        const values=Object.fromEntries(new FormData(form));
        const source=await api.request('sources',{...values,kind:'rss',family:values.name,tier:values.contentRole==='community'?'social':'regional',enabled:true,interval:900000,allowFullText:false,permissions:'Public feed links and publisher-supplied text only; provider reuse terms apply.'});
        await api.request('sources/poll',{id:source.id});form.reset();form.hidden=true;await refresh();feedback('Feed added and queued for a connection check.');
      }catch(error){feedback(error.message);}finally{button.disabled=false;}
    });
  }
  function feedback(message){dialog.querySelector('#source-directory-feedback').textContent=message;}
  function render(){
    const q=dialog.querySelector('#source-search').value.trim().toLowerCase(),role=dialog.querySelector('#source-role').value,status=dialog.querySelector('#source-status').value;
    const matches=rows.filter(s=>(!q||[s.name,s.family,s.category,s.purpose].join(' ').toLowerCase().includes(q))&&(!role||s.contentRole===role)&&(!status||(status==='working'?s.enabled&&s.health?.ok:status==='unavailable'?s.enabled&&s.health&&!s.health.ok:!s.enabled)));
    const owner=api.session?.ownerAuthorized;
    for(const b of dialog.querySelectorAll('[data-source-poll-all],[data-source-add]')) b.hidden=!owner;
    dialog.querySelector('#source-summary').textContent=`${matches.length} of ${rows.length} sources · ${rows.filter(s=>s.enabled&&s.health?.ok).length} connected`;
    dialog.querySelector('#source-cards').innerHTML=matches.slice(0,limit).map(s=>{
      const h=s.health||{},c=h.lastPoll||{};
      return `<article class="source-card"><div class="source-card-heading"><h3>${e(s.name)}</h3><span class="source-state ${h.ok&&s.enabled?'working':''}">${e(state(s))}</span></div><small>${e(roles[s.contentRole]||s.kind)} · ${e(s.category||s.language||'General')}</small><p>${e(s.purpose||'Publisher-supplied feed text and links.')}</p><div class="source-contribution"><b>${e(h.totalItems||0)}</b> collected items${h.lastPoll?` · Last poll: ${c.added||0} new, ${c.revised||0} revised, ${c.leads||0} leads, ${c.unchanged||0} unchanged${c.rejected?`, ${c.rejected} rejected`:''}`:''}</div>${h.error?`<p class="source-issue">${e(h.error)}${h.retryAt?` · Retry after ${e(date(h.retryAt))}`:''}</p>`:''}${h.warning?`<p class="source-issue">${e(h.warning)}</p>`:''}<small>Checked ${e(date(h.checkedAt))}${h.durationMs!=null?` · ${(h.durationMs/1000).toFixed(1)}s`:''}</small><div class="source-card-actions"><button data-source-preview="${e(s.id)}">Collected items</button>${owner?`<button data-source-edit="${e(s.id)}">Edit connection</button><button data-source-toggle="${e(s.id)}">${s.enabled?'Pause':'Enable'}</button>${s.enabled?`<button data-source-poll="${e(s.id)}">Poll now</button>`:''}`:''}</div></article>`;
    }).join('')||'<p>No sources match these filters.</p>';
    dialog.querySelector('[data-source-more]').hidden=matches.length<=limit;
  }
  async function preview(id){
    selected=id;const token=++previewToken,source=rows.find(s=>s.id===id),panel=dialog.querySelector('#source-preview');
    panel.innerHTML='<p>Loading collected items…</p>';
    const result=await api.request('source-items?id='+encodeURIComponent(id));
    if(token!==previewToken||!dialog.open)return;
    panel.innerHTML=`<h3>${e(source?.name)}</h3><p>${result.total} collected items · up to 12 recent items</p>${result.items.map(item=>`<article><small>${e(item.discoveryOnly?'Research lead':roles[item.contentRole]||'Reporting')} · ${e(date(item.publishedAt||item.collectedAt))}${item.publishedAt?'':' (collection date)'}</small><h4><a href="${e(safeURL(item.url))}" target="_blank" rel="noopener noreferrer">${e(item.title)} ↗</a></h4><p>${e(item.summary)}</p></article>`).join('')||'<p>No usable items have been collected yet. Check the connection status or queue a poll.</p>'}`;
    if(innerWidth<800)panel.scrollIntoView({behavior:'smooth',block:'start'});
  }
  function refresh(){
    if(refreshing)return refreshing;
    refreshing=api.request('sources').then(result=>{
      const rank=s=>!s.enabled?3:s.health?.ok?0:s.health?2:1;
      rows=result.sources.sort((a,b)=>rank(a)-rank(b)||a.name.localeCompare(b.name));render();
    }).finally(()=>{refreshing=null;});
    return refreshing;
  }
  document.addEventListener('click',async event=>{
    if(!event.target.closest('[data-open-source-directory]'))return;
    mount();if(!dialog.open)dialog.showModal();
    try{await refresh();}catch(error){feedback(error.message);}
  });
  setInterval(()=>{if(dialog?.open&&!document.hidden)refresh().catch(error=>feedback(error.message));},10000);
})();
