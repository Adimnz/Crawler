/* Official public feeds: Google Trends RSS, Bing News RSS, Wikipedia pageviews; optional X API with the user's own key */
const gtGeos = ['US', 'GB', 'CA', 'AU', 'IN'];
let gtI = 0;
job('Google Trends', async () => {
  const doc = await fetchAny(`https://trends.google.com/trending/rss?geo=${gtGeos[gtI++ % gtGeos.length]}`, parseXML);
  doc.querySelectorAll('item').forEach(i => {
    const title = i.querySelector('title')?.textContent || '', news = [...i.getElementsByTagName('ht:news_item_title')].map(n => n.textContent).join(' ');
    addPost({ id: 'gt_' + title + '_' + (i.querySelector('pubDate')?.textContent || ''), src: 'Google Trends', ts: Date.parse(i.querySelector('pubDate')?.textContent) || Date.now(), text: title + ' ' + news, url: i.querySelector('link')?.textContent || '', sub: (i.getElementsByTagName('ht:approx_traffic')[0]?.textContent || '') + ' searches' });
  });
}, 120000);
async function bingNews(q) {
  const doc = await fetchAny(`https://www.bing.com/news/search?q=${encodeURIComponent(q)}&format=rss`, parseXML);
  return [...doc.querySelectorAll('item')].map(i => ({ id: 'bn_' + i.querySelector('link')?.textContent, src: 'News', ts: Date.parse(i.querySelector('pubDate')?.textContent), text: i.querySelector('title')?.textContent || '', url: i.querySelector('link')?.textContent || '', sub: i.getElementsByTagName('News:Source')[0]?.textContent || 'Bing News' }));
}
const xCfg = () => { try { return JSON.parse(localStorage.getItem('xcfg') || 'null'); } catch (e) { return null; } };
$('xbtn').onclick = () => {
  const base = prompt('Your X API proxy base URL (a proxy you run that forwards to api.x.com and adds CORS headers):', xCfg()?.base || '');
  if (base === null) return;
  const token = base ? prompt('X API bearer token (kept only in this browser):', '') : '';
  localStorage.setItem('xcfg', JSON.stringify(base && token ? { base: base.replace(/\/$/, ''), token } : null));
};
async function xSearch(q) {
  const c = xCfg(); if (!c) return [];
  const r = await fetch(`${c.base}/2/tweets/search/recent?query=${encodeURIComponent(q)}&max_results=20&tweet.fields=created_at,public_metrics`, { headers: { Authorization: 'Bearer ' + c.token } });
  if (!r.ok) throw new Error('X HTTP ' + r.status);
  return ((await r.json()).data || []).map(t => ({ id: 'x_' + t.id, src: 'X', ts: Date.parse(t.created_at), text: t.text, url: 'https://x.com/i/web/status/' + t.id, sub: (t.public_metrics?.like_count || 0) + ' likes' }));
}
async function wikiViews(a) {
  const nm = (a.name || '').trim(), c = ext.wiki.get(a.sym);
  if (nm.length < 3 || (c && Date.now() - c.t < 6e5)) return;
  const o = await fetchJSON(`https://en.wikipedia.org/w/api.php?action=opensearch&search=${encodeURIComponent(nm)}&limit=1&format=json&origin=*`), title = o[1]?.[0];
  if (!title) { ext.wiki.set(a.sym, { t: Date.now(), spike: 0 }); return; }
  const f = d => d.toISOString().slice(0, 10).replace(/-/g, '');
  const j = await fetchJSON(`https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/${encodeURIComponent(title.replace(/ /g, '_'))}/daily/${f(new Date(Date.now() - 15 * DAY))}/${f(new Date(Date.now() - DAY))}`);
  const v = j.items.map(i => i.views), last = v[v.length - 1], base = v.slice(0, -1).reduce((x, y) => x + y, 0) / Math.max(1, v.length - 1);
  ext.wiki.set(a.sym, { t: Date.now(), title, last, spike: (last + 1) / (base + 1) });
}
const wikiLine = sym => { const w = ext.wiki.get(sym); return w?.title ? `<div class="dim">Wikipedia "${esc(w.title)}": ${w.last} views yesterday (${w.spike.toFixed(1)}x the prior 2-week average)</div>` : ''; };

/* Targeted sweep: search the open web for each radar candidate by name */
const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
async function searchAsset(a) {
  const nm = (a.name || '').replace(/["()]/g, '').trim().slice(0, 40), term = nm.length >= 3 ? nm : a.sym;
  const first = term.split(' ')[0], key = (first.length >= 4 ? first : term).toLowerCase();
  const re = new RegExp('\\b' + escRe(key) + '\\b|\\$' + a.sym + '\\b', 'i'), kind = a.type === 'crypto' ? 'crypto' : 'stock';
  const tag = o => ({ ...o, syms: [a.sym] });
  const jobs = [
    rss(`"${term}" ${kind === 'crypto' ? '(crypto OR token OR coin)' : 'stock'} when:1d`).then(r => r.map(x => newsPost(x, [a.sym]))),
    bsky(kind === 'crypto' ? `${term} crypto` : `$${a.sym}`).then(r => r.map(tag)),
    fetchJSON(`https://www.reddit.com/search.json?q=${encodeURIComponent(term + ' ' + kind)}&sort=new&t=day&limit=25&raw_json=1`).then(j => j.data.children.map(c => tag(redditPost(c.data)))),
    fetchJSON(`https://hn.algolia.com/api/v1/search_by_date?query=${encodeURIComponent(term)}&tags=story&numericFilters=created_at_i>${Math.floor(Date.now() / 1000) - 86400}`).then(j => j.hits.map(h => tag({ id: 'hn_' + h.objectID, src: 'HackerNews', ts: h.created_at_i * 1000, text: h.title, url: h.url || 'https://news.ycombinator.com/item?id=' + h.objectID, sub: 'HN' }))),
    bingNews(`"${term}" ${kind === 'crypto' ? 'crypto' : 'stock'}`).then(r => r.map(tag)),
    xSearch(`($${a.sym} OR "${term}") -is:retweet lang:en`).then(r => r.map(tag))
  ];
  const res = await Promise.allSettled(jobs);
  res.forEach(r => r.status === 'fulfilled' && r.value.forEach(p => { if (re.test(p.text)) addPost(p); }));
  wikiViews(a).catch(() => {});
  return res.some(r => r.status === 'fulfilled');
}
let sq = 0, searching = false;
setInterval(async () => {
  if (document.hidden || searching) return;
  const t = lastRadar.slice(0, 12), cur = lastAllMap.get(sel);
  if (cur && !t.includes(cur)) t.push(cur);
  if (!t.length) return;
  searching = true;
  try { setStatus('Targeted search', await searchAsset(t[sq++ % t.length])); } catch (e) { setStatus('Targeted search', false, e.message); }
  searching = false;
}, 8000);

