/* Asset research stays in the three existing destinations. */
(() => {
  'use strict';
  const api = window.CrawlerServer;
  let state = null, signature = '', theme = 'all', selected = '', revision = '', assetQuery = '', selectedReport = '';
  const date = value => value ? new Date(value).toLocaleString() : 'Data unavailable';
  const number = value => typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(value ?? 'Data unavailable');
  const sourceLink = item => item.url || item.sourceUrl ? `<a href="${esc(safeURL(item.url || item.sourceUrl))}" target="_blank" rel="noopener noreferrer">Source ↗</a>` : '';
  function mount() {
    const overview = document.createElement('section'); overview.id = 'asset-research'; overview.className = 'overview-section asset-research';
    $('research-strip').after(overview);
    const portfolios = document.createElement('section'); portfolios.id = 'watch-portfolios'; portfolios.className = 'research-box';
    $('workspace-summary').after(portfolios);
    const controls = document.createElement('section'); controls.id = 'autonomous-controls'; controls.className = 'research-box';
    $('server-operations').before(controls);
    const dialog = document.createElement('dialog'); dialog.id = 'asset-profile-dialog'; dialog.className = 'asset-profile-dialog';
    dialog.innerHTML = '<div class="tool-dialog-head"><h2 id="asset-dialog-title">Asset research</h2><button class="btn" id="close-asset-profile" aria-label="Close asset research">×</button></div><div id="asset-profile-content"></div>';
    document.body.append(dialog);
    $('filter').addEventListener('input', event => { assetQuery = event.target.value.trim().toLowerCase(); render(false); });
    const shortcut = document.createElement('button'); shortcut.dataset.jump = 'asset-research'; shortcut.textContent = 'Asset research ↗';
    document.querySelector('.rail-shortcuts').append(shortcut);
    document.addEventListener('click', async event => {
      const button = event.target.closest('button'); if (!button) return;
      try {
        if (button.dataset.assetProfile) await openProfile(button.dataset.assetProfile);
        if (button.dataset.researchReport) await openReport(button.dataset.researchReport);
        if (button.dataset.portfolioTheme) { theme = button.dataset.portfolioTheme; renderPortfolios(); }
        if (button.id === 'close-asset-profile') dialog.close();
        if (button.id === 'open-portfolios') { window.CrawlerHub.navigate('watchlist'); $('watch-portfolios').scrollIntoView({ block: 'start' }); }
        if (button.id === 'run-asset-research' || button.id === 'discover-assets') {
          await api.mutation(button.id === 'discover-assets' ? 'investment/discover' : 'investment/run', {}); button.textContent = 'Queued';
        }
        if (button.dataset.enableProvider) await enableProvider(button.dataset.enableProvider, button);
      } catch (error) { const feedback = $('investment-feedback'); if (feedback) feedback.textContent = error.message; }
    });
    document.addEventListener('change', async event => {
      if (event.target.id === 'profile-revision') { revision = event.target.value; await openProfile(selected, revision); }
      if (event.target.id === 'report-revision') await openReport(selectedReport, event.target.value);
    });
    document.addEventListener('submit', async event => {
      if (event.target.id === 'asset-event-study-form') {
        event.preventDefault(); const values = Object.fromEntries(new FormData(event.target));
        try { const result = await api.request('event-study?' + new URLSearchParams({ assetId: selected, ...values })); $('asset-study-output').innerHTML = `<p class="sm">${esc(result.status)} · ${esc(result.reason || result.method || '')}</p>${(result.metrics || []).map(renderItem).join('')}<p class="dim sm">${esc(result.limitations.join(' '))}</p>`; }
        catch (error) { $('asset-study-output').textContent = error.message; } return;
      }
      if (event.target.id === 'asset-exposure-form') {
        event.preventDefault(); const form = event.target, values = Object.fromEntries(new FormData(form)), feedback = form.querySelector('[role=status]');
        try {
          const doc = (await api.request('raw?id=' + encodeURIComponent(values.documentId))).documentId;
          if (!doc) throw new Error('Source document unavailable');
          if (values.type === 'political-exposure' || values.type === 'regulatory-exposure' || values.type === 'government-contract') {
            await api.mutation('policy-records', { ...values, reviewed: form.elements.reviewed.checked });
          }
          await api.mutation('relationships', { from: selected, to: values.target, type: values.type, evidence: [values.documentId], quote: values.quote, confirmed: true, reviewed: form.elements.reviewed.checked });
          await api.mutation('investment/run', {}); feedback.textContent = 'Exposure recorded; evidence review queued.';
        } catch (error) { feedback.textContent = error.message; } return;
      }
      if (event.target.id !== 'investment-rules-form') return;
      event.preventDefault(); const form = event.target, values = Object.fromEntries(new FormData(form));
      values.enabled = form.elements.enabled.checked; values.discoveryEnabled = form.elements.discoveryEnabled.checked;
      try { await api.mutation('investment/rules', values); await refresh(true); form.querySelector('[role=status]').textContent = 'Saved. Research review queued.'; } catch (error) { form.querySelector('[role=status]').textContent = error.message; }
    });
    window.addEventListener('crawler:server-state', () => refresh()); render(); refresh();
  }
  let loading = false, lastFetch = 0;
  async function refresh(force = false) {
    if (document.body.dataset.experience && document.body.dataset.experience !== 'workspace') return;
    if (!api.connected) { state = null; signature = ''; render(); return; }
    if (loading || !force && Date.now() - lastFetch < 5000) return;
    loading = true;
    try {
      const result = await api.request('investment'); lastFetch = Date.now();
      const next = JSON.stringify(result); state = result;
      if (next !== signature) { signature = next; render(); }
    } catch (error) { $('investment-feedback').textContent = error.message; }
    finally { loading = false; }
  }
  function card(p) {
    if (!matches(p)) return '';
    return `<button class="asset-research-card" data-asset-profile="${esc(p.id)}"><span class="asset-card-top"><b>${esc(p.asset.ticker || p.asset.name)}</b><span class="research-state ${p.qualified ? 'qualified' : ''}">${esc(p.status)}</span></span><span>${esc(p.asset.name)}</span><span class="dim sm">${esc(p.asset.exchange || p.asset.chain || p.asset.assetClass)} · revision ${p.version} · ${p.marketFresh ? 'Current provider price' : 'Price unavailable or stale'}</span><span class="sm">${esc(p.whatChanged[0] || 'Evidence reviewed')}</span></button>`;
  }
  function render(refreshControls = true) {
    const openDetails = [...$('asset-research').querySelectorAll('details[open]')].map(d => d.className);
    const connected = api.connected;
    $('asset-research').innerHTML = `<div class="hub-section-heading"><div><span class="eyebrow">AUTONOMOUS INTELLIGENCE</span><h2>Asset research</h2></div><button class="btn sm" id="open-portfolios">Watch portfolios ↗</button></div>${!state ? `<p class="dim">${connected ? 'Loading research…' : 'Start the research server to collect asset profiles, track financial evidence, and maintain watch portfolios.'}</p>` : `<p class="dim sm">${state.profiles.length} source-backed profiles · ${state.profiles.filter(p => p.qualified).length} meet monitoring criteria · last review ${date(state.lastRunAt)}</p><div class="asset-research-grid">${state.profiles.filter(matches).slice(0, 6).map(card).join('') || '<p class="dim sm">No verified instruments collected yet. Enable a financial provider in Sources & system; identities are discovered from reporting automatically.</p>'}</div>${state.reports.length ? `<details class="cross-market-reports"><summary>Cross-market reports · ${state.reports.length}</summary>${state.reports.slice(0, 6).map(r => `<button class="brief-link" data-research-report="${esc(r.id)}"><b>${esc(r.title)}</b><span>v${r.version} · ${date(r.createdAt)}</span></button>`).join('')}</details>` : ''}`}`;
    for (const details of $('asset-research').querySelectorAll('details')) if (openDetails.includes(details.className)) details.open = true;
    renderPortfolios(); if (refreshControls) renderControls();
  }
  function renderPortfolios() {
    const portfolios = state?.portfolios || [];
    $('watch-portfolios').innerHTML = `<div class="hub-section-heading"><h2>Research watch portfolios</h2><span>${state?.profiles.filter(p => p.qualified).length || 0} unique qualified assets</span></div><p class="dim sm">Thematic monitoring lists. Each asset retains one profile across themes. Entries have no investment weights, targets, or expected returns.</p><div class="portfolio-filters" role="group" aria-label="Portfolio theme"><button class="btn sm ${theme === 'all' ? 'primary' : ''}" data-portfolio-theme="all">All themes</button>${portfolios.map(p => `<button class="btn sm ${theme === p.id ? 'primary' : ''}" data-portfolio-theme="${p.id}">${esc(p.name)} <span>${p.qualifiedCount}</span></button>`).join('')}</div>${portfolios.filter(p => theme === p.id).map(p => `<details class="portfolio-group"${theme !== 'all' ? ' open' : ''}><summary>${esc(p.name)} <span class="dim">${p.qualifiedCount} monitoring · ${p.entries.length} researched</span></summary>${p.entries.map(e => { const profile = state.profiles.find(x => x.id === e.assetId); return profile ? card(profile) : ''; }).join('') || '<p class="dim sm">No assets meet this theme yet.</p>'}<p class="dim sm">Sector coverage: ${esc(JSON.stringify(p.sectorCounts || {}))} · Geography: ${esc(JSON.stringify(p.geographyCounts || {}))}</p>${p.correlations?.length ? `<details><summary>Observed correlations</summary><pre>${esc(JSON.stringify(p.correlations, null, 2))}</pre></details>` : '<p class="dim sm">Correlations: Data unavailable until compatible price histories cover the required sample.</p>'}</details>`).join('') || ''}<div class="asset-research-grid">${state?.profiles.filter(p => theme === 'all').map(card).join('') || ''}</div>`;
  }
  function renderControls() {
    if ($('autonomous-controls').contains(document.activeElement)) return;
    const openDetails = [...$('autonomous-controls').querySelectorAll(':scope > details')].map(d => d.open);
    const r = state?.rules;
    $('autonomous-controls').innerHTML = `<div class="hub-section-heading"><h2>Autonomous asset research</h2><span>${r ? r.enabled ? 'Active while server runs' : 'Paused' : 'Server required'}</span></div><p class="dim sm">Observe → Detect → Investigate → Correlate → Evaluate → Profile → Curate → Monitor</p>${r ? `<div class="investment-actions"><button class="btn sm" id="run-asset-research">Review evidence now</button><button class="btn sm" id="discover-assets">Discover instruments</button></div><p class="sm dim">${esc(state.discovery?.status || 'Identity discovery has not run yet.')} ${state.discovery?.checkedAt ? date(state.discovery.checkedAt) : ''}</p><details><summary>Financial providers</summary><p class="sm dim">Set server credentials in CRAWLER/.env, then enable a provider. SEC provides filings and statements; a licensed market feed is still needed for equity prices.</p><div class="investment-actions"><button class="btn sm" data-enable-provider="sec">Enable SEC discovery</button><button class="btn sm" data-enable-provider="crypto">Enable digital asset data</button><button class="btn sm" data-enable-provider="fred">Enable economic vintages</button></div><p class="dim sm">SEC contact ${api.health?.investment?.secConfigured ? 'configured' : 'required: SEC_USER_AGENT'} · FRED key ${api.health?.investment?.fredConfigured ? 'configured' : 'required: FRED_API_KEY'} · CoinGecko key ${api.health?.investment?.cryptoConfigured ? 'configured' : 'required: COINGECKO_API_KEY'}</p></details><details><summary>Monitoring rules & thresholds</summary><form id="investment-rules-form" class="stack-form"><label class="chk"><input type="checkbox" name="enabled"${r.enabled ? ' checked' : ''}> Autonomous research enabled</label><label class="chk"><input type="checkbox" name="discoveryEnabled"${r.discoveryEnabled ? ' checked' : ''}> Discover instruments from collected reporting</label><div class="form-columns">${[['observationDays','Observation period, days',1,365],['marketMaxAgeHours','Maximum price age, hours',1,168],['triggerMaxAgeDays','Trigger validity, days',1,365],['reviewGraceDays','Removal review period, days',1,90],['priceAnomalyPercent','Price change threshold, %',.1,100],['volumeMultiple','Volume / prior median',1.1,100],['minimumHistorySamples','Minimum historical samples',10,365],['cycleMinutes','Review interval, minutes',1,1440]].map(([key,label,min,max]) => `<label>${label}<input type="number" name="${key}" min="${min}" max="${max}" step="${key === 'priceAnomalyPercent' || key === 'volumeMultiple' ? '.1' : '1'}" value="${r[key]}" required></label>`).join('')}</div><p class="dim sm">Thresholds are analyst configuration. Historical threshold crossings are descriptive and do not imply predictive validation.</p><button class="btn primary">Save monitoring rules</button><p role="status"></p></form></details>` : ''}<p id="investment-feedback" class="form-feedback" role="status"></p>`;
    [...$('autonomous-controls').querySelectorAll(':scope > details')].forEach((details, index) => { details.open = !!openDetails[index]; });
  }
  function matches(p) { return !assetQuery || [p.asset.name, p.asset.ticker, p.id, p.status, p.asset.exchange, p.asset.chain].join(' ').toLowerCase().includes(assetQuery); }
  async function enableProvider(kind, button) {
    const presets = {
      sec: { id: 'sec-discovery', name: 'SEC EDGAR discovery', kind: 'sec', url: 'https://www.sec.gov/files/company_tickers_exchange.json', config: { discoveryOnly: true }, credentialEnv: 'SEC_USER_AGENT', family: 'SEC EDGAR' },
      crypto: { id: 'coingecko', name: 'CoinGecko asset research', kind: 'coingecko', url: 'https://api.coingecko.com/api/v3/simple/price', config: { ids: ['bitcoin', 'ethereum'] }, family: 'CoinGecko', credentialEnv: 'COINGECKO_API_KEY' },
      fred: { id: 'fred', name: 'FRED economic vintages', kind: 'fred_vintages', url: 'https://api.stlouisfed.org/fred/series/observations', config: { series: ['CPIAUCSL', 'FEDFUNDS', 'UNRATE', 'GDP'] }, family: 'Federal Reserve Bank of St. Louis', credentialEnv: 'FRED_API_KEY' }
    };
    await api.mutation('sources', { ...presets[kind], enabled: true, tier: 'primary', interval: 3600000, permissions: 'Configured public-provider research access. Provider access and reuse terms apply.', language: 'en' });
    await api.mutation('sources/poll', { id: presets[kind].id }); button.textContent = 'Enabled · collection queued';
  }
  function renderItem(item) {
    if (item.value !== undefined) return `<article class="profile-measure"><div><b>${esc(item.metric || item.type || 'Measurement')}</b><strong>${esc(number(item.value))} ${esc(item.unit || '')}</strong></div><p class="dim sm">${esc(item.currency || '')} ${esc(item.periodStart || '')} ${item.periodEnd ? '→ ' + esc(item.periodEnd) : ''} · observed ${date(item.observedAt)}${item.stale ? ' · STALE' : ''}</p>${item.formula ? `<p class="sm">${esc(item.formula)}</p>` : ''}${sourceLink(item)}<details><summary>Inputs & provenance</summary><pre>${esc(JSON.stringify(item, null, 2))}</pre></details></article>`;
    if (item.identityVerified !== undefined) return `<p><b>${esc(item.name)}</b> · ${esc(item.ticker)} · ${esc(item.exchange || item.chain || item.assetClass)}</p><p class="dim sm">${esc(item.id)} · identity checked ${date(item.identityCheckedAt)} ${sourceLink({url:item.identitySource})}</p>`;
    if (item.condition) return `<p class="sm"><b>${esc(item.condition)}</b> → ${esc(item.action)}</p>`;
    if (item.title) return `<p>${esc(item.title)} ${sourceLink(item)}<br><span class="dim sm">Published ${date(item.publishedAt)} · retrieved ${date(item.retrievedAt)} · source v${item.version}</span></p>`;
    if (item.text) return `<p class="sm">${esc(item.text)} ${item.evidenceIds?.length ? `<span class="dim">Evidence: ${esc(item.evidenceIds.join(', '))}</span>` : ''}</p>`;
    return `<pre>${esc(JSON.stringify(item, null, 2))}</pre>`;
  }
  async function openProfile(id, at = '') {
    selected = id; revision = at;
    const result = await api.request('asset-profile?id=' + encodeURIComponent(id) + (at ? '&at=' + at : ''));
    const p = result.profile, dialog = $('asset-profile-dialog');
    $('asset-dialog-title').textContent = p.asset.name + ' · ' + (p.asset.ticker || p.asset.id);
    $('asset-profile-content').innerHTML = `<div class="profile-summary"><span class="research-state ${p.qualified ? 'qualified' : ''}">${esc(p.status)}</span><span class="dim sm">Assessed ${date(p.assessedAt)} · price ${p.marketFresh ? 'within configured age limit' : 'unavailable or stale'}</span></div><label class="profile-version-picker">Revision<select id="profile-revision"><option value="">Latest</option>${result.revisions.map(v => `<option value="${v.assessedAt}"${String(v.assessedAt) === at ? ' selected' : ''}>v${v.version} · ${date(v.assessedAt)}</option>`).join('')}</select></label><section class="profile-change"><h3>What changed?</h3>${p.whatChanged.map(t => `<p class="sm">${esc(t)}</p>`).join('')}</section>${Object.entries(p.sections).map(([name, section]) => `<details class="profile-section"${['Identity','Market performance','Research conclusion','Monitoring criteria'].includes(name) ? ' open' : ''}><summary>${esc(name)}${section.status !== 'Available' ? ' · Data unavailable' : ''}</summary>${section.items.map(renderItem).join('') || '<p class="dim sm">Data unavailable. Unsupported conclusions are withheld.</p>'}</details>`).join('')}<details class="profile-section"><summary>Risks, missing data & qualification gates</summary>${[...p.risks, ...p.qualificationGaps].map(t => `<p class="sm">${esc(typeof t === 'string' ? t : JSON.stringify(t))}</p>`).join('')}<pre>${esc(JSON.stringify(p.missingData, null, 2))}</pre></details>`;
    $('asset-profile-content').insertAdjacentHTML('beforeend', profileTools(p, !!at));
    if (!dialog.open) dialog.showModal();
    try {
      const history = await api.request('asset-assessments?id=' + encodeURIComponent(id));
      if (selected !== id || revision !== at) return;
      const assessment = history.assessments.find(r => r.profileVersion === p.version)?.assessment;
      $('profile-assessment').innerHTML = assessment ? `<p class="dim sm">Source extracts checked independently of the model. Interpretations remain pending review.</p>${assessment.facts.map(f => `<blockquote>${esc(f.text)}<p class="dim sm">${f.evidence.map(sourceLink).join(' · ')}</p></blockquote>`).join('') || '<p>No supported source extracts established in the checked records.</p>'}${assessment.uncertainties.map(t => `<p class="sm">${esc(t)}</p>`).join('')}` : '<p class="dim sm">No AI assessment for this revision. Configure server AI and opt into automatic analysis to run bounded investigations. The evidence profile and qualification gates operate independently.</p>';
    } catch { /* The independently calculated profile remains available. */ }
  }
  function profileTools(p, historical) {
    const docs = p.sourceHistory.map(d => `<option value="${esc(d.id)}">${esc(d.title.slice(0, 90))}</option>`).join('');
    return `<details class="profile-section"><summary>Historical threshold evaluation</summary><p class="dim sm">Configured price threshold replayed against the retrieved daily history. Observed subsequent returns describe history and do not predict outcomes.</p><pre>${esc(JSON.stringify(p.thresholdHistory, null, 2))}</pre></details><details class="profile-section"><summary>Research assessment</summary><div id="profile-assessment">Loading assessment history…</div></details>${historical ? '' : `<details class="profile-section"><summary>Compare market response to a source publication</summary><form id="asset-event-study-form" class="stack-form"><label>Benchmark<select name="benchmarkId" required>${(state?.profiles || []).filter(x => x.id !== p.id).map(x => `<option value="${esc(x.id)}">${esc(x.asset.name)}</option>`).join('')}</select></label><label>Source publication<select name="documentId" required>${docs}</select></label><button class="btn sm">Calculate observed response</button></form><div id="asset-study-output"></div></details><details class="profile-section"><summary>Record a documented exposure</summary><form id="asset-exposure-form" class="stack-form"><label>Exposure type<select name="type"><option>economic-exposure</option><option>rate-exposure</option><option>currency-exposure</option><option>political-exposure</option><option>regulatory-exposure</option><option>government-contract</option><option>geographic-exposure</option><option>supplier</option><option>customer</option><option>ownership</option></select></label><label>Documented entity / policy identifier<input name="target" required placeholder="policy:jurisdiction:record-id"></label><label>Evidence document<select name="documentId" required>${docs}</select></label><label>Exact supporting source quote<textarea name="quote" required></textarea></label><details><summary>Policy procedure (required for political exposure)</summary><label>Procedural status<select name="status">${['Attributed statement','Proposal','Passed bill','Enacted law','Proposed rule','Final rule','Government contract','Opinion'].map(s => `<option>${s}</option>`).join('')}</select></label><label>Jurisdiction<input name="jurisdiction"></label><label>Supported event date<input name="eventAt" type="date"></label><label>Effective date, when enacted / final<input name="effectiveDate" type="date"></label><label>Remaining procedural steps<textarea name="remainingSteps"></textarea></label></details><label class="chk"><input type="checkbox" name="reviewed" required> I reviewed the original evidence and the stated relationship</label><button class="btn sm">Record reviewed exposure</button><p role="status"></p></form></details>`}`;
  }
  async function openReport(id, at = '') {
    selectedReport = id;
    const result = await api.request('cross-market-report?id=' + encodeURIComponent(id) + (at ? '&at=' + at : '')), r = result.report;
    $('asset-dialog-title').textContent = r.title;
    $('asset-profile-content').innerHTML = `<p class="dim sm">Cross-market report v${r.version} · ${date(r.createdAt)}</p><h3>What happened?</h3>${r.whatHappened.map(f => `<blockquote>${esc(f.text)}<p class="dim sm">Attributed to ${esc(f.attribution)} · ${date(f.publishedAt)} ${sourceLink(f)}</p></blockquote>`).join('')}<h3>Observed financial changes</h3>${r.financialObservations.map(f => `<h4>${esc(f.assetId)}</h4>${f.metrics.map(renderItem).join('')}`).join('') || '<p>Data unavailable.</p>'}<h3>Documented exposure</h3>${r.documentedExposure.map(renderItem).join('') || '<p>Data unavailable. Mentions do not establish business exposure.</p>'}<h3>What remains uncertain?</h3>${r.uncertainties.map(u => `<p class="sm">${esc(u)}</p>`).join('')}<h3>Assets qualified for monitoring</h3>${r.monitoringCandidates.map(id => `<button class="btn sm" data-asset-profile="${esc(id)}">${esc(id)}</button>`).join('') || '<p>No asset currently meets all research gates.</p>'}<h3>What would change the assessment?</h3>${r.nextVerificationTriggers.map(renderItem).join('') || '<p>New original records, independent review, or compatible market observations.</p>'}`;
    $('asset-profile-content').insertAdjacentHTML('afterbegin', `<label class="profile-version-picker">Report revision<select id="report-revision"><option value="">Latest</option>${result.revisions.map(v => `<option value="${v.createdAt}"${String(v.createdAt) === at ? ' selected' : ''}>v${v.version} · ${date(v.createdAt)}</option>`).join('')}</select></label><section class="profile-change"><h3>What changed?</h3>${r.whatChanged.map(t => `<p class="sm">${esc(t)}</p>`).join('')}</section>`);
    if (!$('asset-profile-dialog').open) $('asset-profile-dialog').showModal();
  }
  mount();
})();
