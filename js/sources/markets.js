/* ---------------- Prediction markets: crowd-priced odds on crypto, stocks, rates and policy ---------------- */
ext.pm = []; ext.pmAsset = new Map();
const PM_REL = /\b(bitcoin|btc|ethereum|eth|crypto\w*|solana|xrp|dogecoin|fed|rate cuts?|rate hikes?|fomc|recession|inflation|cpi|tariffs?|etf|nasdaq|s&p|dow|stocks?|ipo|earnings|nvidia|tesla|apple|microsoft|google|amazon|meta|trump|election|shutdown|debt ceiling|oil|gold|treasury|bank|stablecoin|sec)\b/i;
const pmItem = (src, q, p, vol, end, url) => ({ src, q, p, vol, end, url, syms: extract(q) });

async function pollPolymarket() {
  const j = await fetchJSON('https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=300&order=volume24hr&ascending=false');
  return j.filter(m => PM_REL.test(m.question)).map(m => { let p; try { p = +JSON.parse(m.outcomePrices)[0]; } catch (e) { return null; } return pmItem('Polymarket', m.question, p, +m.volume24hr || 0, m.endDate, 'https://polymarket.com/market/' + m.slug); }).filter(Boolean);
}
async function pollKalshi() {
  const j = await fetchJSON('https://api.elections.kalshi.com/trade-api/v2/markets?limit=400&status=open');
  return (j.markets || []).filter(m => PM_REL.test(m.title)).map(m => pmItem('Kalshi', m.title, (m.last_price || m.yes_bid || 0) / 100, +m.volume_24h || 0, m.close_time, 'https://kalshi.com/markets/' + (m.event_ticker || m.ticker)));
}
job('Prediction markets', async () => {
  const res = await Promise.allSettled([pollPolymarket(), pollKalshi()]);
  if (res.every(r => r.status === 'rejected')) throw res[0].reason;
  ext.pm = res.flatMap(r => r.status === 'fulfilled' ? r.value : []).filter(m => m.p > 0 && m.p < 1).sort((a, b) => b.vol - a.vol);
}, 300000);

// Per-asset lookup on Manifold, cached for 10 minutes.
function pmLookup(sym) {
  const c = ext.pmAsset.get(sym); if (c && Date.now() - c.t < 6e5) return;
  ext.pmAsset.set(sym, { t: Date.now(), list: c?.list || [] });
  const term = names.get(sym) || sym;
  fetchJSON(`https://api.manifold.markets/v0/search-markets?term=${encodeURIComponent(term)}&limit=8&sort=liquidity&filter=open&contractType=BINARY`)
    .then(l => ext.pmAsset.set(sym, { t: Date.now(), list: l.filter(m => m.probability != null && new RegExp('\\b' + term.split(' ')[0].replace(/[^\w]/g, '') + '\\b', 'i').test(m.question)).map(m => ({ src: 'Manifold', q: m.question, p: m.probability, vol: m.volume24Hours || 0, end: m.closeTime, url: m.url, syms: [sym] })) }))
    .catch(() => {});
}
const pmFor = sym => [...ext.pm.filter(m => m.syms.includes(sym)), ...(ext.pmAsset.get(sym)?.list || [])].sort((a, b) => b.vol - a.vol).slice(0, 4);
const pmHTML = m => `<a class="pmk" href="${esc(safeURL(m.url))}" target="_blank" rel="noopener noreferrer"><b>${Math.round(m.p * 100)}%</b><span>${esc(m.q)}<small class="dim">${m.src} · $${money(m.vol)} / 24h${m.end ? ' · ends ' + esc(String(m.end).slice(0, 10)) : ''}</small></span></a>`;
