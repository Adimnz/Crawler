/* ---------------- Source pollers ---------------- */
const ext = { cg: new Map(), yh: new Map(), st: new Map(), ape: new Map() };
const names = new Map();
const SUBS = 'wallstreetbets+stocks+investing+StockMarket+options+CryptoCurrency+CryptoMarkets+Bitcoin+ethereum+Daytrading+pennystocks+SatoshiStreetBets+Solana';
const redditPost = (d) => ({ id: 'r_' + d.id, src: 'Reddit', ts: d.created_utc * 1000, text: (d.title || d.link_title || '') + ' ' + (d.selftext || d.body || ''), url: 'https://www.reddit.com' + d.permalink, sub: 'r/' + d.subreddit, eng: (d.score || 0) + (d.num_comments || 0) });
async function pollRedditComments() {
  const j = await fetchJSON(`https://www.reddit.com/r/${SUBS}/comments.json?limit=100&raw_json=1`);
  j.data.children.forEach(c => addPost(redditPost(c.data)));
}
async function pollRedditPosts() {
  for (const k of ['new', 'hot']) {
    const j = await fetchJSON(`https://www.reddit.com/r/${SUBS}/${k}.json?limit=100&raw_json=1`);
    j.data.children.forEach(c => addPost(redditPost(c.data)));
  }
}
async function poll4chan() {
  const pages = await fetchJSON('https://a.4cdn.org/biz/catalog.json');
  for (const pg of pages) for (const t of pg.threads) {
    const add = (o, id) => { if (isSeen('4_' + id)) return; addPost({ id: '4_' + id, src: '4chan', ts: o.time * 1000, text: stripHTML((t.sub || '') + ' ' + (o.com || '')), url: `https://boards.4chan.org/biz/thread/${t.no}#p${id}`, sub: '/biz/' }); };
    add(t, t.no); (t.last_replies || []).forEach(r => add(r, r.no));
  }
}
function stMessage(m) {
  return { id: 'st_' + m.id, src: 'StockTwits', ts: Date.parse(m.created_at), text: m.body, url: `https://stocktwits.com/${m.user?.username}/message/${m.id}`,
    syms: (m.symbols || []).map(s => s.symbol.replace(/\.X$/, '')),
    sent: m.entities?.sentiment?.basic === 'Bullish' ? 1 : m.entities?.sentiment?.basic === 'Bearish' ? -1 : null, sub: '@' + (m.user?.username || '') };
}
async function pollStockTwits() {
  const j = await fetchJSON('https://api.stocktwits.com/api/2/streams/trending.json');
  j.messages.forEach(m => addPost(stMessage(m)));
  const t = await fetchJSON('https://api.stocktwits.com/api/2/trending/symbols.json');
  t.symbols.forEach((s, i) => { const sym = s.symbol.replace(/\.X$/, ''); ext.st.set(sym, { rank: i, crypto: /\.X$/.test(s.symbol) }); names.set(sym, names.get(sym) || s.title); if (!/\.X$/.test(s.symbol)) known.stock.add(sym); });
}
async function pollYahooTrending() {
  const j = await fetchJSON('https://query1.finance.yahoo.com/v1/finance/trending/US?count=25');
  j.finance.result[0].quotes.forEach((q, i) => { if (/^[A-Z]{1,5}$/.test(q.symbol)) { ext.yh.set(q.symbol, { rank: i }); known.stock.add(q.symbol); } });
}
async function pollCoinGecko() {
  const j = await fetchJSON('https://api.coingecko.com/api/v3/search/trending');
  j.coins.forEach((c, i) => { const it = c.item, s = it.symbol.toUpperCase(); ext.cg.set(s, { rank: i, price: +it.data?.price || null, chg: it.data?.price_change_percentage_24h?.usd ?? null, t: Date.now() }); names.set(s, names.get(s) || it.name); });
}
async function pollApe() {
  for (const [f, type] of [['all-stocks', 'stock'], ['all-crypto', 'crypto']]) {
    const j = await fetchJSON(`https://apewisdom.io/api/v1.0/filter/${f}/page/1`);
    j.results.forEach(r => { const s = r.ticker.replace(/\.X$/, ''); ext.ape.set(s, { type, mentions: +r.mentions, ups: +r.upvotes, rank: +r.rank, prev: +r.mentions_24h_ago || 0 }); names.set(s, names.get(s) || r.name); if (type === 'stock') known.stock.add(s); });
  }
}
async function pollFNG() {
  const x = (await fetchJSON('https://api.alternative.me/fng/?limit=1')).data[0];
  $('fng').textContent = `Crypto Fear & Greed: ${x.value} (${x.value_classification})`;
}
job('Reddit chat', pollRedditComments, 12000);
job('Reddit posts', pollRedditPosts, 30000);
job('4chan /biz/', poll4chan, 90000);
job('StockTwits', pollStockTwits, 20000);
job('Yahoo trend', pollYahooTrending, 60000);
job('CoinGecko', pollCoinGecko, 60000);
job('ApeWisdom', pollApe, 60000);
job('Alt.me', pollFNG, 300000);

