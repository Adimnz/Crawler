const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(expired=false){
  const listeners={},intervals=[];
  let html='',fail=false;
  const host={querySelectorAll:()=>[],replaceChildren(){html='';},append(p){html=p.textContent;},set innerHTML(v){html=v;},get innerHTML(){return html;},set textContent(v){html=v;}};
  const value={boardId:'board',revision:1,asOf:Date.now(),eligibleCount:1,settings:{roundTripCostBps:10},whatChanged:['Initial assessment'],coverage:{storedDocumentsScreened:1,relevantDocuments:1,branchesIncluded:1,candidateAssets:1,scope:'Stored data'},sourceManifest:[],limitations:[],method:'Synthetic test',
    assets:[{assetId:'equity:NASDAQ:FIX',ticker:'FIX',name:'Fixture',assetClass:'equity',status:'Eligible entry signal',potentialReturn:{medianPercent:1,p10Percent:-2,p90Percent:3},analysis:{method:'Fixed model',limitations:[],usedHistorySessions:500,pointInTimeSamples:50,roundTripCostBps:10},blockers:[],topicEvidence:[],expiresAt:Date.now()+(expired?-1000:3600000),holdingHorizonSessions:5}]};
  const api={connected:true,session:{ownerAuthorized:true},request:async()=>{if(fail)throw new Error('Transport failed');return value;}};
  const context={window:{CrawlerServer:api,CrawlerNetwork:{detail:{board:{id:'board'}}},addEventListener:(name,fn)=>listeners[name]=fn},document:{hidden:false,body:{dataset:{experience:'topic'}},getElementById:id=>id==='board-recommendations'?host:null,addEventListener(){},createElement:()=>({})},esc:v=>String(v).replaceAll('<','&lt;'),safeURL:v=>v||'',Date,Number,JSON,Promise,Blob,URL,setTimeout,setInterval:fn=>intervals.push(fn),alert(){}};
  vm.runInNewContext(fs.readFileSync('js/recommendations-ui.js','utf8'),context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  return {listeners,api,host,flush,setFail(){fail=true;},value};
}
test('expired source prices cannot display an eligible return or eligible count',async()=>{
  const fixture=setup(true);fixture.listeners['crawler:board-ready']();await fixture.flush();
  assert.match(fixture.host.innerHTML,/Expired — refresh required/);
  assert.match(fixture.host.innerHTML,/0 eligible entry signal/);
  assert.match(fixture.host.innerHTML,/Historical 10th–90th percentile<\/dt><dd>Withheld/);
});
test('transport failure clears prior advice and board events do not restore it',async()=>{
  const fixture=setup();fixture.listeners['crawler:board-ready']();await fixture.flush();
  assert.match(fixture.host.innerHTML,/1 eligible entry signal/);
  fixture.setFail();fixture.listeners['crawler:server-state']();await fixture.flush();
  assert.match(fixture.host.innerHTML,/Recommendation unavailable/);
  fixture.listeners['crawler:board-ready']();await fixture.flush();
  assert.doesNotMatch(fixture.host.innerHTML,/eligible entry signal/);
});
