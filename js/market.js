/* ---------------- Live crypto prices (Binance WS with failover) ---------------- */
const WSH = ['wss://stream.binance.com:9443', 'wss://data-stream.binance.vision', 'wss://stream.binance.us:9443'];
const live = new Map();
let wsI = 0, ws, lastMsg = 0;
function connectTicker() {
  if (window.CrawlerServer?.offline) return;
  const me = ws = new WebSocket(WSH[wsI] + '/ws/!miniTicker@arr'); lastMsg = Date.now();
  me.onopen = () => setStatus('Price stream', true, WSH[wsI]);
  me.onmessage = ev => {
    lastMsg = Date.now();
    for (const t of JSON.parse(ev.data)) {
      if (!t.s.endsWith('USDT')) continue;
      const b = t.s.slice(0, -4); if (STABLE.has(b)) continue;
      const o = +t.o, c = +t.c;
      live.set(b, { price: c, chg: o ? (c - o) / o * 100 : 0, vol: +t.q, t: Date.now(), marketAt: +t.E || Date.now() });
      if (b.length >= 3) known.crypto.add(b);
    }
  };
  const fail = () => { if (ws !== me) return; ws = null; setStatus('Price stream', false, 'reconnecting'); wsI = (wsI + 1) % WSH.length; if (!window.CrawlerServer?.offline) setTimeout(connectTicker, 1500); };
  me.onclose = me.onerror = fail;
}
setInterval(() => { if (ws && Date.now() - lastMsg > 15000) ws.close(); }, 5000);
connectTicker();
window.addEventListener('crawler:server-state', () => {
  if (window.CrawlerServer?.offline && ws) {
    const current = ws;
    ws = null; current.onclose = current.onerror = null;
    current.close();
    setStatus('Price stream', false, 'Research server stopped');
  }
});
window.addEventListener('crawler:experience-change', () => {
  if (document.body.dataset.experience === 'workspace') { if (!ws) connectTicker(); }

});

/* ---------------- Stock quotes (Yahoo, rotating) ---------------- */
const YMAP = { '1m': ['1m', '1d'], '5m': ['5m', '1d'], '15m': ['15m', '5d'], '1h': ['60m', '1mo'], '1d': ['1d', '6mo'] };
const quotes = new Map(), invalid = new Set(), mini = new Map();
const priceFresh = (quote, maxAge = 120000) => !!quote && Number.isFinite(quote.price) && Number.isFinite(quote.t) && Date.now() - quote.t <= maxAge;
async function dexCandles(sym, iv, limit) {
  const d = ext.dex.get(sym), [tf, agg] = { '1m': ['minute', 1], '5m': ['minute', 5], '15m': ['minute', 15], '1h': ['hour', 1], '1d': ['day', 1] }[iv];
  const net = { polygon: 'polygon_pos', avalanche: 'avax' }[d.chain] || d.chain;
  const j = await fetchJSON(`https://api.geckoterminal.com/api/v2/networks/${net}/pools/${d.pair}/ohlcv/${tf}?aggregate=${agg}&limit=${limit}`);
  return j.data.attributes.ohlcv_list.reverse().map(x => ({ t: x[0] * 1000, o: x[1], h: x[2], l: x[3], c: x[4], v: x[5] }));
}
async function fetchCandles(type, sym, iv, limit = 150) {
  if (type === 'crypto' && !live.has(sym) && ext.dex.has(sym)) return dexCandles(sym, iv, limit);
  if (type === 'crypto') {
    const k = await binanceREST(`/api/v3/klines?symbol=${sym}USDT&interval=${iv}&limit=${limit}`);
    return k.map(x => ({ t: x[0], o: +x[1], h: +x[2], l: +x[3], c: +x[4], v: +x[5] }));
  }
  const [yi, yr] = YMAP[iv];
  const j = await fetchJSON(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${yi}&range=${yr}`).catch(e => { if (e.status === 404) invalid.add(sym); throw e; });
  if (j.chart.error || !j.chart.result) { invalid.add(sym); throw new Error('unknown symbol ' + sym); }
  const r = j.chart.result[0], q = r.indicators.quote[0], out = [];
  (r.timestamp || []).forEach((t, i) => { if (q.close[i] != null) out.push({ t: t * 1000, o: q.open[i], h: q.high[i], l: q.low[i], c: q.close[i], v: q.volume[i] || 0 }); });
  if (yr === '1d' && r.meta) quotes.set(sym, { price: r.meta.regularMarketPrice, chg: r.meta.chartPreviousClose ? (r.meta.regularMarketPrice - r.meta.chartPreviousClose) / r.meta.chartPreviousClose * 100 : null, t: Date.now(), marketAt: r.meta.regularMarketTime * 1000 || null });
  return out.slice(-limit);
}
let quoteQueue = [], qi = 0;
setInterval(async () => {
  if (window.CrawlerServer?.offline || document.hidden) return;
  if (!quoteQueue.length) return;
  const sym = quoteQueue[qi++ % quoteQueue.length];
  if (invalid.has(sym)) return;
  try { const c = await fetchCandles('stock', sym, '5m', 80); mini.set('stock:' + sym, { t: Date.now(), c }); setStatus('Yahoo quotes', true); }
  catch (e) { if (!invalid.has(sym)) setStatus('Yahoo quotes', false, e.message); }
}, 3000);


