/* ---------------- Wider news & social sweep ---------------- */
async function rss(q) {
  const doc = await fetchAny(`https://news.google.com/rss/search?q=${encodeURIComponent(q)}&hl=en-US&gl=US&ceid=US:en`, parseXML);
  return [...doc.querySelectorAll('item')].map(i => ({ title: i.querySelector('title')?.textContent || '', link: i.querySelector('link')?.textContent || '', ts: Date.parse(i.querySelector('pubDate')?.textContent), source: i.querySelector('source')?.textContent || '' }));
}
const newsPost = (x, syms) => ({ id: 'n_' + x.link, src: 'News', ts: x.ts, text: x.title, title: x.title, url: x.link, sub: x.source, syms, language: 'en', raw: { title: x.title, link: x.link, publishedAt: x.ts, source: x.source } });
const NEWSQ = ['penny stock surges when:1d', 'meme coin trending when:1d', 'new cryptocurrency token launch when:1d', 'IPO debut stock jumps when:1d', 'small cap stock soars when:1d', 'crypto news when:1h', 'stock market movers when:1h', 'local business stock announcement when:1d'];
let nq = 0;
job('Google News', async () => { (await rss(NEWSQ[nq++ % NEWSQ.length])).forEach(x => addPost(newsPost(x))); }, 15000);
const GDQ = ['(stock OR shares) (surges OR soars OR plunges)', '(cryptocurrency OR token) (launch OR surges OR listing)', '"penny stock" OR "meme coin"', 'IPO (debut OR priced)'];
let gq = 0;
job('GDELT', async () => {
  const j = await fetchJSON(`https://api.gdeltproject.org/api/v2/doc/docapi?query=${encodeURIComponent(GDQ[gq++ % GDQ.length] + ' sourcelang:eng')}&mode=artlist&format=json&maxrecords=75&timespan=2h&sort=datedesc`);
  (j.articles || []).forEach(a => { const d = a.seendate; addPost({ id: 'g_' + a.url, src: 'News', ts: Date.UTC(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8), +d.slice(9, 11), +d.slice(11, 13), +d.slice(13, 15)), text: a.title, url: a.url, sub: a.domain + (a.sourcecountry ? ' (' + a.sourcecountry + ')' : '') }); });
}, 40000);
job('Mastodon', async () => {
  for (const tag of ['bitcoin', 'cryptocurrency', 'memecoin', 'stocks', 'pennystocks', 'investing']) {
    (await fetchJSON(`https://mastodon.social/api/v1/timelines/tag/${tag}?limit=40`)).forEach(s => { if (!isSeen('m_' + s.id)) addPost({ id: 'm_' + s.id, src: 'Mastodon', ts: Date.parse(s.created_at), text: stripHTML(s.content), url: s.url, sub: '@' + s.account.acct }); });
  }
}, 60000);
async function bsky(q) {
  const j = await fetchJSON(`https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=${encodeURIComponent(q)}&limit=30&sort=latest`);
  return (j.posts || []).map(p => ({ id: 'b_' + p.uri, src: 'Bluesky', ts: Date.parse(p.record.createdAt), text: p.record.text, url: `https://bsky.app/profile/${p.author.handle}/post/${p.uri.split('/').pop()}`, sub: '@' + p.author.handle }));
}
job('Bluesky', async () => { for (const q of ['memecoin', 'pennystocks', 'crypto launch', 'stock surge']) (await bsky(q)).forEach(addPost); }, 45000);

