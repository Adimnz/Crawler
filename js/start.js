/* A topic is the entry point. Autonomous work runs on the research server. */
(() => {
  'use strict';
  const api = window.CrawlerServer;
  let current = null, settings = null, recent = [], loading = false, polling = false, lastSettings = 0, navigationVersion = 0, settingsRequest = null, recentRequest = null;
  let modelGeneration = 0, modelTimer = null;
  const date = value => value ? new Date(value).toLocaleString() : 'Not yet reviewed';
  const qualified = item => item.qualified === true;
  const dialog = $('openai-connection-dialog');
  const safeText = value => esc(typeof value === 'string' ? value : value?.text || value?.question || '');

  function showStart() {
    navigationVersion++;
    document.body.dataset.experience = 'start'; $('start-screen').hidden = false; $('topic-workspace').hidden = true;
    window.dispatchEvent(new Event('crawler:experience-change'));
    $('start-feedback').textContent = ''; $('start-query').focus(); window.scrollTo(0, 0); renderRecentButton();
  }
  function showWorkspace() {
    navigationVersion++;
    document.body.dataset.experience = 'workspace'; $('start-screen').hidden = true; $('topic-workspace').hidden = true;
    window.dispatchEvent(new Event('crawler:experience-change'));
    window.CrawlerHub.navigate('overview'); renderRecentButton();
    if (api.connected) { api.refresh().catch(() => {}); api.pull().catch(() => {}); }
  }
  function showTopic(topic) {
    navigationVersion++;
    current = topic; document.body.dataset.experience = 'topic'; $('start-screen').hidden = true; $('topic-workspace').hidden = false;
    window.dispatchEvent(new Event('crawler:experience-change'));
    renderTopic(); renderRecentButton();
  }
  async function openTopic(id) {
    const navigation = navigationVersion;
    const topic = await api.request('topics?id=' + encodeURIComponent(id));
    if (navigation === navigationVersion) { showTopic(topic); window.scrollTo(0, 0); }
  }
  async function search(query) {
    query = String(query || '').trim(); if (!query || loading) return;
    const feedback = document.body.dataset.experience === 'topic' ? $('topic-feedback') : $('start-feedback');
    loading = true;
    const navigation = navigationVersion;
    for (const button of document.querySelectorAll('#start-search-form button, #topic-search-form button')) button.disabled = true;
    try {
      if (window.CrawlerNetwork?.dirty) await window.CrawlerNetwork.save();
      if (!api.connected) await api.probe();
      if (!api.connected) {
        if (api.session?.accountConfigured) { window.CrawlerAccounts?.open('login'); throw new Error('Sign in to start your private investigation.'); }
        if (api.session?.authenticationRequired) { await openConnection(); throw new Error('Unlock your research server to start this search.'); }
        throw new Error('Start the research server: python CRAWLER/run.py');
      }
      const topic = await api.request('topics', { query });
      if (navigation === navigationVersion) { showTopic(topic); window.scrollTo(0, 0); }
      await loadRecent();
    } catch (error) { if (feedback?.isConnected) feedback.textContent = error.message; }
    finally { loading = false; for (const button of document.querySelectorAll('#start-search-form button, #topic-search-form button')) button.disabled = false; }
  }
  function assetCard(item, candidate = false) {
    return `<button class="topic-asset" data-asset-profile="${esc(item.assetId || item.id)}"><div class="topic-asset-top"><b>${esc(item.ticker || item.name || item.assetId)}</b><span class="research-state ${qualified(item) ? 'qualified' : ''}">${esc(item.status || (candidate ? 'Under investigation' : 'Monitoring'))}</span></div><h3>${esc(item.name || item.assetId)}</h3><p>${esc(item.reason || 'Related source records are available for review.')}</p><small>${candidate ? 'Research candidate · qualification pending' : 'Meets the current evidence gates'} · ${item.evidenceIds?.length || 0} linked record(s) · Open profile ↗</small></button>`;
  }
  function evidenceLink(record, discovered = false) {
    return `<a class="topic-evidence-item" href="${esc(safeURL(record.url))}" target="_blank" rel="noopener noreferrer">${esc(record.title || record.url)} ↗<span>${esc(record.source || (discovered ? 'Discovered source · verification pending' : 'Collected source'))}${record.publishedAt ? ' · ' + (record.publishedEstimated ? 'Collected ' : 'Published ') + date(record.publishedAt) : ''}</span></a>`;
  }
  function researchEvidence(rows, key) {
    if (!rows?.length) return '';
    return `<details class="topic-citations" data-topic-section="citations-${esc(key)}"><summary>${rows.length} supporting source${rows.length === 1 ? '' : 's'}</summary>${rows.map(row => `<div><a href="${esc(safeURL(row.url))}" target="_blank" rel="noopener noreferrer">${esc(row.title || 'Open source')} ↗</a>${row.quote ? `<blockquote>${esc(row.quote)}</blockquote>` : ''}</div>`).join('')}</details>`;
  }
  function researchFindings(rows, section) {
    return (rows || []).slice(0, 8).map((finding, index) => `<article class="topic-finding"><p>${safeText(finding)}</p>${researchEvidence(finding.evidence, section + '-' + index)}</article>`).join('');
  }
  function subjectCard(subject) {
    return `<article class="topic-subject" data-watch-subject="${esc(subject.id)}"><h3>${esc(subject.name)}</h3><p>${esc(subject.connection || '')}</p>${subject.watchFor ? `<p class="topic-watch-for"><span>Watch next</span>${safeText(subject.watchFor)}</p>` : ''}${researchEvidence(subject.evidence, subject.id)}</article>`;
  }
  function renderTopic() {
    if (!current || document.body.dataset.experience !== 'topic') return;
    const p = current, state = p.state || p.status || 'Queued', busy = ['Queued', 'Researching'].includes(state);
    const entries = (p.entries || []).filter(qualified), candidates = [...(p.candidates || []), ...(p.entries || []).filter(item => !qualified(item))];
    const uniqueCandidates = [...new Map(candidates.map(item => [item.assetId || item.id, item])).values()];
    const records = p.evidence || [], plan = p.plan || {}, report = p.marketResearch || {};
    const questions = report.nextQuestions?.length ? report.nextQuestions : plan.questions || plan.researchQuestions || p.questions || [];
    const subjects = p.watchSubjects || report.subjects || [];
    const groups = [['company', 'Companies'], ['market', 'Markets'], ['financial_institution', 'Financial institutions']];
    const summary = report.summary || [], hasReport = summary.length || report.drivers?.length || report.risks?.length;
    const aiError = report.aiError || (!hasReport && (p.discoveryError || p.planError));
    const coverage = [...new Set([...(report.limitations || []), ...(p.limitations || [])])];
    const active = document.activeElement, typedQuery = active?.id === 'topic-query' ? active.value : null;
    const retainedBoard = window.CrawlerNetwork?.detail?.board.topicId === p.id ? $('research-network') : null;
    const boardFocus = retainedBoard?.contains(active) ? {element:active,start:active.selectionStart,end:active.selectionEnd} : null;
    const savedDetails = [...$('topic-workspace').querySelectorAll('details[open]')].map(d => d.dataset.topicSection);
    $('topic-workspace').innerHTML = `<div class="topic-search-row"><form id="topic-search-form" class="start-search" role="search"><label class="sr-only" for="topic-query">Research another topic</label><input id="topic-query" maxlength="500" value="${esc(typedQuery ?? p.query)}" placeholder="Research another topic…" required><button type="submit" aria-label="Research this topic">↗</button></form></div><section id="research-network" class="research-network" aria-label="Research observation board"></section>
      <div class="topic-head"><div><span class="topic-state ${busy ? 'busy' : ''}"><i></i>${esc(state)}${p.enabled === false ? ' · automatic updates paused' : ''}</span><h1>${esc(p.title || p.query)}</h1><p>Market research and a watchlist of the companies, markets and financial institutions connected to your topic.</p></div><div class="topic-head-actions"><button class="btn sm" id="refresh-topic"${busy ? ' disabled' : ''}>${busy ? 'Research in progress' : 'Research again'}</button><button class="btn sm" id="toggle-topic">${p.enabled === false ? 'Resume updates' : 'Pause updates'}</button></div></div>
      ${aiError && !busy ? `<div class="topic-ai-notice" role="status"><span>${safeText(aiError.message)} ${records.length ? 'Collected source research is shown below.' : 'Review the connection and research again.'}</span><button class="btn sm" data-openai-connect>OpenAI settings ↗</button></div>` : settings && !settings.configured ? '<div class="topic-ai-notice"><span>Connect OpenAI to research this topic across your collected sources and expand coverage.</span><button class="btn sm" data-openai-connect>Connect AI ↗</button></div>' : ''}
      <nav class="topic-statline" aria-label="Jump to topic information">${groups.map(([kind, label]) => `<a href="#topic-watch-${kind}"><b>${subjects.filter(s => s.kind === kind).length}</b>${label.toLowerCase()}</a>`).join('')}<a href="#topic-sources"><b>${records.length}</b>source records</a><span>Updated ${date(p.lastRunAt || p.updatedAt)}</span></nav>
      <p id="topic-feedback" class="form-feedback" role="status"></p>${busy ? `<p class="topic-progress" role="status">${esc(p.progress || 'Collecting sources and researching your topic.')} You can leave this page while research continues.</p>` : ''}<div class="topic-layout"><div><section class="topic-block topic-report" id="topic-research"><div class="topic-section-heading"><h2>Market research</h2>${report.method ? `<span>${esc(report.method)}${report.model ? ' · ' + esc(report.model) : ''}</span>` : ''}</div>${hasReport ? `${researchFindings(summary, 'summary')}<div class="topic-research-columns">${report.drivers?.length ? `<section><h3>Market drivers</h3>${researchFindings(report.drivers, 'drivers')}</section>` : ''}${report.risks?.length ? `<section><h3>Risks & uncertainties</h3>${researchFindings(report.risks, 'risks')}</section>` : ''}</div><p class="topic-report-note">${report.method === 'OpenAI source research' ? 'AI analysis with supporting source passages. ' : ''}Source reports remain subject to verification.</p>` : `<div class="topic-empty"><b>${busy ? 'Building your market brief…' : records.length ? 'Collected sources are ready to review.' : 'This topic needs more source coverage.'}</b>${busy ? 'The server is reading relevant sources, identifying connected organizations and investigating market drivers.' : records.length ? 'Research again to generate a current brief from the connected OpenAI model.' : 'Connect OpenAI for research and source discovery, or add relevant feeds in Sources & System.'}</div>`}</section>
      <section class="topic-block" id="topic-watchlist"><h2>Companies, markets & institutions</h2>${subjects.length ? groups.map(([kind, label]) => { const rows = subjects.filter(s => s.kind === kind); return `<section class="topic-subject-group" id="topic-watch-${kind}"><h3>${label}<span>${rows.length}</span></h3>${rows.length ? `<div class="topic-subjects">${rows.map(subjectCard).join('')}</div>` : '<p class="topic-coverage-gap">No subjects of this type are identified in the current source set.</p>'}</section>`; }).join('') : `<p class="topic-coverage-gap">${busy ? 'Connected subjects will appear as source research completes.' : 'No named watch subjects are supported by the sources checked yet.'}</p>`}</section>
      ${entries.length || uniqueCandidates.length ? `<details class="topic-block topic-financial" data-topic-section="financial" open><summary>Financial profiles · ${entries.length + uniqueCandidates.length}</summary><p>Detailed financial coverage has separate identity, price and observation checks. Topic monitoring uses the source connections above.</p>${entries.length ? `<div class="topic-assets">${entries.map(item => assetCard(item)).join('')}</div>` : ''}${uniqueCandidates.length ? `<h3>Under investigation</h3><div class="topic-assets">${uniqueCandidates.map(item => assetCard(item, true)).join('')}</div>` : ''}</details>` : ''}
      <section class="topic-block" id="topic-sources"><h2>The evidence behind this topic</h2>${records.map(record => evidenceLink(record)).join('') || `<p class="topic-coverage-gap">${busy ? 'Related records will appear as collection completes.' : 'No matching source records were retrieved from the sources checked.'}</p>`}</section>
      ${p.discoveryLinks?.length ? `<details class="topic-block" data-topic-section="discovery"><summary>Additional discovered sources · ${p.discoveryLinks.length}</summary>${p.discoveryLinks.map(record => evidenceLink(record, true)).join('')}</details>` : ''}</div>
      <aside class="topic-aside"><section class="topic-block"><h2>Research direction</h2><div class="topic-plan-terms">${(plan.searchTerms || [p.query]).slice(0, 10).map(term => `<span>${safeText(term)}</span>`).join('')}</div><p>${esc(plan.method || p.planMethod || 'Search terms guide retrieval; they do not establish financial exposure.')}</p>${questions.length ? `<ul>${questions.slice(0, 6).map(question => `<li>${safeText(question)}</li>`).join('')}</ul>` : ''}</section>
      <section class="topic-block"><h2>What changed?</h2>${(p.whatChanged || [busy ? 'Initial research queued.' : 'No new verified evidence in the checked source set.']).map(change => `<p>${safeText(change)}</p>`).join('')}</section>
      ${coverage.length ? `<details class="topic-block topic-coverage" data-topic-section="coverage"><summary>Coverage & open questions · ${coverage.length}</summary>${coverage.map(gap => `<p>${safeText(gap)}</p>`).join('')}</details>` : ''}
      <section class="topic-block"><h2>Ongoing research</h2><p>${p.enabled === false ? 'Automatic updates are paused.' : 'The server checks connected subjects and sources every ' + (p.refreshMinutes || 60) + ' minutes while it is running. New related evidence brings the next review forward.'}</p>${settings?.configured && !settings.automaticAnalysis ? '<p>Manual searches use OpenAI. Enable automatic AI in connection settings for model research between visits.</p><button class="text-button" data-openai-connect>Automatic AI settings ↗</button>' : ''}${p.enabled && p.nextRefreshAt ? `<p>Next review ${date(p.nextRefreshAt)}</p>` : ''}<button class="text-button" id="topic-open-workspace">Sources & research workspace ↗</button></section></aside></div>`;
    for (const detail of $('topic-workspace').querySelectorAll('details')) if (savedDetails.includes(detail.dataset.topicSection)) detail.open = true;
    if (typedQuery !== null) { $('topic-query').focus(); $('topic-query').setSelectionRange(typedQuery.length, typedQuery.length); }
    if(retainedBoard){
      $('research-network').replaceWith(retainedBoard);
      if(boardFocus){boardFocus.element.focus({preventScroll:true});if(boardFocus.start!=null)boardFocus.element.setSelectionRange(boardFocus.start,boardFocus.end);}
    }
    window.CrawlerNetwork?.attach(p);
  }
  async function pollTopic() {
    if (!current || !api.connected || polling || document.hidden) return;
    polling = true;
    const topicId = current.id;
    try { const result = await api.request('topics?id=' + encodeURIComponent(topicId)); if (current?.id === topicId && JSON.stringify(result) !== JSON.stringify(current)) { current = result; renderTopic(); } }
    catch (error) { if ($('topic-feedback')) $('topic-feedback').textContent = error.message; }
    finally { polling = false; }
  }
  async function loadRecent() {
    if (!api.connected || recentRequest) return recentRequest;
    recentRequest = (async () => { try { recent = (await api.request('topics')).topics || []; renderRecentButton(); } catch { /* Retry on the next server-state event. */ } })().finally(() => { recentRequest = null; });
    return recentRequest;
  }
  function renderRecentButton() {
    $('recent-topics-button')?.remove();
    if (!recent.length || document.body.dataset.experience !== 'start') return;
    const button = document.createElement('button'); button.id = 'recent-topics-button'; button.className = 'topic-recent'; button.textContent = 'Your topics · ' + recent.length;
    button.onclick = () => {
      const modal = document.createElement('dialog'); modal.className = 'connection-dialog'; modal.id = 'recent-topics-dialog';
      modal.innerHTML = `<div class="connection-heading"><h2>Your topics</h2><button class="connection-close" aria-label="Close saved topics">×</button></div><div class="recent-topic-list">${recent.map(topic => `<button data-open-topic="${esc(topic.id)}">${esc(topic.title || topic.query)}<span>${esc(topic.state || topic.status || 'Saved')} · ${date(topic.lastRunAt || topic.updatedAt)}</span></button>`).join('')}</div>`;
      document.body.append(modal); modal.querySelector('.connection-close').onclick = () => modal.close(); modal.addEventListener('close', () => modal.remove()); modal.showModal();
    };
    document.body.append(button);
  }
  async function loadSettings(force = false) {
    if (!api.connected || !force && Date.now() - lastSettings < 10000) return;
    if (settingsRequest) return settingsRequest;
    settingsRequest = (async () => { try { const next = await api.request('ai/settings', undefined, 10000), changed = JSON.stringify(settings) !== JSON.stringify(next); settings = next; lastSettings = Date.now(); updateConnectionStatus(); if (changed) renderTopic(); } catch { /* The connection dialog reports server availability. */ } })().finally(() => { settingsRequest = null; });
    return settingsRequest;
  }
  function updateConnectionStatus() {
    const verified = settings?.configured && settings.lastTest?.ok;
    for (const button of document.querySelectorAll('.start-ai-button')) {
      button.classList.toggle('connected', !!verified);
      button.querySelector('span').textContent = verified ? settings.automaticAnalysis ? 'AI research active' : 'OpenAI connected' : settings?.configured ? 'OpenAI settings' : 'Connect OpenAI';
    }
  }
  async function openConnection() {
    if (!api.connected) await api.probe();
    const needsOwner = api.session?.authenticationRequired && !api.session?.authorized;
    $('owner-unlock-form').hidden = !needsOwner;
    $('openai-connection-form').hidden = !!needsOwner;
    if (!dialog.open) dialog.showModal();
    if (needsOwner) { $('owner-unlock-form').elements.ownerToken.focus(); return; }
    await loadSettings(true);
    const form = $('openai-connection-form');
    form.elements.apiKey.value = '';
    form.elements.model.innerHTML = settings?.model ? `<option value="${esc(settings.model)}">${esc(settings.model)} · saved model</option>` : '<option value="">Enter your key to load available models</option>';
    form.elements.model.disabled = !settings?.model;
    form.elements.apiKey.placeholder = settings?.keyConfigured ? 'Key saved · leave blank to keep it' : 'Enter your OpenAI API key';
    form.elements.automaticAnalysis.checked = settings ? !!settings.automaticAnalysis : true;
    // First connection is an explicit opt-in to automatic research.
    if (!settings?.keyConfigured) form.elements.automaticAnalysis.checked = true;
    $('disconnect-openai').hidden = !settings?.keyConfigured;
    $('openai-storage-status').textContent = settings?.storage || '';
    $('openai-connection-feedback').textContent = api.connected ? settings?.lastTest?.message || '' : 'This page has no research API. Start python CRAWLER/run.py and open the Python app URL.';
    form.querySelector('button[type=submit]').disabled = !api.connected;
    $('load-openai-models').disabled = !api.connected;
    $('open-server-app').hidden = api.connected;
    $('openai-model-status').textContent = '';
    if (api.connected && settings?.keyConfigured) loadModels();
  }
  async function loadModels() {
    clearTimeout(modelTimer);
    const form = $('openai-connection-form'), input = form.elements.apiKey, select = form.elements.model;
    if (!api.connected || !input.value.trim() && !settings?.keyConfigured) { $('openai-model-status').textContent = 'Enter your API key first.'; return; }
    const generation = ++modelGeneration, selected = select.value || settings?.model || '';
    $('load-openai-models').disabled = true; $('openai-model-status').textContent = 'Loading available models…';
    const values = { apiKey: input.value.trim() };
    try {
      const result = await api.request('ai/models', values, 100000);
      if (generation !== modelGeneration || !dialog.open) return;
      const rows = result.models || [];
      select.innerHTML = '<option value="">Choose a research model</option>' + rows.map(row => `<option value="${esc(row.id)}">${esc(row.id)}</option>`).join('');
      if (rows.some(row => row.id === selected)) select.value = selected;
      select.disabled = !rows.length;
      $('openai-model-status').textContent = rows.length ? rows.length + ' models available to this key.' : 'No text research models were returned for this key.';
      $('openai-connection-feedback').textContent = '';
    } catch (error) {
      if (generation === modelGeneration && dialog.open) { $('openai-model-status').textContent = 'Models could not be loaded.'; $('openai-connection-feedback').textContent = error.message; }
    } finally { values.apiKey = ''; if (generation === modelGeneration) $('load-openai-models').disabled = !api.connected; }
  }
  async function testConnection() {
    const status = await api.request('ai/test', {}, 110000), checked = status.connectionTest || status.lastTest;
    settings = status; updateConnectionStatus();
    $('openai-connection-feedback').textContent = checked?.message || 'Connection could not be verified.';
    return !!checked?.ok;
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button) return;
    try {
      if (button.id === 'open-workspace' || button.id === 'topic-open-workspace') showWorkspace();
      if (button.id === 'new-topic-search') showStart();
      if (button.matches('[data-openai-connect]')) await openConnection();
      if (button.id === 'close-openai-connection') dialog.close();
      if (button.id === 'load-openai-models') await loadModels();
      if ((button.id === 'refresh-topic' || button.id === 'toggle-topic') && current) {
        const id = current.id, result = await api.request(button.id === 'refresh-topic' ? 'topics/refresh' : 'topics/toggle', { id, ...(button.id === 'toggle-topic' ? { enabled: !current.enabled } : {}) });
        if (current?.id === id) { current = result; renderTopic(); }
      }
      if (button.dataset.openTopic) { $('recent-topics-dialog')?.close(); await openTopic(button.dataset.openTopic); }
      if (button.id === 'test-openai-connection') { button.disabled = true; try { await testConnection(); } finally { button.disabled = false; } }
      if (button.id === 'disconnect-openai') { settings = await api.request('ai/settings', { disconnect: true }); await openConnection(); updateConnectionStatus(); renderTopic(); }
    } catch (error) { const feedback = dialog.open ? $('openai-connection-feedback') : $('topic-feedback') || $('start-feedback'); if (feedback) feedback.textContent = error.message; }
  });
  document.addEventListener('submit', async event => {
    if (event.target.id === 'start-search-form' || event.target.id === 'topic-search-form') { event.preventDefault(); await search(event.target.querySelector('input').value); }
    if (event.target.id === 'owner-unlock-form') {
      event.preventDefault(); const form = event.target;
      try { await api.login(form.elements.ownerToken.value); form.elements.ownerToken.value = ''; await openConnection(); }
      catch (error) { form.querySelector('[role=status]').textContent = error.message; }
    }
    if (event.target.id === 'openai-connection-form') {
      event.preventDefault(); const form = event.target, button = form.querySelector('button[type=submit]'); button.disabled = true;
      const values = { apiKey: form.elements.apiKey.value.trim(), model: form.elements.model.value.trim(), automaticAnalysis: form.elements.automaticAnalysis.checked };
      $('openai-connection-feedback').textContent = 'Verifying the selected model…';
      try {
        const result = await api.request('ai/connect', values, 110000); settings = result; updateConnectionStatus();
        if (result.connectionTest?.ok) {
          form.elements.apiKey.value = '';
          dialog.close(); updateConnectionStatus();
          if (current) {
            const id = current.id, result = await api.request('topics/refresh', { id });
            if (current?.id === id) current = result;
          }
          renderTopic();
        } else $('openai-connection-feedback').textContent = result.connectionTest?.message || 'The connection could not be verified. Choose another model or check the key.';
      } catch (error) { $('openai-connection-feedback').textContent = error.message; }
      finally { values.apiKey = ''; button.disabled = false; }
    }
  });
  $('openai-connection-form').elements.apiKey.addEventListener('input', () => {
    modelGeneration++; clearTimeout(modelTimer); $('load-openai-models').disabled = !api.connected;
    if ($('openai-connection-form').elements.apiKey.value.trim().length >= 8) modelTimer = setTimeout(loadModels, 500);
  });
  dialog.addEventListener('close', () => { modelGeneration++; clearTimeout(modelTimer); $('openai-connection-form').elements.apiKey.value = ''; $('owner-unlock-form').elements.ownerToken.value = ''; });
  document.addEventListener('keydown', event => {
    if (document.body.dataset.experience !== 'workspace' && !dialog.open && ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' || event.key === '/' && !event.target.matches('input,textarea,select'))) {
      event.preventDefault(); event.stopImmediatePropagation(); (document.body.dataset.experience === 'topic' ? $('topic-query') : $('start-query')).focus();
    }
  }, true);
  window.addEventListener('crawler:server-state', () => { loadSettings(); loadRecent(); });
  window.CrawlerStart = { showStart, showWorkspace, openTopic, search };
  setInterval(pollTopic, 4000); loadSettings(); loadRecent();
})();
