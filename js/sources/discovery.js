/* ---------------- New / low-cost asset discovery ---------------- */
ext.dex = new Map(); ext.scr = new Map(); ext.ipo = new Map(); ext.wiki = new Map();
const CHAIN_OK = new Set(['solana', 'ethereum', 'base', 'bsc', 'arbitrum', 'polygon', 'avalanche', 'sui', 'ton']);
function ingestPairs(chain, pairs) {
  for (const p of pairs) {
    const s = p.baseToken?.symbol; if (!s || !/^[A-Za-z0-9]{2,10}$/.test(s)) continue;
    const sym = s.toUpperCase(), liq = p.liquidity?.usd || 0;
    if (live.has(sym) || liq < 5000) continue;
    const cur = ext.dex.get(sym); if (cur && cur.liq > liq && cur.addr !== p.baseToken.address) continue;
    ext.dex.set(sym, { chain, pair: p.pairAddress, addr: p.baseToken.address, price: +p.priceUsd, chg: p.priceChange?.h24 ?? null, liq, vol: p.volume?.h24 || 0, created: p.pairCreatedAt || Date.now(), url: p.url, fdv: p.fdv || null, t: Date.now() });
    names.set(sym, names.get(sym) || p.baseToken.name);
  }
  while (ext.dex.size > 500) ext.dex.delete(ext.dex.keys().next().value);
}
async function pollDex() {
  const lists = [await fetchJSON('https://api.dexscreener.com/token-profiles/latest/v1'), await fetchJSON('https://api.dexscreener.com/token-boosts/latest/v1').catch(() => [])];
  const byChain = {};
  lists.flat().forEach(t => { if (CHAIN_OK.has(t.chainId)) (byChain[t.chainId] ||= new Set()).add(t.tokenAddress); });
  for (const [chain, set] of Object.entries(byChain)) ingestPairs(chain, await fetchJSON(`https://api.dexscreener.com/tokens/v1/${chain}/${[...set].slice(0, 30).join(',')}`));
}
async function refreshDex() {
  const byChain = {};
  lastRadar.filter(a => a.dx).slice(0, 20).forEach(a => (byChain[a.dx.chain] ||= []).push(a.dx.addr));
  for (const [chain, addrs] of Object.entries(byChain)) ingestPairs(chain, await fetchJSON(`https://api.dexscreener.com/tokens/v1/${chain}/${addrs.slice(0, 30).join(',')}`));
}
async function pollScreeners() {
  for (const id of ['small_cap_gainers', 'day_gainers', 'most_actives']) {
    const j = await fetchJSON(`https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&scrIds=${id}&count=50`);
    (j.finance.result[0].quotes || []).forEach(q => {
      if (!/^[A-Z]{1,5}$/.test(q.symbol)) return;
      ext.scr.set(q.symbol, { id, first: q.firstTradeDateMilliseconds || null, cap: q.marketCap || null, vol: q.regularMarketVolume || 0 });
      quotes.set(q.symbol, { price: q.regularMarketPrice, chg: q.regularMarketChangePercent, t: Date.now(), marketAt: q.regularMarketTime * 1000 || null });
      known.stock.add(q.symbol); names.set(q.symbol, names.get(q.symbol) || q.shortName || q.longName);
    });
  }
}
async function pollIPO() {
  const j = await fetchJSON('https://api.nasdaq.com/api/ipo/calendar?date=' + new Date().toISOString().slice(0, 7));
  (j?.data?.priced?.rows || []).forEach(r => {
    const s = (r.proposedTickerSymbol || '').toUpperCase(); if (!/^[A-Z]{1,5}$/.test(s)) return;
    const [m, d, y] = (r.pricedDate || '').split('/');
    ext.ipo.set(s, { t: y ? Date.UTC(+y, +m - 1, +d) : Date.now() }); known.stock.add(s); names.set(s, names.get(s) || r.companyName);
  });
}
job('DexScreener', pollDex, 30000);
job('Dex refresh', refreshDex, 20000);
job('Yahoo screeners', pollScreeners, 60000);
job('IPO calendar', pollIPO, 1800000);

