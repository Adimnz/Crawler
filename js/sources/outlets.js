/* ---------------- Major news outlets: US and international, markets, crypto, regulators, company filings ---------------- */
const FINREL_RE = /\b(stocks?|shares|markets?|crypto\w*|bitcoin|ether\w*|tokens?|etfs?|ipo|earnings|inflation|rates?|economy|economic|trade|tariffs?|dollar|bank\w*|invest\w*|wall street|nasdaq|dow|oil|gold|merger|acquisition|filing|revenue|profit|ceo)\b/i;
const SECTORS = ['Crypto policy', 'Chips & export controls', 'Energy', 'EVs', 'Pharma & FDA', 'AI', 'Banking'];

// [name, feed url, tier]. Tiers feed the reliability weights (see reliability.js).
const OUTLETS = [
  // Regulators, central banks and company filings: primary sources
  ['SEC Press', 'https://www.sec.gov/news/pressreleases.rss', 'primary'], ['SEC 8-K filings', 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=40&output=atom', 'primary'],
  ['Federal Reserve', 'https://www.federalreserve.gov/feeds/press_all.xml', 'primary'], ['ECB', 'https://www.ecb.europa.eu/rss/press.html', 'primary'],
  ['Bank of England', 'https://www.bankofengland.co.uk/rss/news', 'primary'], ['CFTC', 'https://www.cftc.gov/RSS/RSSGP/rssgp.xml', 'primary'],
  // Company-issued press releases (accurate about what the company says, but promotional)
  ['PR Newswire', 'https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss', 'regional'],
  ['GlobeNewswire', 'https://www.globenewswire.com/RssFeed/subjectcode/18-Public%20Companies/feedTitle/GlobeNewswire%20-%20Public%20Companies', 'regional'],
  // US business and politics
  ['CNBC', 'https://www.cnbc.com/id/100003114/device/rss/rss.html', 'major'], ['CNBC Markets', 'https://www.cnbc.com/id/20910258/device/rss/rss.html', 'major'], ['CNBC Investing', 'https://www.cnbc.com/id/15839069/device/rss/rss.html', 'major'],
  ['MarketWatch', 'https://feeds.content.dowjones.io/public/rss/mw_topstories', 'major'], ['MarketWatch Pulse', 'https://feeds.content.dowjones.io/public/rss/mw_marketpulse', 'major'],
  ['WSJ Markets', 'https://feeds.content.dowjones.io/public/rss/RSSMarketsMain', 'major'], ['WSJ Business', 'https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness', 'major'],
  ['NYT Business', 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml', 'major'], ['NYT Economy', 'https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml', 'major'], ['NYT Politics', 'https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml', 'major'],
  ['Washington Post Business', 'https://feeds.washingtonpost.com/rss/business', 'major'], ['Fox Business', 'https://moxie.foxbusiness.com/google-publisher/latest.xml', 'specialist'],
  ['Yahoo Finance', 'https://finance.yahoo.com/news/rssindex', 'specialist'], ['Seeking Alpha', 'https://seekingalpha.com/market_currents.xml', 'specialist'], ['Benzinga', 'https://www.benzinga.com/feed', 'specialist'],
  ['Investopedia', 'https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline', 'specialist'], ['Business Insider', 'https://feeds.businessinsider.com/custom/all', 'specialist'],
  ['Forbes Business', 'https://www.forbes.com/business/feed/', 'specialist'], ['TechCrunch', 'https://techcrunch.com/feed/', 'specialist'],
  ['Politico', 'https://rss.politico.com/politics-news.xml', 'specialist'], ['The Hill', 'https://thehill.com/news/feed/', 'specialist'], ['NPR Economy', 'https://feeds.npr.org/1017/rss.xml', 'major'],
  // International
  ['BBC Business', 'https://feeds.bbci.co.uk/news/business/rss.xml', 'major'], ['Guardian Business', 'https://www.theguardian.com/business/rss', 'major'], ['Guardian US Politics', 'https://www.theguardian.com/us-news/us-politics/rss', 'major'],
  ['Sky News Business', 'https://feeds.skynews.com/feeds/rss/business.xml', 'specialist'], ['Independent Business', 'https://www.independent.co.uk/news/business/rss', 'regional'],
  ['DW Business', 'https://rss.dw.com/rdf/rss-en-bus', 'specialist'], ['France 24 Business', 'https://www.france24.com/en/business/rss', 'specialist'], ['Euronews Business', 'https://www.euronews.com/rss?level=theme&name=business', 'specialist'],
  ['Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml', 'specialist'], ['Nikkei Asia', 'https://asia.nikkei.com/rss/feed/nar', 'major'], ['SCMP Business', 'https://www.scmp.com/rss/92/feed', 'specialist'],
  ['Straits Times Business', 'https://www.straitstimes.com/news/business/rss.xml', 'specialist'], ['CNA Business', 'https://www.channelnewsasia.com/rssfeeds/8395954', 'specialist'],
  ['Economic Times Markets', 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms', 'specialist'], ['Livemint Markets', 'https://www.livemint.com/rss/markets', 'specialist'],
  ['ABC Australia Business', 'https://www.abc.net.au/news/feed/51120/rss.xml', 'specialist'], ['Japan Times Business', 'https://www.japantimes.co.jp/news/business/feed/', 'regional'],
  ['Arabian Business', 'https://www.arabianbusiness.com/rss', 'regional'], ['BusinessLIVE South Africa', 'https://www.businesslive.co.za/rss/?publication=bd', 'regional'],
  // Crypto
  ['CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'specialist'], ['Cointelegraph', 'https://cointelegraph.com/rss', 'specialist'], ['Decrypt', 'https://decrypt.co/feed', 'specialist'],
  ['The Block', 'https://www.theblock.co/rss.xml', 'specialist'], ['Bitcoin Magazine', 'https://bitcoinmagazine.com/.rss/full/', 'specialist'], ['CryptoSlate', 'https://cryptoslate.com/feed/', 'specialist'],
  ['Blockworks', 'https://blockworks.co/feed', 'specialist'], ['DL News', 'https://www.dlnews.com/arc/outboundfeeds/rss/', 'specialist'], ['The Defiant', 'https://thedefiant.io/api/feed', 'specialist'],
  ['BeInCrypto', 'https://beincrypto.com/feed/', 'regional'], ['CryptoPotato', 'https://cryptopotato.com/feed/', 'regional'], ['Bitcoinist', 'https://bitcoinist.com/feed/', 'regional'], ['U.Today', 'https://u.today/rss', 'regional'],
];
// Wire services and papers without an open feed, reached through Google News site: searches.
const GN_OUTLETS = [['Reuters', 'site:reuters.com (markets OR stocks OR crypto OR tariffs OR regulation OR Fed OR earnings)', 'wire'], ['Bloomberg', 'site:bloomberg.com (markets OR stocks OR crypto OR tariffs OR earnings)', 'wire'],
  ['AP News', 'site:apnews.com (economy OR stocks OR crypto OR tariffs OR Congress OR earnings)', 'wire'], ['Financial Times', 'site:ft.com (markets OR crypto OR tariffs OR earnings)', 'wire'],
  ['The Economist', 'site:economist.com (markets OR crypto OR economy)', 'major'], ['Barrons', 'site:barrons.com (stocks OR crypto OR earnings)', 'major'], ['Axios', 'site:axios.com (markets OR crypto OR stocks OR tariffs)', 'specialist']];
// Regional Google News editions give local and international coverage of the same assets.
const GN_EDITIONS = [['UK', 'en-GB', 'GB'], ['India', 'en-IN', 'IN'], ['Australia', 'en-AU', 'AU'], ['Canada', 'en-CA', 'CA'], ['Singapore', 'en-SG', 'SG'], ['South Africa', 'en-ZA', 'ZA'],
  ['Nigeria', 'en-NG', 'NG'], ['Ireland', 'en-IE', 'IE'], ['New Zealand', 'en-NZ', 'NZ'], ['Philippines', 'en-PH', 'PH'], ['Hong Kong', 'en-HK', 'HK'], ['Israel', 'en-IL', 'IL']];

function feedItems(doc) {
  return [...doc.querySelectorAll('item, entry')].map(i => {
    const t = s => i.querySelector(s)?.textContent || '';
    const link = i.querySelector('link')?.getAttribute('href') || t('link');
    const media = [...i.getElementsByTagName('media:content'), ...i.getElementsByTagName('media:thumbnail'), ...i.getElementsByTagName('enclosure')].filter(n => !n.getAttribute('type') || /^image/.test(n.getAttribute('type'))).map(n => n.getAttribute('url')).find(Boolean) || /<img[^>]+src=["'](https:[^"']+)/i.exec(t('description') || t('content'))?.[1] || '';
    return { title: t('title'), image: media, desc: t('description') || t('summary') || t('content'), link: link.trim(), date: t('pubDate') || t('published') || t('updated') };
  });
}
const outletPost = (name, tier, it) => { const text = it.title + ' ' + stripHTML(it.desc).slice(0, 300); return { id: 'o_' + it.link, src: 'News', outlet: true, listed: true, tier, ts: Date.parse(it.date) || Date.now(), title: it.title, image: it.image, text, url: it.link, sub: name, language: 'en', publishedEstimated: !Date.parse(it.date), topic: topicSyms(text), raw: { title: it.title, description: it.desc, link: it.link, publicationDate: it.date } }; };
let outPtr = 0, gnTick = 0;
const BATCH = 10;
job('Major outlets', async () => {
  const batch = Array.from({ length: BATCH }, (_, k) => OUTLETS[(outPtr + k) % OUTLETS.length]); outPtr = (outPtr + BATCH) % OUTLETS.length;
  const gn = GN_OUTLETS[gnTick % GN_OUTLETS.length], ed = GN_EDITIONS[gnTick % GN_EDITIONS.length]; gnTick++;
  const res = await Promise.allSettled([
    ...batch.map(([n, u, tier]) => fetchAny(u, parseXML).then(doc => { feedItems(doc).forEach(it => { if (it.link) addPost(outletPost(n, tier, it)); }); feedHealth(n, true); }).catch(e => { feedHealth(n, false, e.message); throw e; })),
    rss(gn[1] + ' when:1d').then(r => r.forEach(x => addPost({ ...newsPost(x), outlet: true, tier: gn[2], sub: gn[0] + (x.source ? ' via ' + x.source : ''), topic: topicSyms(x.title) }))),
    fetchAny(`https://news.google.com/rss/search?q=${encodeURIComponent('(stocks OR shares OR crypto OR bitcoin OR earnings) when:1d')}&hl=${ed[1]}&gl=${ed[2]}&ceid=${ed[2]}:en`, parseXML)
      .then(doc => feedItems(doc).forEach(it => { const src = it.title.split(' - ').pop(); addPost({ id: 'ge_' + it.link, src: 'News', outlet: true, ts: Date.parse(it.date) || Date.now(), text: it.title, url: it.link, sub: `${src} (${ed[0]})`, topic: topicSyms(it.title) }); })),
  ]);
  if (res.every(r => r.status === 'rejected')) throw res[0].reason;
}, 40000);
