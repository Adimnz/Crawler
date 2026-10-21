/* Same-origin research API. API keys never enter this module or browser storage. */
(() => {
  'use strict';
  const engine = window.CrawlerIntelligence;
  let connected = false, session = null, health = null, cursor = { at: 0, id: '' }, pulling = false;
  let serverSources = [], workspace = null, operations = null, metrics = [], lastFailure = '', syncTimer, hydrated = false;
  const dossiers = new Map(), pendingDossiers = new Set();
  let probing = null, refreshing = null, everConnected = false, shuttingDown = false;
  let nextProbeAt = 0, retryDelay = 15000, lastUpdate = {};
  const inWorkspace = () => !document.body.dataset.experience || document.body.dataset.experience === 'workspace';
  const emit = () => window.dispatchEvent(new CustomEvent('crawler:server-state'));
  function lifecycleUI() {
    if (!document.body) return;
    let banner = document.getElementById('crawler-server-lifecycle');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'crawler-server-lifecycle';
      banner.className = 'crawler-server-lifecycle';
      banner.setAttribute('role', 'status');
      banner.setAttribute('aria-live', 'polite');
      banner.innerHTML = '<strong id="crawler-lifecycle-heading"></strong><span id="crawler-lifecycle-message"></span><button id="crawler-server-retry" type="button">Reconnect</button>';
      banner.querySelector('button').addEventListener('click', () => { nextProbeAt = 0; probe(); });
      document.body.append(banner);
    }
    banner.hidden = connected || !everConnected;
    if (!banner.hidden) {
      banner.querySelector('strong').textContent = shuttingDown ? 'Research server is shutting down' : 'Research server is offline';
      banner.querySelector('span').textContent = shuttingDown
        ? 'Research collection is stopping. Saved boards remain on disk. This browser tab cannot be forcibly closed by a local server.'
        : 'Background research and live updates are unavailable. Start the Python server again, then reconnect.';
    }
    for (const button of document.querySelectorAll('[data-stop-crawler-server]')) {
      button.hidden = !connected || !session?.ownerAuthorized;
    }
  }
  function disconnected(stopping = false) {
    if (!connected && !everConnected && !stopping) return;
    const changed = connected || (!shuttingDown && stopping);
    connected = false; health = null; shuttingDown = shuttingDown || stopping;
    nextProbeAt = Date.now() + retryDelay;
    retryDelay = Math.min(60000, retryDelay * 2);
    lifecycleUI(); if (changed) emit();
  }
  async function request(path, body, timeout = 45000) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Crawler-CSRF': session?.csrf || '' }, body: body === undefined ? undefined : JSON.stringify(body) });
      const result = await response.json().catch(() => ({ error: 'Research API did not return JSON.' }));
      if (result.status === 'stopping') disconnected(true);
      if (!response.ok) throw new Error(result.error || 'Research service request failed.');
      return result;
    } catch (error) {
      if (error instanceof TypeError || error.name === 'AbortError') disconnected();
      throw error;
    } finally { clearTimeout(timer); }
  }
  function probe() {
    if (probing) return probing;
    probing = probeOnce().finally(() => { probing = null; });
    return probing;
  }
  async function probeOnce() {
    if (!/^https?:$/.test(location.protocol)) { emit(); return; }
    const wasConnected = connected;
    try {
      const result = await request('ready', undefined, 5000);
      if (result.service !== 'trend-crawler' || !result.ready) throw new Error('Research server not ready');
      health = result;
      if (!wasConnected) session = await request('session', undefined, 5000);
      connected = !!session?.authorized;
      if (connected) { everConnected = true; shuttingDown = false; retryDelay = 15000; nextProbeAt = 0; }
      lastFailure = '';
    } catch {
      disconnected();
      lastFailure = 'The research API is unavailable at this address. Open the URL printed by the Python server.';
    }
    lifecycleUI(); if (connected !== wasConnected) emit();
    if (connected && !wasConnected && inWorkspace()) { refresh(true).catch(() => {}); pull().catch(() => {}); }
  }
  function refresh(force = false) {
    if (refreshing) return refreshing;
    refreshing = refreshOnce(force).finally(() => { refreshing = null; });
    return refreshing;
  }
  async function refreshOnce(force = false) {
    if (!connected || document.hidden) return;
    const cadence = {sources:120000,workspace:60000,operations:90000,metrics:120000,events:60000};
    const names = Object.keys(cadence).filter(name => force || Date.now() - (lastUpdate[name] || 0) > cadence[name]);
    const results = await Promise.allSettled(names.map(name => request(name)));
    for (let index=0; index<names.length; index++) {
      const name=names[index], result=results[index];
      if (result.status !== 'fulfilled') continue;
      lastUpdate[name]=Date.now();
      if (name==='sources') serverSources=result.value.sources;
      if (name==='workspace') workspace=result.value;
      if (name==='operations') { operations=result.value; health=operations.health; }
      if (name==='metrics') metrics=result.value.observations;
      if (name==='events') engine.setServerAnalyses(result.value.events);
    }
    for (const source of serverSources) if (source.health) {
      feedStat[source.name] = { ok: source.health.ok, okN: source.health.successes || 0, total: source.health.checks || 0, msg: source.health.error || '', checkedAt: source.health.checkedAt };
      sources[source.name] = { ok: source.health.ok, okN: source.health.successes || 0, total: source.health.checks || 0, msg: source.health.error || '', checkedAt: source.health.checkedAt };
    }
    if (serverSources.length) {
      const good = serverSources.filter(s => s.enabled && s.health?.ok).length, enabled = serverSources.filter(s => s.enabled).length;
      $('srctxt').textContent = good + '/' + enabled + ' feeds healthy'; $('srcdot').className = 'dotc ' + (good ? 'up' : '');
    }
    emit();
  }
  async function pull() {
    if (!connected || pulling) return;
    pulling = true;
    try {
      for (let page = 0; page < 10; page++) {
        const result = await request('documents?after=' + cursor.at + '&afterId=' + encodeURIComponent(cursor.id));
        for (const doc of result.documents) {
          const syms = (doc.entities || []).flatMap(entity => entity.id.startsWith('equity:') || entity.id.startsWith('unresolved:ticker:') ? [entity.id.split(':').pop()] : entity.id === 'crypto:coingecko:bitcoin' ? ['BTC'] : entity.id === 'crypto:coingecko:ethereum' ? ['ETH'] : []);
          const post = { id: 'server-' + doc.id, src: 'News', outlet: true, listed: true, title: doc.title, text: doc.text, url: doc.url, sub: doc.source, tier: doc.tier, language: doc.language, ts: doc.publishedAt, publishedEstimated: doc.publishedEstimated, eventAt: doc.eventAt, syms, categories: doc.categories,
            serverId: doc.id, serverEventId: doc.eventId, translation: doc.translation,
            raw: { title: doc.title, text: doc.text, source: doc.source, url: doc.url, sourceVersion: doc.version, sourceRetrievedAt: doc.retrievedAt, objectKey: doc.objectKey } };
          addPost(post);
          // The active post store may have already seen this text while derived analysis changed.
          engine.ingest(post, { text: post.text, url: post.url, source: post.sub, publishedAt: post.ts, ...post.raw });
        }
        cursor = result.cursor;
        if (!result.hasMore) break;
      }
      engine.mergeServerEvents();
      if (!hydrated && workspace?.saved) {
        const localId = id => [...engine.documents.values()].find(doc => doc.serverEventId === id)?.eventId || id;
        engine.state.saved = [...new Set([...engine.state.saved, ...(workspace.saved.saved || []).map(localId)])];
        for (const [id, note] of Object.entries(workspace.saved.notes || {})) if (!engine.state.notes[localId(id)]) engine.state.notes[localId(id)] = note;
        engine.persist(); hydrated = true;
      }
      engine.flush(); lastFailure = '';
    } catch (error) { lastFailure = error.message; }
    finally { pulling = false; emit(); }
  }
  function serverEvent(localEventId) {
    return [...engine.documents.values()].find(doc => doc.eventId === localEventId && doc.serverEventId)?.serverEventId;
  }
  async function dossier(signal) {
    const serverId = signal?.documents.find(doc => doc.serverId)?.serverId;
    if (!connected || !serverId) return null;
    if (dossiers.has(serverId) && Date.now() - dossiers.get(serverId).fetchedAt < 30000) return dossiers.get(serverId).value;
    if (pendingDossiers.has(serverId)) return dossiers.get(serverId)?.value || null;
    pendingDossiers.add(serverId);
    try {
      const value = await request('dossier?documentId=' + encodeURIComponent(serverId));
      dossiers.delete(serverId);
      dossiers.set(serverId, { value, fetchedAt: Date.now() });
      if (dossiers.size > 120) dossiers.delete(dossiers.keys().next().value);
      let reviewedChanged = false;
      const localDocs = new Map([...engine.documents.values()].filter(d => d.serverId).map(d => [d.serverId, d]));
      for (const claim of value.claims) {
        const id = 'server-review-' + claim.id, existing = engine.state.claims.find(c => c.id === id), local = localDocs.get(claim.documentId);
        if (!local || (!existing && claim.reviewRequired)) continue;
        if (existing?.updatedAt === claim.updatedAt) continue;
        const reviewed = { id, serverId: claim.id, eventId: local.eventId, text: claim.text, status: claim.status, rationale: claim.rationale || 'Source changed; assessment needs review.', confidence: 'Analyst reviewed',
          evidence: (claim.evidence || []).filter(link => localDocs.has(link.documentId)).map(link => ({ ...link, documentId: localDocs.get(link.documentId).id })), directEvidence: claim.directEvidenceReviewed, independenceReviewed: claim.independenceReviewed, needsReview: claim.reviewRequired, createdAt: claim.createdAt, updatedAt: claim.updatedAt, history: claim.history || [] };
        if (existing) engine.state.claims[engine.state.claims.indexOf(existing)] = reviewed; else engine.state.claims.push(reviewed);
        reviewedChanged = true;
      }
      if (reviewedChanged) engine.persist(); emit(); return value;
    } catch (error) { lastFailure = error.message; return null; }
    finally { pendingDossiers.delete(serverId); }
  }
  function cachedDossier(signal) { const id = signal?.documents.find(doc => doc.serverId)?.serverId; return dossiers.get(id)?.value || null; }
  async function mutation(path, body) {
    try { const result = await request(path, body); if (/^(claims\/|investigate|documents\/)/.test(path)) dossiers.clear(); lastFailure = ''; await refresh(true); return result; }
    catch (error) { lastFailure = error.message; emit(); throw error; }
  }
  function queueWorkspaceSync() {
    if (!connected) return;
    clearTimeout(syncTimer); syncTimer = setTimeout(() => mutation('workspace', { saved: engine.state.saved.map(id => serverEvent(id) || id), notes: Object.fromEntries(Object.entries(engine.state.notes).map(([id, text]) => [serverEvent(id) || id, text])) }).catch(() => {}), 600);
  }
  for (const name of ['toggleSaved', 'saveNote']) {
    const original = engine[name]; engine[name] = (...args) => { const result = original(...args); queueWorkspaceSync(); return result; };
  }
  window.CrawlerServer = {
    request, refresh, pull, probe, dossier, cachedDossier, mutation, serverEvent,
    get connected() { return connected; }, get health() { return health; }, get session() { return session; }, get sources() { return serverSources; }, get workspace() { return workspace; }, get operations() { return operations; }, get metrics() { return metrics; }, get error() { return lastFailure; },
    async login(token) { session = await request('login', { token }); connected = !!session.authorized; if (connected) { everConnected = true; shuttingDown = false; } lifecycleUI(); emit(); if (inWorkspace()) { refresh().catch(() => {}); pull().catch(() => {}); } },
    async shutdown() {
      if (!connected || !session?.ownerAuthorized) throw new Error('Only the research server owner can stop it.');
      const result = await request('control/shutdown', {});
      shuttingDown = true; disconnected(true); return result;
    },
    research(question) { return mutation('research', { question, conversationId: 'research-desk' }); },
    async investigate(signal) { const eventId = serverEvent(signal.id); if (!eventId) throw new Error('This signal has not been collected by the research server.'); return mutation('investigate', { eventId }); }
  };
  document.addEventListener('click', async event => {
    if (!event.target.closest('[data-stop-crawler-server]')) return;
    if (!confirm('Stop the research server? Collection and scheduled research will stop; browser tabs will display an offline notice.')) return;
    try { await window.CrawlerServer.shutdown(); }
    catch (error) { lastFailure = error.message; lifecycleUI(); }
  });
  window.addEventListener('DOMContentLoaded', () => { lifecycleUI(); probe(); });
  window.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() >= nextProbeAt) probe(); });
  setInterval(() => {
    if (document.hidden) return;
    if (connected) { probe(); if (inWorkspace()) pull(); }
    else if (Date.now() >= nextProbeAt) probe();
  }, 15000);
  setInterval(() => { if (connected && !document.hidden && inWorkspace()) refresh().catch(() => {}); }, 60000);
})();
