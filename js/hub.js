/* Three destinations; one overview. Existing crawler modules remain directly accessible. */
(() => {
  'use strict';
  const engine = window.CrawlerIntelligence, api = window.CrawlerServer;
  let destination = 'overview', inspector = 'signal', inspectorOpen = false, composing = false, dossierKey = '', lastOps = '', lastWatch = '';
  const originalRender = window.IntelligenceUI.render;
  const date = value => value ? new Date(value).toLocaleString() : 'Not available';
  const link = doc => `<a href="${esc(safeURL(doc.url))}" target="_blank" rel="noopener noreferrer">${esc(doc.source || doc.title)} ↗</a>`;
  function mount() {
    window.CrawlerSignalLimit = 24;
    $('tabs').hidden = true;
    $('tabs').setAttribute('aria-hidden', 'true');
    $('filter').placeholder = 'Search topics, companies, sources…';
    $('filter').insertAdjacentHTML('afterend', '<kbd class="search-key">Ctrl K</kbd>');
    $('tab-intelligence').querySelector('h1').innerHTML = 'Your research overview<span class="accent">.</span>';
    $('tab-intelligence').querySelector('.research-heading p').textContent = 'The developments that matter, with their evidence close at hand.';
    $('tab-intelligence').querySelector('.eyebrow').textContent = 'THE RESEARCH DESK';
    const researchStrip = document.createElement('section'); researchStrip.className = 'hub-research-strip'; researchStrip.id = 'research-strip';
    researchStrip.innerHTML = '<div><span class="assistant-symbol">✧</span><b>Ask your research</b><span class="dim sm">An answer is only as useful as its evidence.</span></div>';
    researchStrip.append($('research-question'));
    $('tab-intelligence').querySelector('.research-heading').after(researchStrip);
    $('research-query').placeholder = 'What is changing, why does it matter, and what should I watch?';
    $('clear-chat').textContent = 'Reset';
    const controls = $('tab-intelligence').querySelector('.research-controls'), more = document.createElement('details');
    more.className = 'hub-more-filters'; more.innerHTML = '<summary>More filters</summary><div class="research-controls"></div>';
    for (const id of ['i-region', 'i-status', 'i-impact']) more.querySelector('.research-controls').append($(id).closest('label'));
    controls.after(more);
    $('i-lifecycle').querySelector('[data-life=""]').textContent = 'All';
    const priorityHeading = document.createElement('div'); priorityHeading.className = 'hub-section-heading'; priorityHeading.innerHTML = '<h2>Priority signals</h2><span>Open any signal to follow the evidence ↗</span>';
    $('signal-list').before(priorityHeading);
    $('signal-list').insertAdjacentHTML('afterend', '<button class="btn sm" id="show-more-signals">Show more signals</button>');
    const market = document.createElement('section'); market.id = 'overview-markets'; market.className = 'overview-section';
    market.innerHTML = '<div class="hub-section-heading"><h2>The Mark</h2><span>Provider quotes · activity · related reporting</span></div><div class="overview-market-table"></div><details id="overview-radar"><summary>New & low-cost assets</summary></details>';
    market.querySelector('.overview-market-table').append($('tab-picks'));
    market.querySelector('details').append($('tab-radar'));
    const news = document.createElement('section'); news.id = 'overview-news'; news.className = 'overview-section';
    news.innerHTML = '<div class="hub-section-heading"><h2>Newsstand</h2><span>Original links, attribution, and timestamps</span></div>';
    news.append($('tab-news'));
    news.insertAdjacentHTML('beforeend', '<button class="btn sm" id="show-more-reporting">Show more reporting</button><details class="market-expectations"><summary>Prediction market context</summary></details>');
    news.querySelector('.market-expectations').append($('pmmacro'));
    const stream = document.createElement('details'); stream.id = 'overview-stream'; stream.className = 'overview-section'; stream.innerHTML = '<summary>All collected activity</summary>'; stream.append($('tab-feed'));
    $('tab-intelligence').append(market, news, stream);
    const assistant = document.createElement('aside'); assistant.id = 'assistant-panel'; assistant.hidden = true;
    assistant.innerHTML = '<div class="hub-section-heading"><div><div class="eyebrow">RESEARCH ASSISTANT</div><h2>Follow the evidence</h2></div><button class="btn sm" id="close-assistant">Back to signal</button></div><p id="assistant-mode" class="dim sm"></p>';
    assistant.append($('research-chat'));
    const suggestions = $('tab-research').querySelector('.question-suggestions'); assistant.append(suggestions);
    $('research-detail').after(assistant);
    const mentions = document.createElement('details'); mentions.id = 'asset-mentions'; mentions.innerHTML = '<summary>All mentions & source filters</summary>'; mentions.append($('tab-mentions')); $('detail').append(mentions);
    $('tab-workspace').querySelector('h1').innerHTML = 'Your watchlist<span class="accent">.</span>';
    $('tab-workspace').querySelector('.research-heading p').textContent = 'Saved investigations, monitors, briefs, and outcomes.';
    $('tab-registry').querySelector('h1').innerHTML = 'Sources & system<span class="accent">.</span>';
    $('tab-registry').querySelector('.research-heading p').textContent = 'Manage collection, connected services, and research operations.';
    const ops = document.createElement('div'); ops.id = 'server-operations'; $('tab-registry').querySelector('.research-heading').after(ops);
    const browserTools = document.createElement('details'); browserTools.className = 'research-box browser-tools'; browserTools.innerHTML = '<summary>Browser connector tools & diagnostics</summary>';
    $('srcpanel').hidden = false; browserTools.append($('srcpanel')); browserTools.append($('tab-sources')); $('tab-registry').append(browserTools);
    browserTools.addEventListener('toggle', () => { if (browserTools.open) { $('tab-sources').hidden = false; renderSources(); } });
    const serverWatch = document.createElement('div'); serverWatch.id = 'server-watchlist'; $('workspace-summary').after(serverWatch);
    $('workspace-forecasts').closest('section').id = 'local-forecast-section';
    $('source-form').closest('details').id = 'browser-source-registration';
    const dialog = document.createElement('dialog'); dialog.id = 'research-tools'; dialog.innerHTML = '<div class="tool-dialog-head"><h2 id="tool-title">Research tool</h2><button class="btn" id="close-tools" aria-label="Close research tool">×</button></div><div id="tool-content"></div>'; document.body.append(dialog);
    $('srcbtn').onclick = () => navigate('operations');
    $('overview-radar').addEventListener('toggle', () => renderRadar());
    $('overview-stream').addEventListener('toggle', () => renderStream());
    document.addEventListener('click', handleClick, true);
    document.addEventListener('error', event => { const img = event.target; if (img.tagName === 'IMG' && img.closest('.news-card')) { img.closest('.news-card').classList.add('noimg'); img.remove(); } }, true);
    document.addEventListener('submit', handleToolSubmit);
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('filter').focus(); $('filter').select(); }
      if (event.key === '/' && !event.target.matches('input,textarea,select')) { event.preventDefault(); focusResearch(); }
    });
    window.addEventListener('crawler:server-state', () => { renderStatus(); renderServerDossier(); if (destination === 'operations') renderOperations(); if (destination === 'watchlist') renderServerWorkspace(); });
    window.addEventListener('crawler:research-answer', () => { inspector = 'chat'; compose(); });
    engine.subscribe(() => { $('rail-saved-count').textContent = engine.state.saved.length; });
    // Keep the six boilerplate question blocks out of the default evidence path.
    simplifyInspector(); renderStatus(); compose();
  }
  function navigate(next) {
    if (document.body.dataset.experience !== 'workspace') {
      document.body.dataset.experience = 'workspace'; $('start-screen').hidden = true; $('topic-workspace').hidden = true;
      window.dispatchEvent(new Event('crawler:experience-change'));
    }
    destination = next;
    const internal = next === 'watchlist' ? 'workspace' : next === 'operations' ? 'registry' : 'intelligence';
    $('tabs').querySelector('[data-t="' + internal + '"]').click();
    document.querySelectorAll('[data-destination]').forEach(button => { button.classList.toggle('on', button.dataset.destination === next); button.setAttribute('aria-current', button.dataset.destination === next ? 'page' : 'false'); });
    compose(); window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function focusResearch() { navigate('overview'); $('research-query').focus(); $('research-strip').scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  const PAGES = {
    overview: ['THE RESEARCH DESK', 'Priority signals', 'The developments that matter, with their evidence close at hand.'],
    markets: ['MARKETS', 'The Mark', 'Stock and crypto quotes with provider timestamps. Stale data is labeled.'],
    reporting: ['REPORTING', 'Newsstand', 'Original links, attribution and timestamps from every collected source.'],
    activity: ['ACTIVITY', 'All collected activity', 'Everything the crawler has collected, newest first.']
  };
  function compose() {
    if (composing) return; composing = true;
    const page = PAGES[destination], overview = destination === 'overview', markets = destination === 'markets';
    document.body.dataset.destination = destination;
    document.body.dataset.inspector = inspector;
    document.body.dataset.inspectorOpen = String(inspectorOpen || inspector !== 'signal');
    if (page) {
      $('tab-intelligence').hidden = false;
      for (const id of ['tab-picks', 'tab-radar', 'tab-news', 'tab-feed']) $(id).hidden = false;
      const heading = $('tab-intelligence').querySelector('.research-heading');
      heading.querySelector('.eyebrow').textContent = page[0];
      heading.querySelector('h1').innerHTML = page[1] + '<span class="accent">.</span>';
      heading.querySelector('p').textContent = page[2];
      if (markets) { renderPicks(); if ($('overview-radar').open) renderRadar(); }
      if (destination === 'reporting') renderNews(true);
      if (destination === 'activity') { $('overview-stream').open = true; renderStream(); }
    }
    $('research-detail').hidden = !overview || inspector !== 'signal' || !inspectorOpen;
    $('detail').hidden = !(overview || markets) || inspector !== 'asset';
    $('assistant-panel').hidden = !overview || inspector !== 'chat';
    $('tab-mentions').hidden = false;
    if ((overview || markets) && inspector === 'asset') { renderDetail(); renderMentions(); }
    if (destination === 'operations') renderOperations();
    if (destination === 'watchlist') { renderServerWorkspace(); window.CrawlerNetwork?.renderPanels(); }
    simplifyInspector(); renderServerDossier(); renderStatus();
    $('show-more-signals').hidden = $('signal-list').querySelectorAll('.signal-card').length < window.CrawlerSignalLimit;
    composing = false;
  }
  function simplifyInspector() {
    const root = $('research-detail');
    if (!root.querySelector('.dossier-head') || root.querySelector('.inspector-actions')) return;
    const actions = document.createElement('div'); actions.className = 'inspector-actions'; actions.innerHTML = '<button class="btn sm" id="close-signal">Close details</button><button class="btn sm" id="ask-about-signal">Ask about this</button><button class="btn sm" id="investigate-signal">Investigate gaps</button><button class="btn sm" id="review-signal">Review a claim</button>';
    root.querySelector('.dossier-head').append(actions);
    const sections = root.querySelector('.dossier-sections');
    const brief = sections.querySelector('section');
    if (brief) {
      const dl = brief.querySelector('dl');
      const visible = document.createElement('div'); visible.className = 'inspector-summary';
      const signal = window.IntelligenceUI.selectedSignal();
      if (signal) visible.innerHTML = `<p>${signal.mentions} collected record${signal.mentions === 1 ? '' : 's'} · ${signal.chains} candidate reporting chain${signal.chains === 1 ? '' : 's'} · ${signal.primary} primary record${signal.primary === 1 ? '' : 's'}.</p><div class="watch-next"><span>WATCH NEXT</span><p>${esc(signal.watchNext)}</p></div>`;
      brief.querySelector('h3').textContent = 'At a glance';
      if (dl) dl.replaceWith(visible);
    }
    const details = [...sections.children].filter(node => node.tagName === 'DETAILS');
    for (const item of details) {
      const text = item.querySelector('summary')?.textContent || '';
      if (text.startsWith('Claim-level')) item.dataset.detailKind = 'claims';
      if (text.startsWith('Investigation notes')) item.dataset.detailKind = 'notes';
      if (text.startsWith('Evidence & reporting lineage')) { item.dataset.detailKind = 'evidence'; item.querySelector('summary').firstChild.textContent = 'Sources & evidence '; }
      item.open = root._preserveOpen ? root._preserveOpen.includes(item.dataset.detailKind || item.querySelector('summary')?.firstChild.textContent.trim()) : item.dataset.detailKind === 'evidence';
    }
    const serverSection = document.createElement('section'); serverSection.id = 'server-dossier'; sections.prepend(serverSection);
  }
  function renderStatus() {
    document.body.classList.toggle('server-mode', api.connected);
    const status = $('backend-state'); if (!status) return;
    const health = api.health;
    status.innerHTML = `<i class="dotc ${api.connected ? 'up' : ''}"></i>${api.connected ? 'Research server connected' : health ? 'Server sign-in required' : 'Browser mode'}`;
    const label = $('tab-intelligence').querySelector('.mode-label');
    label.innerHTML = `<i class="dotc ${api.connected ? 'up' : ''}"></i>${api.connected ? 'Server collection' : 'Browser collection'}`;
    $('assistant-mode').textContent = api.connected ? health.ai.configured ? 'Server AI · citations checked against collected source records.' : 'Server retrieval · configure a model and API key to enable AI synthesis.' : 'Local evidence search · start python CRAWLER/run.py for server research.';
    if (api.connected) {
      $('tab-workspace').querySelector('.coverage-note').textContent = 'Saved investigations sync to the research server. Server monitors and scheduled briefs continue while the server is running, including when the browser is closed.';
      $('tab-registry').querySelector('.coverage-note').textContent = 'The server owns source collection, retries, document storage, and analysis. Browser source diagnostics remain available below for legacy market feeds.';
    }
    if (api.error) { $('research-notice').textContent = api.error; $('research-notice').hidden = false; $('research-notice').classList.add('notice-error'); }
  }
  async function renderServerDossier() {
    if (document.body.dataset.experience && document.body.dataset.experience !== 'workspace') return;
    if (!api.connected || !window.IntelligenceUI.selectedSignal() || inspector !== 'signal') return;
    const signal = window.IntelligenceUI.selectedSignal(), cached = api.cachedDossier(signal);
    api.dossier(signal);
    if (!cached) return;
    const target = $('server-dossier'); if (!target) return;
    const key = cached.event.id + ':' + cached.event.updatedAt + ':' + cached.claims.map(c => c.updatedAt).join(',') + ':' + cached.investigations.length;
    if (target.dataset.renderKey === key) return;
    target.dataset.renderKey = key;
    target.innerHTML = `<div class="server-analysis-head"><h3>Research findings</h3><span>${esc(cached.trend.lifecycle)}</span></div><div class="mini-metrics"><div><b>${cached.claims.length}</b><span>Extracted claims</span></div><div><b>${cached.contradictions.length}</b><span>Possible conflicts</span></div><div><b>${cached.trend.acceleration == null ? '—' : cached.trend.acceleration.toFixed(1) + '×'}</b><span>Activity / baseline</span></div></div>
      ${cached.contradictions.length ? `<div class="finding-alert">${cached.contradictions.length} possible factual conflict(s) need review. Differences in periods, attribution, or units may explain them.</div>` : ''}
      ${cached.coverageGaps.map(text => `<p class="dim sm">△ ${esc(text)}</p>`).join('')}
      ${cached.documents.filter(d => d.translation).slice(0, 3).map(d => `<details><summary>English translation · ${esc(d.source)} (${esc(d.language)})</summary><p>${esc(d.translation.title)}</p><p>${esc(d.translation.text)}</p><p class="dim sm">Derived translation; original source preserved below.</p></details>`).join('')}
      <details><summary>Extracted claims & contradictions</summary>${cached.claims.slice(0, 12).map(claim => `<div class="auto-claim"><span class="evidence-badge status-${claim.status.toLowerCase()}">${esc(claim.status)}</span><p>${esc(claim.text)}</p><small class="dim">${esc(claim.method)}${claim.highConsequence ? ' · additional review required' : ''}</small><button class="text-button sm" data-server-review="${esc(claim.id)}">Review with evidence ↗</button></div>`).join('')}${cached.contradictions.map(c => `<p class="dim sm">${esc(c.kind)} · ${esc(c.reason)}</p>`).join('')}</details>
      ${cached.metrics.length ? `<details open><summary>Related measurements</summary>${cached.metrics.map(m => `<p class="sm"><b>${esc(m.assetId)}</b> · ${esc(m.metric)} ${esc(m.value)}${m.stale ? ' · delayed / historical' : ''}<br><span class="dim">${date(m.observedAt)} · ${m.samples} samples${m.robustZ == null ? '' : ' · robust z ' + m.robustZ}</span></p>`).join('')}</details>` : ''}
      ${cached.investigations.slice(0, 1).map(item => `<details open><summary>Investigation in progress</summary><ul class="gap-list">${item.questions.map(q => `<li>${esc(q)}</li>`).join('')}</ul><p class="dim sm">${item.followupJobs.length} registered-source follow-ups queued.</p></details>`).join('')}
      <p class="method-note">${esc(cached.trend.method)} Seasonal comparison: ${cached.trend.seasonalSamples} covered historical sample(s); ${cached.trend.robustSeasonalZ == null ? 'anomaly not assessed' : 'robust z ' + cached.trend.robustSeasonalZ}.</p>`;
  }
  function showTool(title, html) { $('tool-title').textContent = title; $('tool-content').innerHTML = html; if (!$('research-tools').open) $('research-tools').showModal(); }
  function renderOperations() {
    const target = $('server-operations'); if (!target) return;
    const key = JSON.stringify([api.connected, api.health, api.sources, api.operations?.jobs.map(j => [j.id, j.state, j.updated_at]), api.error]);
    if (key === lastOps) return; lastOps = key;
    if (!api.connected) {
      target.innerHTML = `<section class="research-box"><h2>${api.health ? 'Connect to the research server' : 'Run the research server'}</h2><p class="dim sm">Start <code>python CRAWLER/run.py</code> from your project folder. Collection, monitoring, briefs, and evidence storage then run independently of the browser.</p>${api.health ? '<form id="server-login" class="stack-form"><label>Owner access token<input type="password" name="token" autocomplete="current-password" required></label><button class="btn primary">Connect</button><p class="form-feedback"></p></form>' : '<button class="btn" id="retry-server">Check connection</button>'}<p class="dim sm">Server AI, PostgreSQL, S3, and provider credentials are configured in CRAWLER/.env. Credentials are never stored in the page.</p></section>`;
      return;
    }
    const h = api.health, jobs = api.operations?.jobs || [], sources = api.sources;
    target.innerHTML = `<div class="system-metrics"><div><span>Collection</span><b>${h.workers} service threads</b></div><div><span>Evidence store</span><b>${esc(h.storage)}</b></div><div><span>Research AI</span><b>${h.ai.configured ? esc(h.ai.model) : 'Not configured'}</b></div><div><span>Job queue</span><b>${h.queued} queued · ${h.deadLetters} failed</b></div></div>
      <section class="research-box"><div class="hub-section-heading"><h2>Server sources</h2><button class="btn sm" data-open-source-directory>Browse all sources</button><button class="btn sm" id="configure-connector">Add connector</button></div><div class="source-list">${sources.slice(0, 8).map(s => `<article><div><b>${esc(s.name)}</b><p class="dim sm">${esc(s.kind)} · ${esc(s.language || 'unknown')} · ${esc(s.family || s.name)}${s.geographyVerified ? ' · publisher geography reviewed' : ''}</p><small class="${s.health?.ok ? 'up' : 'dim'}">${s.enabled ? s.health ? s.health.ok ? 'Healthy · ' + date(s.health.checkedAt) : esc(s.health.error) : 'Awaiting first poll' : 'Paused'}</small></div><div class="source-actions"><button class="btn sm" data-edit-connector="${esc(s.id)}">Edit</button><button class="btn sm" data-server-toggle-source="${esc(s.id)}">${s.enabled ? 'Pause' : 'Enable'}</button>${s.enabled ? `<button class="btn sm" data-poll-source="${esc(s.id)}">Poll now</button>` : ''}</div></article>`).join('')}</div></section>
      <div class="tool-grid"><button class="research-box tool-card" id="import-document"><b>Import evidence</b><span>Text, permitted documents, PDF, or media provenance.</span></button><button class="research-box tool-card" id="historical-replay"><b>Historical replay</b><span>Inspect the records and reviews available at a past time.</span></button><button class="research-box tool-card" id="show-measurements"><b>Quantitative signals</b><span>Namespaced assets, stale-data checks, and anomalies.</span></button><button class="research-box tool-card" id="show-audit"><b>Audit & integrity</b><span>${api.operations?.auditIntegrity.valid ? 'Hash chain verified' : 'Integrity check requires attention'} · ${api.operations?.auditIntegrity.entries || 0} entries.</span></button></div>
      <details class="research-box"><summary>Worker queue & recovery</summary>${jobs.slice(0, 30).map(j => `<div class="queue-row"><span><b>${esc(j.kind)}</b> · ${esc(j.state)} · attempt ${j.attempts}<small>${esc(j.last_error || '')}</small></span>${j.state === 'dead' ? `<button class="btn sm" data-retry-job="${esc(j.id)}">Retry</button>` : ''}</div>`).join('') || '<p class="dim sm">No jobs yet.</p>'}</details>
      <details class="research-box"><summary>Connected services & permissions</summary><p class="dim sm">Raw storage: ${esc(h.objects)}. Automatic AI enrichment: ${h.ai.automaticAnalysis ? 'enabled' : 'disabled'}. Source text remains untrusted. High-consequence claims need additional review. Server access uses a same-origin session; remote hosting requires an owner token and HTTPS.</p><p class="dim sm">A provider must be configured and licensed for its intended use. Generic JSON connectors can supply institutional, options, exchange, or chain data using server-held environment credentials. Tickernames alone are not used as asset identities.</p></details>`;
  }
  function renderServerWorkspace() {
    const root = $('server-watchlist'); if (!root) return;
    if (!api.connected || !api.workspace) { root.innerHTML = ''; return; }
    const w = api.workspace, key = JSON.stringify(w); if (key === lastWatch) return; lastWatch = key;
    root.innerHTML = `<section class="research-box"><div class="hub-section-heading"><h2>Intelligence briefs</h2><button class="btn sm" id="generate-brief">Generate brief</button></div><form id="brief-schedule-form" class="inline-form"><label>Every <select name="hours"><option value="24">24 hours</option><option value="168">7 days</option><option value="1">hour</option></select></label><button class="btn sm">Schedule brief</button><span class="form-feedback"></span></form>${w.schedules.map(s => `<p class="sm">${esc(s.name)} · every ${s.hours}h · ${s.enabled ? 'next ' + date(s.nextRunAt) : 'paused'} <button class="text-button sm" data-toggle-schedule="${esc(s.id)}">${s.enabled ? 'Pause' : 'Resume'}</button></p>`).join('')}${w.briefs.slice(0, 5).map(b => `<button class="brief-link" data-open-brief="${esc(b.id)}"><span>${date(b.createdAt)}</span><b>${b.sections.length} developments ↗</b></button>`).join('')}</section>
      <section class="research-box"><h2>Server monitors & notifications</h2>${w.monitors.map(m => `<div class="workspace-item"><div><b>${esc(m.query)}</b><p class="dim sm">Momentum ≥ ${m.minMomentum} · ${m.enabled ? 'active' : 'paused'} · ${m.lastMatches.length} matching event(s)</p></div><button class="btn sm" data-server-monitor="${esc(m.id)}">${m.enabled ? 'Pause' : 'Resume'}</button></div>`).join('') || '<p class="dim sm">Create a monitor below to run it on the server.</p>'}${w.notifications.slice(0, 8).map(n => `<p class="notification-item">● ${esc(n.title)} <span class="dim sm">${date(n.createdAt)}</span></p>`).join('')}</section>
      <section class="research-box"><h2>Server scenarios & outcomes</h2>${w.forecasts.map(f => `<article class="forecast-record"><span class="eyebrow">${esc(f.outcome)}</span><h3>${esc(f.statement)}</h3><p class="dim sm">Recorded ${date(f.createdAt)} · review ${date(f.dueAt)}</p><p class="sm">Assumptions: ${esc(f.assumptions)}</p>${f.resolvedAt ? `<p class="sm">${esc(f.resolution)}</p>` : `<button class="btn sm" data-resolve-server-forecast="${esc(f.id)}">Record outcome</button>`}</article>`).join('') || '<p class="dim sm">Record a scenario from a signal to track its outcome here.</p>'}<p class="dim sm">${w.forecastEvaluation.length ? w.forecastEvaluation.map(c => `${esc(c.cohort)}: ${c.samples} resolved probabilities · Brier ${c.brierScore.toFixed(3)}. Evaluation remains uncalibrated.`).join(' ') : 'No resolved probability forecasts to evaluate. Qualitative scenarios do not produce a Brier score.'}</p></section>`;
  }
  function connectorForm(source = {}) {
    const checked = key => source[key] ? ' checked' : '';
    return `<form id="connector-tool-form" class="stack-form"><input type="hidden" name="id" value="${esc(source.id || '')}"><div class="form-columns"><label>Source name<input name="name" value="${esc(source.name || '')}" required></label><label>Connector<select name="kind">${['rss', 'json', 'coingecko', 'fred', 'sec', 'fred_vintages', 'coingecko_asset'].map(k => `<option${source.kind === k ? ' selected' : ''}>${k}</option>`).join('')}</select></label></div><label>HTTPS endpoint<input name="url" type="url" value="${esc(source.url || '')}" required></label><div class="form-columns"><label>Publisher family<input name="family" value="${esc(source.family || '')}"></label><label>Language<input name="language" value="${esc(source.language || 'unknown')}"></label><label>Region<input name="region" value="${esc(source.region || '')}"></label></div><div class="form-columns"><label>Source tier<select name="tier">${['regional', 'primary', 'wire', 'major', 'specialist', 'social'].map(v => `<option${source.tier === v ? ' selected' : ''}>${v}</option>`).join('')}</select></label><label>Poll interval, seconds<input name="seconds" type="number" min="60" value="${(source.interval || 300000) / 1000}" required></label></div><label>Permitted collection & reuse<textarea name="permissions" required>${esc(source.permissions || '')}</textarea></label><label>Connector mapping / configuration JSON<textarea name="config" rows="5">${esc(JSON.stringify(source.config || {}, null, 2))}</textarea></label><p class="dim sm">JSON mappings: {"itemsPath":"data", "recordType":"observation", "assetClass":"equity", "metric":"price_usd", "fields":{"assetId":"asset_id", "value":"price", "observedAt":"timestamp"}}. Use namespaced IDs such as equity:NASDAQ:NVDA or crypto:ethereum:0x… .</p><div class="form-columns"><label>Credential environment variable<input name="credentialEnv" value="${esc(source.credentialEnv || '')}" placeholder="PROVIDER_API_KEY"></label><label>Credential header<input name="credentialHeader" value="${esc(source.credentialHeader || 'Authorization')}"></label><label>Header prefix<input name="credentialPrefix" value="${esc(source.credentialPrefix ?? 'Bearer ')}"></label></div><label class="chk"><input type="checkbox" name="geographyVerified"${checked('geographyVerified')}> Publisher geography reviewed</label><label class="chk"><input type="checkbox" name="allowFullText"${checked('allowFullText')}> Allow permitted full-document retrieval</label><label class="chk"><input type="checkbox" name="enabled"${checked('enabled')}> Enable server collection</label><button class="btn primary">Save connector</button><p class="form-feedback" role="status"></p></form>`;
  }
  function reviewServerClaim(id) {
    const d = api.cachedDossier(window.IntelligenceUI.selectedSignal()), claim = d?.claims.find(c => c.id === id); if (!claim) return;
    showTool('Review extracted claim', `<p>${esc(claim.text)}</p><p class="dim sm">Original quote: ${esc(claim.quote)}</p><form id="server-review-form" class="stack-form"><input type="hidden" name="id" value="${esc(id)}"><label>Evidence status<select name="status">${window.CrawlerResearch.STATUSES.map(s => `<option${claim.status === s ? ' selected' : ''}>${s}</option>`).join('')}</select></label><label>Reason for this assessment<textarea name="rationale" required></textarea></label>${d.documents.map(doc => `<label>${esc(doc.source)} · ${esc(doc.title.slice(0, 90))}<select data-server-evidence="${esc(doc.id)}"><option value="">Not linked</option><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="context">Context / correction</option></select></label>`).join('')}<label class="chk"><input type="checkbox" name="directEvidenceReviewed"> Direct evidence reviewed</label><label class="chk"><input type="checkbox" name="independenceReviewed"> Reporting independence reviewed</label><label class="chk"><input type="checkbox" name="additionalReview"> Additional high-consequence review completed</label><label>Reviewer<input name="reviewer" value="Local analyst" required></label><button class="btn primary">Save assessment</button><p class="form-feedback" role="status"></p></form>`);
  }
  async function handleClick(event) {
    const b = event.target.closest('button');
    if (event.target.closest('[data-s]') && !event.target.closest('a')) inspector = 'asset';
    if (b?.dataset.signal) { inspector = 'signal'; inspectorOpen = true; }
    if (!b) return;
    try {
      if (b.dataset.destination) navigate(b.dataset.destination);
      if (b.dataset.jump) navigate({ 'overview-markets': 'markets', 'overview-news': 'reporting' }[b.dataset.jump] || 'overview');
      if (b.id === 'focus-research') focusResearch();
      if (b.id === 'show-more-signals') { window.CrawlerSignalLimit += 12; window.IntelligenceUI.render('intelligence', true); }
      if (b.id === 'show-more-reporting') { const expanded = $('overview-news').classList.toggle('reporting-expanded'); b.textContent = expanded ? 'Show fewer reports' : 'Show more reporting'; }
      if (b.id === 'close-assistant') { inspector = 'signal'; compose(); }
      if (b.id === 'close-signal') { inspectorOpen = false; compose(); }
      if (b.id === 'close-tools') $('research-tools').close();
      if (b.id === 'retry-server') await api.probe();
      if (b.id === 'ask-about-signal') { const s = window.IntelligenceUI.selectedSignal(); if (s) { $('research-query').value = 'What evidence and uncertainty should I watch for ' + s.title + '?'; focusResearch(); } }
      if (b.id === 'investigate-signal') { const s = window.IntelligenceUI.selectedSignal(); if (s) { if (api.connected) { await api.investigate(s); b.textContent = 'Follow-ups queued'; } else { const section = $('research-detail').querySelector('.gap-list'); section?.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } }
      if (b.id === 'review-signal') { const d = api.cachedDossier(window.IntelligenceUI.selectedSignal()); if (api.connected && d?.claims.length) reviewServerClaim(d.claims[0].id); else { const detail = $('research-detail').querySelector('[data-detail-kind=claims]'); if (detail) { detail.open = true; detail.scrollIntoView({ behavior: 'smooth', block: 'start' }); } } }
      if (b.dataset.editClaim && api.connected) { const claim = engine.state.claims.find(c => c.id === b.dataset.editClaim); if (claim?.serverId) { event.stopImmediatePropagation(); reviewServerClaim(claim.serverId); return; } }
      if (b.dataset.serverReview) reviewServerClaim(b.dataset.serverReview);
      if (b.id === 'configure-connector' || b.dataset.editConnector) showTool(b.dataset.editConnector ? 'Edit connector' : 'Connect a source', connectorForm(api.sources.find(s => s.id === b.dataset.editConnector)));
      if (b.dataset.serverToggleSource) { const s = api.sources.find(s => s.id === b.dataset.serverToggleSource); await api.mutation('sources/toggle', { id: s.id, enabled: !s.enabled }); }
      if (b.dataset.pollSource) { await api.mutation('sources/poll', { id: b.dataset.pollSource }); b.textContent = 'Queued'; }
      if (b.dataset.retryJob) await api.mutation('jobs/retry', { id: b.dataset.retryJob });
      if (b.id === 'generate-brief') { const brief = await api.mutation('briefs', {}); openBrief(brief); }
      if (b.dataset.openBrief) openBrief(api.workspace.briefs.find(item => item.id === b.dataset.openBrief));
      if (b.dataset.toggleSchedule) { const s = api.workspace.schedules.find(item => item.id === b.dataset.toggleSchedule); await api.mutation('schedules/toggle', { id: s.id, enabled: !s.enabled }); }
      if (b.dataset.serverMonitor) { const m = api.workspace.monitors.find(item => item.id === b.dataset.serverMonitor); await api.mutation('monitors/toggle', { id: m.id, enabled: !m.enabled }); }
      if (b.dataset.resolveServerForecast) showTool('Record scenario outcome', `<form id="server-outcome-form" class="stack-form"><input name="id" type="hidden" value="${esc(b.dataset.resolveServerForecast)}"><label>Outcome<select name="outcome"><option>Occurred</option><option>Did not occur</option><option>Inconclusive</option></select></label><label>Outcome evidence and source references<textarea name="evidence" required></textarea></label><button class="btn primary">Record outcome</button><p class="form-feedback"></p></form>`);
      if (b.id === 'historical-replay') showTool('Historical replay', '<form id="replay-tool-form" class="stack-form"><label>What did the system know at this time?<input type="datetime-local" name="at" required></label><button class="btn primary">Replay evidence</button><p class="form-feedback"></p></form><div id="replay-output"></div>');
      if (b.id === 'show-measurements') showTool('Quantitative observations', `<p class="dim sm">Measurements retain provider timestamps and namespaced asset identities. Correlation does not establish an effect.</p>${api.metrics.map(m => `<div class="research-box"><b>${esc(m.assetId)}</b><p>${esc(m.metric)}: ${esc(m.value)} · ${m.stale ? 'Historical / delayed' : 'Recent observation'}</p><p class="dim sm">${date(m.observedAt)} · ${m.samples} samples · robust z ${m.robustZ ?? 'unavailable'}</p>${m.warnings.map(w => `<p class="dim sm">${esc(w)}</p>`).join('')}</div>`).join('') || '<p class="dim sm">Enable a quantitative connector to collect observations.</p>'}`);
      if (b.id === 'show-audit') showTool('Research audit integrity', `<p class="dim sm">${api.operations.auditIntegrity.valid ? 'Hash chain is consistent.' : 'Audit chain integrity failed.'} Server owners can modify storage; use external backups for independent attestation.</p>${(api.workspace?.audit || []).map(item => `<div class="audit-item"><time>${date(item.at)}</time><b>${esc(item.action)}</b><p>${esc(JSON.stringify(item.detail))}</p></div>`).join('')}`);
      if (b.id === 'import-document') showTool('Import permitted evidence', `<form id="import-tool-form" class="stack-form"><label>Registered source<select name="sourceId">${api.sources.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</select></label><label>Title<input name="title" required></label><label>Original HTTPS URL<input type="url" name="url" required></label><label>Published at (optional)<input type="datetime-local" name="publishedAt"></label><label>Source text or media description<textarea name="text" rows="6"></textarea></label><label>File (optional)<input type="file" name="file" accept="text/plain,text/html,application/json,application/pdf,image/*,video/*"></label><p class="dim sm">Only import material you are allowed to retain and analyze. PDF extraction requires the optional pypdf adapter. Media provenance does not establish whether the content is true.</p><button class="btn primary">Import record</button><p class="form-feedback"></p></form>`);
    } catch (error) { if ($('research-tools').open) $('tool-content').insertAdjacentHTML('beforeend', `<p class="form-feedback error">${esc(error.message)}</p>`); else { $('research-notice').textContent = error.message; $('research-notice').hidden = false; } }
  }
  function openBrief(brief) { if (!brief) return; showTool('Intelligence brief · ' + date(brief.createdAt), `<p class="dim sm">${esc(brief.note)}</p>${brief.sections.map(item => `<article class="research-box"><span class="eyebrow">${esc(item.lifecycle)}</span><h3>${esc(item.title)}</h3><p class="dim sm">${esc(item.watchNext)}</p>${item.sources.map(link).join(' · ')}</article>`).join('') || '<p class="dim sm">No collected events yet.</p>'}`); }
  async function handleToolSubmit(event) {
    const form = event.target, id = form.getAttribute('id');
    if (!['server-login', 'connector-tool-form', 'server-review-form', 'brief-schedule-form', 'server-outcome-form', 'replay-tool-form', 'import-tool-form'].includes(id)) return;
    event.preventDefault(); const data = Object.fromEntries(new FormData(form)), feedback = form.querySelector('.form-feedback');
    const submit = form.querySelector('button[type=submit],button'); if (submit) submit.disabled = true;
    try {
      if (id === 'server-login') await api.login(data.token);
      if (id === 'connector-tool-form') { data.config = JSON.parse(data.config || '{}'); data.interval = Number(data.seconds) * 1000; for (const key of ['enabled', 'allowFullText', 'geographyVerified']) data[key] = !!data[key]; if (!data.id) delete data.id; await api.mutation('sources', data); $('research-tools').close(); }
      if (id === 'server-review-form') { for (const key of ['directEvidenceReviewed', 'independenceReviewed', 'additionalReview']) data[key] = !!data[key]; data.evidence = [...form.querySelectorAll('[data-server-evidence]')].filter(el => el.value).map(el => ({ documentId: el.dataset.serverEvidence, relation: el.value })); await api.mutation('claims/review', data); $('research-tools').close(); dossierKey = ''; await api.dossier(window.IntelligenceUI.selectedSignal()); }
      if (id === 'brief-schedule-form') await api.mutation('briefs/schedule', data);
      if (id === 'server-outcome-form') { await api.mutation('forecasts/resolve', data); $('research-tools').close(); }
      if (id === 'replay-tool-form') { const result = await api.request('replay?at=' + new Date(data.at).getTime()); $('replay-output').innerHTML = `<p class="dim sm">${date(result.asOf)} · ${result.documents.length} visible record(s) · ${result.claims.length} visible claim(s).</p><p class="dim sm">${esc(result.note)}</p>${result.documents.slice(0, 20).map(doc => `<div class="research-box"><b>${esc(doc.title)}</b><p class="sm">Version ${doc.version} · retrieved ${date(doc.retrievedAt)}</p>${link(doc)}</div>`).join('')}`; }
      if (id === 'import-tool-form') {
        const file = form.querySelector('[name=file]').files[0]; delete data.file;
        if (data.publishedAt) data.publishedAt = new Date(data.publishedAt).getTime(); else delete data.publishedAt;
        if (file) { if (file.size > 8 * 1024 * 1024) throw new Error('Files must be 8 MB or smaller.'); data.contentType = file.type || 'text/plain'; data.contentBase64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); }); data.description = data.text; }
        await api.mutation('documents/import', data); await api.pull();
      }
      if (feedback?.isConnected) { feedback.textContent = 'Saved.'; feedback.classList.remove('error'); }
    } catch (error) { if (feedback) { feedback.textContent = error.message; feedback.classList.add('error'); } }
    finally { if (submit?.isConnected) submit.disabled = false; }
  }
  window.CrawlerHub = { navigate, compose, editSource(source) { showTool('Edit connector', connectorForm(source)); }, navigateToModule(name) {
    if (name === 'sources' || name === 'registry') return navigate('operations');
    if (name === 'workspace') return navigate('watchlist');
    if (name === 'news') return navigate('reporting');
    if (name === 'picks') return navigate('markets');
    if (name === 'mentions') { navigate('markets'); inspector = 'asset'; $('asset-mentions').open = true; renderMentions(); compose(); $('asset-mentions').scrollIntoView({ behavior: 'smooth' }); return; }
    navigate('overview');
  } };
  window.IntelligenceUI.render = (...args) => { originalRender(...args); if ($('assistant-panel')) compose(); };
  mount();
})();

