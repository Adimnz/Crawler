/* ---------------- Source reliability: static tiers, live corroboration, measured track record ---------------- */
const TIER_W = { primary: 1, wire: .9, major: .8, specialist: .65, regional: .55, community: .35, social: .25, anon: .12 };
const SRC_TIER = { Reddit: 'community', StockTwits: 'community', HackerNews: 'community', Forums: 'community', Bluesky: 'social', Mastodon: 'social', X: 'social', '4chan': 'anon', Twitch: 'anon', Politics: 'regional' };
const NAME_TIERS = [
  [/sec\.gov|federal reserve|federalreserve|ecb\.europa|bank of england|cftc|treasury\.gov/i, 'primary'],
  [/reuters|associated press|apnews|\bap news|bloomberg|financial times|ft\.com/i, 'wire'],
  [/wsj|wall street journal|new york times|nytimes|bbc|cnbc|guardian|marketwatch|economist|nikkei|washington post|barron|npr\b/i, 'major'],
  [/coindesk|cointelegraph|the block|theblock|decrypt|blockworks|seeking alpha|benzinga|investopedia|yahoo|forbes|business insider|politico|the hill|al jazeera|dw\.com|france ?24|sky news|straits times|scmp|economic times|livemint|abc\.net|channel news|axios|techcrunch/i, 'specialist'],
];
const tierFromName = n => { for (const [re, t] of NAME_TIERS) if (re.test(n || '')) return t; return 'regional'; };
const defaultTier = p => p.tier || (p.src === 'News' ? tierFromName(p.sub) : SRC_TIER[p.src] || 'social');

// Measured hit rate per platform (filled by history.js); nudges the weight once there is enough data.
const trackRate = {};
const trackAdj = src => { const t = trackRate[src]; return t && t.n >= 30 ? .7 + (t.hit + 2) / (t.n + 4) * .6 : 1; };
const postWeight = p => Math.max(.05, Math.min(1, TIER_W[p.tier] * trackAdj(p.src)));
const famOf = p => p.src === 'News' ? String(p.sub || 'news').split(' via ')[0].toLowerCase() : p.src;

// Per-feed health for the curated outlet list.
const feedStat = {};
const feedHealth = (n, ok, msg = '') => { const s = feedStat[n] ||= { okN: 0, total: 0 }; s.total++; s.checkedAt = Date.now(); if (ok) { s.okN++; s.lastSuccess = s.checkedAt; } s.ok = ok; s.msg = msg; };

// Outlets found by searches (not in our curated list) are tracked so their reliability can be judged by corroboration.
const discovered = new Map();
function noteOutlet(p) {
  if (p.src !== 'News' || p.listed) return;
  const f = famOf(p), e = discovered.get(f) || { n: 0, tier: p.tier };
  e.n++; discovered.set(f, e);
  if (discovered.size > 400) discovered.delete(discovered.keys().next().value);
}
// Share of an outlet's asset-linked items that a high-tier outlet also reported within 6h.
function corroboration(fam) {
  const hi = new Map();
  for (const p of newsPosts) if (p.w >= .8 && famOf(p) !== fam) for (const s of p.syms) { if (!hi.has(s)) hi.set(s, []); hi.get(s).push(p.ts); }
  let tot = 0, ok = 0;
  for (const p of newsPosts) {
    if (famOf(p) !== fam || !p.syms.length) continue;
    tot++; if (p.syms.some(s => (hi.get(s) || []).some(t => Math.abs(t - p.ts) < 6 * 36e5))) ok++;
  }
  return { tot, rate: tot ? ok / tot : null };
}
