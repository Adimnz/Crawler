/* ---------------- Universe, extraction, sentiment ---------------- */
const SEEDS = 'AAPL MSFT NVDA TSLA AMZN GOOGL GOOG META AMD INTC NFLX SPY QQQ GME AMC PLTR COIN MSTR HOOD SOFI BABA RIVN LCID UBER DIS JPM WMT COST SMCI AVGO ARM TSM PYPL SHOP SNOW CRWD NKE XOM CVX PFE MRNA LLY UNH DJT RDDT IONQ SOUN TQQQ SQQQ SPXL IWM DIA VOO VTI ARKK MARA RIOT CLSK BBAI RKLB ASTS NIO'.split(' ');
const known = { crypto: new Set(), stock: new Set(SEEDS) };
const STOP = new Set('ALL FOR THE AND ARE CEO USD USA ETF IPO YOLO IMO LOL WSB FED GDP CPI SEC EPS ATH FUD NEW ONE NOW OUT CAN ANY BIG TOP HAS WAS NOT BUT YOU YOUR WHO WHY HOW WTF OMG EDIT TLDR LMAO FOMO ITM OTM DCA APY APR PUMP DUMP LONG SHORT BUY SELL HOLD CALL PUTS PUT BULL BEAR MOON GAIN LOSS RED GREEN NEAR FLOW SUN OM ENS GAS POL SAFE OPEN HIGH LOW RISK FREE TRUE FAKE REAL MORE LESS WITH FROM THAT THIS THEY WILL JUST LIKE WHAT WHEN ALSO HAVE BEEN OVER INTO ONLY NEXT LAST YEAR WEEK DAY ETC OP PM AM EST UTC GMT PDT AI TA FA DD NFA PSA IRS CFO CTO'.split(' '));
const ALIASES = { bitcoin:'BTC', ethereum:'ETH', solana:'SOL', dogecoin:'DOGE', ripple:'XRP', cardano:'ADA', shiba:'SHIB', litecoin:'LTC', chainlink:'LINK', avalanche:'AVAX',
  tesla:'TSLA', nvidia:'NVDA', microsoft:'MSFT', amazon:'AMZN', palantir:'PLTR', gamestop:'GME', coinbase:'COIN', microstrategy:'MSTR', netflix:'NFLX', alphabet:'GOOGL', intel:'INTC', broadcom:'AVGO', robinhood:'HOOD' };
const ALIAS_RE = new RegExp('\\b(' + Object.keys(ALIASES).join('|') + ')\\b', 'gi');
const nameIndex = new Map();
let nameRe = null;
const NAME_NOISE = /\b(inc|corp|corporation|holdings|ltd|limited|company|co|plc|group|class|common|stock|ordinary|shares|the)\b|[.,()]/g;
setInterval(() => {
  nameIndex.clear();
  for (const [s, n] of names) {
    const k = String(n || '').toLowerCase().replace(NAME_NOISE, ' ').replace(/\s+/g, ' ').trim();
    if (k.length >= 5 && !WORDSTOP.has(k) && !nameIndex.has(k)) nameIndex.set(k, s);
  }
  // One combined regex is much faster than testing every name against every post.
  const keys = [...nameIndex.keys()].sort((a, b) => b.length - a.length).map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  nameRe = keys.length ? new RegExp('\\b(' + keys.join('|') + ')\\b', 'g') : null;
}, 10000);
function extract(text) {
  const out = new Set();
  if (nameRe) for (const m of text.toLowerCase().matchAll(nameRe)) out.add(nameIndex.get(m[1]));
  for (const m of text.matchAll(/\$([A-Za-z]{1,6})\b/g)) { const s = m[1].toUpperCase(); if (!STABLE.has(s) && !STOP.has(s)) out.add(s); }
  const letters = text.replace(/[^A-Za-z]/g, ''), caps = letters.replace(/[^A-Z]/g, '');
  if (letters.length < 20 || caps.length / letters.length < .6) {
    for (const m of text.matchAll(/\b[A-Z]{3,6}\b/g)) { const s = m[0]; if (!STOP.has(s) && !STABLE.has(s) && (known.crypto.has(s) || known.stock.has(s))) out.add(s); }
  }
  for (const m of text.matchAll(ALIAS_RE)) out.add(ALIASES[m[1].toLowerCase()]);
  return [...out];
}
const BULL = new Set('moon mooning bull bullish calls long buy buying breakout rally surge soar soaring pump undervalued squeeze green beat upgrade ath strong rip rocket gain gains hodl accumulate accumulating winner profit profits bounce recovery jumps climbs rises upgrades approves approval record boost rebound wins deal partnership launches'.split(' '));
const BEAR = new Set('bear bearish puts short sell selling crash dump dumping overvalued red miss downgrade rug scam fraud bagholder tank plunge drop falling collapse recession fear liquidated rekt fade loss losses bubble ponzi delisted falls slumps slides plunges drops cuts probe investigation lawsuit bans fines halts hack hacked exploit delay warns tariffs sanctions layoffs bankruptcy'.split(' '));
function sentiment(text) {
  let b = (text.match(/🚀|📈|🟢|💎|🐂/g) || []).length, r = (text.match(/📉|🔴|🐻|💀|🩸/g) || []).length;
  for (const w of text.toLowerCase().match(/[a-z]+/g) || []) { if (BULL.has(w)) b++; else if (BEAR.has(w)) r++; }
  return b + r ? (b - r) / (b + r) : 0;
}
const WORDSTOP = new Set('the and for that this with you are was but not have has had they them their from just like what when will would could should been about into than then there here your its it\'s i\'m don\'t can\'t out all any one get got how why who which more most some such only over also very much many want going think know need make made still back even well see too off now new want say said like really actually because thing things people time good bad lol yes yeah one two its dont cant thats youre theyre amp http https www com reddit comment comments post stock stocks crypto coin coins market'.split(' '));
const topicCache = new Map();
function topics(sym, list, n = 8) {
  const c = topicCache.get(sym);
  if (c && Date.now() - c.t < 15000) return c.v.slice(0, n);
  const freq = new Map();
  for (const p of list) {
    const seen = new Set(), toks = (p.text.toLowerCase().match(/[a-z][a-z'-]{2,}/g) || []).filter(w => !WORDSTOP.has(w) && !STOP.has(w.toUpperCase()) && w !== sym.toLowerCase());
    toks.forEach((w, i) => { seen.add(w); if (i) seen.add(toks[i - 1] + ' ' + w); });
    seen.forEach(w => freq.set(w, (freq.get(w) || 0) + 1));
  }
  const ranked = [...freq].filter(([, k]) => k >= 2).sort((a, b) => b[1] - a[1] || b[0].length - a[0].length).slice(0, 20);
  const v = ranked.filter(([w, k]) => w.includes(' ') || !ranked.some(([x, kk]) => x.includes(' ') && x.split(' ').includes(w) && kk >= k)).slice(0, 10);
  topicCache.set(sym, { t: Date.now(), v }); return v.slice(0, n);
}

