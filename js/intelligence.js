/* Browser-local evidence engine. No retrieved text is evaluated as code or instructions. */
(() => {
  'use strict';
  const HOUR = 36e5, DAY_MS = 24 * HOUR, MAX_DOCUMENTS = 12000;
  const STATUSES = ['Verified', 'Corroborated', 'Developing', 'Unverified', 'Disputed', 'Misleading', 'Contradicted', 'Retracted'];
  const STOPWORDS = new Set('the a an and or of to in on for from at by with as is are was were be has have had that this it its says said new news live update updates report reports latest after before amid over into about will may could would'.split(' '));
  const CATEGORIES = {
    Politics: /\b(election|congress|parliament|president|minister|legislation|bill|regulat\w*|sanction\w*|tariff\w*|government|politic\w*)\b/i,
    Crypto: /\b(crypto\w*|bitcoin|ethereum|blockchain|stablecoin|defi|token\w*|btc|eth|solana)\b/i,
    Technology: /\b(ai|artificial intelligence|chip\w*|semiconductor\w*|technology|software|cyber\w*|comput\w*|nvidia|github)\b/i,
    Economics: /\b(inflation|employment|gdp|econom\w*|interest rates?|central bank|federal reserve|unemployment|cpi)\b/i,
    Science: /\b(research\w*|scient\w*|study|clinical|vaccine|pubmed|arxiv|health|climate)\b/i,
    Equities: /\b(stock\w*|shares|earnings|nasdaq|equities|ipo|dividend|revenue|merger|investor\w*)\b/i,
    Trade: /\b(trade|shipping|logistics|port|oil|gas|energy|commodit\w*|supply chain|export\w*)\b/i,
    Social: /\b(social|campaign|viral|reddit|bluesky|mastodon|twitch|influencer\w*)\b/i
  };
  const REGIONS = {
    'North America': /\b(us|u\.s\.|united states|american|canada|canadian|mexico|washington|congress|federal reserve)\b/i,
    Europe: /\b(europe\w*|eu|ecb|uk|britain|british|england|france|german\w*|brussels|ukraine|russia\w*)\b/i,
    'Asia Pacific': /\b(asia\w*|china|chinese|japan\w*|india\w*|taiwan\w*|korea\w*|australia\w*|singapore|hong kong)\b/i,
    'Middle East': /\b(middle east|israel\w*|iran\w*|saudi|gaza|lebanon|qatar|uae)\b/i,
    Africa: /\b(africa\w*|nigeria\w*|kenya\w*|egypt\w*|ethiopia\w*)\b/i,
    'Latin America': /\b(latin america|brazil\w*|argentina|chile|colombia\w*|peru)\b/i
  };
  const hash = text => { let value = 2166136261; for (const c of String(text)) value = Math.imul(value ^ c.charCodeAt(0), 16777619); return (value >>> 0).toString(36); };
  const tokens = text => [...new Set((String(text).toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => t.length > 2 && !STOPWORDS.has(t)))];
  const similarity = (a, b) => { const right = new Set(b); const shared = a.filter(t => right.has(t)).length; return shared / Math.max(1, a.length + b.length - shared); };
  const canonicalURL = value => {
    try { const url = new URL(value); if (!['https:', 'http:'].includes(url.protocol)) return ''; url.hash = ''; for (const key of [...url.searchParams.keys()]) if (/^(utm_|fbclid|gclid|ref$)/i.test(key)) url.searchParams.delete(key); url.searchParams.sort(); return url.href; } catch { return ''; }
  };
  const sourceFamily = name => String(name || 'Unknown').toLowerCase().split(' via ')[0].replace(/\s*\([^)]*\)/g, '').replace(/\b(markets?|business|politics|investing|economy|press|8-k filings)\b/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim() || 'unknown';
  const infer = (text, patterns) => Object.entries(patterns).filter(([, pattern]) => pattern.test(text)).map(([name]) => name);
  const uid = prefix => prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  const clone = value => JSON.parse(JSON.stringify(value));

  function createEngine(options = {}) {
    const documents = new Map(), dirty = new Set(), listeners = new Set(), tokenIndex = new Map(), eventIndex = new Map(), serverAnalyses = new Map();
    const storageKey = 'trend-crawler-research-v1';
    let db = null, revision = 0, storageWarning = '', archiveLoaded = false;
    let state = { version: 1, startedAt: Date.now(), coverage: [], saved: [], notes: {}, claims: [], alerts: [], forecasts: [], sources: [], sourceOverrides: {}, audit: [] };
    if (!options.memory) {
      try { const saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); if (saved?.version === 1) state = { ...state, ...saved }; } catch { storageWarning = 'Workspace storage is unavailable. Export your research before closing this page.'; }
    }
    const notify = () => { revision++; listeners.forEach(listener => listener()); };
    function persist() {
      if (!options.memory) try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch { storageWarning = 'Workspace storage is full or unavailable. Export your research to preserve changes.'; }
      notify();
    }
    function recordCoverage(now = Date.now()) {
      const last = state.coverage[state.coverage.length - 1];
      if (last && now - last.end <= 90000) last.end = now;
      else state.coverage.push({ start: now, end: now });
      state.coverage = state.coverage.filter(span => span.end >= now - 366 * DAY_MS).slice(-5000);
      persist();
    }
    function coverageRatio(start, end) {
      const covered = state.coverage.reduce((sum, span) => sum + Math.max(0, Math.min(span.end, end) - Math.max(span.start, start)), 0);
      return Math.min(1, covered / Math.max(1, end - start));
    }
    function audit(action, subject, detail) {
      state.audit.push({ id: uid('audit'), at: Date.now(), action, subject, detail });
      if (state.audit.length > 1500) state.audit.splice(0, state.audit.length - 1500);
    }
    function index(doc) {
      for (const token of doc.keywords) { if (!tokenIndex.has(token)) tokenIndex.set(token, new Set()); tokenIndex.get(token).add(doc.id); }
      if (!eventIndex.has(doc.eventId)) eventIndex.set(doc.eventId, new Set()); eventIndex.get(doc.eventId).add(doc.id);
    }
    function eventFor(keywords, at) {
      const candidates = new Set();
      for (const token of keywords) for (const id of tokenIndex.get(token) || []) candidates.add(id);
      let best = null, score = .51;
      for (const id of [...candidates].slice(-600)) {
        const doc = documents.get(id); if (!doc || Math.abs(doc.publishedAt - at) > 3 * DAY_MS) continue;
        const overlap = similarity(keywords, doc.keywords);
        if (overlap > score && keywords.filter(t => doc.keywords.includes(t)).length >= 3) { best = doc.eventId; score = overlap; }
      }
      return best;
    }
    function ingest(post, raw = {}) {
      if (!post?.id || typeof post.text !== 'string' || !Number.isFinite(post.ts)) return null;
      const now = Date.now(), url = canonicalURL(post.url), article = ['News', 'Politics'].includes(post.src), id = url && article ? 'doc-' + hash(url) : 'doc-' + hash(post.src + ':' + post.id);
      const title = String(post.title || post.text).slice(0, 600), keywords = tokens(title);
      const previous = documents.get(id);
      const contentHash = hash(JSON.stringify({ text: post.text, raw, title }));
      if (previous?.contentHash === contentHash) {
        if (post.serverId && (previous.serverId !== post.serverId || previous.serverEventId !== post.serverEventId || JSON.stringify(previous.translation) !== JSON.stringify(post.translation))) {
          Object.assign(previous, { serverId: post.serverId, serverEventId: post.serverEventId, translation: post.translation }); dirty.add(id); notify();
        }
        return previous;
      }
      const source = String(post.sub || post.src || 'Unknown');
      const custom = state.sources.find(s => s.name === source), override = state.sourceOverrides[source] || {};
      const doc = {
        id, originalId: post.id, url, title, text: post.text, source, platform: post.src,
        family: override.family || custom?.family || sourceFamily(source), tier: post.tier || 'unknown',
        language: post.language || custom?.language || 'unknown', regions: post.region ? [post.region] : infer(post.text, REGIONS),
        categories: [...new Set([...infer(post.text, CATEGORIES), ...(custom?.category ? [custom.category] : []), ...(post.categories || [])])], entities: [...new Set(post.syms || [])], keywords,
        serverId: post.serverId || previous?.serverId, serverEventId: post.serverEventId || previous?.serverEventId, translation: post.translation || previous?.translation,
        publishedAt: post.ts, publishedEstimated: !!post.publishedEstimated, retrievedAt: now, firstRetrievedAt: previous?.firstRetrievedAt || previous?.retrievedAt || now,
        eventAt: post.eventAt || null, correctedAt: previous ? now : null, analyzedAt: now,
        raw: clone(raw), contentHash, eventId: previous?.eventId || eventFor(keywords, post.ts) || 'event-' + hash(id),
        versions: previous ? [...previous.versions, { at: previous.retrievedAt, raw: previous.raw, text: previous.text, contentHash: previous.contentHash }].slice(-10) : []
      };
      documents.set(id, doc); index(doc); dirty.add(id);
      if (previous) {
        for (const claim of state.claims) if (claim.evidence.some(e => e.documentId === id)) {
          claim.history.push({ at: now, status: claim.status, rationale: 'Linked source changed; previous assessment preserved for review.' });
          claim.status = 'Developing'; claim.needsReview = true; claim.updatedAt = now;
        }
        audit('Source revision', doc.eventId, doc.source + ': linked assessments require review.'); persist();
      } else notify();
      if (documents.size > MAX_DOCUMENTS || documents.size % 100 === 0) prune(); return doc;
    }
    function prune() {
      const protectedIds = new Set(state.claims.flatMap(c => c.evidence.map(e => e.documentId)));
      const protectedEvents = new Set([...state.saved, ...state.forecasts.map(f => f.eventId), ...Object.keys(state.notes)]);
      const sorted = [...documents.values()].sort((a, b) => a.retrievedAt - b.retrievedAt);
      for (const doc of sorted) {
        if (protectedIds.has(doc.id) || protectedEvents.has(doc.eventId)) continue;
        if (documents.size <= MAX_DOCUMENTS && doc.retrievedAt > Date.now() - 365 * DAY_MS) break;
        documents.delete(doc.id); dirty.delete(doc.id);
        eventIndex.get(doc.eventId)?.delete(doc.id); if (!eventIndex.get(doc.eventId)?.size) eventIndex.delete(doc.eventId);
        for (const word of doc.keywords) { tokenIndex.get(word)?.delete(doc.id); if (!tokenIndex.get(word)?.size) tokenIndex.delete(word); }
        if (db) db.transaction('documents', 'readwrite').objectStore('documents').delete(doc.id);
      }
    }
    function flush() {
      if (!db || !dirty.size) return;
      try {
        const tx = db.transaction('documents', 'readwrite'), store = tx.objectStore('documents');
        const pending = [...dirty].map(id => [id, documents.get(id)?.contentHash]); pending.forEach(([id]) => { const doc = documents.get(id); if (doc) store.put(doc); });
        tx.oncomplete = () => pending.forEach(([id, contentHash]) => { if (documents.get(id)?.contentHash === contentHash) dirty.delete(id); });
        tx.onerror = () => { storageWarning = 'Evidence archive could not be saved. Export your research.'; notify(); };
      } catch { storageWarning = 'Evidence archive is unavailable. Export your research.'; notify(); }
    }
    async function open() {
      if (options.memory) { archiveLoaded = true; return; }
      try {
        db = await new Promise((resolve, reject) => {
          const request = indexedDB.open('trend-crawler-evidence', 1);
          request.onupgradeneeded = () => request.result.createObjectStore('documents', { keyPath: 'id' });
          request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
          request.onblocked = () => reject(new Error('Archive upgrade blocked by another tab'));
        });
        const saved = await new Promise((resolve, reject) => { const req = db.transaction('documents').objectStore('documents').getAll(); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
        for (const doc of saved) if (!documents.has(doc.id)) { documents.set(doc.id, doc); index(doc); }
        prune(); flush();
      } catch { storageWarning = 'Persistent evidence storage is unavailable. This session still works; export before closing.'; }
      archiveLoaded = true; notify();
    }
    // A chain is a conservative publisher/content grouping, never proof of independent investigation.
    function lineage(list) {
      const groups = [];
      for (const doc of list) {
        const matches = groups.filter(group => group.some(other => other.family === doc.family || similarity(other.keywords, doc.keywords) >= .8 || (other.url && other.url === doc.url)));
        if (!matches.length) groups.push([doc]);
        else { const first = matches[0]; first.push(doc); for (const group of matches.slice(1)) { first.push(...group); groups.splice(groups.indexOf(group), 1); } }
      }
      return groups;
    }
    function claimsFor(eventId) { return state.claims.filter(c => c.eventId === eventId); }
    function mergeServerEvents() {
      const groups = new Map(); let changed = false;
      for (const doc of documents.values()) if (doc.serverEventId) { if (!groups.has(doc.serverEventId)) groups.set(doc.serverEventId, []); groups.get(doc.serverEventId).push(doc); }
      for (const group of groups.values()) {
        const target = group[0].eventId;
        for (const doc of group) if (doc.eventId !== target) {
          const original = doc.eventId;
          eventIndex.get(original)?.delete(doc.id);
          doc.eventId = target; dirty.add(doc.id); index(doc); changed = true;
          if (state.saved.includes(original) && !state.saved.includes(target)) state.saved.push(target);
          if (state.notes[original] && !state.notes[target]) state.notes[target] = state.notes[original];
          for (const claim of state.claims) if (claim.eventId === original && claim.evidence.length && claim.evidence.every(link => documents.get(link.documentId)?.eventId === target)) claim.eventId = target;
          if (!eventIndex.get(original)?.size) { eventIndex.delete(original); state.saved = state.saved.filter(id => id !== original); }
        }
      }
      if (changed) persist();
    }
    function setServerAnalyses(events) {
      let changed = false;
      for (const event of events) if (event.analysis && JSON.stringify(serverAnalyses.get(event.id)) !== JSON.stringify(event.analysis)) { serverAnalyses.set(event.id, event.analysis); changed = true; }
      if (changed) notify();
    }
    function assessment(eventId, asOf = Date.now()) {
      const claims = claimsFor(eventId).filter(c => c.createdAt <= asOf).map(c => {
        if (c.updatedAt <= asOf) return c;
        const prior = [...c.history].reverse().find(item => item.at <= asOf);
        return prior ? { ...c, ...prior } : { ...c, status: 'Unverified', needsReview: true };
      });
      if (!claims.length) return { status: 'Unverified', confidence: 'Not assessed', label: 'Reported statements have not been reviewed.' };
      const priority = ['Retracted', 'Contradicted', 'Misleading', 'Disputed', 'Unverified', 'Developing', 'Corroborated', 'Verified'];
      let status = priority.find(s => claims.some(c => c.status === s)) || 'Unverified';
      const headline = [...(eventIndex.get(eventId) || [])].map(id => documents.get(id)).filter(d => d && d.retrievedAt <= asOf).sort((a, b) => a.publishedAt - b.publishedAt)[0]?.title;
      const headlineReviewed = headline && claims.some(c => ['Verified', 'Corroborated'].includes(c.status) && similarity(tokens(c.text), tokens(headline)) >= .9);
      if (['Verified', 'Corroborated'].includes(status) && !headlineReviewed) status = 'Developing';
      return { status, confidence: claims.some(c => c.needsReview) ? 'Review required' : 'Analyst assessed', label: claims.length + ' reviewed claim(s). ' + (headlineReviewed ? 'The headline statement has a matching review; other statements may remain unreviewed.' : 'The headline statement is not verified by these reviews. Inspect each specific claim.') };
    }
    function signals(settings = {}) {
      const now = settings.now || Date.now(), windowMs = settings.windowMs || DAY_MS, groups = new Map();
      for (const doc of documents.values()) {
        if (doc.publishedAt > now || doc.retrievedAt > now || doc.publishedAt < now - 2 * windowMs) continue;
        if (!groups.has(doc.eventId)) groups.set(doc.eventId, []); groups.get(doc.eventId).push(doc);
      }
      const results = [];
      for (const [id, all] of groups) {
        const current = all.filter(d => d.publishedAt >= now - windowMs); if (!current.length) continue;
        const previous = all.length - current.length, chains = lineage(current), review = assessment(id, now);
        const categories = [...new Set(current.flatMap(d => d.categories))], regions = [...new Set(current.flatMap(d => d.regions))], entities = [...new Set(current.flatMap(d => d.entities))];
        const primary = current.filter(d => d.tier === 'primary'), publishers = new Set(current.map(d => d.family)).size;
        const serverTrend = windowMs === DAY_MS && !settings.now ? serverAnalyses.get(current.find(d => d.serverEventId)?.serverEventId) : null;
        const baselineCoverage = serverTrend ? Math.min(serverTrend.coverage, serverTrend.baselineCoverage) : coverageRatio(now - 2 * windowMs, now);
        const baselineReady = serverTrend ? serverTrend.baselineAvailable : state.startedAt <= now - 2 * windowMs && baselineCoverage >= .95;
        const acceleration = serverTrend ? serverTrend.acceleration : baselineReady ? current.length / Math.max(1, previous) : null;
        const momentum = serverTrend?.momentum ?? Math.round(Math.min(100, 20 * Math.log2(current.length + 1) + (acceleration == null ? 0 : 12 * Math.log2(acceleration + 1))));
        const credibility = ['Verified', 'Corroborated'].includes(review.status) ? 80 : ['Contradicted', 'Retracted', 'Misleading'].includes(review.status) ? 5 : Math.min(45, primary.length * 12 + chains.length * 6);
        const impact = Math.min(100, categories.length * 12 + entities.length * 8 + primary.length * 8 + (categories.includes('Politics') || categories.includes('Economics') ? 20 : 0));
        const diversity = Math.min(100, publishers * 10 + regions.length * 12);
        const uncertainty = review.status === 'Unverified' ? 85 : review.status === 'Developing' ? 65 : review.status === 'Disputed' ? 80 : 30;
        const coverageGaps = [];
        const languages = new Set(current.map(d => d.language).filter(l => l !== 'unknown'));
        if (!languages.size) coverageGaps.push('Source language is unknown; multilingual coverage cannot be assessed.');
        else if (languages.size === 1) coverageGaps.push('Only ' + [...languages][0] + '-language material is represented. Local-language perspectives may be missing.');
        if (current.some(d => d.language === 'unknown')) coverageGaps.push('Some source languages are unclassified.');
        if (!regions.length) coverageGaps.push('Affected geography is unclassified.');
        if (!primary.length) coverageGaps.push('No primary document is linked in this collection.');
        if (!baselineReady) coverageGaps.push('An equal-window baseline needs 95% collection uptime across both windows; observed coverage is ' + Math.round(baselineCoverage * 100) + '%.');
        if (current.some(d => d.publishedEstimated)) coverageGaps.push('Some publication times were estimated from retrieval time.');
        const lifecycle = ['Disputed', 'Misleading', 'Contradicted', 'Retracted'].includes(review.status) ? 'Contested' : acceleration != null && acceleration < .7 ? 'Cooling' : acceleration != null && acceleration > 1.5 ? 'Emerging' : current.length > 4 && primary.length ? 'Watch for confirmation' : 'Early signal';
        const titleDoc = [...current].sort((a, b) => a.publishedAt - b.publishedAt)[0];
        const signal = { id, title: titleDoc.title, documents: current.sort((a, b) => b.publishedAt - a.publishedAt), categories, regions, entities,
          mentions: current.length, publishers, chains: chains.length, lineage: chains, primary: primary.length,
          momentum, credibility, impact, diversity, uncertainty, acceleration, previous, baselineReady, baselineCoverage, lifecycle,
          ...review, coverageGaps, firstSeen: Math.min(...all.map(d => d.firstRetrievedAt || d.retrievedAt)), lastPublished: Math.max(...current.map(d => d.publishedAt)),
          rank: Math.round(momentum * .3 + credibility * .3 + impact * .25 + diversity * .15 - uncertainty * .1),
          watchNext: primary.length ? 'Check the next official update, effective date, or measurable outcome against the linked primary record.' : 'Locate the original record and reporting that independently investigated this specific statement.',
          invalidate: 'A correction, withdrawn primary record, conflicting direct evidence, or a return to baseline would require reassessment.'
        };
        results.push(signal);
      }
      const q = String(settings.query || '').toLowerCase();
      const filtered = results.filter(s => (!q || (s.title + ' ' + s.entities.join(' ') + ' ' + s.categories.join(' ') + ' ' + s.documents.map(d => d.source).join(' ')).toLowerCase().includes(q))
        && (!settings.category || s.categories.includes(settings.category)) && (!settings.region || s.regions.includes(settings.region))
        && (!settings.status || s.status === settings.status) && (!settings.lifecycle || s.lifecycle === settings.lifecycle)
        && (!settings.type || s.categories.includes(settings.type === 'crypto' ? 'Crypto' : 'Equities'))
        && (!settings.minImpact || s.impact >= settings.minImpact) && (!settings.saved || state.saved.includes(s.id)));
      const field = { chronological: 'lastPublished', momentum: 'momentum', credibility: 'credibility', impact: 'impact' }[settings.sort] || 'rank';
      return filtered.sort((a, b) => b[field] - a[field] || b.lastPublished - a.lastPublished);
    }
    function signalById(id, windowMs = 365 * DAY_MS) { return signals({ windowMs }).find(s => s.id === id); }
    function toggleSaved(id) { state.saved = state.saved.includes(id) ? state.saved.filter(s => s !== id) : [...state.saved, id]; audit('Watchlist changed', id, state.saved.includes(id) ? 'Saved' : 'Removed'); persist(); }
    function saveNote(id, text) { state.notes[id] = String(text).slice(0, 20000); audit('Research note saved', id, 'Analyst annotation; not source evidence.'); persist(); }
    function reviewClaim(input) {
      if (!STATUSES.includes(input.status) || !input.text?.trim() || !input.rationale?.trim()) throw new Error('A claim, evidence status, and explanation are required.');
      const evidence = (input.evidence || []).filter(e => documents.get(e.documentId)?.eventId === input.eventId && ['supports', 'contradicts', 'context'].includes(e.relation));
      const supporting = evidence.filter(e => e.relation === 'supports');
      if (input.status === 'Verified' && (!supporting.length || !input.directEvidence)) throw new Error('Verified requires a supporting record and confirmation that you reviewed direct evidence.');
      if (input.status === 'Corroborated' && (!input.independenceReviewed || lineage(supporting.map(e => documents.get(e.documentId))).length < 2)) throw new Error('Corroborated requires at least two distinct reporting chains and an analyst review of independence.');
      if (['Disputed', 'Contradicted'].includes(input.status) && !evidence.some(e => e.relation === 'contradicts')) throw new Error('Link the contradicting evidence for this assessment.');
      if (['Misleading', 'Retracted'].includes(input.status) && !evidence.length) throw new Error('Link the contextual evidence or publisher correction.');
      const now = Date.now(), previous = state.claims.find(c => c.id === input.id);
      const claim = { id: previous?.id || uid('claim'), eventId: input.eventId, text: input.text.trim().slice(0, 2000), status: input.status,
        rationale: input.rationale.trim().slice(0, 4000), confidence: input.confidence || 'Unassessed', evidence, directEvidence: !!input.directEvidence,
        independenceReviewed: !!input.independenceReviewed, needsReview: false, createdAt: previous?.createdAt || now, updatedAt: now,
        history: previous ? [...previous.history, { at: previous.updatedAt, status: previous.status, rationale: previous.rationale, evidence: previous.evidence }] : [] };
      if (previous) state.claims[state.claims.indexOf(previous)] = claim; else state.claims.push(claim);
      // Record withdrawals invalidate every other assessment relying on that same record.
      if (claim.status === 'Retracted') for (const dependent of state.claims) {
        if (dependent.id === claim.id || !dependent.evidence.some(e => evidence.some(link => link.documentId === e.documentId))) continue;
        dependent.history.push({ at: now, status: dependent.status, rationale: dependent.rationale });
        dependent.status = 'Developing'; dependent.needsReview = true; dependent.updatedAt = now;
      }
      audit('Claim assessed', input.eventId, claim.status + ': ' + claim.text); persist(); return claim;
    }
    function addAlert(input) {
      const query = String(input.query || '').trim().slice(0, 200); if (!query) throw new Error('Enter a topic or entity to monitor.');
      const alert = { id: uid('alert'), query, minMomentum: Math.max(0, Math.min(100, Number(input.minMomentum) || 0)), status: input.status || '', enabled: true, createdAt: Date.now(), matches: [], triggeredAt: null };
      state.alerts.push(alert); audit('Monitor created', alert.id, query); persist(); return alert;
    }
    function evaluateAlerts() {
      let changed = false;
      for (const alert of state.alerts.filter(a => a.enabled)) {
        const matches = signals({ query: alert.query, status: alert.status }).filter(s => s.momentum >= alert.minMomentum).map(s => s.id);
        if (JSON.stringify(matches) !== JSON.stringify(alert.matches)) { alert.matches = matches; if (matches.length) alert.triggeredAt = Date.now(); changed = true; }
      }
      if (changed) persist();
    }
    function toggleAlert(id) { const alert = state.alerts.find(a => a.id === id); if (alert) { alert.enabled = !alert.enabled; audit('Monitor changed', id, alert.enabled ? 'Enabled' : 'Paused'); persist(); } }
    function addForecast(input) {
      if (!input.statement?.trim() || !input.assumptions?.trim() || !(Number(input.dueAt) > Date.now())) throw new Error('Enter a scenario, its assumptions, and a future review date.');
      const forecast = { id: uid('forecast'), eventId: input.eventId, statement: input.statement.trim().slice(0, 2000), assumptions: input.assumptions.trim().slice(0, 2000), dueAt: Number(input.dueAt), createdAt: Date.now(), confidence: 'Qualitative; uncalibrated', outcome: 'Pending', resolution: '', resolvedAt: null };
      state.forecasts.push(forecast); audit('Scenario recorded', input.eventId, forecast.statement); persist(); return forecast;
    }
    function resolveForecast(id, outcome, resolution) {
      const forecast = state.forecasts.find(f => f.id === id);
      if (!forecast || forecast.resolvedAt) throw new Error('This scenario is already resolved or unavailable.');
      if (!['Occurred', 'Did not occur', 'Inconclusive'].includes(outcome) || !resolution?.trim()) throw new Error('An outcome and an evidence-linked explanation are required.');
      forecast.outcome = outcome; forecast.resolution = resolution.trim().slice(0, 4000); forecast.resolvedAt = Date.now();
      audit('Scenario resolved', forecast.eventId, outcome + ': ' + forecast.resolution); persist();
    }
    function addSource(input) {
      if (!input.name?.trim() || !/^https:\/\//i.test(input.url || '') || !canonicalURL(input.url)) throw new Error('Enter a source name and a valid HTTPS RSS or Atom feed URL.');
      if (state.sources.some(s => s.url === input.url)) throw new Error('This feed is already registered.');
      const source = { id: uid('source'), name: input.name.trim().slice(0, 100), url: canonicalURL(input.url), family: sourceFamily(input.family || input.name),
        language: String(input.language || 'unknown').slice(0, 30), region: String(input.region || '').slice(0, 50), category: String(input.category || '').slice(0, 50),
        permissions: String(input.permissions || 'Not reviewed').slice(0, 500), enabled: !!input.enabled, tier: 'regional', interval: 300000, createdAt: Date.now() };
      state.sources.push(source); audit('Source registered', source.id, source.name); persist(); return source;
    }
    function toggleSource(id) { const source = state.sources.find(s => s.id === id); if (source) { source.enabled = !source.enabled; audit('Source changed', id, source.enabled ? 'Polling enabled' : 'Polling paused'); persist(); } }
    function exportData() { return { schema: 'trend-crawler-research/1', exportedAt: new Date().toISOString(), workspace: clone(state), documents: clone([...documents.values()]), limits: { maxUnpinnedDocuments: MAX_DOCUMENTS, retentionDays: 365, raw: 'Retrieved feed/post fields; full articles are not downloaded.', versionsPerDocument: 10, execution: 'Browser open and visible', assessment: 'Heuristic grouping plus explicit analyst reviews; no autonomous fact checking' } }; }
    return { documents, ingest, open, flush, signals, signalById, lineage, assessment, claimsFor, toggleSaved, saveNote, reviewClaim, addAlert, evaluateAlerts, toggleAlert, addForecast, resolveForecast, addSource, toggleSource, exportData, recordCoverage, coverageRatio, persist, mergeServerEvents, setServerAnalyses,
      subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }, get state() { return state; }, get revision() { return revision; }, get storageWarning() { return storageWarning; }, get archiveLoaded() { return archiveLoaded; } };
  }
  window.CrawlerResearch = { createEngine, tokens, similarity, canonicalURL, sourceFamily, STATUSES, CATEGORIES, REGIONS };
  const engine = window.CrawlerIntelligence = createEngine();
  engine.open();
  engine.recordCoverage();
  setInterval(() => { if (!document.hidden) engine.recordCoverage(); }, 30000);
  setInterval(() => engine.flush(), 10000);
  setInterval(() => engine.evaluateAlerts(), 30000);
  window.addEventListener('pagehide', () => engine.flush());
})();
