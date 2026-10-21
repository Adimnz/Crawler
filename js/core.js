const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DAY = 864e5;
const STABLE = new Set(['USDT','USDC','BUSD','FDUSD','DAI','TUSD','USD1','USDP','USD']);

/* ---------------- Networking with failover ---------------- */
const PROXIES = [
  null,
  u => 'https://corsproxy.io/?url=' + encodeURIComponent(u),
  u => 'https://api.allorigins.win/raw?url=' + encodeURIComponent(u),
  u => 'https://api.codetabs.com/v1/proxy?quest=' + encodeURIComponent(u),
];
const routeFor = {};
let activeReqs = 0; const waitingReqs = [];
const acquire = () => activeReqs < 8 ? (activeReqs++, Promise.resolve()) : new Promise(r => waitingReqs.push(r));
const release = () => { const n = waitingReqs.shift(); if (n) n(); else activeReqs--; };
async function timed(url, ms = 6000) {
  await acquire();
  const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch(url, { signal: c.signal });
    if (!r.ok) { const e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
    return await r.text();
  } finally { clearTimeout(t); release(); }
}
const hostDown = {};
async function fetchAny(url, parse) {
  const host = new URL(url).host, start = routeFor[host] ?? 0;
  if (hostDown[host] > Date.now()) throw new Error('cooling down');
  let err;
  for (let k = 0; k < PROXIES.length; k++) {
    const i = (start + k) % PROXIES.length;
    try {
      const j = parse(await timed(PROXIES[i] ? PROXIES[i](url) : url));
      routeFor[host] = i; return j;
    } catch (e) { err = e; if (e.status === 404) throw e; }
  }
  hostDown[host] = Date.now() + 120000;
  throw err;
}
const fetchJSON = url => fetchAny(url, JSON.parse);
const parseXML = t => { const d = new DOMParser().parseFromString(t, 'text/xml'); if (d.querySelector('parsererror')) throw new Error('bad xml'); return d; };
const REST = ['https://api.binance.com', 'https://data-api.binance.vision', 'https://api.binance.us'];
let restIdx = 0;
async function binanceREST(path) {
  for (let k = 0; k < REST.length; k++) {
    const i = (restIdx + k) % REST.length;
    try { const j = JSON.parse(await timed(REST[i] + path, 8000)); restIdx = i; return j; } catch (e) {}
  }
  return fetchJSON(REST[0] + path);
}
const sources = {};
function setStatus(n, ok, msg = '') {
  const s = sources[n] ||= { okN: 0, total: 0 };
  s.ok = ok; s.msg = msg; s.total++; s.checkedAt = Date.now(); if (ok) { s.okN++; s.lastSuccess = s.checkedAt; }
  const e = Object.entries(sources), good = e.filter(([, s]) => s.ok).length;
  $('srctxt').textContent = `${good}/${e.length} sources live`;
  $('srcdot').className = 'dotc ' + (good === e.length ? 'up' : good * 2 > e.length ? '' : 'down');
  $('status').innerHTML = e.map(([k, s]) => `<div class="src"><i class="dotc ${s.ok ? 'up' : 'down'}"></i>${esc(k)}<span class="dim" title="${esc(s.msg)}">${s.ok ? '' : esc(s.msg)}</span></div>`).join('');
}
function job(name, fn, ms, delay = 0) {
  let fails = 0;
  const run = async () => {
    if (document.hidden) return setTimeout(run, 5000);
    if (document.body.dataset.experience && document.body.dataset.experience !== 'workspace') return setTimeout(run, 5000);
    if (window.CrawlerServer?.connected && !['Prediction markets'].includes(name)) return setTimeout(run, Math.max(ms, 15000));
    try { await fn(); fails = 0; setStatus(name, true); } catch (e) { fails++; setStatus(name, false, e.message); }
    setTimeout(run, fails ? ms * Math.min(8, 2 ** fails) : ms);
  };
  setTimeout(run, delay + Math.random() * 1500);
}

