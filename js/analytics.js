/* ---------------- Per-asset stats, scoring, signals ---------------- */
const statsCache = new Map();
const STATS_TTL = 20000;

function computeStats(sym) {
  const list = byAsset.get(sym) || [], now = Date.now();
  const s = { day: list.length, recent: 0, bull: 0, bear: 0, neu: 0, bySrc: {}, pol: 0, eng: 0, news: 0, heads: [], topicHeads: byTopic.get(sym) || [], buckets: new Array(18).fill(0), list };
  let wsum = 0, wsent = 0; const fams = new Set(), srcAcc = {};
  for (const p of list) {
    const w = p.w ?? .3;
    if (Math.abs(p.sent) > .15) { wsum += w; wsent += w * p.sent; const q = srcAcc[p.src] ||= [0, 0]; q[0] += p.sent; q[1]++; }
    if (w >= .5) fams.add(famOf(p));
    if (p.src === 'News' || p.src === 'Politics') { s.news++; s.heads.push(p); }
    if (now - p.ts < 18e5) s.recent++;
    p.sent > .15 ? s.bull++ : p.sent < -.15 ? s.bear++ : s.neu++;
    s.bySrc[p.src] = (s.bySrc[p.src] || 0) + 1;
    if (p.pol) s.pol++;
    s.eng += p.eng || 0;
    const b = Math.floor((now - p.ts) / 6e5); if (b >= 0 && b < 18) s.buckets[17 - b]++;
  }
  s.sent = s.bull + s.bear ? (s.bull - s.bear) / (s.bull + s.bear) : 0;
  const hs = [...s.heads, ...s.topicHeads].filter(p => Math.abs(p.sent) > .15);
  const hw = hs.reduce((x, p) => x + (p.w ?? .3), 0);
  s.newsTone = hw ? hs.reduce((x, p) => x + (p.w ?? .3) * p.sent, 0) / hw : 0;
  s.wsent = wsum ? wsent / wsum : 0;
  s.cred = fams.size;
  s.srcSent = {};
  for (const k in srcAcc) { const m = srcAcc[k][0] / srcAcc[k][1]; if (Math.abs(m) > .15) s.srcSent[k] = +m.toFixed(2); }
  s.topicN = s.topicHeads.length;
  return s;
}
// Cached until new posts arrive for the symbol or the time-window buckets go stale.
function statsFor(sym) {
  const c = statsCache.get(sym), v = (assetVer.get(sym) || 0) + (topicVer.get(sym) || 0);
  if (c && c.v === v && Date.now() - c.t < STATS_TTL) return c.s;
  const s = computeStats(sym);
  statsCache.set(sym, { v, t: Date.now(), s });
  return s;
}

function typeOf(sym) {
  if (ext.dex.has(sym) && !live.has(sym)) return 'crypto';
  if (ext.scr.has(sym) || ext.ipo.has(sym)) return 'stock';
  if (ext.cg.has(sym)) return 'crypto';
  if (ext.ape.has(sym)) return ext.ape.get(sym).type;
  if (ext.st.get(sym)?.crypto) return 'crypto';
  if (known.stock.has(sym) && !live.has(sym)) return 'stock';
  return live.has(sym) || known.crypto.has(sym) ? 'crypto' : 'stock';
}
function signal(a) {
  if (a.news >= 2) return a.newsTone > .2 ? 'Positive news' : a.newsTone < -.2 ? 'Negative news' : 'In the news';
  if (a.day < 3 && !a.trend) return 'Low data';
  if (a.sent > .25 && a.chg > 0) return 'Bullish momentum';
  if (a.sent > .25 && a.chg < -3) return 'Dip-buy chatter';
  if (a.sent < -.25 && a.chg < 0) return 'Bearish pressure';
  if (a.sent < -.25 && a.chg > 3) return 'Squeeze / fade risk';
  if (a.recent >= 5 && Math.abs(a.chg || 0) < 1.5) return 'Hype, no move yet';
  return a.recent >= 3 ? 'Heating up' : 'Watch';
}

function buildAssets() {
  const syms = new Set([...byAsset.keys(), ...ext.cg.keys(), ...ext.yh.keys(), ...ext.st.keys(), ...ext.ape.keys(), ...ext.dex.keys(), ...ext.scr.keys(), ...ext.ipo.keys()]);
  const out = [], now = Date.now();
  for (const sym of syms) {
    if (invalid.has(sym)) continue;
    const l = live.get(sym), q = quotes.get(sym), cg = ext.cg.get(sym), ape = ext.ape.get(sym), dx = ext.dex.get(sym), sc = ext.scr.get(sym), ipo = ext.ipo.get(sym);
    const mentions = byAsset.get(sym)?.length || 0, trend = !!(cg || ext.yh.has(sym) || ext.st.has(sym));
    const type = typeOf(sym);
    // Cheap rejects first so stats are only built for plausible rows.
    if (type === 'stock' && !q && mentions < 2 && !trend && !ape && !sc && !ipo) continue;
    if (mentions < 1 && !trend && !ape && !dx && !sc && !ipo) continue;
    const st = statsFor(sym);
    const a = { sym, type, name: names.get(sym) || '', ...st, ape, trend };
    const observed = [l, q, dx, cg].filter(Boolean), fresh = observed.find(v => priceFresh(v, v === l ? 30000 : 600000));
    a.price = fresh?.price ?? null;
    a.chg = fresh?.chg ?? null;
    a.quoteAt = fresh?.marketAt || fresh?.t || null;
    a.priceStale = observed.length > 0 && !fresh;
    a.dx = dx; a.sc = sc; a.cong = ext.cong.get(sym)?.length || 0;
    const t0 = dx ? dx.created : sc?.first || ipo?.t || null;
    a.ageDays = t0 ? (now - t0) / DAY : null;
    a.isNew = a.ageDays != null && a.ageDays < (type === 'crypto' ? 30 : 365);
    a.lowCost = a.price != null && a.price < (type === 'crypto' ? 1 : 5);
    let older = 0; for (let i = 0; i < 15; i++) older += st.buckets[i];
    a.accel = (st.recent + 1) / (older / 5 + 1);
    const live4 = st.day >= 1 || trend || sc || (dx && dx.vol >= 25000 && dx.liq >= 10000) || ipo;
    a.radar = (a.isNew || a.lowCost) && live4 ? Math.min(40, st.recent * 6) + Math.min(20, 10 * Math.log2(a.accel + 1)) + (a.isNew ? 20 : 0) + (a.lowCost ? 10 : 0) + (a.trend ? 8 : 0)
      + Math.min(10, Math.abs(a.chg || 0) / 2) + Math.min(10, 5 * Object.keys(st.bySrc).length) : 0;
    out.push(a);
  }
  let mDay = 1, mRec = 1, mApe = 1;
  for (const a of out) { if (a.day > mDay) mDay = a.day; if (a.recent > mRec) mRec = a.recent; if ((a.ape?.mentions || 0) > mApe) mApe = a.ape.mentions; }
  for (const a of out) {
    a.score = 30 * Math.sqrt(a.day / mDay) + 25 * Math.sqrt(a.recent / mRec) + 10 * Math.sqrt((a.ape?.mentions || 0) / mApe)
      + (ext.cg.has(a.sym) ? 12 - ext.cg.get(a.sym).rank * .6 : 0) + (ext.yh.has(a.sym) ? 12 - ext.yh.get(a.sym).rank * .4 : 0) + (ext.st.has(a.sym) ? 8 - ext.st.get(a.sym).rank * .3 : 0)
      + 10 * Math.min(1, Math.abs(a.chg || 0) / 10) + 3 * Math.max(0, Object.keys(a.bySrc).length - 1) + Math.min(8, a.pol * 2) + Math.min(8, a.cong * 2) + Math.min(12, a.news * 3) + Math.min(6, a.topicN * 1.5) + Math.min(9, a.cred * 3) - (a.day >= 3 && a.cred === 0 ? 4 : 0);
    a.signal = signal(a);
  }
  return out;
}

/* ---------------- Small formatters ---------------- */
const money = n => n == null ? '--' : n >= 1e9 ? (n / 1e9).toFixed(1) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : n.toFixed(0);
const moodWord = s => s > .25 ? 'Bullish' : s < -.25 ? 'Bearish' : 'Mixed';
const toneWord = s => s > .2 ? 'positive' : s < -.2 ? 'negative' : 'mixed';
const spark = b => { let m = 1; for (const v of b) if (v > m) m = v; return `<svg width="70" height="20" viewBox="0 0 70 20"><polyline fill="none" stroke="#4da3ff" stroke-width="1.5" points="${b.map((v, i) => `${(i / 17 * 68 + 1).toFixed(1)},${(19 - v / m * 17).toFixed(1)}`).join(' ')}"/></svg>`; };
const sbar = a => { const t = a.bull + a.bear + a.neu || 1; return `<span class="sbar" title="bullish ${a.bull} / neutral ${a.neu} / bearish ${a.bear}"><i class="b" style="width:${a.bull / t * 100}%"></i><i class="n" style="width:${a.neu / t * 100}%"></i><i class="s" style="width:${a.bear / t * 100}%"></i></span>`; };
const chgHTML = c => c == null ? '<span class="dim">--</span>' : `<span class="${c >= 0 ? 'up' : 'down'}">${c >= 0 ? '+' : ''}${c.toFixed(2)}%</span>`;
const ago = ts => { const s = Math.max(0, (Date.now() - ts) / 1000); return s < 60 ? Math.floor(s) + 's' : s < 3600 ? Math.floor(s / 60) + 'm' : Math.floor(s / 3600) + 'h'; };
function analysis(a) {
  const p = [];
  if (a.news) p.push(`${a.news} headline${a.news > 1 ? 's' : ''}, tone ${toneWord(a.newsTone)}`);
  if (a.topicN) p.push(`${a.topicN} related policy/sector headline${a.topicN > 1 ? 's' : ''}`);
  if (a.recent >= 3) p.push(`chatter ${a.accel.toFixed(1)}x normal`);
  else if (a.day) p.push(`${a.day} mentions, ${moodWord(a.sent).toLowerCase()}`);
  if (Math.abs(a.chg || 0) >= 3) p.push(`${a.chg > 0 ? 'up' : 'down'} ${Math.abs(a.chg).toFixed(1)}%`);
  if (a.cong) p.push(`${a.cong} congress trades`);
  if (a.cred >= 2) p.push(`${a.cred} publisher families; independence unreviewed`);
  else if (a.day >= 3 && a.cred === 0) p.push('unconfirmed, social sources only');
  return p.join(' · ') || 'Not enough data yet';
}
