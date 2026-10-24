/* ---------------- Rendering, events, main loop ---------------- */
let lastAll = [], lastAllMap = new Map(), lastRadar = [], typeSel = '', tab = 'intelligence', lastBuild = 0, moversNow = [];
const setHTML = (el, h) => { if (el._h !== h) { el._h = h; el.innerHTML = h; } };
const memoStore = new Map();
window.addEventListener('crawler:post', () => memoStore.delete('heads6h'));
const memo = (key, ms, fn) => { const m = memoStore.get(key); if (m && Date.now() - m.t < ms) return m.v; const v = fn(); memoStore.set(key, { t: Date.now(), v }); return v; };
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const flags = a => (a.isNew ? `<span class="tag new">new ${a.ageDays < 1 ? Math.max(1, Math.round(a.ageDays * 24)) + 'h' : Math.round(a.ageDays) + 'd'}</span>` : '') + (a.lowCost ? '<span class="tag low">low cost</span>' : '') + (a.dx && a.dx.liq < 25000 ? '<span class="tag risk">thin liquidity</span>' : '')
  + (a.cred >= 2 ? `<span class="tag">${a.cred} publishers</span>` : a.day >= 3 && !a.cred ? '<span class="tag risk">unconfirmed</span>' : '');
function rowHTML(a, extra = '') {
  return `<div class="row${a.sym === sel ? ' sel' : ''}" data-s="${esc(a.sym)}" data-t="${a.type}">
    <div><div class="sym">${esc(a.sym)}<span class="tag ${a.type}">${a.type}</span>${flags(a)}</div><div class="nm">${esc(a.name)}</div></div>
    <div><div>${a.price == null ? '--' : '$' + fmtP(a.price)}</div>${chgHTML(a.chg)}<div class="dim sm">${a.priceStale ? 'Quote unavailable / stale' : a.quoteAt ? 'Provider quote ' + new Date(a.quoteAt).toLocaleTimeString() : ''}</div></div>
    <div>${spark(a.buckets)}<div class="dim sm">${a.recent} in 30m</div></div>
    <div>${sbar(a)}<div class="dim sm">${moodWord(a.sent)}</div></div>
    <div class="why"><span class="sig">${esc(a.signal)}</span>${esc(analysis(a))}${extra}</div></div>`;
}

function renderPicks() {
  if (document.body.dataset.destination === 'markets') {
    const q = $('filter').value.trim().toUpperCase();
    const assets = [...[...live].map(([sym, value]) => ({sym, type:'crypto', ...value})), ...[...quotes].map(([sym, value]) => ({sym, type:'stock', ...value}))]
      .filter(a => (!typeSel || a.type===typeSel) && (!q || a.sym.includes(q))).sort((a,b) => a.type.localeCompare(b.type) || a.sym.localeCompare(b.sym)).slice(0,200);
    setHTML($('rows'), assets.map(a => `<button class="market-quote" data-s="${esc(a.sym)}" data-t="${a.type}"><b>${esc(a.sym)} <small>${a.type}</small></b><strong>${Number.isFinite(a.price)?'$'+fmtP(a.price):'Unavailable'}</strong>${chgHTML(a.chg)}<small>${priceFresh(a)?'Provider update':'Stale / unavailable'} · ${a.t?new Date(a.marketAt || a.t).toLocaleTimeString():'No timestamp'}</small></button>`).join('') || '<div class="empty">Waiting for stock and crypto provider quotes. No estimated prices are shown.</div>');
    return;
  }
  const q = $('filter').value.trim().toUpperCase();
  const rows = lastAll.filter(a => (!typeSel || a.type === typeSel) && (!q || a.sym.includes(q) || a.name.toUpperCase().includes(q))).sort((a, b) => b.score - a.score).slice(0, 40);
  if (!sel && !userPicked && rows.length) select(rows[0].sym, rows[0].type);
  setHTML($('rows'), rows.map(a => rowHTML(a)).join('') || '<div class="empty">Collecting data...</div>');
}
function renderRadar() {
  setHTML($('radar'), lastRadar.filter(a => !typeSel || a.type === typeSel).map(a => rowHTML(a, a.dx ? ` · liquidity $${money(a.dx.liq)}` : a.sc?.cap ? ` · mcap $${money(a.sc.cap)}` : '')).join('') || '<div class="empty">Scanning for new and low-cost assets...</div>');
}

function postHTML(p) {
  const u = safeURL(p.url), tone = p.sent > .15 ? 'up' : p.sent < -.15 ? 'down' : '';
  return `<div class="post"><a class="pt" ${u ? `href="${esc(u)}" target="_blank" rel="noopener noreferrer"` : ''}>${esc(p.text.slice(0, 200))}</a>
    <div class="pm"><i class="dotc ${tone}"></i>${esc(p.sub || p.src)} · ${ago(p.ts)} ago<span class="tag ${p.w >= .7 ? 'ok' : p.w < .3 ? 'risk' : ''}" title="reliability weight ${(p.w ?? 0).toFixed(2)}">${esc(p.tier || '')}</span>${p.pol ? '<span class="tag pol">political</span>' : ''}${p.syms.slice(0, 4).map(s => `<span class="chip" data-s="${esc(s)}">${esc(s)}</span>`).join('')}</div></div>`;
}
const byTime = (x, y) => y.ts - x.ts;
function cardHTML(p) {
  const u = safeURL(p.url), img = safeURL(p.image), tone = p.sent > .15 ? 'up' : p.sent < -.15 ? 'down' : '';
  const outlet = String(p.sub || p.src).split(' via ')[0], title = p.title || p.text.slice(0, 200);
  const body = p.text.startsWith(title) ? p.text.slice(title.length).replace(/^[\s.:\-]+/, '') : p.text;
  const href = u ? `href="${esc(u)}" target="_blank" rel="noopener noreferrer"` : '';
  const media = img ? `<img src="${esc(img)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : '';
  return `<article class="news-card${img ? '' : ' noimg'}"><a class="nc-media" ${href} tabindex="-1" aria-hidden="true">${media}<span class="nc-fallback">${esc(outlet.slice(0, 1).toUpperCase())}</span></a>
    <div class="nc-body"><div class="nc-meta"><i class="dotc ${tone}"></i><b>${esc(outlet)}</b><span>${ago(p.ts)} ago</span></div>
    <a class="nc-title" ${href}>${esc(title.slice(0, 200))}</a>${body ? `<p>${esc(body.slice(0, 180))}</p>` : ''}
    <div class="nc-tags">${p.tier ? `<span class="tag ${p.w >= .7 ? 'ok' : p.w < .3 ? 'risk' : ''}" title="reliability weight ${(p.w ?? 0).toFixed(2)}">${esc(p.tier)}</span>` : ''}${p.pol ? '<span class="tag pol">political</span>' : ''}${(p.syms || []).slice(0, 3).map(s => `<span class="chip">${esc(s)}</span>`).join('')}</div></div></article>`;
}

function renderDetail() {
  if (!sel) return;
  const a = lastAllMap.get(sel), st = statsFor(sel), l = live.get(sel), q = quotes.get(sel), dx = ext.dex.get(sel), last = candles[candles.length - 1];
  pmLookup(sel);
  const quote = selType === 'crypto' ? (priceFresh(l, 30000) ? l : priceFresh(dx, 600000) ? dx : null) : priceFresh(q, 600000) ? q : null;
  const price = quote?.price;
  $('dSym').textContent = sel;
  setHTML($('dName'), `${esc(names.get(sel) || '')} <span class="tag ${selType}">${selType}</span>`);
  $('dPrice').textContent = price != null ? '$' + fmtP(price) : 'Quote unavailable';
  $('dChg').innerHTML = chgHTML(quote?.chg) + (quote ? '<div class="dim sm">Provider quote ' + esc(new Date(quote.marketAt || quote.t).toLocaleString()) + '</div>' : '<div class="dim sm">No fresh provider response</div>');
  const t = st.bull + st.bear + st.neu || 1, tmax = Math.max(1, ...st.buckets), tp = topics(sel, st.list, 8);
  const heads = [...st.heads].sort(byTime).slice(0, 4), pol = [...st.topicHeads].sort(byTime).slice(0, 3);
  const sec = (h, body) => body ? `<div class="sec"><div class="sh">${h}</div>${body}</div>` : '';
  const extra = (dx ? `<div class="dim sm">DEX token on ${esc(dx.chain)} · liquidity $${money(dx.liq)} · 24h volume $${money(dx.vol)} · ${((Date.now() - dx.created) / DAY).toFixed(1)} days old · <a style="color:var(--acc)" href="${esc(safeURL(dx.url))}" target="_blank" rel="noopener noreferrer">DexScreener</a><br>New tokens carry high rug-pull risk.</div>` : '') + wikiLine(sel) + congLine(sel);
  setHTML($('dStats'),
    `<div class="sum">${a ? `<span class="sig">${esc(a.signal)}</span>${esc(analysis(a))}` : ''}</div>`
    + `<div class="kv"><div><b>${st.day}</b><span>mentions 24h</span></div><div><b>${st.recent}</b><span>last 30 min</span></div><div><b>${st.news}</b><span>headlines</span></div><div><b>${st.cred}</b><span>publisher families</span></div></div>`
    + memo('outlook:' + sel, 15000, () => outlookHTML(sel, selType, a))
    + sec('Prediction markets', pmFor(sel).map(pmHTML).join(''))
    + `<div class="mood">${sbar(st)}<div class="dim sm">${(st.bull / t * 100).toFixed(0)}% bullish · ${(st.neu / t * 100).toFixed(0)}% neutral · ${(st.bear / t * 100).toFixed(0)}% bearish</div></div>`
    + `<div class="tl" title="mentions per 10 min, last 3 hours">${st.buckets.map(v => `<i style="height:${v / tmax * 100}%"></i>`).join('')}</div>`
    + sec('In the news', heads.map(postHTML).join(''))
    + sec('Policy and sector headlines that may affect it', pol.map(postHTML).join(''))
    + sec('Talking about', tp.map(([w, k]) => `<span class="chip">${esc(w)} <small>${k}</small></span>`).join(''))
    + sec('Often mentioned with', memo('rel:' + sel, 10000, () => relatedHTML(sel, st.list)))
    + (extra ? `<div class="sec">${extra}</div>` : '')
    + `<div class="sec"><a class="btn sm" data-go="mentions">See all ${st.day} mentions with filters</a></div>`);
}

// Headline set for the last 6h, recomputed at most every 8s.
const sixHourHeads = () => memo('heads6h', 8000, () => newsPosts.filter(p => p.ts > Date.now() - 6 * 36e5).sort(byTime));
function categoryPages(items, renderItem) {
  const groups = new Map();
  for (const item of items) {
    const category = item.categories?.[0] || (item.pol ? 'Politics & policy' : 'General');
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(item);
  }
  return [...groups].map(([category, rows]) => `<section class="category-section"><h2>${esc(category)} <small>${rows.length}</small></h2><div class="category-cards">${rows.map(renderItem).join('')}</div></section>`).join('');
}
function renderNews(full) {
  const heads = sixHourHeads();
  const pol = heads.filter(p => p.pol).length, nz = heads.filter(p => Math.abs(p.sent) > .15), neg = nz.filter(p => p.sent < 0).length;
  const tone = nz.length ? `${Math.round(neg / nz.length * 100)}% negative` : 'neutral';
  $('pNews').textContent = heads.length ? `${heads.length} headlines in 6h · tone ${tone} · ${pol} political` : '';
  if (!full) return;
  const cnt = new Map(); heads.forEach(p => p.syms.forEach(s => cnt.set(s, (cnt.get(s) || 0) + 1)));
  const covered = [...cnt].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([s, n]) => {
    const ss = heads.filter(p => p.syms.includes(s)).map(p => p.sent).filter(x => Math.abs(x) > .15), m = ss.length ? ss.reduce((x, y) => x + y, 0) / ss.length : 0;
    return `<span class="chip" data-s="${esc(s)}">${esc(s)} ${n} <span class="${m > .2 ? 'up' : m < -.2 ? 'down' : 'dim'}">${m > .2 ? '▲' : m < -.2 ? '▼' : '●'}</span></span>`;
  }).join('');
  const sectors = POL_TOPICS.map(([re], i) => [SECTORS[i], heads.filter(p => re.test(p.text)).length]).filter(x => x[1]).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([n, c]) => `<span class="chip">${n} ${c}</span>`).join('');
  const th = topics('__news', heads, 8).map(([w, k]) => `<span class="chip">${esc(w)} ${k}</span>`).join('');
  setHTML($('read'), heads.length ? `<p>${heads.length} headlines from ${new Set(heads.map(p => p.sub.split(' via ')[0])).size} outlets in the last 6 hours. ${pol} (${Math.round(pol / heads.length * 100)}%) touch politics or regulation. Overall tone is ${tone}.</p>`
    + (covered ? `<div class="rl">Most covered assets</div>${covered}` : '') + (sectors ? `<div class="rl">Policy themes</div>${sectors}` : '') + (th ? `<div class="rl">Topics</div>${th}` : '') : '<div class="dim">Reading major outlets...</div>');
  setHTML($('headlines'), categoryPages(heads.filter(p => (!$('polOnly').checked || p.pol) && (! $('filter').value.trim() || (p.title+' '+p.text+' '+p.sub).toLowerCase().includes($('filter').value.trim().toLowerCase()))).slice(0, 60), cardHTML) || '<div class="empty">No headlines yet.</div>');
  const macro = ext.pm.slice(0, 10);
  setHTML($('pmmacro'), macro.length ? `<div class="sh">What prediction markets are pricing in</div>${macro.map(pmHTML).join('')}` : '<div class="dim sm">Loading prediction markets...</div>');
}
function renderStream() {
  setHTML($('stream'), categoryPages(recentPosts.slice(-300).sort(byTime).filter(p => ! $('filter').value.trim() || (p.title+' '+p.text+' '+p.sub).toLowerCase().includes($('filter').value.trim().toLowerCase())).slice(0, 60), cardHTML) || '<div class="empty">Waiting for posts...</div>');
}

/* Mentions for the selected asset, with source / mood / reliability filters */
const mFilter = { srcs: new Set(), sent: '', rel: 0 };
function renderMentions() {
  if (!sel) return setHTML($('mlist'), '<div class="empty">Select an asset to see its mentions.</div>');
  const all = statsFor(sel).list, counts = {};
  all.forEach(p => counts[p.src] = (counts[p.src] || 0) + 1);
  $('mtitle').textContent = `${sel} mentions`;
  setHTML($('mchips'), Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([s, n]) => `<button class="fchip${mFilter.srcs.has(s) ? ' on' : ''}" data-src="${esc(s)}">${esc(s)} ${n}</button>`).join(''));
  const list = all.filter(p => (!mFilter.srcs.size || mFilter.srcs.has(p.src)) && (p.w ?? 0) >= mFilter.rel
    && (!mFilter.sent || (mFilter.sent === 'bull' ? p.sent > .15 : mFilter.sent === 'bear' ? p.sent < -.15 : Math.abs(p.sent) <= .15))).sort(byTime);
  $('mcount').textContent = `${list.length} of ${all.length}`;
  setHTML($('mlist'), list.slice(0, 150).map(postHTML).join('') || '<div class="empty">No mentions match these filters.</div>');
}

/* Source quality: feed uptime, outlet tiers, corroboration and measured platform track record */
function renderSources() {
  const feeds = Object.entries(sources).map(([n, s]) => `<tr><td>${esc(n)}</td><td>${s.total ? Math.round(s.okN / s.total * 100) + '%' : '--'}</td><td class="dim">${s.ok ? 'ok' : esc(s.msg)}</td></tr>`).join('');
  const outl = Object.entries(feedStat).sort((a, b) => b[1].okN / b[1].total - a[1].okN / a[1].total).map(([n, s]) => `<span class="chip" title="${esc(s.msg)}"><i class="dotc ${s.ok ? 'up' : 'down'}"></i> ${esc(n)} ${Math.round(s.okN / s.total * 100)}%</span>`).join('');
  const fam = new Map();
  for (const p of newsPosts) { const f = famOf(p), e = fam.get(f) || { n: 0, tier: p.tier, w: p.w, listed: !!p.listed }; e.n++; fam.set(f, e); }
  const top = [...fam].sort((a, b) => b[1].n - a[1].n).slice(0, 25);
  const outRows = memo('corr', 20000, () => top.map(([f, e]) => { const c = corroboration(f); return { f, e, c }; })).map(({ f, e, c }) => {
    const verdict = c.tot < 3 ? '<span class="dim">too little data</span>' : c.rate >= .6 ? 'frequent topic overlap' : c.rate < .2 ? 'limited topic overlap' : 'mixed topic overlap';
    return `<tr><td>${esc(f)}</td><td>${esc(e.tier)}</td><td>${e.n}</td><td>${c.rate == null ? '--' : Math.round(c.rate * 100) + '%'}</td><td>${verdict}</td><td class="dim">${e.listed ? 'curated' : 'discovered'}</td></tr>`;
  }).join('');
  const tr = Object.entries(trackRate).sort((a, b) => b[1].n - a[1].n).map(([s, r]) => `<tr><td>${esc(s)}</td><td>${esc(SRC_TIER[s] || '')}</td><td>${r.n}</td><td>${r.n >= 30 ? Math.round(r.hit / r.n * 100) + '%' : 'building'}</td></tr>`).join('');
  const pts = [...hist.values()].reduce((x, a) => x + a.length, 0);
  setHTML($('srcview'),
    `<div class="card2"><div class="sh">Source weights and coverage diagnostics</div><p class="dim sm">Static source tiers weight the legacy market sentiment model. Publisher counts and coverage overlap do not establish independent confirmation or truth. The overlap metric checks whether a high-tier outlet mentioned the same symbol within six hours; it does not compare specific claims. Use Intelligence for claim-level analyst assessments and candidate reporting lineage. Platform track record measures historical mood versus later price direction (${pts.toLocaleString()} saved points); it is not a source-accuracy score or calibrated prediction.</p></div>`
    + `<div class="card2"><div class="sh">Curated outlet feeds (uptime)</div>${outl || '<span class="dim sm">Loading...</span>'}</div>`
    + `<div class="card2"><div class="sh">Outlets seen in the last 24h</div><table class="tbl"><tr><th>Outlet</th><th>Tier</th><th>Items</th><th>Topic overlap</th><th>Observation</th><th></th></tr>${outRows}</table></div>`
    + `<div class="card2"><div class="sh">Platform track record (mood vs next-hour price)</div><table class="tbl"><tr><th>Platform</th><th>Tier</th><th>Samples</th><th>Hit rate</th></tr>${tr || '<tr><td colspan="4" class="dim">Needs about an hour of history first.</td></tr>'}</table></div>`
    + `<div class="card2"><div class="sh">Data feeds</div><table class="tbl"><tr><th>Feed</th><th>Uptime</th><th>Status</th></tr>${feeds}</table></div>`);
}

function moversList() {
  const out = [...live].filter(([, v]) => priceFresh(v, 30000) && v.vol > 8e6).sort((a, b) => Math.abs(b[1].chg) - Math.abs(a[1].chg)).slice(0, 6).map(([s, v]) => ({ sym: s, type: 'crypto', price: v.price, chg: v.chg }));
  const st = [...quotes].filter(([s, v]) => priceFresh(v, 600000) && !invalid.has(s) && v.chg != null && quoteQueue.includes(s)).sort((a, b) => Math.abs(b[1].chg) - Math.abs(a[1].chg)).slice(0, 4);
  st.forEach(([s, v]) => out.push({ sym: s, type: 'stock', price: v.price, chg: v.chg }));
  return out;
}
function renderMovers() {
  moversNow = moversList();
  const m = moversNow.filter(x => !typeSel || x.type === typeSel);
  setHTML($('movers'), m.map(x => `<div class="mv" data-s="${esc(x.sym)}" data-t="${x.type}"><div class="mt"><b>${esc(x.sym)}</b>${chgHTML(x.chg)}</div><canvas data-k="${x.type}:${esc(x.sym)}"></canvas></div>`).join(''));
  document.querySelectorAll('#movers canvas').forEach(cv => {
    const e = mini.get(cv.dataset.k); if (!e || !e.c.length) return;
    const cs = e.c.map(c => ({ ...c })), [type, sym] = cv.dataset.k.split(':'), p = type === 'crypto' ? live.get(sym)?.price : quotes.get(sym)?.price;
    if (p != null) { const L = cs[cs.length - 1]; L.c = p; L.h = Math.max(L.h, p); L.l = Math.min(L.l, p); }
    drawCandles(cv, cs, true);
  });
}
// One mini-chart fetch at a time, only while the tab is visible.
setInterval(async () => {
  if (!browserCollectionAllowed() || window.CrawlerServer?.offline || document.hidden) return;
  for (const x of moversNow) {
    const k = x.type + ':' + x.sym, e = mini.get(k);
    if (e && Date.now() - e.t < (x.type === 'crypto' ? 90000 : 3e5)) continue;
    try { mini.set(k, { t: Date.now(), c: await fetchCandles(x.type, x.sym, x.type === 'crypto' ? '15m' : '5m', 48) }); } catch (er) { mini.set(k, { t: Date.now(), c: e?.c || [] }); }
    return;
  }
}, 2000);

/* ---------------- Main loop: heavy work is throttled and only runs for what is visible ---------------- */
function renderAll() {
  if (window.CrawlerServer?.offline) return;
  if (window.CrawlerHub && document.body.dataset.experience && document.body.dataset.experience !== 'workspace') return;
  const now = Date.now();
  if (now - lastBuild > 3000) {
    lastAll = buildAssets(); lastBuild = now;
    lastAllMap = new Map(lastAll.map(a => [a.sym, a]));
    lastRadar = lastAll.filter(a => a.radar > 0).sort((a, b) => b.radar - a.radar).slice(0, 25);
    quoteQueue = lastAll.filter(a => a.type === 'stock').sort((a, b) => b.score - a.score).slice(0, 25).map(a => a.sym);
    $('updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
    $('cnt').textContent = `${ingested.toLocaleString()} posts read, ${posts.size.toLocaleString()} in the last 24h`;
  }
  if (tab === 'picks') renderPicks();
  else if (tab === 'radar') renderRadar();
  else if (tab === 'feed') renderStream();
  else if (tab === 'mentions') renderMentions();
  else if (tab === 'sources') renderSources();
  renderNews(tab === 'news');
  window.IntelligenceUI?.render(tab);
  if (!['intelligence', 'research', 'workspace', 'registry'].includes(tab)) renderDetail();
  renderMovers();
}
(function loop() { if (!document.hidden && !window.CrawlerServer?.offline) renderAll(); setTimeout(loop, 2500); })();

/* ---------------- Events ---------------- */
$('tabs').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  tab = b.dataset.t; [...$('tabs').children].forEach(x => x.classList.toggle('on', x === b));
  ['intelligence', 'research', 'workspace', 'registry', 'picks', 'radar', 'news', 'mentions', 'feed', 'sources'].forEach(t => $('tab-' + t).hidden = t !== tab);
  renderAll();
};
$('mchips').onclick = e => { const b = e.target.closest('[data-src]'); if (!b) return; const s = b.dataset.src; mFilter.srcs.has(s) ? mFilter.srcs.delete(s) : mFilter.srcs.add(s); renderMentions(); };
$('msent').onchange = e => { mFilter.sent = e.target.value; renderMentions(); };
$('mrel').onchange = e => { mFilter.rel = +e.target.value; renderMentions(); };
$('mclear').onclick = () => { mFilter.srcs.clear(); mFilter.sent = ''; mFilter.rel = 0; $('msent').value = ''; $('mrel').value = '0'; renderMentions(); };
document.addEventListener('click', e => { const g = e.target.closest('[data-go]'); if (g) { if (window.CrawlerHub) window.CrawlerHub.navigateToModule(g.dataset.go); else $('tabs').querySelector(`[data-t="${g.dataset.go}"]`).click(); } });
$('type').onclick = e => { const b = e.target.closest('button'); if (!b) return; typeSel = b.dataset.v; [...$('type').children].forEach(x => x.classList.toggle('on', x === b)); renderAll(); };
$('srcbtn').onclick = () => { $('srcpanel').hidden = !$('srcpanel').hidden; };
$('polOnly').onchange = () => renderAll();
$('filter').oninput = debounce(renderAll, 150);
document.addEventListener('click', e => {
  const el = e.target.closest('[data-s]'); if (!el || e.target.closest('a')) return;
  select(el.dataset.s, el.dataset.t || typeOf(el.dataset.s), true);
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) renderAll(); });
renderAll();


