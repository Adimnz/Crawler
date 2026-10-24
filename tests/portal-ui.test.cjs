const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');

function ui(){
  const nodes={rows:{},filter:{value:''}};
  const ctx={window:{addEventListener(){},CrawlerActivity:{tags:()=>'<span>Portfolio watch</span>'}},document:{body:{dataset:{destination:'markets'}}},
    $:id=>nodes[id],esc:escape,safeURL:u=>u?.startsWith('https://')?u:'',ago:()=>1,fmtP:n=>String(n),priceFresh:q=>Date.now()-q.t<60000,
    chgHTML:v=>v==null?'—':v+'%',live:new Map([['BTC',{price:10,t:Date.now(),chg:null,name:'Bitcoin'}]]),quotes:new Map([['FIX',{price:20,t:Date.now(),chg:-2,name:'Fixture'}]])};
  vm.createContext(ctx);
  const code=fs.readFileSync('js/ui.js','utf8').split('/* Mentions for the selected asset')[0];
  vm.runInContext(code,ctx);
  return {ctx,nodes,run:code=>vm.runInContext(code,ctx)};
}
const article=(id,title,tier='major',age=1000)=>({id,title,text:title,sub:'Synthetic publisher',src:'News',tier,ts:Date.now()-age,url:'https://example.test/'+id,sent:0,w:.8,syms:[]});

test('The Mark groups accessible list rows and does not invent missing quote changes',()=>{
  const f=ui();f.run('renderPicks()');const html=f.nodes.rows.innerHTML;
  assert.equal((html.match(/class="market-list"/g)||[]).length,2);
  assert.match(html,/<h2>Stocks<\/h2>/);assert.match(html,/<h2>Crypto assets<\/h2>/);
  assert.match(html,/Not supplied/);assert.match(html,/data-s="BTC"/);
  assert.doesNotMatch(html,/market-quote|class="card|0%/);
});
test('Newsstand promotes source-labeled recent breaking news and major reporting without recategorizing rumors',()=>{
  const f=ui();f.ctx.articles=[article('normal','Synthetic earnings update'),article('rumor','Huge price rumor','social'),article('breaking','BREAKING: Synthetic filing published','wire'),article('old','Breaking: Yesterday’s synthetic event','major',5*36e5)];
  const html=f.run('newsFrontPage(articles)');
  assert.match(html,/news-breaking/);assert.match(html,/Breaking &amp; top reporting|Breaking & top reporting/);
  const strip=html.match(/<div class="news-breaking">(.*?)<\/div>/s)[1];
  assert.match(strip,/Synthetic filing/);assert.doesNotMatch(strip,/rumor|Yesterday/);
  assert.match(html,/news-lead-grid/);assert.match(html,/Portfolio watch/);
});
test('Newsstand keeps hostile source text escaped and never creates breaking labels from sentiment',()=>{
  const f=ui();f.ctx.articles=[article('x','<img src=x onerror=alert(1)>','major')];
  const html=f.run('newsFrontPage(articles)');assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img src=x|news-breaking/);
});

function activity(){
  const events={},intervals=[];let html='',requests=0,resolve;
  const host={querySelectorAll:()=>[],set innerHTML(v){html=v;},get innerHTML(){return html;}};
  const api={connected:true,busy:false,request:()=>{requests++;return new Promise(r=>resolve=r);}};
  const window={CrawlerServer:api,CrawlerNetwork:{detail:{board:{id:'board'}}},addEventListener:(name,fn)=>events[name]=fn};
  const document={hidden:false,body:{dataset:{experience:'topic'}},getElementById:id=>id==='agent-activity'?host:null,addEventListener(){}};
  vm.runInNewContext(fs.readFileSync('js/agent-activity.js','utf8'),{window,document,esc:escape,Date,Number,Math,setInterval:fn=>intervals.push(fn)});
  return {window,events,intervals,host,api,requests:()=>requests,resolve:value=>resolve(value),flush:()=>new Promise(r=>setImmediate(r))};
}
test('activity shows server-supplied progress, preserves it on disconnect, and does not simulate increases',async()=>{
  const f=activity();f.events['crawler:board-ready']();
  f.resolve({tasks:[{id:'job',kind:'topic-research',status:'Running',percent:28,stage:'Checking original sources',events:[{at:Date.now(),message:'Checked two sources',percent:28}]}],organizationPolicy:{enabled:true}});
  await f.flush();assert.match(f.host.innerHTML,/28%/);assert.match(f.host.innerHTML,/Checked two sources/);
  for(const tick of f.intervals)tick();await f.flush();assert.equal(f.requests(),1);
  f.api.connected=false;f.events['crawler:server-state']();assert.match(f.host.innerHTML,/28%/);assert.match(f.host.innerHTML,/interrupted/);
  assert.doesNotMatch(f.host.innerHTML,/Task completed|100%/);
});
test('a late activity response cannot populate a different observation board',async()=>{
  const f=activity();f.events['crawler:board-ready']();f.window.CrawlerNetwork.detail.board.id='other';
  f.resolve({tasks:[{id:'secret',kind:'topic-research',status:'Complete',percent:100,stage:'Previous board details',events:[]}]});
  await f.flush();assert.doesNotMatch(f.host.innerHTML,/Previous board details/);
});

test('collected quotes use their source freshness window and preserve the original observation time',()=>{
  const code=fs.readFileSync('js/market.js','utf8').match(/^const priceFresh = .*$/m)[0];
  const at=Date.now()-3600000;
  const c={Date,Number,quote:{price:10,t:at,maxAgeMs:7200000}};
  assert.equal(vm.runInNewContext(code+'\npriceFresh(quote,30000)',c),true);
  assert.equal(c.quote.t,at);
  c.quote.maxAgeMs=60000;
  assert.equal(vm.runInNewContext('priceFresh(quote,30000)',c),false);
});
test('ambiguous tickers and changed currencies remove previously eligible cached prices',async()=>{
  const source=fs.readFileSync('js/server-bridge.js','utf8');
  const code=source.slice(source.indexOf('  async function refreshOnce('),source.indexOf('  async function pull()'));
  let rows=[{assetId:'btc',symbol:'BTC',type:'crypto',currency:'USD',price:10,observedAt:Date.now(),maxAgeMs:7200000},{assetId:'fix',symbol:'FIX',type:'stock',currency:'USD',price:20,observedAt:Date.now()}];
  const c={connected:true,document:{hidden:false},Date,Map,Set,Promise,lastUpdate:{},live:new Map(),quotes:new Map(),engine:{setServerAnalyses(){}},emit(){},
    request:async name=>name==='market-data'?{quotes:rows}:name==='sources'?{sources:[]}:name==='operations'?{health:{}}:name==='metrics'?{observations:[]}:name==='events'?{events:[]}:{} };
  vm.createContext(c);vm.runInContext(code,c);
  await vm.runInContext('refreshOnce(true)',c);assert.equal(c.live.get('BTC').price,10);assert.equal(c.quotes.get('FIX').price,20);
  rows=[rows[0],{...rows[0],assetId:'btc-other'},{...rows[1],currency:'EUR'}];
  await vm.runInContext('refreshOnce(true)',c);assert.equal(c.live.has('BTC'),false);assert.equal(c.quotes.has('FIX'),false);
});
