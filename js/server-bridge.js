/* Same-origin research API. API keys never enter this module or browser storage. */
(() => {
  'use strict';
  const engine = window.CrawlerIntelligence;
  let connected = false, session = null, health = null, cursor = { at: 0, id: '' }, pulling = false;
  let serverSources = [], workspace = null, operations = null, metrics = [], lastFailure = '', syncTimer, hydrated = false;
  const dossiers = new Map(), pendingDossiers = new Set();
  let probing = null, refreshing = null;
  const inWorkspace = () => !document.body.dataset.experience || document.body.dataset.experience === 'workspace';
  const emit = () => window.dispatchEvent(new CustomEvent('crawler:server-state'));
  async function request(path, body, timeout = 45000) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Crawler-CSRF': session?.csrf || '' }, body: body === undefined ? undefined : JSON.stringify(body) });
      const result = await response.json().catch(() => ({ error: 'Research API did not return JSON.' }));
      if (!response.ok) throw new Error(result.error || 'Research service request failed.');
      return result;
    } finally { clearTimeout(timer); }
  }
  function probe() {
    if (probing) return probing;
    probing = probeOnce().finally(() => { probing = null; });
    return probing;
  }
  async function probeOnce() {
    if (!/^https?:$/.test(location.protocol)) { emit(); return; }
    try {
      const result = await request('ready', undefined, 5000);
      if (result.service !== 'trend-crawler') return;
      health = result;
      session = await request('session', undefined, 5000); connected = !!session.authorized;
      lastFailure = '';
    } catch { connected = false; health = null; lastFailure = 'The research API is unavailable at this address. Open the URL printed by the Python server.'; }
    emit();
    if (connected && inWorkspace()) { refresh().catch(() => {}); pull().catch(() => {}); }
  }
  function refresh() {
    if (refreshing) return refreshing;
    refreshing = refreshOnce().finally(() => { refreshing = null; });
    return refreshing;
  }
  async function refreshOnce() {
    if (!connected) return;
    const results = await Promise.allSettled([request('sources'), request('workspace'), request('operations'), request('metrics'), request('events')]);
    if (results[0].status === 'fulfilled') serverSources = results[0].value.sources;
    if (results[1].status === 'fulfilled') workspace = results[1].value;
    if (results[2].status === 'fulfilled') { operations = results[2].value; health = operations.health; }
    if (results[3].status === 'fulfilled') metrics = results[3].value.observations;
    if (results[4].status === 'fulfilled') engine.setServerAnalyses(results[4].value.events);
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
      dossiers.set(serverId, { value, fetchedAt: Date.now() });
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
    try { const result = await request(path, body); if (/^(claims\/|investigate|documents\/)/.test(path)) dossiers.clear(); lastFailure = ''; await refresh(); return result; }
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
    async login(token) { session = await request('login', { token }); connected = !!session.authorized; emit(); if (inWorkspace()) { refresh().catch(() => {}); pull().catch(() => {}); } },
    research(question) { return mutation('research', { question, conversationId: 'research-desk' }); },
    async investigate(signal) { const eventId = serverEvent(signal.id); if (!eventId) throw new Error('This signal has not been collected by the research server.'); return mutation('investigate', { eventId }); }
  };
  window.addEventListener('DOMContentLoaded', probe);
  setInterval(() => { if (!document.hidden) { if (connected && inWorkspace()) pull(); else if (!connected) probe(); } }, 10000);
  setInterval(() => { if (connected && !document.hidden && inWorkspace()) refresh().catch(() => {}); }, 30000);
})();
