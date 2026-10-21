/* ---------------- Post store ---------------- */
const posts = new Map(), byAsset = new Map(), byTopic = new Map();
const assetVer = new Map(), topicVer = new Map();
const seenIds = new Set();
const recentPosts = [], newsPosts = [];
let ingested = 0;
const isSeen = id => seenIds.has(id);
const bump = (m, s) => m.set(s, (m.get(s) || 0) + 1);
function addPost(p) {
  if (!p || typeof p.id !== 'string' || typeof p.text !== 'string') return;
  const previous = posts.get(p.id);
  if (previous && previous.text === p.text.slice(0, 600) && JSON.stringify(previous.raw || {}) === JSON.stringify(p.raw || {})) return;
  const age = Date.now() - p.ts;
  if (!Number.isFinite(p.ts) || age < -120000) return;
  const original = { text: p.text, url: p.url || '', source: p.sub || p.src, publishedAt: p.ts, ...(p.raw || {}) };
  if (age >= DAY) {
    if (p.outlet || p.src === 'News' || p.src === 'Politics') window.CrawlerIntelligence?.ingest({ ...p, text: p.text.slice(0, 600), tier: defaultTier(p), syms: [...new Set([...(p.syms || []), ...extract(p.text)])] }, original);
    return;
  }
  const syms = new Set((p.syms || []).filter(s => !STABLE.has(s)));
  extract(p.text).forEach(s => syms.add(s));
  p.pol = p.pol ?? isPol(p.text);
  if (!syms.size && p.src !== 'Politics' && p.src !== 'News' && !p.outlet) return;
  if (previous) {
    for (const map of [byAsset, byTopic]) for (const [key, list] of map) {
      const index = list.findIndex(item => item.id === p.id); if (index >= 0) list.splice(index, 1);
      bump(map === byAsset ? assetVer : topicVer, key);
    }
    for (const list of [newsPosts, recentPosts]) { const index = list.findIndex(item => item.id === p.id); if (index >= 0) list.splice(index, 1); }
  }
  seenIds.add(p.id);
  p.text = p.text.slice(0, 600);
  if (p.sent == null) p.sent = sentiment(p.text);
  p.tier = defaultTier(p); p.w = postWeight(p); noteOutlet(p);
  p.syms = [...syms]; posts.set(p.id, p); ingested++;
  window.CrawlerIntelligence?.ingest(p, original);
  window.dispatchEvent?.(new CustomEvent('crawler:post'));
  recentPosts.push(p); if (recentPosts.length > 1500) recentPosts.splice(0, 500);
  if (p.src === 'News' || p.src === 'Politics') newsPosts.push(p);
  for (const s of p.syms) { if (!byAsset.has(s)) byAsset.set(s, []); byAsset.get(s).push(p); bump(assetVer, s); }
  if (p.pol) for (const s of p.topic || []) if (!syms.has(s)) { if (!byTopic.has(s)) byTopic.set(s, []); byTopic.get(s).push(p); bump(topicVer, s); }
}
setInterval(() => {
  if (document.hidden) return;
  const cut = Date.now() - DAY;
  for (const [id, p] of posts) if (p.ts < cut) posts.delete(id);
  for (const [s, a] of byAsset) { if (a[0].ts >= cut && a.every(p => p.ts >= cut)) continue; const f = a.filter(p => p.ts >= cut); f.length ? byAsset.set(s, f) : byAsset.delete(s); bump(assetVer, s); }
  for (const [s, a] of byTopic) { const f = a.filter(p => p.ts >= cut); f.length ? byTopic.set(s, f) : byTopic.delete(s); bump(topicVer, s); }
  for (let i = newsPosts.length - 1; i >= 0; i--) if (newsPosts[i].ts < cut) newsPosts.splice(i, 1);
  if (seenIds.size > 60000) { seenIds.clear(); for (const id of posts.keys()) seenIds.add(id); }
}, 60000);
const stripHTML = h => new DOMParser().parseFromString(h || '', 'text/html').body.textContent.replace(/\s+/g, ' ').trim();
const safeURL = u => /^https:\/\//.test(u || '') ? u : '';

