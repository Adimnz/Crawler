const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const flush=()=>new Promise(r=>setImmediate(r));
function bridge(fetch){
 const element={hidden:true,textContent:'',className:'',querySelector:()=>element};
 const engine={toggleSaved(){},saveNote(){},mergeServerEvents(){},flush(){},state:{saved:[],notes:{}},documents:new Map()};
 const c={window:{CrawlerIntelligence:engine,addEventListener(){},dispatchEvent(){}},document:{hidden:true,body:{dataset:{}},getElementById:()=>element,querySelectorAll:()=>[],addEventListener(){}},location:{protocol:'http:'},CustomEvent:class{},AbortController,TypeError,Error,Date,Map,Set,Promise,setTimeout,clearTimeout,setInterval(){},fetch};
 vm.runInNewContext(fs.readFileSync('js/server-bridge.js','utf8'),c);return c.window.CrawlerServer;
}
const ok=value=>({ok:true,status:200,json:async()=>value});
test('duplicate API reads share one request and distinct reads have bounded concurrency',async()=>{
 let active=0,maximum=0,physical=0;const releases=[];
 const api=bridge(async path=>{physical++;active++;maximum=Math.max(maximum,active);await new Promise(r=>releases.push(r));active--;return ok({path});});
 const one=api.request('same');const two=api.request('same');await flush();assert.equal(physical,1);
 releases.shift()();await Promise.all([one,two]);
 const reads=Array.from({length:8},(_,i)=>api.request('data-'+i));await flush();assert.equal(active,3);
 while(releases.length){releases.shift()();await flush();}
 await Promise.all(reads);assert.equal(maximum,3);
});
test('server busy responses preserve the connection and readiness bypasses data pressure',async()=>{
 let busy=false;
 const api=bridge(async path=>{
  if(path==='/api/ready')return ok({service:'trend-crawler',ready:true});
  if(path==='/api/session')return ok({authorized:true});
  if(path.startsWith('/api/documents'))return ok({documents:[],cursor:{at:0,id:''},hasMore:false});
  return busy?{ok:false,status:503,json:async()=>({code:'SERVER_BUSY',retryAfterMs:3000,error:'Busy'})}:ok({});
 });
 await api.probe();assert.equal(api.connected,true);busy=true;
 await assert.rejects(api.request('data'),e=>e.code==='SERVER_BUSY');
 await api.probe();assert.equal(api.connected,true);assert.equal(api.mode,'server');assert.equal(api.busy,true);
});
test('local startup and server mode never launch cross-origin collectors',async()=>{
 let fetches=0;const scheduled=[];
 const c={window:{CrawlerServer:{mode:'connecting'}},location:{protocol:'http:'},document:{getElementById:()=>({})},URL,Map,Set,Promise,Date,AbortController,fetch:async()=>{fetches++;return ok({});},setTimeout:fn=>{scheduled.push(fn);return 1;},clearTimeout(){}};
 vm.runInNewContext(fs.readFileSync('js/core.js','utf8'),c);
 await assert.rejects(vm.runInNewContext("fetchAny('https://example.test/feed',JSON.parse)",c));
 vm.runInNewContext("job('fixture',()=>{throw new Error('collector started');},1000)",c);await scheduled.shift()();
 c.window.CrawlerServer.mode='server';await assert.rejects(vm.runInNewContext("fetchAny('https://example.test/feed',JSON.parse)",c));
 assert.equal(fetches,0);
});
