/* ---------------- Forums, streaming chat, political influence ---------------- */
const POL_RE = /\b(tariffs?|sanctions?|executive order|white house|congress|senate|legislation|regulat\w+|federal reserve|rate cuts?|rate hikes?|treasury|subsid\w+|election|president|trump|biden|administration|antitrust|lawsuit|export controls?|embargo|stablecoin bill|crypto bill|etf approval|bailout|stimulus)\b|\b(SEC|FOMC|FTC|DOJ|CFTC|Fed)\b/i;
const isPol = t => POL_RE.test(t);
const POL_TOPICS = [[/crypto|digital asset|bitcoin|stablecoin|blockchain/i, ['BTC', 'ETH']], [/semiconductor|chips act|export control/i, ['NVDA', 'AMD', 'INTC', 'TSM']], [/\boil\b|natural gas|drilling/i, ['XOM', 'CVX']],
  [/electric vehicle|\bEV\b/i, ['TSLA', 'RIVN']], [/pharmaceutical|drug pricing|\bFDA\b/i, ['PFE', 'LLY', 'MRNA']], [/artificial intelligence|\bAI\b/i, ['NVDA', 'MSFT', 'GOOGL']], [/\bbanks?\b|financial institution/i, ['JPM', 'BAC']]];
const topicSyms = t => POL_TOPICS.filter(([re]) => re.test(t)).flatMap(([, s]) => s);
const FIN_RE = /crypto|digital asset|tariff|trade|securities|energy|bank|financ|semiconductor|pharmaceutical|oil|gas|tax|sanction|artificial intelligence/i;
job('Federal Register', async () => {
  const j = await fetchJSON('https://www.federalregister.gov/api/v1/documents.json?per_page=40&order=newest&fields%5B%5D=title&fields%5B%5D=abstract&fields%5B%5D=html_url&fields%5B%5D=document_number&fields%5B%5D=agencies');
  j.results.forEach(d => { const text = d.title + ' ' + (d.abstract || ''); if (FIN_RE.test(text)) addPost({ id: 'fr_' + d.document_number, src: 'Politics', ts: Date.now(), text, url: d.html_url, sub: 'Federal Register ' + (d.agencies?.[0]?.name || ''), pol: true, topic: topicSyms(text) }); });
}, 600000);
job('Politics feed', async () => {
  const doc = await fetchAny('https://trumpstruth.org/feed', parseXML);
  doc.querySelectorAll('item').forEach(i => { const link = i.querySelector('link')?.textContent; if (isSeen('ts_' + link)) return; const text = (i.querySelector('title')?.textContent || '') + ' ' + stripHTML(i.querySelector('description')?.textContent); addPost({ id: 'ts_' + link, src: 'Politics', ts: Date.parse(i.querySelector('pubDate')?.textContent), text, url: link, sub: 'Truth Social (public archive)', pol: true, topic: topicSyms(text) }); });
}, 120000);
ext.cong = new Map();
const CONG_URLS = ['https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json', 'https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json'];
job('Congress trades', async () => {
  const cut = Date.now() - 60 * DAY, m = new Map(), res = await Promise.allSettled(CONG_URLS.map(fetchJSON));
  if (res.every(r => r.status === 'rejected')) throw res[0].reason;
  res.forEach((r, k) => r.status === 'fulfilled' && r.value.forEach(t => {
    const sym = (t.ticker || '').toUpperCase(), d = Date.parse(t.transaction_date);
    if (!/^[A-Z]{1,5}$/.test(sym) || !(d > cut)) return;
    if (!m.has(sym)) m.set(sym, []);
    m.get(sym).push({ who: t.representative || t.senator, type: /purchase/i.test(t.type) ? 'buy' : /sale/i.test(t.type) ? 'sell' : 'other', amt: t.amount, d, ch: k ? 'Senate' : 'House' });
  }));
  ext.cong = m;
}, 21600000, 30000);
const congLine = sym => {
  const c = (ext.cong.get(sym) || []).sort((a, b) => b.d - a.d); if (!c.length) return '';
  const b = c.filter(x => x.type === 'buy').length, l = c[0];
  return `<div class="dim">Congress trades (60d): <b>${b}</b> buys / <b>${c.filter(x => x.type === 'sell').length}</b> sells &middot; latest: ${esc(l.who)} (${l.ch}) ${l.type} ${esc(l.amt)} on ${new Date(l.d).toLocaleDateString()}</div>`;
};
function relatedHTML(sym, list) {
  const c = new Map(); list.forEach(p => p.syms.forEach(s => { if (s !== sym) c.set(s, (c.get(s) || 0) + 1); }));
  const r = [...c].sort((a, b) => b[1] - a[1]).slice(0, 8);
  return r.length ? r.map(([s, n]) => `<span class="chip" data-s="${esc(s)}">$${esc(s)} <small>${n}</small></span>`).join('') : '';
}
job('Lemmy forums', async () => {
  for (const q of ['bitcoin', 'stock market', 'memecoin', 'investing', 'tariffs']) {
    const j = await fetchJSON(`https://lemmy.world/api/v3/search?q=${encodeURIComponent(q)}&type_=Posts&sort=New&limit=30`);
    j.posts.forEach(x => addPost({ id: 'l_' + x.post.ap_id, src: 'Forums', ts: Date.parse(x.post.published), text: x.post.name + ' ' + (x.post.body || ''), url: x.post.ap_id, sub: 'c/' + x.community.name, eng: (x.counts.score || 0) + (x.counts.comments || 0) }));
  }
}, 60000);
job('Bitcointalk', async () => {
  for (const b of [159, 5]) {
    const doc = await fetchAny(`https://bitcointalk.org/index.php?type=rss;action=.xml;board=${b}.0;limit=40`, parseXML);
    doc.querySelectorAll('item').forEach(i => { const link = i.querySelector('link')?.textContent; if (isSeen('bt_' + link)) return; addPost({ id: 'bt_' + link, src: 'Forums', ts: Date.parse(i.querySelector('pubDate')?.textContent), text: (i.querySelector('title')?.textContent || '') + ' ' + stripHTML(i.querySelector('description')?.textContent), url: link, sub: b === 159 ? 'Bitcointalk altcoin launches' : 'Bitcointalk speculation' }); });
  }
}, 90000);
let twitchWS, twitchN = 0;
function connectTwitch() {
  if (window.CrawlerServer?.offline) return;
  let ch = []; try { ch = JSON.parse(localStorage.getItem('twitchCh') || '[]'); } catch (e) {}
  if (twitchWS) { twitchWS.onclose = null; twitchWS.close(); twitchWS = null; }
  if (!ch.length) return;
  const w = twitchWS = new WebSocket('wss://irc-ws.chat.twitch.tv:443');
  w.onopen = () => { w.send('PASS SCHMOOPIIE'); w.send('NICK justinfan' + Math.floor(Math.random() * 1e6)); w.send('JOIN ' + ch.map(c => '#' + c).join(',')); setStatus('Twitch chat', true, ch.join(', ')); };
  w.onmessage = ev => ev.data.split('\r\n').forEach(line => {
    if (line.startsWith('PING')) return w.send('PONG :tmi.twitch.tv');
    const m = line.match(/^:(\w+)!.* PRIVMSG #(\w+) :(.*)$/); if (!m) return;
    addPost({ id: 'tw_' + ++twitchN, src: 'Twitch', ts: Date.now(), text: m[3], url: 'https://www.twitch.tv/' + m[2], sub: '#' + m[2] + ' ' + m[1] });
  });
  w.onclose = () => { if (twitchWS !== w) return; setStatus('Twitch chat', false, 'reconnecting'); if (!window.CrawlerServer?.offline) setTimeout(connectTwitch, 5000); };
}
$('twbtn').onclick = () => {
  const v = prompt('Live Twitch channels to listen to (comma separated, finance/crypto streamers you pick):', '');
  if (v === null) return;
  try { localStorage.setItem('twitchCh', JSON.stringify(v.split(',').map(s => s.trim().toLowerCase()).filter(s => /^[a-z0-9_]{3,25}$/.test(s)))); } catch (e) {}
  connectTwitch();
window.addEventListener('crawler:server-state', () => {
  if (window.CrawlerServer?.offline && twitchWS) {
    const current = twitchWS;
    twitchWS = null;
    current.onclose = null;
    current.close();
    setStatus('Twitch chat', false, 'Research server stopped');
  }
});
};
connectTwitch();

