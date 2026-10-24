/* Research UI shares the existing crawler's live ingestion; no simulated records. */
(() => {
  'use strict';
  const engine = window.CrawlerIntelligence, model = window.CrawlerResearch;
  const WINDOWS = { '5m': 3e5, '1h': 36e5, '6h': 216e5, '24h': 864e5, '7d': 6048e5, '30d': 2592e6, '90d': 7776e6, '1y': 31536e6 };
  const researchTabs = new Set(['intelligence', 'research', 'workspace', 'registry']);
  let selected = '', currentTab = 'intelligence', lastRender = '', lastDetail = '', registryStamp = '', chatContext = '';
  let chat = [], lastAlertCheck = 0;
  const date = ts => ts ? new Date(ts).toLocaleString() : 'Unknown';
  const options = (values, label) => `<option value="">${esc(label)}</option>` + values.map(v => `<option>${esc(v)}</option>`).join('');
  const empty = (title, text) => `<div class="research-empty"><div class="empty-orbit">◎</div><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
  const badge = status => `<span class="evidence-badge status-${status.toLowerCase()}">${esc(status)}</span>`;
  const announce = (text, isError = false) => { const node = $('research-notice'); node.textContent = text; node.classList.toggle('notice-error', isError); node.hidden = false; };
  const freshLink = doc => { const url = safeURL(doc.url); return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(doc.title)}</a>` : `<span>${esc(doc.title)}</span>`; };
  const button = (id, label, cls = '') => `<button class="btn ${cls}" data-signal="${esc(id)}">${esc(label)}</button>`;
  function initialize() {
    $('tab-intelligence').innerHTML = `
      <div class="research-heading"><div><div class="eyebrow">GLOBAL RESEARCH DESK</div><h1>Trend intelligence<span class="accent">.</span></h1><p class="dim">Find the signal. Follow the evidence.</p></div><span class="mode-label"><i class="dotc up"></i> Browser research</span></div>
      <div class="research-metrics" id="research-metrics"></div>
      <div class="research-controls">
        <label>Coverage<select id="i-category">${options(Object.keys(model.CATEGORIES), 'All domains')}</select></label>
        <label>Geography<select id="i-region">${options(Object.keys(model.REGIONS), 'All regions')}</select></label>
        <label>Evidence<select id="i-status">${options(model.STATUSES, 'Any assessment')}</select></label>
        <label>Window<select id="i-window">${Object.keys(WINDOWS).map(v => `<option${v === '24h' ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
        <label>Rank by<select id="i-sort"><option value="rank">Research priority</option><option value="momentum">Momentum</option><option value="credibility">Evidence strength</option><option value="impact">Potential impact</option><option value="chronological">Most recent</option></select></label>
        <label>Impact<select id="i-impact"><option value="0">Any impact</option><option value="40">40+ heuristic</option><option value="70">70+ heuristic</option></select></label>
      </div>
      <div class="signal-toolbar"><div class="seg" id="i-lifecycle"><button class="on" data-life="">All signals</button><button data-life="Emerging">Emerging</button><button data-life="Contested">Contested</button><button data-life="Cooling">Cooling</button></div><label class="chk"><input type="checkbox" id="i-saved"> Watchlist only</label></div>
      <div class="coverage-note" id="coverage-note"></div><div class="research-notice" id="research-notice" role="status" hidden></div>
      <section id="priority-briefing" aria-label="Signal desk briefing"></section><div class="signal-list" id="signal-list"></div><p class="method-note">Scores are transparent heuristics for research triage. Publisher and content clusters are candidate reporting chains; independence requires review. Missing history is shown as unavailable.</p>`;
    $('tab-research').innerHTML = `
      <div class="research-heading"><div><div class="eyebrow">EVIDENCE EXPLORER</div><h1>Ask your collection<span class="accent">.</span></h1><p class="dim">Search collected evidence and inspect the records behind each answer.</p></div></div>
      <div class="coverage-note">Local, deterministic research assistant. It searches your archive and retains topic context for follow-ups. Autonomous web investigation and language-model analysis need a backend.</div>
      <div class="question-suggestions"><button class="fchip" data-question="Which stories lack independent verification?">Find verification gaps</button><button class="fchip" data-question="What technology developments should I watch?">Explore technology</button><button class="fchip" data-question="What politics stories have primary sources?">Find primary records</button><button class="fchip" data-question="What changed?">Follow up: what changed?</button></div>
      <div class="research-chat" id="research-chat" aria-live="polite">${empty('Start with a research question', 'Ask about an entity, a domain, missing evidence, primary sources, or recent changes. Responses cite collected records.')}</div>
      <form id="research-question" class="question-form"><label class="sr-only" for="research-query">Research question</label><input id="research-query" maxlength="500" placeholder="What developments should I watch in technology?" required><button class="btn primary" type="submit">Research ↗</button><button class="btn" type="button" id="clear-chat">Clear</button></form>`;
    $('tab-workspace').innerHTML = `
      <div class="research-heading"><div><div class="eyebrow">YOUR INVESTIGATIONS</div><h1>Research workspace<span class="accent">.</span></h1><p class="dim">Keep watchlists, notes, monitoring conditions, and accountable scenarios.</p></div><button class="btn" id="export-research">Export research ↓</button></div>
      <div class="coverage-note">Saved locally in this browser. Monitors run while the app is open and visible. Export includes retrieved records, source revisions, claim reviews, notes, scenarios, and the audit log.</div>
      <div id="workspace-summary"></div>
      <section class="research-box"><h2>Create a monitor</h2><form id="alert-form" class="stack-form"><label>Topic or entity<input name="query" placeholder="e.g. semiconductor" maxlength="200" required></label><div class="form-columns"><label>Minimum momentum<input type="number" name="minMomentum" min="0" max="100" value="35" required></label><label>Evidence condition<select name="status">${options(model.STATUSES, 'Any assessment')}</select></label></div><button class="btn primary" type="submit">Add monitor</button></form><div id="workspace-alerts"></div></section>
      <section class="research-box"><h2>Saved investigations</h2><div id="workspace-saved"></div></section>
      <section class="research-box"><h2>Scenario accountability</h2><p class="dim sm">Record a scenario from a signal's research view. Original statements, assumptions, and dates remain fixed when you record an outcome.</p><div id="workspace-forecasts"></div></section>
      <section class="research-box"><h2>Research audit trail</h2><div id="workspace-audit"></div></section><div id="workspace-feedback" class="form-feedback" role="status"></div>`;
    $('tab-registry').innerHTML = `
      <div class="research-heading"><div><div class="eyebrow">INFORMATION FOUNDATION</div><h1>Source intelligence<span class="accent">.</span></h1><p class="dim">Inspect coverage, provenance, access permissions, and feed health.</p></div></div>
      <div class="coverage-note">Existing feeds retain their polling schedules and retry backoff. Custom RSS/Atom feeds use adaptive polling. Public access does not establish reuse permissions; record provider terms before enabling a custom feed.</div>
      <div id="registry-summary"></div><div class="registry-scroll"><table class="tbl registry-table"><thead><tr><th>Source / publisher family</th><th>Type / language</th><th>Health</th><th>Records</th><th>Permissions / polling</th></tr></thead><tbody id="registry-rows"></tbody></table></div>
      <details class="research-box"><summary>Register an RSS / Atom source</summary><form id="source-form" class="stack-form"><div class="form-columns"><label>Source name<input name="name" required maxlength="100"></label><label>Publisher family<input name="family" placeholder="Owner or original publisher"></label></div><label>HTTPS feed URL<input name="url" type="url" pattern="https://.*" placeholder="https://publisher.example/feed.xml" required></label><div class="form-columns"><label>Language<input name="language" value="unknown" placeholder="e.g. en, fr, ja"></label><label>Region<select name="region">${options(Object.keys(model.REGIONS), 'Unclassified')}</select></label><label>Domain<select name="category">${options(Object.keys(model.CATEGORIES), 'Auto classify')}</select></label></div><label>Permitted uses / licensing notes<textarea name="permissions" placeholder="Collection, retention, analysis, redistribution, commercial-use restrictions" required maxlength="500"></textarea></label><label class="chk"><input type="checkbox" name="enabled"> Enable polling after reviewing access terms</label><button class="btn primary" type="submit">Register source</button><div id="source-feedback" class="form-feedback" role="status"></div></form></details>`;
    document.addEventListener('click', event=>{
      const button=event.target.closest('[data-priority-category]');if(!button)return;
      $('i-category').value=button.dataset.priorityCategory;render(currentTab,true);
    });
    document.addEventListener('click', handleClick);
    document.addEventListener('submit', handleSubmit);
    document.addEventListener('change', e => { if (e.target.closest('.research-controls') || e.target.id === 'i-saved') render(currentTab, true); });
    $('i-lifecycle').onclick = e => { const b = e.target.closest('[data-life]'); if (!b) return; $('i-lifecycle').querySelectorAll('button').forEach(el => el.classList.toggle('on', el === b)); render(currentTab, true); };
  }
  function settings() {
    return { query: $('filter').value.trim(), category: $('i-category').value, region: $('i-region').value, status: $('i-status').value,
      windowMs: WINDOWS[$('i-window').value], sort: $('i-sort').value, minImpact: Number($('i-impact').value), saved: $('i-saved').checked,
      lifecycle: $('i-lifecycle').querySelector('.on')?.dataset.life || '', type: $('type').querySelector('.on')?.dataset.v || '' };
  }
  function render(tabName = currentTab, force = false) {
    currentTab = tabName;
    const show = researchTabs.has(tabName);
    $('research-detail').hidden = !show; $('detail').hidden = show;
    document.body.classList.toggle('research-mode', show);
    if (!show) return;
    const stamp = engine.revision + ':' + Math.floor(Date.now() / 15000) + ':' + tabName + ':' + JSON.stringify(settings());
    if (!force && stamp === lastRender) return; lastRender = stamp;
    if (Date.now() - lastAlertCheck > 30000) { lastAlertCheck = Date.now(); engine.evaluateAlerts(); }
    if (tabName === 'intelligence') renderSignals();
    if (tabName === 'workspace' && (force || !document.activeElement?.closest('#tab-workspace form'))) renderWorkspace();
    if (tabName === 'registry') renderRegistry(force);
    renderDetail(force);
  }
  function renderSignals() {
    const signals = engine.signals(settings()), docs = [...engine.documents.values()], primary = docs.filter(d => d.tier === 'primary').length;
    $('research-metrics').innerHTML = [[docs.length.toLocaleString(), 'Archived records'], [signals.length, 'Matching signals'], [primary, 'Primary records'], [engine.state.claims.length, 'Reviewed claims']].map(([value, label]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
    const start = engine.state.startedAt, unavailable = !engine.archiveLoaded ? 'Opening evidence archive…' : engine.storageWarning;
    $('coverage-note').textContent = unavailable || (window.CrawlerServer?.connected ? `Server collection · ${$('i-window').value} window · ${signals.filter(s => s.baselineReady).length} signals with an available baseline. 24h scores include server collection history; other windows use the retained browser archive.` : `Collecting since ${date(start)}. ${$('i-window').value} window · ${signals.filter(s => s.baselineReady).length} signals with a complete collection-time baseline. Live sources can be delayed or unavailable.`);
    const categories = new Map();
    for(const signal of signals) { const category=signal.categories[0] || 'General';categories.set(category,(categories.get(category)||0)+1); }
    $('priority-briefing').innerHTML = `<div class="priority-desk"><div><span class="eyebrow">YOUR NEXT RESEARCH DECISION</span><h2>See what changed.<br>Know what needs a closer look.</h2><p>Follow source records, compare conflicting claims, and save the developments you want to track.</p></div><dl><div><dt>Emerging</dt><dd>${signals.filter(s=>s.lifecycle==='Emerging').length}</dd></div><div><dt>Contested</dt><dd>${signals.filter(s=>s.lifecycle==='Contested').length}</dd></div><div><dt>With primary records</dt><dd>${signals.filter(s=>s.primary>0).length}</dd></div></dl></div><nav class="priority-domains" aria-label="Signal categories">${[...categories].map(([name,count])=>`<button data-priority-category="${esc(name)}">${esc(name)} <span>${count}</span></button>`).join('')}${$('i-category').value?'<button data-priority-category="">Clear category ×</button>':''}</nav>`;
    $('signal-list').innerHTML = categoryPages(signals.slice(0, window.CrawlerSignalLimit || 60), (signal, i) => `
      <article class="signal-card${selected === signal.id ? ' selected' : ''}">
        <div class="signal-top"><span class="signal-number">${String(i + 1).padStart(2, '0')}</span><span class="signal-domains">${esc(signal.categories.join(' · ') || 'General research')}</span><span class="lifecycle">${esc(signal.lifecycle)}</span><button class="save-signal${engine.state.saved.includes(signal.id) ? ' saved' : ''}" data-save="${esc(signal.id)}" aria-label="${engine.state.saved.includes(signal.id) ? 'Remove from' : 'Add to'} watchlist" aria-pressed="${engine.state.saved.includes(signal.id)}">${engine.state.saved.includes(signal.id) ? '★' : '☆'}</button></div>
        <button class="signal-title" data-signal="${esc(signal.id)}">${esc(signal.title)}</button>
        <div class="signal-scores"><div class="momentum-score"><strong>${signal.momentum}<small>/100</small></strong><span>Attention momentum</span></div><div>${badge(signal.status)}<span class="dim sm">${esc(signal.confidence)}</span></div><div><strong>${signal.mentions}<small> records</small></strong><span>${signal.chains} candidate chain${signal.chains === 1 ? '' : 's'}</span></div></div>
        <p class="signal-source-summary"><small>SOURCE EXCERPT · ${esc(signal.documents[0]?.source || "Collected record")}</small>${esc((signal.documents[0]?.text || signal.documents[0]?.title || "").slice(0,200))}</p><div class="signal-watch"><span>WATCH NEXT</span><p>${esc(signal.watchNext)}</p></div>
        <div class="signal-bottom"><span>${signal.acceleration == null ? 'Baseline building' : signal.acceleration.toFixed(1) + '× prior window'} · ${signal.primary} primary · ${signal.coverageGaps.length} coverage gaps</span><button data-signal="${esc(signal.id)}">Open research ↗</button></div>
      </article>`) || empty('Waiting for a research signal', docs.length ? 'No collected records match these filters. Try a longer window or another domain.' : 'The crawler is gathering real records. Source health and custom feeds are available in Source registry.');
    if (!selected && signals.length) selected = signals[0].id;
  }
  function renderDetail(force) {
    const signal = selected ? engine.signalById(selected, Math.max(WINDOWS[$('i-window').value], 864e5)) || engine.signalById(selected) : null;
    if (!signal) { $('research-detail').innerHTML = `<div class="dossier-empty"><span class="eyebrow">RESEARCH VIEW</span>${empty('Every signal has a paper trail', 'Open a signal to inspect sources, individual claims, reporting lineage, relationships, and what would change the assessment.')}</div>`; return; }
    const key = selected + ':' + engine.revision + ':' + $('i-window').value;
    if (!force && lastDetail === key) return;
    if (!force && $('research-detail').contains(document.activeElement) && document.activeElement.matches('input,textarea,select')) return;
    lastDetail = key;
    const docs = signal.documents, claims = engine.claimsFor(signal.id), note = engine.state.notes[signal.id] || '';
    const detailRoot = $('research-detail');
    detailRoot._preserveOpen = detailRoot.dataset.signalId === signal.id ? [...detailRoot.querySelectorAll('.dossier-sections > details[open]')].map(item => item.dataset.detailKind || item.querySelector('summary')?.firstChild.textContent.trim()) : null;
    detailRoot.dataset.signalId = signal.id;
    $('research-detail').innerHTML = `<div class="dossier-head"><div class="eyebrow">SIGNAL RESEARCH · ${esc(signal.id)}</div><h2>${esc(signal.title)}</h2><div class="dossier-meta">${badge(signal.status)}<span>${esc(signal.confidence)}</span></div><p class="dim sm">${esc(signal.label)}</p><button class="btn" data-save="${esc(signal.id)}">${engine.state.saved.includes(signal.id) ? '★ Watching' : '☆ Add to watchlist'}</button></div>
      <div class="dossier-sections">
      <section><h3>Research brief</h3><dl class="research-brief"><dt>What is happening?</dt><dd>${docs.length} collected record(s) mention this candidate event. Their statements remain attributable to the linked sources.</dd><dt>Is it credible?</dt><dd>${signal.publishers} publisher families · ${signal.chains} candidate reporting chains · ${signal.primary} primary record(s). Independence and factual accuracy require claim-level review.</dd><dt>Why is it happening?</dt><dd>No causal explanation has been established by this local engine. Compare primary documents and alternative explanations below.</dd><dt>Why might it matter?</dt><dd>${esc(signal.categories.join(', ') || 'Domain not classified')}${signal.entities.length ? ' · linked symbols: ' + esc(signal.entities.join(', ')) : ''}. Impact ${signal.impact}/100 is a metadata heuristic, not an estimate of consequences.</dd><dt>What could happen next?</dt><dd>Record a conditional scenario with its assumptions and review date. Probabilities are unavailable without calibration.</dd><dt>What should I watch?</dt><dd>${esc(signal.watchNext)}</dd></dl></section>
      <section><h3>Coverage & uncertainty</h3><ul class="gap-list">${signal.coverageGaps.map(gap => `<li>${esc(gap)}</li>`).join('') || '<li>Coverage must still be checked against the affected region.</li>'}</ul><p class="dim sm">Region tags come from text, not verified publisher location. Translation and media provenance checks are not running.</p></section>
      <section><h3>Challenge the interpretation</h3><p>${esc(signal.invalidate)}</p><p class="dim sm">Research question: what direct evidence would show that the reported development or its assumed effects are wrong?</p></section>
      <details><summary>Ranking dimensions & calculation</summary><dl class="research-brief"><dt>Attention momentum · ${signal.momentum}/100</dt><dd>Logarithmic current publication count plus acceleration when a collection baseline exists. Measures activity.</dd><dt>Evidence strength · ${signal.credibility}/100</dt><dd>Unreviewed chains and primary records are capped at 45. Reviewed Verified or Corroborated claims score 80; misleading, contradicted, or retracted claims score 5. These are triage weights, not probabilities.</dd><dt>Potential impact · ${signal.impact}/100</dt><dd>Domain count, co-mentioned entities, and primary-record activity. Consequences remain unassessed.</dd><dt>Source diversity · ${signal.diversity}/100</dt><dd>Publisher-family and affected-region counts. Unknown ownership or geographic gaps can reduce its usefulness.</dd><dt>Uncertainty · ${signal.uncertainty}/100</dt><dd>A fixed penalty based on review status, not calibrated confidence.</dd><dt>Research priority · ${signal.rank}</dt><dd>0.30 × momentum + 0.30 × evidence strength + 0.25 × impact + 0.15 × diversity − 0.10 × uncertainty. Adjust rankings with the dashboard controls.</dd></dl></details>
      <details open><summary>Evidence & reporting lineage <span>${docs.length} records / ${signal.chains} candidate chains</span></summary><p class="dim sm">Grouping combines publisher families and near-identical headlines. These are candidates for analyst review; shared ownership and hidden syndication may remain undetected.</p>${signal.lineage.map((chain, i) => `<div class="lineage-group"><div class="chain-label">CHAIN ${i + 1} · ${chain.length} record(s)</div>${chain.slice(0, 12).map(doc => `<div class="evidence-document">${freshLink(doc)}<div class="pm">${esc(doc.source)} · ${esc(doc.tier)} · ${esc(doc.language)}${doc.correctedAt ? ' · source revised' : ''}</div><details><summary>Provenance & original retrieved fields</summary><dl class="provenance"><dt>Published</dt><dd>${date(doc.publishedAt)}${doc.publishedEstimated ? ' (estimated)' : ''}</dd><dt>Event time</dt><dd>${date(doc.eventAt)}</dd><dt>Retrieved</dt><dd>${date(doc.retrievedAt)}</dd><dt>Analyzed</dt><dd>${date(doc.analyzedAt)}</dd><dt>Corrected / changed</dt><dd>${date(doc.correctedAt)}</dd><dt>Publisher family</dt><dd>${esc(doc.family)}</dd></dl><pre>${esc(JSON.stringify(doc.raw, null, 2))}</pre>${doc.versions.length ? `<p class="dim sm">${doc.versions.length} previous source version(s), retained in export.</p>` : ''}</details></div>`).join('')}</div>`).join('')}</details>
      <details open><summary>Claim-level assessments <span>${claims.length} reviewed</span></summary><div id="claim-list">${claims.map(claim => `<article class="reviewed-claim">${badge(claim.status)} <span class="dim sm">${esc(claim.confidence)} analyst confidence${claim.needsReview ? ' · review required' : ''}</span><p>${esc(claim.text)}</p><p class="dim sm">${esc(claim.rationale)}</p><div class="claim-links">${claim.evidence.map(link => { const doc = engine.documents.get(link.documentId); return doc ? `<div class="sm">${esc(link.relation)}: ${freshLink(doc)}</div>` : ''; }).join('')}</div><button class="btn sm" data-edit-claim="${esc(claim.id)}">Revise assessment</button><details><summary>Assessment history</summary><p class="dim sm">Created ${date(claim.createdAt)} · updated ${date(claim.updatedAt)}</p>${claim.history.map(item => `<p class="sm">${date(item.at)} · ${esc(item.status)} · ${esc(item.rationale)}</p>`).join('') || '<p class="dim sm">First assessment.</p>'}</details></article>`).join('') || '<p class="dim sm">Statements have not been fact checked. Review a specific claim against the source records.</p>'}</div>
      <form id="claim-form" class="stack-form"><input type="hidden" name="eventId" value="${esc(signal.id)}"><input type="hidden" name="id"><label>Specific factual statement<textarea name="text" required maxlength="2000">${esc(signal.title)}</textarea></label><div class="form-columns"><label>Evidence status<select name="status">${model.STATUSES.map(s => `<option${s === 'Unverified' ? ' selected' : ''}>${s}</option>`).join('')}</select></label><label>Analyst confidence<select name="confidence"><option>Unassessed</option><option>Low</option><option>Medium</option><option>High</option></select></label></div><label>Why this assessment?<textarea name="rationale" required maxlength="4000" placeholder="Explain the direct evidence, contradictions, or missing context."></textarea></label><div class="evidence-picker"><span class="field-label">Link evidence to this statement</span>${docs.slice(0, 30).map(doc => `<label><span>${esc(doc.source)} · ${esc(doc.title.slice(0, 100))}</span><select data-evidence="${esc(doc.id)}"><option value="">Not linked</option><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="context">Context / correction</option></select></label>`).join('')}</div><label class="chk"><input type="checkbox" name="directEvidence"> I reviewed direct evidence for this specific claim.</label><label class="chk"><input type="checkbox" name="independenceReviewed"> I checked that the supporting records investigated the claim independently.</label><button class="btn primary" type="submit">Save claim assessment</button><div class="form-feedback" role="status"></div></form></details>
      <details><summary>Perspectives & factual disagreement</summary><p class="dim sm">Political framing is separate from factual support. No ideological label changes an evidence status.</p>${docs.slice(0, 8).map(doc => `<div class="perspective"><b>${esc(doc.source)}</b><p>${esc(doc.title)}</p><span class="dim sm">${/\b(says|claims|alleges|warns)\b/i.test(doc.title) ? 'Attributed statement; inspect the underlying evidence.' : 'Reported statement; framing and facts need separate review.'}</span></div>`).join('')}<p class="dim sm">Missing information: original documents, independent investigation, affected local perspectives, and alternative causal explanations may be absent. Different tone alone does not establish a factual contradiction.</p></details>
      <details><summary>Entity & evidence graph</summary>${graph(signal)}<p class="dim sm">Solid links: source records grouped into this candidate event. Dashed links: symbol co-mentions extracted from text. Co-mention does not establish ownership, causation, or a future market effect.</p></details>
      <details><summary>Attention over time</summary>${timeline(signal)}<p class="dim sm">Publication counts in six equal bins of the selected window. Missing collection intervals cannot be interpreted as zero activity. Current ${signal.mentions}; prior equal window ${signal.baselineReady ? signal.previous : 'unavailable'}.</p></details>
      <details open><summary>Investigation notes</summary><form id="note-form" class="stack-form"><input type="hidden" name="eventId" value="${esc(signal.id)}"><label>Questions, alternative explanations, and next steps<textarea name="text" rows="4" maxlength="20000" placeholder="Your notes remain separate from source evidence.">${esc(note)}</textarea></label><button class="btn" type="submit">Save notes</button><div class="form-feedback" role="status"></div></form></details>
      <details><summary>Record a conditional scenario</summary><form id="forecast-form" class="stack-form"><input type="hidden" name="eventId" value="${esc(signal.id)}"><label>Measurable outcome to monitor<textarea name="statement" required maxlength="2000" placeholder="If the proposal is finalized, watch for a published implementation schedule."></textarea></label><label>Assumptions & disconfirming evidence<textarea name="assumptions" required maxlength="2000"></textarea></label><label>Review on<input type="date" name="dueDate" required min="${new Date().toLocaleDateString('en-CA')}"></label><button class="btn" type="submit">Record scenario</button><div class="form-feedback" role="status"></div></form></details>
      </div>`;
    window.CrawlerHub?.compose();
  }
  function graph(signal) {
    const nodes = [...signal.documents.slice(0, 4).map(d => ({ label: d.source, inferred: false })), ...signal.entities.slice(0, 4).map(label => ({ label, inferred: true }))];
    if (!nodes.length) return '<p class="dim sm">No relationships have been extracted.</p>';
    return `<svg class="evidence-graph" viewBox="0 0 460 250" role="img" aria-label="Evidence and co-mentioned entity graph">${nodes.map((node, i) => { const x = i < 4 ? 100 : 360, y = 35 + (i % 4) * 59; return `<line x1="230" y1="125" x2="${x}" y2="${y}"${node.inferred ? ' stroke-dasharray="5 5"' : ''}/><rect x="${x - 78}" y="${y - 15}" width="156" height="30" rx="8"/><text x="${x}" y="${y + 4}" text-anchor="middle">${esc(node.label.slice(0, 22))}</text>`; }).join('')}<circle cx="230" cy="125" r="32"/><text x="230" y="130" text-anchor="middle">Event</text></svg>`;
  }
  function timeline(signal) {
    const now = Date.now(), windowMs = WINDOWS[$('i-window').value], bins = Array(6).fill(0);
    for (const doc of signal.documents) { const slot = Math.floor((doc.publishedAt - (now - windowMs)) / windowMs * 6); if (slot >= 0 && slot < 6) bins[slot]++; }
    const max = Math.max(1, ...bins);
    return `<div class="attention-chart" aria-label="Publication counts over the selected window">${bins.map((n, i) => `<div title="Bin ${i + 1}: ${n} records"><span>${n}</span><i style="height:${Math.max(3, n / max * 70)}px"></i></div>`).join('')}</div><div class="timeline-labels"><span>${date(now - windowMs)}</span><span>Now</span></div>`;
  }
  function renderWorkspace() {
    const state = engine.state, completed = state.forecasts.filter(f => f.resolvedAt).length;
    $('workspace-summary').innerHTML = `<div class="research-metrics">${[[state.saved.length, 'Saved signals'], [state.alerts.filter(a => a.enabled).length, 'Active monitors'], [state.forecasts.length, 'Recorded scenarios'], [completed, 'Evaluated outcomes']].map(([n, l]) => `<div><span>${l}</span><strong>${n}</strong></div>`).join('')}</div>`;
    $('workspace-alerts').innerHTML = state.alerts.map(a => `<div class="workspace-item"><div><b>${esc(a.query)}</b><p class="dim sm">Momentum ≥ ${a.minMomentum} · ${esc(a.status || 'Any status')} · ${a.enabled ? 'Active' : 'Paused'} · ${a.matches.length} current match(es)${a.triggeredAt ? ' · last match ' + date(a.triggeredAt) : ''}</p>${a.matches.slice(0, 5).map(id => button(id, 'Open matching signal', 'sm')).join('')}</div><button class="btn sm" data-toggle-alert="${esc(a.id)}">${a.enabled ? 'Pause' : 'Resume'}</button></div>`).join('') || '<p class="dim sm">No monitors yet.</p>';
    $('workspace-saved').innerHTML = state.saved.map(id => { const s = engine.signalById(id); return `<div class="workspace-item"><div>${s ? `<button class="text-button" data-signal="${esc(id)}">${esc(s.title)}</button><p class="dim sm">${esc(s.status)} · ${s.mentions} archived record(s)</p>` : `<b>${esc(id)}</b><p class="dim sm">No records available in the retained archive window.</p>`}${state.notes[id] ? `<p class="note-preview">${esc(state.notes[id].slice(0, 220))}</p>` : ''}</div><button class="btn sm" data-save="${esc(id)}">Remove</button></div>`; }).join('') || '<p class="dim sm">Save a signal from Intelligence to begin an investigation.</p>';
    $('workspace-forecasts').innerHTML = state.forecasts.map(f => `<article class="forecast-record"><span class="eyebrow">${esc(f.outcome)}${!f.resolvedAt && f.dueAt < Date.now() ? ' · REVIEW DUE' : ''}</span><h3>${esc(f.statement)}</h3><p class="dim sm">Recorded ${date(f.createdAt)} · review ${date(f.dueAt)} · ${esc(f.confidence)}</p><p><b>Assumptions:</b> ${esc(f.assumptions)}</p>${f.resolvedAt ? `<p><b>Resolution:</b> ${esc(f.resolution)}</p><p class="dim sm">Resolved ${date(f.resolvedAt)}</p>` : `<form class="stack-form outcome-form" data-forecast="${esc(f.id)}"><label>Outcome<select name="outcome"><option>Occurred</option><option>Did not occur</option><option>Inconclusive</option></select></label><label>Outcome evidence & source references<textarea name="resolution" required placeholder="Describe what happened and cite source URLs or archived document IDs."></textarea></label><button class="btn sm" type="submit">Record outcome</button><div class="form-feedback" role="status"></div></form>`}</article>`).join('') || '<p class="dim sm">No scenarios recorded. Open a signal to preserve an original forecast and its assumptions.</p>';
    $('workspace-audit').innerHTML = state.audit.slice(-30).reverse().map(a => `<div class="audit-item"><time>${date(a.at)}</time><b>${esc(a.action)}</b><p>${esc(a.detail)}</p></div>`).join('') || '<p class="dim sm">Research activity will appear here.</p>';
  }
  function registryEntries() {
    const entries = OUTLETS.map(([name, url, tier]) => ({ name, url, tier, family: model.sourceFamily(name), language: 'en', permissions: 'Provider terms not recorded', builtIn: true }));
    entries.push(...GN_OUTLETS.map(([name, , tier]) => ({ name, url: '', tier, family: model.sourceFamily(name), language: 'en', permissions: 'Search results / provider terms not recorded', builtIn: true })));
    entries.push(...engine.state.sources);
    const names = new Set(entries.map(s => s.name));
    for (const doc of engine.documents.values()) if (!names.has(doc.source)) { names.add(doc.source); entries.push({ name: doc.source, tier: doc.tier, family: doc.family, language: doc.language, permissions: 'Discovered; permissions not reviewed', discovered: true }); }
    return entries;
  }
  function renderRegistry(force) {
    const stamp = engine.revision + ':' + Math.floor(Date.now() / 15000); if (!force && stamp === registryStamp) return; registryStamp = stamp;
    const records = new Map(); for (const doc of engine.documents.values()) records.set(doc.source, (records.get(doc.source) || 0) + 1);
    const feeds = registryEntries(), failed = Object.values(feedStat).filter(s => !s.ok).length;
    $('registry-summary').innerHTML = `<p class="dim sm">${feeds.length} registered or discovered sources · ${failed} feeds reporting failures · ${new Set([...engine.documents.values()].map(d => d.language).filter(l => l !== 'unknown')).size} identified language(s). Licensing metadata is descriptive and does not grant rights.</p>`;
    $('registry-rows').innerHTML = feeds.map(source => {
      const health = feedStat[source.name], label = health ? health.ok ? 'Healthy' : 'Unavailable' : source.discovered ? 'Observed via aggregator' : 'Not checked';
      return `<tr><td><b>${esc(source.name)}</b><small>${esc(source.family)}</small></td><td>${esc(source.tier)}<small>${esc(source.language || 'unknown')}${source.region ? ' · ' + esc(source.region) : ''}</small></td><td><span class="health-label ${health ? health.ok ? 'up' : 'down' : 'dim'}">${esc(label)}</span><small>${health ? date(health.checkedAt) : 'No direct health sample'}</small>${health?.msg ? `<small>${esc(health.msg)}</small>` : ''}</td><td>${records.get(source.name) || 0}</td><td><small>${esc(source.permissions)}</small>${source.id ? `<button class="btn sm" data-toggle-source="${esc(source.id)}">${source.enabled ? 'Pause' : 'Enable'} polling</button>` : '<small>Existing connector</small>'}</td></tr>`;
    }).join('');
  }
  async function ask(question) {
    if (window.CrawlerServer?.connected) {
      $('research-chat').innerHTML = '<div class="dim sm">Searching collected evidence…</div>';
      window.dispatchEvent(new CustomEvent('crawler:research-answer'));
      try {
        const result = await window.CrawlerServer.research(question);
        const docs = new Map(result.documents.map(doc => [doc.id, doc]));
        const answer = `<p>${esc(result.answer)}</p>${result.assertions.map(item => `<div class="chat-result"><p>${esc(item.text)}</p>${item.documentIds.map((id, i) => { const doc = docs.get(id); return doc ? `<div class="sm"><a href="${esc(safeURL(doc.url))}" target="_blank" rel="noopener noreferrer">${esc(doc.source)} ↗</a><blockquote>${esc(item.quotes[i])}</blockquote></div>` : ''; }).join('')}</div>`).join('')}<p class="dim sm">${result.uncertainties.map(esc).join(' ')}</p><div class="question-suggestions">${result.nextQuestions.map(text => `<button class="fchip" data-question="${esc(text)}">${esc(text)}</button>`).join('')}</div>`;
        chat.push({ question, answer }); chat = chat.slice(-15);
        $('research-chat').innerHTML = chat.map(entry => `<div class="chat-question">${esc(entry.question)}</div><div class="chat-answer">${entry.answer}</div>`).join('');
        $('research-query').value = '';
      } catch (error) { $('research-chat').innerHTML = `<p class="form-feedback error">${esc(error.message)}</p>`; }
      return;
    }
    let q = question.trim(); if (!q) return;
    const lower = q.toLowerCase(), followup = /^(what changed|what about|and |why |show (me )?(the )?(sources|evidence)|what would)/i.test(q);
    const domain = Object.keys(model.CATEGORIES).find(c => lower.includes(c.toLowerCase()) || (c === 'Technology' && /semiconductor|chips|\bai\b/.test(lower)) || (c === 'Equities' && /stocks|shares/.test(lower)));
    const namesInQuestion = [...new Set([...engine.documents.values()].flatMap(d => d.entities))].filter(name => new RegExp('\\b' + name.replace(/[^\w]/g, '') + '\\b', 'i').test(q));
    const useful = model.tokens(q).filter(t => !new Set('what which stories developments should watch happening about show sources evidence independent verification lack primary have changed emerging strongest arguments against interpretation following please explain last hours'.split(' ')).has(t));
    let term = namesInQuestion[0] || (domain ? '' : useful.slice(0, 2).join(' '));
    if (followup && !term && !domain) term = chatContext;
    if (term) chatContext = term; else if (domain) chatContext = domain;
    let found = engine.signals({ windowMs: WINDOWS[$('i-window').value], category: domain || '', query: term });
    if (/unverified|verification|unconfirmed|lack/.test(lower)) found = found.filter(s => !['Verified', 'Corroborated'].includes(s.status));
    if (/primary/.test(lower)) found = found.filter(s => s.primary > 0);
    if (/changed|48 hours|last 48/.test(lower)) found = found.filter(s => Date.now() - s.lastPublished < 1728e5);
    const answer = found.length ? `<p>I found ${found.length} matching candidate event(s) in the selected archive window${chatContext ? ' for ' + esc(chatContext) : ''}. These are collected observations; causal effects and future outcomes are not established.</p>${found.slice(0, 5).map(s => `<div class="chat-result"><button class="text-button" data-signal="${esc(s.id)}">${esc(s.title)}</button><p class="sm">${esc(s.status)} · ${s.mentions} records · ${s.chains} candidate chain(s). ${esc(s.watchNext)}</p><div class="sm dim">Evidence: ${s.documents.slice(0, 3).map((d, i) => `<a href="${esc(safeURL(d.url))}" target="_blank" rel="noopener noreferrer">[${i + 1}] ${esc(d.source)}</a>`).join(' · ')}</div>${/changed/.test(lower) ? `<p class="sm dim">${s.documents.filter(d => d.correctedAt).length} source revision(s); ${engine.claimsFor(s.id).reduce((n, c) => n + c.history.length, 0)} assessment revision(s). A full historical comparison needs the retained records.</p>` : ''}</div>`).join('')}<p class="dim sm">${found.some(s => s.coverageGaps.length) ? 'Coverage gaps remain. Inspect each research view before drawing a conclusion.' : 'Review the linked evidence for context.'}</p>` : '<p>Insufficient evidence in this collection to answer that question. Try an entity, a domain such as Technology or Politics, or a longer window. The local assistant cannot retrieve additional sources on demand or establish an unreported causal relationship.</p>';
    chat.push({ question: q, answer }); if (chat.length > 15) chat.shift();
    $('research-chat').innerHTML = chat.map(entry => `<div class="chat-question">${esc(entry.question)}</div><div class="chat-answer"><span class="eyebrow">COLLECTION RESEARCH</span>${entry.answer}</div>`).join('');
    $('research-query').value = ''; $('research-chat').scrollTop = $('research-chat').scrollHeight;
    window.dispatchEvent(new CustomEvent('crawler:research-answer'));
  }
  function handleClick(e) {
    const target = e.target.closest('button'); if (!target) return;
    if (target.dataset.signal) { selected = target.dataset.signal; lastDetail = ''; render(currentTab, true); if (innerWidth < 1000) $('research-detail').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    if (target.dataset.save) { engine.toggleSaved(target.dataset.save); render(currentTab, true); }
    if (target.dataset.toggleAlert) { engine.toggleAlert(target.dataset.toggleAlert); renderWorkspace(); }
    if (target.dataset.toggleSource) { engine.toggleSource(target.dataset.toggleSource); renderRegistry(true); }
    if (target.dataset.question) ask(target.dataset.question);
    if (target.id === 'clear-chat') { chat = []; chatContext = ''; $('research-chat').innerHTML = empty('Start a new investigation', 'Your next question starts with fresh topic context.'); }
    if (target.id === 'export-research') {
      engine.flush(); const blob = new Blob([JSON.stringify(engine.exportData(), null, 2)], { type: 'application/json' }), url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = 'trend-crawler-research-' + new Date().toISOString().slice(0, 10) + '.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    if (target.dataset.editClaim) {
      const claim = engine.state.claims.find(c => c.id === target.dataset.editClaim), form = $('claim-form'); if (!claim || !form) return;
      for (const name of ['id', 'text', 'status', 'rationale', 'confidence']) form.elements[name].value = claim[name];
      form.elements.directEvidence.checked = claim.directEvidence; form.elements.independenceReviewed.checked = claim.independenceReviewed;
      form.querySelectorAll('[data-evidence]').forEach(select => { select.value = claim.evidence.find(link => link.documentId === select.dataset.evidence)?.relation || ''; });
      form.scrollIntoView({ behavior: 'smooth', block: 'center' }); form.elements.text.focus();
    }
  }
  async function handleSubmit(e) {
    const form = e.target, formId = form.getAttribute('id');
    if (!['research-question', 'alert-form', 'claim-form', 'note-form', 'forecast-form', 'source-form'].includes(formId) && !form.classList.contains('outcome-form')) return;
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form)), feedback = form.querySelector('.form-feedback');
    try {
      if (formId === 'research-question') { ask($('research-query').value); return; }
      if (formId === 'alert-form') {
        if (window.CrawlerServer?.connected) await window.CrawlerServer.mutation('monitors', data);
        else { engine.addAlert(data); engine.evaluateAlerts(); }
        form.reset(); renderWorkspace();
      }
      if (formId === 'note-form') { engine.saveNote(data.eventId, data.text); }
      if (formId === 'claim-form') { data.evidence = [...form.querySelectorAll('[data-evidence]')].filter(el => el.value).map(el => ({ documentId: el.dataset.evidence, relation: el.value })); engine.reviewClaim(data); lastDetail = ''; renderDetail(true); }
      if (formId === 'forecast-form') { const values = { ...data, dueAt: new Date(data.dueDate + 'T23:59:59').getTime() }; if (window.CrawlerServer?.connected) await window.CrawlerServer.mutation('forecasts', { ...values, eventId: window.CrawlerServer.serverEvent(data.eventId) }); else engine.addForecast(values); form.reset(); }
      if (form.classList.contains('outcome-form')) { engine.resolveForecast(form.dataset.forecast, data.outcome, data.resolution); renderWorkspace(); }
      if (formId === 'source-form') { if (window.CrawlerServer?.connected) await window.CrawlerServer.mutation('sources', { ...data, enabled: !!data.enabled, kind: 'rss' }); else engine.addSource(data); form.reset(); renderRegistry(true); }
      if (feedback?.isConnected) { feedback.textContent = 'Saved.'; feedback.classList.remove('error'); }
      if (formId === 'claim-form') { const current = $('claim-form').querySelector('.form-feedback'); current.textContent = 'Claim assessment saved with its evidence and history.'; }
    } catch (error) { if (feedback) { feedback.textContent = error.message; feedback.classList.add('error'); } else announce(error.message, true); }
  }
  // Custom sources are isolated, retried with exponential backoff, and never block existing connectors.
  const customHealth = new Map(); let customPolling = false;
  async function pollCustom() {
    if (document.hidden || customPolling || window.CrawlerServer?.connected) return;
    const now = Date.now(), source = engine.state.sources.find(s => s.enabled && (customHealth.get(s.id)?.next || 0) <= now); if (!source) return;
    customPolling = true; const health = customHealth.get(source.id) || { failures: 0, next: 0 };
    try {
      const xml = await fetchAny(source.url, parseXML), items = feedItems(xml); let added = 0;
      for (const item of items) {
        if (!item.link) continue;
        const before = engine.documents.size;
        addPost({ ...outletPost(source.name, source.tier, item), language: source.language, region: source.region || undefined });
        if (engine.documents.size > before) added++;
      }
      health.failures = 0; health.next = now + (added > 10 ? 120000 : added ? source.interval : source.interval * 2);
      feedHealth(source.name, true); setStatus('Custom feeds', true);
    } catch (error) {
      health.failures++; health.next = now + source.interval * Math.min(16, 2 ** health.failures);
      feedHealth(source.name, false, error.message); setStatus('Custom feeds', false, error.message);
    } finally { customHealth.set(source.id, health); customPolling = false; }
  }
  initialize();
  window.IntelligenceUI = { render, ask, get selected() { return selected; }, selectedSignal() { return selected ? engine.signalById(selected) : null; } };
  setInterval(pollCustom, 5000);
})();

