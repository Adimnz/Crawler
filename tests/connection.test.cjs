const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
test('request timeout does not disconnect the server; three readiness failures do', async()=>{
  let failReady=false;
  const element={hidden:true,textContent:'',className:'',querySelector:()=>element};
  const engine={toggleSaved(){},saveNote(){},mergeServerEvents(){},flush(){},state:{saved:[],notes:{}},documents:new Map()};
  const context={window:{CrawlerIntelligence:engine,addEventListener(){},dispatchEvent(){}},document:{hidden:true,body:{dataset:{}},getElementById:()=>element,querySelectorAll:()=>[],addEventListener(){}},
    location:{protocol:'http:'},CustomEvent:class{},AbortController,TypeError,Error,Date,Map,Set,Promise,setTimeout,clearTimeout,setInterval(){},
    fetch:async path=>{
      if(path==='/api/slow') {const e=new Error('Timed out');e.name='AbortError';throw e;}
      if(path==='/api/ready' && failReady) throw new TypeError('Network unavailable');
      const value=path==='/api/ready'?{service:'trend-crawler',ready:true}:path==='/api/session'?{authorized:true}:path.startsWith('/api/documents')?{documents:[],cursor:{at:0,id:''},hasMore:false}:{};
      return {ok:true,json:async()=>value};
    }};
  vm.runInNewContext(fs.readFileSync('js/server-bridge.js','utf8'),context);
  const api=context.window.CrawlerServer;
  await api.probe();assert.equal(api.connected,true);
  await assert.rejects(api.request('slow'));await api.probe();assert.equal(api.connected,true);
  failReady=true;
  await api.probe();assert.equal(api.connected,true);
  await api.probe();assert.equal(api.connected,true);
  await api.probe();assert.equal(api.connected,false);
});
