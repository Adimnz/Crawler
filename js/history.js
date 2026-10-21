/* ---------------- History: saved snapshots, source track record, statistical outlook ---------------- */
const HIST_MAX = 1008, HIST_STEP = 600000, HZ1 = 6, HZ2 = 36;   // 10-minute points, 7 days, horizons of 1h and 6h
const hist = new Map(), dirtySyms = new Set();
let idb = null;
const idbReq = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });

async function openHistory() {
  const open = indexedDB.open('trend-crawler', 1);
  open.onupgradeneeded = () => open.result.createObjectStore('hist');
  idb = await idbReq(open);
  const st = idb.transaction('hist').objectStore('hist');
  const keys = await idbReq(st.getAllKeys()), vals = await idbReq(st.getAll());
  keys.forEach((k, i) => hist.set(k, vals[i]));
  evalTrack();
}
function persist() {
  if (!idb || !dirtySyms.size) return;
  const st = idb.transaction('hist', 'readwrite').objectStore('hist');
  dirtySyms.forEach(s => st.put(hist.get(s), s)); dirtySyms.clear();
}

function snapshot() {
  if (document.hidden || !lastAll.length) return;
  const t = Date.now();
  for (const a of [...lastAll].sort((x, y) => y.score - x.score).slice(0, 60)) {
    if (a.price == null) continue;
    const arr = hist.get(a.sym) || [], last = arr[arr.length - 1];
    if (last && t - last.t < HIST_STEP * .8) continue;
    arr.push({ t, p: a.price, d: a.day, r: a.recent, s: +a.sent.toFixed(2), w: +a.wsent.toFixed(2), n: +a.newsTone.toFixed(2), c: a.cred, sc: Math.round(a.score), bs: a.srcSent });
    if (arr.length > HIST_MAX) arr.splice(0, arr.length - HIST_MAX);
    hist.set(a.sym, arr); dirtySyms.add(a.sym);
  }
  evalTrack(); persist();
}

// For each platform: how often did its average mood on an asset match the next hour's price direction?
function evalTrack() {
  const rec = {};
  for (const arr of hist.values()) for (let i = 0; i + HZ1 < arr.length; i++) {
    const a = arr[i], b = arr[i + HZ1];
    if (!a.bs || !(a.p > 0) || b.t - a.t > HIST_STEP * HZ1 * 3) continue;
    const up = b.p > a.p;
    for (const [src, v] of Object.entries(a.bs)) { const r = rec[src] ||= { n: 0, hit: 0 }; r.n++; if ((v > 0) === up) r.hit++; }
  }
  for (const k in trackRate) delete trackRate[k];
  Object.assign(trackRate, rec);
}

const composite = x => .5 * (x.w || 0) + .3 * (x.n || 0) + .2 * (x.s || 0);
const moodBucket = v => v > .15 ? 1 : v < -.15 ? -1 : 0;
// Looks up past moments with the same credibility-weighted mood and reports how price moved afterwards.
function outlook(sym, type, a) {
  const cur = moodBucket(composite({ w: a.wsent, n: a.newsTone, s: a.sent }));
  const calc = (series, H) => {
    let n = 0, up = 0, sum = 0;
    for (const arr of series) for (let i = 0; i + H < arr.length; i++) {
      const x = arr[i], y = arr[i + H];
      if (moodBucket(composite(x)) !== cur || !(x.p > 0) || y.t - x.t > HIST_STEP * H * 3) continue;
      n++; const r = (y.p - x.p) / x.p; sum += r; if (r > 0) up++;
    }
    return { n, pUp: (up + 1) / (n + 2), avg: n ? sum / n : 0 };
  };
  const own = [hist.get(sym) || []], pool = [...hist].filter(([s]) => typeOf(s) === type).map(([, v]) => v);
  const pick = H => { const o = calc(own, H); return o.n >= 8 ? { ...o, scope: 'this asset' } : { ...calc(pool, H), scope: 'similar assets' }; };
  return { cur, h1: pick(HZ1), h6: pick(HZ2), points: (hist.get(sym) || []).length };
}
function outlookHTML(sym, type, a) {
  if (!a) return '';
  const o = outlook(sym, type, a);
  const lean = r => r.n < 5 ? '<span class="dim">insufficient history</span>' : r.pUp > .56 ? '<b class="up">More positive historical outcomes</b>' : r.pUp < .44 ? '<b class="down">More negative historical outcomes</b>' : '<b>No clear historical direction</b>';
  const mood = ['bearish', 'mixed', 'bullish'][o.cur + 1];
  return `<div class="outlook"><div class="sh">Outlook from history</div>
    <div>One-hour historical horizon: ${lean(o.h1)} <span class="dim sm">(${o.h1.n} observations)</span></div>
    <div>Six-hour historical horizon: ${lean(o.h6)} <span class="dim sm">(${o.h6.n} observations)</span></div>
    <div class="dim sm">Current source-weighted mood is ${mood}. Compared against ${o.h1.scope === 'this asset' ? 'this asset' : 'similar assets'}' past moments with the same mood. ${o.points ? o.points + ' saved points for this asset.' : 'History for this asset starts building now.'} Observations can overlap. This model has not been calibrated as a forecast; no predictive probability is available.</div></div>`;
}

openHistory().catch(() => {});
setTimeout(snapshot, 60000);
setInterval(snapshot, HIST_STEP);
