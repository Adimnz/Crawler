/* ---------------- Candle drawing ---------------- */
const fmtP = p => p == null ? '--' : p >= 1000 ? p.toLocaleString(undefined, { maximumFractionDigits: 2 }) : p >= 1 ? p.toFixed(4).replace(/\.?0+$/, '') : p.toPrecision(4);
function drawCandles(cv, cs, isMini, hover, iv) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return null;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  if (!cs.length) return null;
  const padR = isMini ? 2 : 64, padB = isMini ? 2 : 18, volH = isMini ? 0 : Math.round(h * .16);
  const pw = w - padR, ph = h - padB - volH;
  let hi = -Infinity, lo = Infinity, vmax = 0;
  for (const c of cs) { hi = Math.max(hi, c.h); lo = Math.min(lo, c.l); vmax = Math.max(vmax, c.v); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const y = v => 3 + (hi - v) / (hi - lo) * (ph - 6), cw = pw / cs.length, bw = Math.max(1, cw * .7);
  g.font = '10px system-ui'; g.textBaseline = 'middle';
  if (!isMini) {
    g.strokeStyle = '#262c36'; g.fillStyle = '#8b94a3'; g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4, yy = Math.round(y(v)) + .5; g.beginPath(); g.moveTo(0, yy); g.lineTo(pw, yy); g.stroke(); g.fillText(fmtP(v), pw + 5, yy); }
    g.textBaseline = 'alphabetic';
    for (let k = 0; k < 5; k++) { const i = Math.floor(k * (cs.length - 1) / 4), d = new Date(cs[i].t); g.fillText(iv === '1d' ? d.toLocaleDateString([], { month: 'short', day: 'numeric' }) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), Math.min(pw - 34, i * cw), h - 4); }
  }
  cs.forEach((c, i) => {
    const x = i * cw + cw / 2, col = c.c >= c.o ? '#26c281' : '#ef5350';
    g.strokeStyle = g.fillStyle = col;
    g.beginPath(); g.moveTo(x, y(c.h)); g.lineTo(x, y(c.l)); g.stroke();
    g.fillRect(x - bw / 2, Math.min(y(c.o), y(c.c)), bw, Math.max(1, Math.abs(y(c.o) - y(c.c))));
    if (!isMini && vmax) { g.globalAlpha = .35; const vh = c.v / vmax * volH; g.fillRect(x - bw / 2, h - padB - vh, bw, vh); g.globalAlpha = 1; }
  });
  const last = cs[cs.length - 1], ly = y(last.c), up = last.c >= last.o;
  if (!isMini) {
    g.strokeStyle = up ? '#26c281' : '#ef5350'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(0, ly); g.lineTo(pw, ly); g.stroke(); g.setLineDash([]);
    g.fillStyle = up ? '#26c281' : '#ef5350'; g.fillRect(pw, ly - 7, padR, 14); g.fillStyle = '#000'; g.textBaseline = 'middle'; g.fillText(fmtP(last.c), pw + 4, ly);
    if (hover != null && cs[hover]) { const hx = hover * cw + cw / 2; g.strokeStyle = '#8b94a3'; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(hx, 0); g.lineTo(hx, ph); g.stroke(); g.setLineDash([]); }
  }
  return { cw };
}

/* ---------------- Selected-asset chart ---------------- */
let sel = null, selType = null, iv = '5m', candles = [], hover = null, chartGeom = null, userPicked = false, chartTok = 0, kws = null, stockTimer = null;
$('ivs').innerHTML = Object.keys(YMAP).map(k => `<button data-iv="${k}">${k}</button>`).join(' ');
$('ivs').onclick = e => { const b = e.target.closest('button'); if (b) { iv = b.dataset.iv; loadChart(); } };
function drawMain() { chartGeom = drawCandles($('chart'), candles, false, hover, iv); }
let drawQueued = false;
const schedDraw = () => { if (drawQueued) return; drawQueued = true; requestAnimationFrame(() => { drawQueued = false; drawMain(); }); };
$('chart').onmousemove = e => {
  if (!chartGeom || !candles.length) return;
  hover = Math.min(candles.length - 1, Math.max(0, Math.floor(e.offsetX / chartGeom.cw)));
  const c = candles[hover];
  $('ohlc').textContent = `${new Date(c.t).toLocaleString()}  O ${fmtP(c.o)}  H ${fmtP(c.h)}  L ${fmtP(c.l)}  C ${fmtP(c.c)}  Vol ${c.v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  drawMain();
};
$('chart').onmouseleave = () => { hover = null; $('ohlc').innerHTML = '&nbsp;'; drawMain(); };
window.addEventListener('resize', drawMain);

async function loadChart() {
  const tok = ++chartTok;
  document.querySelectorAll('#ivs button').forEach(b => b.classList.toggle('on', b.dataset.iv === iv));
  if (kws) { kws.onclose = null; kws.close(); kws = null; }
  clearInterval(stockTimer);
  candles = []; drawMain();
  if (!sel) return;
  const sym = sel, type = selType;
  try { candles = await fetchCandles(type, sym, iv); } catch (e) { $('ohlc').textContent = 'No chart data: ' + e.message; return; }
  if (tok !== chartTok) return;
  drawMain();
  if (type === 'crypto' && live.has(sym)) openKline(sym, tok);
  else stockTimer = setInterval(async () => { try { const c = await fetchCandles(type, sym, iv); if (tok === chartTok) { candles = c; drawMain(); } } catch (e) {} }, 8000);
}
function openKline(sym, tok) {
  const s = new WebSocket(`${WSH[wsI]}/ws/${sym.toLowerCase()}usdt@kline_${iv}`);
  kws = s;
  s.onmessage = ev => {
    const k = JSON.parse(ev.data).k; if (!k || tok !== chartTok) return;
    const c = { t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v }, L = candles[candles.length - 1];
    if (L && L.t === c.t) candles[candles.length - 1] = c; else { candles.push(c); if (candles.length > 300) candles.shift(); }
    schedDraw();
  };
  s.onclose = () => { if (tok === chartTok) setTimeout(() => tok === chartTok && openKline(sym, tok), 2000); };
}
async function select(sym, type, picked) {
  if (picked) userPicked = true;
  sel = sym; selType = type; loadChart();
  try { (await fetchJSON(`https://api.stocktwits.com/api/2/streams/symbol/${sym}${type === 'crypto' ? '.X' : ''}.json`)).messages.forEach(m => addPost(stMessage(m))); } catch (e) {}
  renderAll();
}

