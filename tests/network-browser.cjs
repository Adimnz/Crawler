/* Actual canvas gestures, private persistence, account forms and queue expansion. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const pause = ms => new Promise(r => setTimeout(r, ms));
async function until(check, message, timeout=40000) {
  const end=Date.now()+timeout;
  while(Date.now()<end){const result=await check();if(result)return result;await pause(150);}
  throw new Error(message);
}
(async()=>{
  const child=spawn('python',[path.join(__dirname,'network_fixture.py')],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  let logs='',browser;
  child.stderr.on('data',chunk=>{logs+=chunk;});
  const exited=new Promise(resolve=>child.once('exit',resolve));
  try{
    const fixture=await new Promise((resolve,reject)=>{
      let output='';
      const timer=setTimeout(()=>reject(new Error('Fixture startup: '+logs)),60000);
      child.stdout.on('data',chunk=>{output+=chunk;if(output.includes('\n')){clearTimeout(timer);try{resolve(JSON.parse(output.split('\n')[0]));}catch(e){reject(e);}}});
      child.once('exit',()=>{clearTimeout(timer);reject(new Error(logs));});
    });
    const base='http://127.0.0.1:'+fixture.port;
    browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--no-proxy-server']});
    const context=await browser.newContext({viewport:{width:1550,height:1050}});
    await context.route('**/*',route=>route.request().url().startsWith(base+'/')?route.continue():route.abort());
    await context.addInitScript(()=>{window.WebSocket=class{close(){}};});
    const page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.setDefaultTimeout(20000);
    const detail=()=>page.evaluate(()=>window.CrawlerNetwork.detail);
    const read=route=>page.evaluate(async route=>(await fetch('/api/'+route)).json(),route);
    const request=(route,body)=>page.evaluate(async({route,body})=>{
      const session=await(await fetch('/api/session')).json();
      const response=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Crawler-CSRF':session.csrf},body:JSON.stringify(body)});
      return {status:response.status,body:await response.json()};
    },{route,body});
    await page.goto(base+'/CRAWLER/');
    await page.waitForFunction(()=>window.CrawlerServer?.connected);
    assert.equal(await page.locator('#research-network').count(),0);
    assert.match(await page.locator('#start-screen').innerText(),/Where do I start/);
    await page.evaluate(id=>window.CrawlerStart.openTopic(id),fixture.topicId);
    await page.waitForSelector('.network-node');
    const initial=await detail(),company=initial.graph.nodes.find(n=>n.label==='Orion Airworks');
    const owner=initial.graph.nodes.find(n=>n.label==='Morgan Vale'),root=initial.graph.rootId;
    assert.ok(company&&owner);
    assert.ok(!initial.graph.edges.some(e=>e.type==='supplied_by'));
    const nodeSelector=id=>'[data-network-node="'+id+'"]';
    async function focus(id) {
      const d=await detail(), n=[...d.graph.nodes,...d.board.manualNodes].find(n=>n.id===id);
      await page.locator('#network-search').fill(n.label);
      await page.locator('[data-network-focus="'+id+'"]').click();
      await page.locator('#network-search').fill('');
    }
    await focus(company.id);
    await page.locator(nodeSelector(company.id)).click();
    await page.waitForFunction(()=>document.querySelector('#network-node-records')?.textContent.includes('UAH 100 million'));
    assert.match(await page.locator('#network-inspector').innerText(),/private|No provider-verified/i);
    const before=(await detail()).board.layout[company.id];
    const box=await page.locator(nodeSelector(company.id)).boundingBox();
    await page.mouse.move(box.x+35,box.y+35);await page.mouse.down();await page.mouse.move(box.x+115,box.y+80,{steps:10});await page.mouse.up();
    assert.notDeepEqual((await detail()).board.layout[company.id],before,'Dragging must move the selected node');
    await page.locator('#network-node-note').fill('Private observation with <script>safe text</script>');
    await page.locator('#network-inspector [data-network-action=pin]').click();
    assert.ok((await detail()).board.pinned.includes(company.id));
    const edge=(await detail()).graph.edges.find(e=>e.type==='owned_by');
    await page.locator('[data-network-inspect-edge="'+edge.id+'"]').click();
    assert.match(await page.locator('#network-inspector').innerText(),/Morgan Vale owns/);
    await page.locator('.network-review summary').click();
    await page.locator('#network-review-form select').selectOption('Verified');
    await page.locator('#network-review-form textarea').fill('Reviewed the original synthetic ownership record and named parties.');
    await page.locator('#network-review-form input[type=checkbox]').check();
    await page.locator('#network-review-form button').click();
    await until(async()=>(await detail()).graph.edges.find(e=>e.id===edge.id)?.status==='Verified','Explicit evidence review failed');
    await focus(company.id);
    await page.locator('#network-inspector [data-network-action=collapse]').click();
    assert.ok((await detail()).board.collapsed.includes(company.id));
    await page.locator(nodeSelector(company.id)).dblclick();
    assert.ok(!(await detail()).board.collapsed.includes(company.id),'Double click must expand the branch');
    assert.ok((await detail()).board.expanded.length>0);
    await page.locator(nodeSelector(company.id)).click({button:'right'});
    await page.locator('#network-context-menu [data-network-action=duplicate-node]').click();
    assert.equal((await detail()).board.manualNodes[0].status,'User assertion');
    await page.locator('[data-network-action=undo]').click();
    assert.equal((await detail()).board.manualNodes.length,0);
    await page.locator('[data-network-action=redo]').click();
    assert.equal((await detail()).board.manualNodes.length,1);
    // Dragging a handle into empty canvas creates a linked personal node.
    await focus(root);
    const handle=await page.locator('[data-connect-from="'+root+'"]').boundingBox();
    const canvas=await page.locator('#network-canvas').boundingBox();
    await page.mouse.move(handle.x+10,handle.y+10);await page.mouse.down();await page.mouse.move(canvas.x+canvas.width-65,canvas.y+85,{steps:12});await page.mouse.up();
    await page.locator('#network-node-editor input[name=label]').fill('My supply question');
    await page.locator('#network-node-editor button[type=submit]').click();
    const manual=(await detail()).board.manualNodes.find(n=>n.label==='My supply question');
    assert.ok((await detail()).board.manualEdges.some(e=>e.from===root&&e.to===manual.id&&e.status==='User assertion'));
    await page.locator('[data-network-action=fit]').click();
    const sourceHandle=await page.locator('[data-connect-from="'+root+'"]').boundingBox();
    const targetNode=await page.locator(nodeSelector(company.id)).boundingBox();
    await page.mouse.move(sourceHandle.x+sourceHandle.width/2,sourceHandle.y+sourceHandle.height/2);await page.mouse.down();
    await page.mouse.move(targetNode.x+targetNode.width/2,targetNode.y+targetNode.height/2,{steps:12});await page.mouse.up();
    await page.locator('#network-edge-editor select').selectOption('user_defined');
    await page.locator('#network-edge-editor textarea[name=claim]').fill('A personal connection to investigate.');
    await page.locator('#network-edge-editor textarea[name=citations]').fill('https://fixture.example/disclosure');
    await page.locator('#network-edge-editor button').click();
    assert.ok((await detail()).board.manualEdges.some(e=>e.from===root&&e.to===company.id&&e.status==='User assertion'&&e.evidence.length===0));
    await page.locator(nodeSelector(root)).click();
    await page.locator(nodeSelector(company.id)).click({modifiers:['Shift']});
    await page.locator('[data-network-action=group]').click();
    await page.locator('#network-group-form input').fill('Core investigation');
    await page.locator('#network-group-form button').click();
    await page.locator('[data-network-action=zoom-in]').click();
    // Edits made during a delayed save must survive and be persisted by its follow-up.
    await focus(company.id);
    let savingStarted;
    const savingRequest=new Promise(resolve=>{savingStarted=resolve;});
    await context.route('**/api/boards/save',async route=>{savingStarted();await pause(250);await route.continue();},{times:1});
    await page.locator('#network-save').click();
    await savingRequest;
    await page.locator('#network-node-note').fill('Edited while the board save was in flight.');
    await until(async()=>!(await page.evaluate(()=>CrawlerNetwork.dirty)),'Save did not finish');
    const saved=(await detail()).board;
    assert.equal((await read('boards?id='+saved.id)).board.notes[company.id],'Edited while the board save was in flight.');
    await page.reload();
    await page.waitForFunction(()=>window.CrawlerServer?.connected);
    await page.evaluate(id=>window.CrawlerNetwork.openBoard(id),saved.id);
    await page.waitForSelector('.network-node');
    const restored=(await detail()).board;
    for(const key of ['layout','notes','manualNodes','manualEdges','groups','pinned','expanded','viewport'])assert.deepEqual(restored[key],saved[key],'Saved '+key+' must restore exactly');
    // Investigate a manual connection as a question, never established evidence.
    await focus(company.id);
    await page.locator('#network-research-form select[name=focus]').selectOption('ownership');
    await page.locator('#network-research-form button[type=submit]').click();
    await until(async()=>(await read('boards?id='+saved.id)).tasks?.some(t=>t.status==='Complete'),'Focused research did not finish',65000);
    await page.screenshot({path:path.join(process.env.TEMP||'.','crawler-network-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile must not scroll horizontally');
    await page.screenshot({path:path.join(process.env.TEMP||'.','crawler-network-mobile.png'),fullPage:true});
    await page.locator('#network-save').click();
    await until(()=>page.evaluate(()=>!CrawlerNetwork.dirty),'Final save failed');
    // Account forms use server cookies; personal research is scoped by the verified provider user.
    await page.goto(base+'/CRAWLER/login.html');
    const login=async name=>{
      await page.locator('form[data-account-action=login] input[name=email]').fill(name+'@example.test');
      await page.locator('form[data-account-action=login] input[name=password]').fill('fixture-password-123');
      await page.locator('form[data-account-action=login] button[type=submit]').click();
      await until(async()=>page.url().endsWith('/CRAWLER/')||await page.locator('[data-account-action=mfa-login]').count(),'Sign in did not advance');
      if(await page.locator('[data-account-action=mfa-login]').count()){
        await page.locator('[data-account-action=mfa-login] input').fill('123456');
        await page.locator('[data-account-action=mfa-login] button').click();
      }
      await page.waitForURL('**/CRAWLER/');
      await page.waitForFunction(()=>window.CrawlerServer?.connected);
    };
    await login('alice');
    assert.equal((await read('my-research')).boards.length,0,'Account must not inherit local owner boards');
    assert.equal((await request('sources',{name:'Forbidden'})).status,401,'Members cannot configure collectors');
    await request('topics',{query:'Drones'});
    await page.evaluate(id=>window.CrawlerStart.openTopic(id),fixture.topicId);
    await page.waitForSelector('.network-node');
    const aliceBoard=(await detail()).board.id;
    await focus(company.id);
    await page.locator('#network-node-note').fill('Alice private research survives sign-out.');
    await page.locator('#network-save').click();
    await until(()=>page.evaluate(()=>!CrawlerNetwork.dirty),'Alice save failed');
    await page.goto(base+'/CRAWLER/account.html');
    await page.locator('[data-account-action=profile] input').fill('Alice Research');
    await page.locator('[data-account-action=profile] button[type=submit]').click();
    await until(async()=>(await read('accounts')).user?.displayName==='Alice Research','Profile did not save');
    await page.locator('[data-account-click=mfa-enroll]').click();
    await page.locator('[data-account-action=mfa-finish] input').fill('123456');
    await page.locator('[data-account-action=mfa-finish] button[type=submit]').click();
    await until(async()=>(await read('accounts')).factors?.some(f=>f.status==='verified'),'MFA enrollment did not complete');
    await page.locator('[data-account-click=logout]').click();
    await page.waitForURL('**/login.html');
    await login('bob');
    assert.equal((await read('my-research')).boards.length,0);
    const denied=await read('boards?id='+aliceBoard);
    assert.ok(denied.error,'Guessed board IDs must not reveal another account');
    assert.equal((await request('boards/save',{id:aliceBoard,baseVersion:1,title:'Hacked'})).status,400);
    const stored=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
    assert.ok(!stored.includes('fixture-password')&&!stored.includes('refresh-token'),'Passwords and provider tokens must not enter browser storage');
    await page.goto(base+'/CRAWLER/account.html');
    await page.locator('[data-account-click=logout]').click();
    await page.waitForURL('**/login.html');
    await login('alice');
    await page.evaluate(id=>window.CrawlerNetwork.openBoard(id),aliceBoard);
    await page.waitForSelector('.network-node');
    assert.equal((await detail()).board.notes[company.id],'Alice private research survives sign-out.');
    assert.deepEqual(errors,[]);
    console.log('Observation board and account browser checks passed');
  }catch(error){console.error(error.stack);console.error(logs.slice(-6000));process.exitCode=1;}
  finally{if(browser)await browser.close();child.stdin.end('\n');await Promise.race([exited,pause(5000)]);if(child.exitCode===null)child.kill();}
})();
