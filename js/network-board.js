/* An editable view of canonical evidence; personal assertions never become facts. */
(() => {
  'use strict';
  const api = window.CrawlerServer;
  const e = value => esc(String(value ?? ''));
  const types = ['observation','question','company','person','journalist','product','financial_institution','financial_record','contract','agency','supplier','material','region','competitor','instrument','market','topic'];
  const relationships = ['user_defined','research_question','authored_by','published_by','reports_on','manufactured_by','owned_by','subsidiary_of','partnered_with','invested_in','financed_by','contract_awarded_to','supplied_by','competes_with','produces','common_ownership','references'];
  const focuses = {costs:'Investigate costs and changes',questions:'Resolve unanswered questions',overview:'Research this entity',ownership:'Investigate ownership',finances:'Investigate finances',contracts:'Find disclosed contracts',suppliers:'Explore documented suppliers',competitors:'Explore competitors',markets:'Find related public instruments',contradictions:'Find contradictory evidence',verify:'Verify selected connection'};
  const label = value => String(value || '').replaceAll('_',' ');
  const uid = () => 'manual-' + crypto.randomUUID();
  const clone = value => JSON.parse(JSON.stringify(value));
  let detail=null, personal=null, topic=null, selected=null, selectedEdge=null, selection=new Set(), dirty=false, undo=[], redo=[], filter='', evidenceFilter='', relationshipFilter='', drag=null, connecting=null, generation=0, pending=false, saving=false, visibleLimit=80;
  let undoKey='', space=false, contextNode=null, focusedNode=null, attachingTopic=null, ignoreClick=false, lastClick=null, savePromise=null, canvasObserver=null, lastBoardPoll=0;
  const nodeWidth=206, nodeHeight=94;
  const active = () => detail && document.body.dataset.experience==='topic' && document.getElementById('research-network');
  const b = () => detail?.board;
  const allNodes = () => [...(detail?.graph.nodes || []),...(b()?.manualNodes || [])];
  const allEdges = () => [...(detail?.graph.edges || []),...(b()?.manualEdges || [])];
  const node = id => allNodes().find(n=>n.id===id);
  function checkpoint() { undo.push(clone(b()));if(undo.length>60)undo.shift();redo=[]; }
  function changed() { dirty=true;document.getElementById('network-save-state')?.replaceChildren(document.createTextNode('Unsaved changes')); }
  function position(id) { return b()?.layout[id] || {x:0,y:0}; }
  function placeNearParents() {
    const layout=b().layout,known=new Set(Object.keys(layout));if(!known.size)return;
    const free=(x,y)=>!Object.values(layout).some(p=>Math.abs(p.x-x)<nodeWidth+24&&Math.abs(p.y-y)<nodeHeight+24);
    const children=new Map();
    for(const edge of allEdges())for(const [p,c] of [[edge.from,edge.to],[edge.to,edge.from]])if(known.has(p)&&!known.has(c)){if(!children.has(p))children.set(p,new Set());children.get(p).add(c);}
    for(const [parent,set] of children){
      const ids=[...set].filter(id=>!layout[id]),base=layout[parent];
      ids.forEach((id,i)=>{
        const angle=2*Math.PI*i/ids.length-Math.PI/2;let radius=nodeWidth+150,spot={x:base.x+Math.cos(angle)*radius,y:base.y+Math.sin(angle)*radius};
        for(let tries=0;tries<12&&!free(spot.x,spot.y);tries++){radius+=70;spot={x:base.x+Math.cos(angle)*radius,y:base.y+Math.sin(angle)*radius};}
        layout[id]=spot;
      });
    }
  }
  function cleanUp() {
    const nodes=visibleNodes(),ids=new Set(nodes.map(n=>n.id)),root=detail.graph.rootId,pinned=new Set(b().pinned),adjacency=new Map();
    for(const edge of allEdges())if(ids.has(edge.from)&&ids.has(edge.to))for(const [x,y] of [[edge.from,edge.to],[edge.to,edge.from]]){if(!adjacency.has(x))adjacency.set(x,[]);adjacency.get(x).push(y);}
    const depth=new Map([[root,0]]),parent=new Map(),queue=[root];
    for(let i=0;i<queue.length;i++)for(const next of adjacency.get(queue[i])||[])if(!depth.has(next)){depth.set(next,depth.get(queue[i])+1);parent.set(next,queue[i]);queue.push(next);}
    const deepest=Math.max(...depth.values());
    for(const n of nodes)if(!depth.has(n.id))depth.set(n.id,deepest+1);
    const levels=[];for(const n of nodes)(levels[depth.get(n.id)]||(levels[depth.get(n.id)]=[])).push(n);
    const next={},rowOf={},perColumn=10,stepX=nodeWidth+120,stepY=nodeHeight+40;let column=0;
    levels.forEach(level=>{
      if(!level)return;
      level.sort((p,q)=>(rowOf[parent.get(p.id)]??0)-(rowOf[parent.get(q.id)]??0)||p.type.localeCompare(q.type)||p.label.localeCompare(q.label));
      for(let start=0;start<level.length;start+=perColumn,column++){
        const chunk=level.slice(start,start+perColumn);
        chunk.forEach((n,i)=>{const y=(i-(chunk.length-1)/2)*stepY;rowOf[n.id]=y;next[n.id]={x:column*stepX,y};});
      }
    });
    checkpoint();
    for(const id of ids)b().layout[id]=pinned.has(id)&&b().layout[id]?b().layout[id]:next[id];
    changed();paintWorld();fit();
  }
  function initialLayout() {
    placeNearParents();
    const columns={topic:0,article:-420,publisher:-780,event:-1120,company:410,financial_institution:410,market:410,product:770,person:770,journalist:-780,financial_record:1130,contract:1130,agency:1490,supplier:1490,competitor:1490,material:1850,region:1850,question:770,instrument:1130,observation:410};
    const buckets=new Map();
    for(const n of allNodes()){
      const column=columns[n.type] ?? 770;
      if(!buckets.has(column))buckets.set(column,[]);
      buckets.get(column).push(n);
    }
    for(const [x,rows] of buckets)rows.forEach((n,i)=>{if(!b().layout[n.id])b().layout[n.id]={x,y:(i-(rows.length-1)/2)*155};});
    if(!b().layout[detail.graph.rootId]) b().layout[detail.graph.rootId]={x:0,y:0};
  }
  function hiddenDescendants() {
    const hidden=new Set(b().hidden || []), expanded=new Set(b().expanded || []), adjacency=new Map();
    for(const edge of allEdges()){if(!adjacency.has(edge.from))adjacency.set(edge.from,[]);adjacency.get(edge.from).push(edge.to);}
    for(const id of b().collapsed || []){
      const queue=[...(adjacency.get(id)||[])],seen=new Set([id]);
      while(queue.length){const next=queue.shift();if(seen.has(next)||next===detail.graph.rootId)continue;seen.add(next);if(!b().pinned.includes(next)&&!expanded.has(next))hidden.add(next);queue.push(...(adjacency.get(next)||[]));}
    }
    return hidden;
  }
  function visibleNodes() {
    if(!detail)return[];
    const hidden=hiddenDescendants(), matches=allNodes().filter(n=>!hidden.has(n.id) && (!filter || (n.label+' '+n.type+' '+(n.summary||'')).toLowerCase().includes(filter)) && (!evidenceFilter || evidenceFilter==='manual' && n.origin==='manual' || evidenceFilter==='questions' && n.type==='question' || evidenceFilter!=='manual' && evidenceFilter!=='questions' && n.status===evidenceFilter));
    if(!matches.some(n=>n.id===detail.graph.rootId))matches.unshift(node(detail.graph.rootId));
    return matches.filter(Boolean).slice(0,visibleLimit);
  }
  function point(event) {
    const rect=document.getElementById('network-canvas').getBoundingClientRect(),view=b().viewport;
    return {x:(event.clientX-rect.left-view.x)/view.zoom,y:(event.clientY-rect.top-view.y)/view.zoom};
  }
  function linePath(edge) {
    const from=position(edge.from),to=position(edge.to),sx=from.x+nodeWidth/2,sy=from.y+nodeHeight/2,tx=to.x+nodeWidth/2,ty=to.y+nodeHeight/2;
    return `M ${sx} ${sy} C ${sx+(tx-sx)/2} ${sy}, ${sx+(tx-sx)/2} ${ty}, ${tx} ${ty}`;
  }
  function rootFocus() {
    const canvas=document.getElementById('network-canvas');if(!canvas)return;
    const root=position(detail.graph.rootId);b().viewport={x:canvas.clientWidth/2-(root.x+nodeWidth/2)*.8,y:canvas.clientHeight/2-(root.y+nodeHeight/2)*.8,zoom:.8};transform();
  }
  function fit() {
    const canvas=document.getElementById('network-canvas'),nodes=visibleNodes();if(!canvas||!nodes.length)return;
    const xs=nodes.map(n=>position(n.id).x),ys=nodes.map(n=>position(n.id).y),minX=Math.min(...xs)-45,maxX=Math.max(...xs)+nodeWidth+45,minY=Math.min(...ys)-45,maxY=Math.max(...ys)+nodeHeight+45;
    const zoom=Math.max(.15,Math.min(1,(canvas.clientWidth-30)/(maxX-minX),(canvas.clientHeight-30)/(maxY-minY)));
    b().viewport={zoom,x:canvas.clientWidth/2-(minX+maxX)/2*zoom,y:canvas.clientHeight/2-(minY+maxY)/2*zoom};transform();changed();
  }
  function transform() {
    const world=document.getElementById('network-world');if(!world)return;
    const view=b().viewport;world.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.zoom})`;
    const zoom=document.getElementById('network-zoom-label');if(zoom)zoom.textContent=Math.round(view.zoom*100)+'%';minimap();
  }
  function minimap() {
    const target=document.getElementById('network-minimap'),canvas=document.getElementById('network-canvas');if(!target||!canvas)return;
    const nodes=visibleNodes();if(!nodes.length)return;
    const xs=nodes.map(n=>position(n.id).x),ys=nodes.map(n=>position(n.id).y),minX=Math.min(...xs)-80,minY=Math.min(...ys)-80,width=Math.max(...xs)-minX+nodeWidth+80,height=Math.max(...ys)-minY+nodeHeight+80,v=b().viewport;
    target.setAttribute('viewBox',`${minX} ${minY} ${width} ${height}`);
    target.innerHTML=nodes.map(n=>`<rect x="${position(n.id).x}" y="${position(n.id).y}" width="${nodeWidth}" height="${nodeHeight}" class="${n.id===detail.graph.rootId?'map-root':''}"/>`).join('')+`<rect class="map-viewport" x="${-v.x/v.zoom}" y="${-v.y/v.zoom}" width="${canvas.clientWidth/v.zoom}" height="${canvas.clientHeight/v.zoom}"/>`;
  }
  function paintWorld() {
    if(!active())return;
    initialLayout();const nodes=visibleNodes(),ids=new Set(nodes.map(n=>n.id));
    const edges=allEdges().filter(edge=>ids.has(edge.from)&&ids.has(edge.to)&&(!relationshipFilter||edge.type===relationshipFilter));
    const world=document.getElementById('network-world');if(!world)return;
    const linked = new Set(selected ? [selected] : []);
    for (const edge of edges) if (edge.from===selected || edge.to===selected) { linked.add(edge.from); linked.add(edge.to); }
    world.innerHTML=`<svg class="network-lines" aria-label="Research relationships"><defs><marker id="network-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>${edges.map(edge=>{
      const from=position(edge.from),to=position(edge.to),status=edge.origin==='manual'?'manual':edge.status==='Verified'?'verified':edge.status==='Corroborated'?'corroborated':edge.status==='Research question'?'question':/disput|review/i.test(edge.status)?'disputed':'reported';
      return `<g class="network-edge ${status}${selected ? (edge.from===selected || edge.to===selected ? ' connected-chain' : ' unfocused') : ''}${selectedEdge===edge.id?' selected':''}" data-network-edge="${e(edge.id)}" role="button" tabindex="0" aria-label="${e(label(edge.type)+': '+edge.claim)}"><path class="network-line-hit" d="${linePath(edge)}"/><path class="network-line" d="${linePath(edge)}" marker-end="url(#network-arrow)"/><text x="${(from.x+to.x)/2+nodeWidth/2}" y="${(from.y+to.y)/2+nodeHeight/2-9}">${e(label(edge.type))}</text></g>`;
    }).join('')}<path id="network-connecting-line" class="network-connecting-line"/></svg><div class="network-node-layer">${nodes.map(n=>`<article class="network-node ${selected && !linked.has(n.id)?'unfocused':''} ${n.origin==='manual'?'manual':''} ${selection.has(n.id)?'selected':''} ${b().pinned.includes(n.id)?'pinned':''}" data-network-node="${e(n.id)}" data-kind="${e(n.type)}" style="left:${position(n.id).x}px;top:${position(n.id).y}px" role="button" tabindex="0" aria-label="${e(n.label+', '+label(n.type)+', '+n.status)}"><span class="network-node-type">${e(label(n.type))}${b().pinned.includes(n.id)?' · pinned':''}</span><b>${e(n.label)}</b><small>${e(n.origin==='manual'?'Your observation':n.status)}</small><button class="network-handle" data-connect-from="${e(n.id)}" aria-label="Drag a connection from ${e(n.label)}" title="Drag to another node or empty canvas">+</button></article>`).join('')}</div>`;
    const counter=document.getElementById('network-counter');if(counter)counter.textContent=`${nodes.length} nodes · ${edges.length} connections`;
    transform();
  }
  function sourceList(evidence) {
    return (evidence||[]).map(ref=>`<div class="network-source"><a href="${e(safeURL(ref.url))}" target="_blank" rel="noopener noreferrer">${e(ref.title||'Original source')} ↗</a><small>Version ${e(ref.version)}${ref.publishedAt?(ref.publishedEstimated?' · Collected ':' · Published ')+new Date(ref.publishedAt).toLocaleDateString():''}${ref.retrievedAt?' · Retrieved '+new Date(ref.retrievedAt).toLocaleDateString():''}</small><blockquote>${e(ref.quote)}</blockquote></div>`).join('');
  }
  function researchControls(id, edgeId='') {
    return `<form id="network-research-form" data-node="${e(id)}" data-edge="${e(edgeId)}"><label>Research further<select name="focus">${Object.entries(focuses).map(([key,title])=>`<option value="${key}"${edgeId&&key==='verify'?' selected':''}>${title}</option>`).join('')}</select></label><div class="network-research-options"><label>Depth<select name="depth"><option>1</option><option>2</option><option>3</option></select></label><label class="network-check"><input type="checkbox" name="automatic">Expand direct documented branches automatically</label></div><button class="network-primary" type="submit">Research further ↗</button><small>Uses the connected OpenAI model. Background expansion follows your AI settings.</small></form>`;
  }
  function inspectNode(id) {
    selected=id;selectedEdge=null;focusedNode=null;const item=node(id),panel=document.getElementById('network-inspector');if(!item||!panel)return;
    panel.innerHTML=`<span class="network-kicker">${e(label(item.type))} · ${e(item.status)}</span><h2>${e(item.label)}</h2>${item.summary?`<p>${e(item.summary)}</p>`:''}<div class="network-inspector-actions"><button data-network-action="pin" data-id="${e(id)}">${b().pinned.includes(id)?'Unpin':'Pin'}</button><button data-network-action="collapse" data-id="${e(id)}">${b().collapsed.includes(id)?'Expand':'Collapse'} branch</button><button data-network-action="watch" data-id="${e(id)}">Add to watch portfolio</button></div>${item.origin==='manual'?`<p class="network-manual-note">Your assertion. AI research can investigate it; editing or attaching a citation does not establish the relationship.</p><button data-network-action="edit-node" data-id="${e(id)}">Edit observation</button>`:''}${item.provenance?`<small>${e(item.provenance)}</small>`:''}<div id="network-node-records"></div>${researchControls(id)}<section><h3>Supporting evidence</h3>${sourceList(item.evidence)||'<p>No original source supports this observation yet.</p>'}</section><section><h3>Your notes</h3><label class="sr-only" for="network-node-note">Private node note</label><textarea id="network-node-note" data-note-id="${e(id)}" maxlength="6000" placeholder="Add an observation, question or research note…">${e(b().notes[id]||'')}</textarea></section><section><h3>Connections</h3>${allEdges().filter(edge=>id===edge.from||id===edge.to).slice(0,30).map(edge=>`<button class="network-related" data-network-inspect-edge="${e(edge.id)}">${e(label(edge.type))} → ${e(node(edge.from===id?edge.to:edge.from)?.label||'Entity')}<small>${e(edge.status)}</small></button>`).join('')||'<p>No documented connections yet.</p>'}</section>`;
    paintWorld();
    if(item.origin==='manual')return;
    const boardId=b().id;
    api.request('network-node?boardId='+encodeURIComponent(boardId)+'&id='+encodeURIComponent(id)).then(result=>{
      if(!active()||b().id!==boardId||selected!==id)return;
      focusedNode=result;const records=document.getElementById('network-node-records');if(!records)return;
      const attrs=result.node.attributes||[];
      records.innerHTML=`${attrs.length?`<section><h3>Corporate & disclosed records</h3><dl>${attrs.map(a=>`<dt>${e(a.field)}</dt><dd>${e(a.value)}</dd>`).join('')}</dl><p class="network-muted">Reported values retain the source's units, dates and currencies. See supporting passages below.</p></section>`:''}${result.financialProfile?`<section><h3>Financial profile</h3><button data-asset-profile="${e(result.financialProfile.id)}">Open verified instrument profile ↗</button><p>${e(result.financialProfile.status)}</p></section>`:item.type==='company'||item.type==='financial_institution'?'<p class="network-muted">No provider-verified instrument is linked. Private-company monitoring does not require a ticker or market price.</p>':''}${item.type==='article'?`<section><h3>Article attribution</h3><p>${e(item.source)}<br>${item.authors?.length?item.authors.map(a=>e(a.name||a)).join(', '):'Individual byline unavailable'}<br>${e(item.reportingStatus||'')}</p></section>`:''}${result.authorWorks?.length?`<section><h3>Source-credited published work</h3>${result.authorWorks.map(d=>`<a class="network-related" href="${e(safeURL(d.url))}" target="_blank" rel="noopener noreferrer">${e(d.title)}<small>${e(d.source)}</small></a>`).join('')}<p class="network-muted">No beliefs, motives or bias labels are inferred from this coverage.</p></section>`:''}${result.claims?.length?`<details><summary>Source claims · ${result.claims.length}</summary>${result.claims.slice(0,12).map(c=>`<p>${e(c.text)}<small>${e(c.status)}</small></p>`).join('')}</details>`:''}${result.sourceHistory?.length?`<details><summary>Source revisions · ${result.sourceHistory.length}</summary>${result.sourceHistory.map(v=>`<p>v${e(v.version)} · ${new Date(v.retrievedAt).toLocaleString()}${v.correctedAt?' · correction/revision':''}</p>`).join('')}</details>`:''}`;
    }).catch(error=>{const records=document.getElementById('network-node-records');if(records&&selected===id)records.textContent=error.message;});
  }
  function inspectEdge(id) {
    const edge=allEdges().find(r=>r.id===id),panel=document.getElementById('network-inspector');if(!edge||!panel)return;
    selectedEdge=id;selected=null;selection.clear();
    panel.innerHTML=`<span class="network-kicker">${e(edge.origin==='manual'?'Personal connection':edge.status)}</span><h2>${e(label(edge.type))}</h2><p><b>${e(node(edge.from)?.label)}</b> → <b>${e(node(edge.to)?.label)}</b></p><p>${e(edge.claim)}</p><p class="network-muted">Observed ${edge.observedAt?new Date(edge.observedAt).toLocaleString():'date unavailable'}<br>Last verified ${edge.lastVerifiedAt?new Date(edge.lastVerifiedAt).toLocaleString():'not verified'}</p>${edge.origin==='manual'?`<div class="network-inspector-actions"><button data-network-action="edit-edge" data-id="${e(id)}">Edit connection</button><button data-network-action="delete-edge" data-id="${e(id)}">Delete personal link</button></div>${edge.citations?.length?`<h3>Your citation references</h3>${edge.citations.map(c=>`<p>${e(c)}</p>`).join('')}`:''}<p class="network-manual-note">Personal assertion. Supporting a new system relationship requires independent original evidence and review.</p>`:''}<section><h3>Why these entities are connected</h3>${sourceList(edge.evidence)||'<p>This is a research question or personal assertion, without an established factual connection.</p>'}</section>${researchControls(edge.from,id)}<section><h3>Your connection notes</h3><textarea id="network-edge-note" data-note-id="${e(id)}" maxlength="6000">${e(b().notes[id]||'')}</textarea></section>`;
    if(api.session?.ownerAuthorized&&edge.origin!=='manual'&&edge.evidence?.length&&edge.status!=='Research question'){
      panel.insertAdjacentHTML('beforeend',`<details class="network-review"><summary>Review this relationship</summary><form id="network-review-form" data-edge="${e(id)}"><label>Evidence status<select name="status"><option>Reported</option><option>Verified</option><option>Corroborated</option><option>Disputed</option></select></label><label>What did the original evidence establish?<textarea name="reason" minlength="12" maxlength="2000" required></textarea></label><label class="network-check"><input type="checkbox" required>I reviewed the original records and the exact relationship.</label><button type="submit">Record evidence review</button></form></details>`);
    }
    paintWorld();
  }
  function taskList() {
    const tasks=(detail?.tasks||[]).slice(0,12);
    return tasks.map(t=>`<div class="network-task"><span>${e(t.label)}</span><small>${e(label(t.focus))} · ${e(t.status)}</small>${t.message?`<small>${e(t.message)}</small>`:''}</div>`).join('')||'<p>Choose a node and a research direction to investigate a branch.</p>';
  }
  function render() {
    const host=document.getElementById('research-network');if(!host||!detail)return;
    host.innerHTML=`<div class="network-heading"><div><span class="network-kicker">RESEARCH OBSERVATION BOARD</span><h2>${e(b().title)}</h2></div><span id="network-save-state">${dirty?'Unsaved changes':'Saved privately'}${b().version?' · v'+b().version:''}</span></div><div class="network-toolbar" role="toolbar" aria-label="Observation board actions"><button id="network-save" data-network-action="save" class="network-primary">Save board</button><button data-network-action="research">Research further</button><button data-network-action="add">+ Add node</button><button data-network-action="arrange">Auto-arrange</button><button data-network-action="cleanup">Clean up nodes</button><button data-network-action="group">Group selected</button><button data-network-action="undo"${undo.length?'':' disabled'} aria-label="Undo board edit">↶</button><button data-network-action="redo"${redo.length?'':' disabled'} aria-label="Redo board edit">↷</button><button data-network-action="export">Export</button><button data-network-action="my-research">My Research</button><button data-network-action="workspace">Workspace ↗</button><a href="/CRAWLER/account.html">Account ↗</a><a href="#topic-research">Market brief ↓</a></div><div class="network-grid"><aside class="network-sidebar"><label class="network-label" for="network-search">Find on this board</label><input id="network-search" value="${e(filter)}" placeholder="Company, author, contract…" autocomplete="off"><label class="network-label" for="network-evidence-filter">Evidence</label><select id="network-evidence-filter"><option value="">All evidence states</option>${['Verified','Corroborated','Reported','Review required','manual','questions'].map(s=>`<option value="${s}"${evidenceFilter===s?' selected':''}>${e(label(s))}</option>`).join('')}</select><label class="network-label" for="network-relationship-filter">Connection type</label><select id="network-relationship-filter"><option value="">All relationships</option>${relationships.map(s=>`<option value="${s}"${relationshipFilter===s?' selected':''}>${e(label(s))}</option>`).join('')}</select><div id="network-search-results"></div><details class="node-type-key"><summary>Node color guide</summary><p>Green · companies<br>Blue · reporting and regions<br>Purple · products and suppliers<br>Gold · money and markets<br>Rose · open questions</p><p>Labels identify each type. Click a node to trace its immediate evidence connections.</p></details><nav class="network-navigation"><button data-network-action="my-research">My Research</button><button data-network-action="portfolios">Saved portfolios</button><button data-network-action="followed">Followed companies</button><button data-network-action="notifications">Notifications${personal?.notifications?.filter(n=>!n.read).length?' · '+personal.notifications.filter(n=>!n.read).length:''}</button></nav><section class="network-panel" data-network-library="portfolios"></section><section><h3>Recent investigations</h3>${(personal?.boards||[]).filter(r=>!r.archived).slice(0,8).map(r=>`<button class="network-recent" data-open-network-board="${e(r.id)}">${e(r.title)}</button>`).join('')||'<p>This board is saved to your workspace.</p>'}</section><section><h3>Research queue</h3><div id="network-tasks">${taskList()}</div><div class="network-queue-actions"><button data-network-action="pause">Pause</button><button data-network-action="resume">Resume</button><button data-network-action="cancel">Cancel</button></div></section><section><h3>Collections</h3>${b().groups.map(g=>`<button class="network-recent" data-network-group="${e(g.id)}">${e(g.label)} · ${g.nodeIds.length}</button>`).join('')||'<p>Shift-click nodes to select, then group.</p>'}</section><button data-network-action="unhide">Show hidden nodes</button></aside><div class="network-center"><div class="network-canvas" id="network-canvas" tabindex="0" aria-label="Pannable research graph. Drag background to pan, scroll to zoom, select a node to inspect. Shift click selects multiple nodes."><div id="network-world" class="network-world"></div><div class="network-canvas-hint">Drag to explore · double-click to expand · drag + to connect</div><div class="network-zoom"><button data-network-action="zoom-out" aria-label="Zoom out">−</button><span id="network-zoom-label">100%</span><button data-network-action="zoom-in" aria-label="Zoom in">+</button><button data-network-action="fit">Fit</button><button data-network-action="root">Topic</button></div><svg id="network-minimap" class="network-minimap" aria-label="Research graph mini-map" role="button" tabindex="0"></svg></div><div class="network-footer"><span id="network-counter"></span><span class="network-legend"><i class="verified"></i>Verified <i class="reported"></i>Reported <i class="question"></i>Question <i class="manual"></i>Personal</span><button data-network-action="show-more">Show more nodes</button></div><p id="network-feedback" class="network-feedback" role="status">${e(detail.graph.warning||topic?.progress||'')}</p></div><aside class="network-inspector" id="network-inspector"><span class="network-kicker">FOLLOW THE CONNECTIONS</span><h2>Start with the evidence.</h2><p>Select a node or line to inspect its original sources and research further.</p><p>Direct business links carry their own evidence. Dotted branches are open questions; purple connections are personal assertions.</p></aside></div>`;
    paintWorld();
    if(selected&&node(selected))inspectNode(selected);else if(selectedEdge&&allEdges().some(e=>e.id===selectedEdge))inspectEdge(selectedEdge);
    document.getElementById('network-canvas').addEventListener('wheel',wheel,{passive:false});
    const toolbar=host.querySelector('.network-toolbar');
    toolbar.insertAdjacentHTML('beforeend','<button data-network-action="queue">Research queue</button>');
    if(!b().viewport.x&&!b().viewport.y)rootFocus();
    canvasObserver?.disconnect();
    const canvas=document.getElementById('network-canvas');let dimensions={w:canvas.clientWidth,h:canvas.clientHeight};
    canvasObserver=new ResizeObserver(()=>{
      if(!active()||!canvas.isConnected)return;
      const w=canvas.clientWidth,h=canvas.clientHeight;
      if(w!==dimensions.w||h!==dimensions.h){b().viewport.x+=(w-dimensions.w)/2;b().viewport.y+=(h-dimensions.h)/2;dimensions={w,h};transform();changed();}
    });
    canvasObserver.observe(canvas);
    renderPanels();
  }
  async function attach(nextTopic) {
    topic=nextTopic;
    if(detail?.board.topicId===topic.id){if(!document.getElementById('network-canvas'))render();return;}
    if(attachingTopic===topic.id)return;
    if(dirty&&detail)await save();
    attachingTopic=topic.id;
    const serial=++generation;
    detail=null;selected=null;selectedEdge=null;selection.clear();undo=[];redo=[];dirty=false;filter='';visibleLimit=80;lastBoardPoll=0;
    const host=document.getElementById('research-network');if(host)host.innerHTML='<div class="network-loading">Opening the observation board…</div>';
    try{
      const result=await api.request('boards',{topicId:topic.id});if(serial!==generation||topic.id!==nextTopic.id)return;
      detail=result;personal=await api.request('my-research');if(serial!==generation)return;render();
    }catch(error){if(host?.isConnected)host.innerHTML=`<p class="network-feedback">${e(error.message)}</p><a href="/CRAWLER/login.html">Sign in to save a private board ↗</a>`;}finally{if(serial===generation)attachingTopic=null;}
  }
  async function openBoard(id) {
    if(dirty)await save();
    const result=await api.request('boards?id='+encodeURIComponent(id));
    const next=await api.request('topics?id='+encodeURIComponent(result.board.topicId));
    detail=result;dirty=false;undo=[];redo=[];selection.clear();selected=null;selectedEdge=null;
    await window.CrawlerStart.openTopic(next.id); // attach uses the already-loaded private board.
  }
  function save() {
    if(savePromise)return savePromise;
    if(!detail)return Promise.resolve();
    saving=true;const button=document.getElementById('network-save');if(button)button.disabled=true;
    savePromise=(async()=>{
      const fields=['title','description','folder','archived','layout','notes','manualNodes','manualEdges','groups','hidden','pinned','collapsed','expanded','viewport'];
      const snapshot=()=>Object.fromEntries(fields.filter(k=>b()[k]!==undefined).map(k=>[k,clone(b()[k])]));
      do{
        const boardId=b().id,values=snapshot();
        const result=await api.request('boards/save',{id:boardId,baseVersion:b().version,...values});
        if(b()?.id!==boardId)return;
        const current=snapshot(),edited=JSON.stringify(current)!==JSON.stringify(values);
        detail=result;
        if(edited)Object.assign(b(),current);
        dirty=edited;
      }while(dirty);
      const status=document.getElementById('network-save-state');if(status)status.textContent='Saved privately · v'+b().version;
      personal=await api.request('my-research');
    })().finally(()=>{saving=false;savePromise=null;if(button)button.disabled=false;});
    return savePromise;
  }
  function feedback(message) { const target=document.getElementById('network-feedback');if(target)target.textContent=message;document.querySelectorAll('.network-panel-status').forEach(el=>{el.textContent=message;}); }
  const portfolioRows=(p,compact)=>`<div class="network-portfolio-card"><div class="network-library-row"><b>${e(p.title)}${p.archived?' · Archived':''}</b><button data-network-delete-portfolio="${e(p.id)}" aria-label="Delete portfolio ${e(p.title)}">Delete</button></div>${(p.items||[]).slice(0,compact?5:50).map(i=>`<div class="network-library-row"><button data-network-followed-board="${e(i.boardId)}" data-node="${e(i.nodeId)}">${e(i.label)}<small>${e(i.researchStatus||i.reason||'')}</small></button><button data-network-remove-watch="${e(p.id)}" data-node="${e(i.nodeId)}" aria-label="Remove ${e(i.label)}">×</button></div>`).join('')||'<small>No items yet. Add nodes from a board.</small>'}</div>`;
  function libraryHTML(kind) {
    const data=personal||{boards:[],portfolios:[]},compact=kind==='portfolios';
    const portfolios=`<div class="network-panel-heading"><h3>Watch portfolios · ${data.portfolios.length}</h3><button data-network-new-portfolio>+ New</button></div>${data.portfolios.map(p=>portfolioRows(p,compact)).join('')||'<p>No watch portfolios yet.</p>'}`;
    if(compact)return portfolios;
    const boards=`<div class="network-panel-heading"><h3>Research boards · ${data.boards.length}</h3></div>${data.boards.map(r=>`<div class="network-library-row"><button data-open-network-board="${e(r.id)}">${e(r.title)}<small>${e(r.folder||'Unfiled')}${r.archived?' · Archived':''}${r.updatedAt?' · '+new Date(r.updatedAt).toLocaleDateString():''}</small></button><button data-network-delete-board="${e(r.id)}" aria-label="Delete board ${e(r.title)}">Delete</button></div>`).join('')||'<p>Search a topic to create your first board.</p>'}`;
    return `<h2>Research boards &amp; portfolios</h2>${boards}${portfolios}<p class="network-panel-status" role="status"></p>`;
  }
  // The same boards and portfolios render in the board sidebar and in the workspace watchlist.
  async function renderPanels() {
    const workspace=document.querySelector('#server-watchlist');
    if(workspace&&!document.getElementById('workspace-research'))workspace.insertAdjacentHTML('beforebegin','<section id="workspace-research" class="research-box network-panel" data-network-library="all"></section>');
    const panels=[...document.querySelectorAll('[data-network-library]')];if(!panels.length)return;
    if(!personal&&api.connected){try{personal=await api.request('my-research');}catch(error){feedback(error.message);return;}}
    for(const panel of panels)panel.innerHTML=libraryHTML(panel.dataset.networkLibrary);
  }
  async function personalChanged(view) {
    personal=await api.request('my-research');
    renderPanels();
    if(document.getElementById('network-edit-dialog')?.open)library(view);
  }
  function modal(content, title='Edit research') {
    document.getElementById('network-edit-dialog')?.remove();const dialog=document.createElement('dialog');dialog.id='network-edit-dialog';dialog.className='network-dialog';
    dialog.innerHTML=`<div class="network-dialog-title"><h2>${e(title)}</h2><button type="button" data-close-network aria-label="Close dialog">×</button></div>${content}`;
    document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();return dialog;
  }
  function nodeEditor(id=null, from=null, at=null) {
    const item=id?node(id):null;
    if(item&&item.origin!=='manual'){inspectNode(id);document.getElementById('network-node-note')?.focus();return;}
    modal(`<form id="network-node-editor" data-id="${e(id||'')}" data-from="${e(from||'')}" data-x="${at?.x||0}" data-y="${at?.y||0}"><label>Name<input name="label" required maxlength="300" value="${e(item?.label||'')}"></label><label>Category<select name="type">${types.map(t=>`<option value="${t}"${item?.type===t?' selected':''}>${e(label(t))}</option>`).join('')}</select></label><label>Observation or research question<textarea name="summary" maxlength="6000">${e(item?.summary||'')}</textarea></label><p>Your addition is a personal assertion, separate from system evidence.</p><button class="network-primary" type="submit">${id?'Save observation':'Add observation'}</button></form>`,id?'Edit personal observation':'New personal observation');
  }
  function edgeEditor(from,to,id=null) {
    const item=id?b().manualEdges.find(e=>e.id===id):null;
    modal(`<form id="network-edge-editor" data-id="${e(id||'')}" data-from="${e(from)}" data-to="${e(to)}"><p>${e(node(from)?.label)} → ${e(node(to)?.label)}</p><label>Relationship type<select name="type">${relationships.map(t=>`<option value="${t}"${item?.type===t?' selected':''}>${e(label(t))}</option>`).join('')}</select></label><label>Description<textarea name="claim" maxlength="1800">${e(item?.claim||'')}</textarea></label><label>Citation references, one per line<textarea name="citations" maxlength="12000">${e((item?.citations||[]).join('\n'))}</textarea></label><p>This link remains a personal assertion. Use Research further to request independent evidence.</p><button type="submit" class="network-primary">Save personal connection</button></form>`,'Connect research objects');
  }
  function download(value,name='research-board.json') {const url=URL.createObjectURL(new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type:typeof value==='string'?'text/csv':'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function library(view='boards') {
    const data=personal||{boards:[],portfolios:[],notifications:[]};
    let content='';
    if(view==='boards')content=`<form id="network-board-properties"><label>Board name<input name="title" value="${e(b().title)}" required maxlength="200"></label><label>Description<textarea name="description" maxlength="2000">${e(b().description)}</textarea></label><label>Folder<input name="folder" value="${e(b().folder)}" maxlength="100"></label><button type="submit">Save details</button></form><h3>Saved investigations</h3>${data.boards.map(row=>`<div class="network-library-row"><button data-open-network-board="${e(row.id)}">${e(row.title)}<small>${e(row.folder||'Unfiled')}${row.archived?' · Archived':''}</small></button></div>`).join('')}<div class="network-dialog-actions"><button data-network-action="duplicate-board">Duplicate current board</button><button data-network-action="archive-board">${b().archived?'Unarchive':'Archive'} board</button><button data-network-action="delete-board">Delete current board</button></div><h3>Layout revisions</h3>${(detail.revisions||[]).map(r=>`<button class="network-revision" data-network-restore="${r.version}">v${r.version} · ${new Date(r.updatedAt).toLocaleString()}</button>`).join('')}`;
    if(view==='portfolios'||view==='followed')content=`<form id="network-new-portfolio"><label>Portfolio name<input name="title" required maxlength="200" placeholder="New thematic watch portfolio"></label><label>Folder<input name="folder" maxlength="100"></label><button type="submit">Create portfolio</button></form>${data.portfolios.map(p=>`<section class="network-portfolio"><h3>${e(p.title)}</h3><small>${e(p.folder||'Unfiled')}</small>${p.items.filter(i=>view!=='followed'||['company','financial_institution','instrument'].includes(i.type)).map(i=>`<div class="network-library-row"><button data-network-followed-board="${e(i.boardId)}" data-node="${e(i.nodeId)}">${e(i.label)}<small>${e(i.reason)}</small></button><button data-network-remove-watch="${e(p.id)}" data-node="${e(i.nodeId)}" aria-label="Remove ${e(i.label)}">×</button></div>`).join('')}<button data-network-delete-portfolio="${e(p.id)}">Delete portfolio</button></section>`).join('')||'<p>No watch portfolios yet.</p>'}`;
    if(view==='notifications')content=`<form id="network-notification-settings"><label class="network-check"><input type="checkbox" name="enabled" checked>Notify me when source evidence changes</label><button type="submit">Save notification settings</button></form>${data.notifications.map(n=>`<div class="network-library-row"><button data-open-network-board="${e(n.boardId)}">${e(n.message)}<small>${new Date(n.at).toLocaleString()}</small></button><button data-network-read-notice="${e(n.id)}">${n.read?'Read':'Mark read'}</button></div>`).join('')||'<p>No source changes to review.</p>'}`;
    const dialog=modal(content,view==='boards'?'My Research':label(view));
    dialog.querySelector('.network-dialog-title').insertAdjacentHTML('afterend','<nav class="network-dialog-actions"><button data-network-action="my-research">Boards</button><button data-network-action="portfolios">Portfolios</button><button data-network-action="followed">Followed companies</button><button data-network-action="notifications">Notifications</button></nav>');
    const notification=dialog.querySelector('[name=enabled]');if(notification)notification.checked=data.preferences?.notifications!==false;
    dialog.querySelectorAll('.network-portfolio').forEach((section,index)=>{
      const portfolio=data.portfolios[index];
      section.querySelector('h3').insertAdjacentHTML('afterend',`<p>${e(portfolio.description||'')}${portfolio.archived?' · Archived':''}</p><button data-network-edit-portfolio="${e(portfolio.id)}">Edit / archive portfolio</button>`);
      portfolio.items.forEach(item=>{if(item.researchStatus)section.insertAdjacentHTML('beforeend',`<p>${e(item.label)} · ${e(item.researchStatus)}</p>`);});
    });
  }
  async function watch(id) {
    const item=node(id);if(!item)return;personal=await api.request('my-research');
    modal(`<form id="network-watch-form" data-node="${e(id)}"><p>${e(item.label)}</p><label>Watch portfolio<select name="portfolioId"><option value="">Create a new portfolio</option>${personal.portfolios.map(p=>`<option value="${e(p.id)}">${e(p.title)}</option>`).join('')}</select></label><label>New portfolio name<input name="title" maxlength="200" value="Research watchlist"></label><label>Why watch this subject?<textarea name="reason" maxlength="2000" required>${e(item.watchFor||item.summary||'Follow developments supported by this investigation')}</textarea></label><button type="submit" class="network-primary">Add to watch portfolio</button></form>`,'Watch this research subject');
  }
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!form.getAttribute('id')?.startsWith('network-'))return;event.preventDefault();
    const values=Object.fromEntries(new FormData(form));
    try{
      if(form.id==='network-node-editor'){
        checkpoint();const id=form.dataset.id||uid(),item={id,label:values.label,type:values.type,summary:values.summary,origin:'manual',status:'User assertion',createdAt:Date.now()};
        const index=b().manualNodes.findIndex(n=>n.id===id);if(index>=0)b().manualNodes[index]=item;else b().manualNodes.push(item);
        if(index<0)b().layout[id]={x:Number(form.dataset.x)||250,y:Number(form.dataset.y)||0};
        if(form.dataset.from)b().manualEdges.push({id:uid(),from:form.dataset.from,to:id,type:'research_question',claim:'Personal research question',origin:'manual',status:'User assertion',evidence:[],citations:[],observedAt:Date.now()});
        changed();document.getElementById('network-edit-dialog').close();render();inspectNode(id);
      }else if(form.id==='network-edge-editor'){
        checkpoint();const item={id:form.dataset.id||uid(),from:form.dataset.from,to:form.dataset.to,type:values.type,claim:values.claim,origin:'manual',status:'User assertion',evidence:[],citations:values.citations.split('\n').map(s=>s.trim()).filter(Boolean).slice(0,8),observedAt:Date.now()};
        const index=b().manualEdges.findIndex(e=>e.id===item.id);if(index>=0)b().manualEdges[index]=item;else b().manualEdges.push(item);changed();document.getElementById('network-edit-dialog').close();render();inspectEdge(item.id);
      }else if(form.id==='network-review-form'){
        const edge=await api.request('network/review',{id:form.dataset.edge,status:values.status,reason:values.reason});
        detail.graph.edges=detail.graph.edges.map(row=>row.id===edge.id?edge:row);inspectEdge(edge.id);feedback('Evidence review recorded.');
      }else if(form.id==='network-portfolio-editor'){
        await api.request('portfolios',{id:form.dataset.id,...values,archived:form.elements.archived.checked});personal=await api.request('my-research');library('portfolios');
      }else if(form.id==='network-research-form'){
        if(dirty)await save();const task=await api.request('network/research',{boardId:b().id,nodeId:form.dataset.node,edgeId:form.dataset.edge||undefined,focus:values.focus,depth:Number(values.depth),automatic:form.elements.automatic.checked});
        detail.tasks.unshift(task);document.getElementById('network-tasks').innerHTML=taskList();feedback('Queued '+label(task.focus)+' research for '+task.label+'.');
      }else if(form.id==='network-watch-form'){
        if(dirty)await save();await api.request('portfolios',{id:values.portfolioId||undefined,title:values.portfolioId?undefined:values.title,nodeId:form.dataset.node,boardId:b().id,reason:values.reason});personal=await api.request('my-research');document.getElementById('network-edit-dialog').close();renderPanels();feedback('Added to your watch portfolio.');
      }else if(form.id==='network-board-properties'){checkpoint();Object.assign(b(),values);changed();await save();document.getElementById('network-edit-dialog').close();render();
      }else if(form.id==='network-new-portfolio'){await api.request('portfolios',values);await personalChanged('portfolios');
      }else if(form.id==='network-group-form'){checkpoint();b().groups.push({id:uid(),label:values.label,nodeIds:[...selection]});changed();document.getElementById('network-edit-dialog').close();render();
      }else if(form.id==='network-notification-settings'){personal=await api.request('my-research',{notificationSettings:form.elements.enabled.checked});feedback('Notification preferences saved.');document.getElementById('network-edit-dialog').close();}
    }catch(error){feedback(error.message);const dialog=document.getElementById('network-edit-dialog');if(dialog){let p=dialog.querySelector('.network-dialog-error');if(!p){p=document.createElement('p');p.className='network-dialog-error';dialog.append(p);}p.textContent=error.message;}}
  });
  document.addEventListener('input',event=>{
    if(event.target.id==='network-search'){filter=event.target.value.toLowerCase().trim();paintWorld();const target=document.getElementById('network-search-results');target.innerHTML=filter?visibleNodes().slice(0,8).map(n=>`<button class="network-recent" data-network-focus="${e(n.id)}">${e(n.label)}</button>`).join(''):'';}
    if(event.target.dataset.noteId){if(undoKey!==event.target.dataset.noteId){checkpoint();undoKey=event.target.dataset.noteId;}b().notes[event.target.dataset.noteId]=event.target.value;changed();}
  });
  document.addEventListener('change',event=>{if(event.target.id==='network-evidence-filter'){evidenceFilter=event.target.value;paintWorld();}if(event.target.id==='network-relationship-filter'){relationshipFilter=event.target.value;paintWorld();}});
  document.addEventListener('click',async event=>{
    const target=event.target.closest('button,a,[data-network-node],[data-network-edge]');if(!target)return;
    if(target.matches('[data-close-network]')){document.getElementById('network-edit-dialog')?.close();return;}
    try{
      if(target.dataset.openNetworkBoard){document.getElementById('network-edit-dialog')?.close();await openBoard(target.dataset.openNetworkBoard);return;}
      if(target.dataset.networkFollowedBoard){document.getElementById('network-edit-dialog')?.close();await openBoard(target.dataset.networkFollowedBoard);setTimeout(()=>focusNode(target.dataset.node),300);return;}
      if(target.dataset.networkRemoveWatch){await api.request('portfolios',{id:target.dataset.networkRemoveWatch,removeNodeId:target.dataset.node});await personalChanged('portfolios');return;}
      if(target.dataset.networkDeletePortfolio){
        const name=personal?.portfolios.find(p=>p.id===target.dataset.networkDeletePortfolio)?.title||'this portfolio';
        if(!confirm('Delete portfolio "'+name+'"? Its watched items are removed; boards are kept.'))return;
        await api.request('portfolios',{id:target.dataset.networkDeletePortfolio,delete:true});await personalChanged('portfolios');return;
      }
      if(target.dataset.networkDeleteBoard){
        const id=target.dataset.networkDeleteBoard,name=personal?.boards.find(r=>r.id===id)?.title||'this board';
        if(!confirm('Delete board "'+name+'" and its saved layouts? Shared source records remain available.'))return;
        await api.request('boards/action',{id,action:'delete'});
        const wasOpen=detail?.board.id===id;if(wasOpen){detail=null;dirty=false;}
        await personalChanged('boards');if(wasOpen)window.CrawlerStart.showStart();return;
      }
      if(target.dataset.networkNewPortfolio!==undefined){const title=prompt('Portfolio name');if(title?.trim()){await api.request('portfolios',{title:title.trim()});await personalChanged('portfolios');}return;}
      if(target.dataset.networkEditPortfolio){
        const p=personal.portfolios.find(p=>p.id===target.dataset.networkEditPortfolio);
        modal(`<form id="network-portfolio-editor" data-id="${e(p.id)}"><label>Name<input name="title" value="${e(p.title)}" required maxlength="200"></label><label>Description<textarea name="description" maxlength="2000">${e(p.description)}</textarea></label><label>Folder<input name="folder" maxlength="100" value="${e(p.folder)}"></label><label class="network-check"><input name="archived" type="checkbox"${p.archived?' checked':''}>Archive this portfolio</label><button type="submit">Save portfolio</button></form>`,'Edit watch portfolio');return;
      }
      if(target.dataset.networkReadNotice){personal=await api.request('my-research',{notificationId:target.dataset.networkReadNotice});library('notifications');return;}
      if(target.dataset.networkRestore){detail=await api.request('boards/action',{id:b().id,action:'restore',version:Number(target.dataset.networkRestore)});dirty=false;undo=[];redo=[];document.getElementById('network-edit-dialog')?.close();render();return;}
      if(!active())return;
      if(target.dataset.networkFocus){focusNode(target.dataset.networkFocus);return;}
      if(target.dataset.networkGroup){const group=b().groups.find(g=>g.id===target.dataset.networkGroup);selection=new Set(group?.nodeIds||[]);filter='';paintWorld();fit();return;}
      if(target.dataset.networkInspectEdge){inspectEdge(target.dataset.networkInspectEdge);return;}
      if(target.dataset.networkEdge){inspectEdge(target.dataset.networkEdge);return;}
      if(target.dataset.networkNode&&!target.dataset.connectFrom){
        if(drag?.moved||ignoreClick)return;
        if(event.shiftKey){selection.has(target.dataset.networkNode)?selection.delete(target.dataset.networkNode):selection.add(target.dataset.networkNode);paintWorld();}else{selection=new Set([target.dataset.networkNode]);inspectNode(target.dataset.networkNode);}return;
      }
      const action=target.dataset.networkAction,id=target.dataset.id||selected||contextNode;
      if(!action)return;document.getElementById('network-context-menu')?.remove();
      if(action==='save'){await save();return;}
      if(action==='add'){nodeEditor();return;}
      if(action==='edit-node'){nodeEditor(id);return;}
      if(action==='edit-edge'){const edge=b().manualEdges.find(e=>e.id===target.dataset.id);edgeEditor(edge.from,edge.to,edge.id);return;}
      if(action==='delete-edge'){checkpoint();b().manualEdges=b().manualEdges.filter(e=>e.id!==target.dataset.id);selectedEdge=null;changed();render();return;}
      if(action==='research'){if(id)inspectNode(id);else inspectNode(detail.graph.rootId);document.getElementById('network-research-form')?.scrollIntoView({block:'nearest'});return;}
      if(action==='watch'){await watch(id);return;}
      if(action==='queue'){modal(`<div>${taskList()}</div><p>Expansion is ${e(b().expansionState)}. Pausing stops further branch steps; an already-running provider request may finish.</p><div class="network-dialog-actions"><button data-network-action="pause">Pause</button><button data-network-action="resume">Resume</button><button data-network-action="cancel">Cancel pending expansion</button></div>`,'Research queue');return;}
      if(action==='pin'){checkpoint();b().pinned=b().pinned.includes(id)?b().pinned.filter(n=>n!==id):[...b().pinned,id];changed();render();return;}
      if(action==='collapse'){checkpoint();b().collapsed=b().collapsed.includes(id)?b().collapsed.filter(n=>n!==id):[...b().collapsed,id];changed();render();return;}
      if(action==='hide'){checkpoint();b().hidden.push(id);selected=null;changed();render();return;}
      if(action==='unhide'){checkpoint();b().hidden=[];b().collapsed=[];changed();render();return;}
      if(action==='duplicate-node'){const original=node(id);checkpoint();const copy={...clone(original),id:uid(),origin:'manual',status:'User assertion',label:original.label+' · personal copy',evidence:[]};b().manualNodes.push(copy);const pos=position(id);b().layout[copy.id]={x:pos.x+80,y:pos.y+130};changed();render();inspectNode(copy.id);return;}
      if(action==='group'){if(!selection.size){feedback('Shift-click nodes to select a group first.');return;}modal('<form id="network-group-form"><label>Collection name<input name="label" required maxlength="120"></label><button type="submit">Group selected nodes</button></form>','Name this research branch');return;}
      if(action==='cleanup'){cleanUp();return;}
      if(action==='workspace'){if(dirty)await save();window.CrawlerStart.showWorkspace();window.CrawlerHub.navigate('watchlist');return;}
      if(action==='arrange'){checkpoint();b().layout={};initialLayout();changed();paintWorld();fit();return;}
      if(action==='undo'&&undo.length){const version=b().version;redo.push(clone(b()));detail.board=undo.pop();b().version=version;changed();render();return;}
      if(action==='redo'&&redo.length){const version=b().version;undo.push(clone(b()));detail.board=redo.pop();b().version=version;changed();render();return;}
      if(action==='fit'){fit();return;}if(action==='root'){rootFocus();changed();return;}
      if(action==='zoom-in'||action==='zoom-out'){const canvas=document.getElementById('network-canvas');zoomAt(action==='zoom-in'?1.2:1/1.2,canvas.clientWidth/2,canvas.clientHeight/2);return;}
      if(action==='show-more'){visibleLimit+=80;paintWorld();return;}
      if(action==='export'){if(dirty)await save();download({schema:'research-network/board-1',...detail,exportedAt:Date.now()});return;}
      if(['my-research','portfolios','followed','notifications'].includes(action)){personal=await api.request('my-research');library(action==='my-research'?'boards':action);return;}
      if(['pause','resume','cancel','duplicate-board','archive-board','delete-board'].includes(action)){
        if(dirty)await save();
        if(action==='archive-board'){b().archived=!b().archived;await save();document.getElementById('network-edit-dialog')?.close();render();return;}
        if(action==='delete-board'){
          modal('<p>Delete this private board and its saved layouts? Shared source records remain available.</p><button data-network-action="confirm-delete-board">Delete this board</button>','Delete board');return;
        }
        detail=await api.request('boards/action',{id:b().id,action:action==='duplicate-board'?'duplicate':action});dirty=false;document.getElementById('network-edit-dialog')?.close();render();return;
      }
      if(action==='confirm-delete-board'){await api.request('boards/action',{id:b().id,action:'delete'});detail=null;dirty=false;document.getElementById('network-edit-dialog')?.close();window.CrawlerStart.showStart();}
    }catch(error){feedback(error.message);}
  });
  function focusNode(id) {
    const item=node(id),canvas=document.getElementById('network-canvas');if(!item||!canvas)return;
    filter='';evidenceFilter='';b().hidden=b().hidden.filter(n=>n!==id);b().collapsed=[];visibleLimit=700;const pos=position(id);b().viewport={zoom:.9,x:canvas.clientWidth/2-(pos.x+nodeWidth/2)*.9,y:canvas.clientHeight/2-(pos.y+nodeHeight/2)*.9};selection=new Set([id]);inspectNode(id);
  }
  function zoomAt(factor,x,y) {const v=b().viewport,next=Math.max(.15,Math.min(3,v.zoom*factor)),ratio=next/v.zoom;b().viewport={x:x-(x-v.x)*ratio,y:y-(y-v.y)*ratio,zoom:next};transform();changed();}
  function wheel(event){if(!active())return;event.preventDefault();const rect=event.currentTarget.getBoundingClientRect();zoomAt(Math.exp(-event.deltaY*.0015),event.clientX-rect.left,event.clientY-rect.top);}
  document.addEventListener('pointerdown',event=>{
    if(!active())return;const canvas=event.target.closest('#network-canvas');if(!canvas||event.button>1)return;
    const handle=event.target.closest('[data-connect-from]'),card=event.target.closest('[data-network-node]');
    if(event.target.closest('.network-zoom,.network-minimap')||event.target.closest('[data-network-edge]'))return;
    if(handle){event.preventDefault();connecting={from:handle.dataset.connectFrom};canvas.setPointerCapture(event.pointerId);return;}
    if(card&&!space&&event.button!==1){const id=card.dataset.networkNode;drag={mode:'node',id,locked:b().pinned.includes(id),start:point(event),origin:{...position(id)},clientX:event.clientX,clientY:event.clientY,moved:false};}
    else drag={mode:'pan',start:{x:event.clientX,y:event.clientY},origin:{...b().viewport},moved:false};
    event.preventDefault(); window.getSelection()?.removeAllRanges();
    canvas.setPointerCapture(event.pointerId);
  });
  let dragFrame = null;
  function scheduleDragPaint() {
    if (dragFrame !== null) return;
    dragFrame = requestAnimationFrame(() => {
      dragFrame = null;
      if (!active()) return;
      for (const el of document.querySelectorAll('[data-network-node]')) {
        const p = position(el.dataset.networkNode); el.style.left=p.x+'px'; el.style.top=p.y+'px';
      }
      const edgeMap = new Map(allEdges().map(edge => [edge.id,edge]));
      for (const el of document.querySelectorAll('[data-network-edge]')) {
        const edge=edgeMap.get(el.dataset.networkEdge); if(!edge)continue;
        el.querySelectorAll('path').forEach(path=>path.setAttribute('d',linePath(edge)));
        const from=position(edge.from),to=position(edge.to),text=el.querySelector('text');
        text.setAttribute('x',(from.x+to.x)/2+nodeWidth/2);text.setAttribute('y',(from.y+to.y)/2+nodeHeight/2-9);
      }
      minimap();
    });
  }
  document.addEventListener('pointermove',event=>{
    if(!active())return;
    if(connecting){const current=point(event),from=position(connecting.from),path=document.getElementById('network-connecting-line');if(path)path.setAttribute('d',`M ${from.x+nodeWidth} ${from.y+nodeHeight/2} L ${current.x} ${current.y}`);return;}
    if(!drag)return;
    if(drag.mode==='node'){
      if(drag.locked)return;
      const current=point(event);if(!drag.moved&&Math.hypot(event.clientX-drag.clientX,event.clientY-drag.clientY)>4){checkpoint();drag.moved=true;}
      if(drag.moved){b().layout[drag.id]={x:drag.origin.x+current.x-drag.start.x,y:drag.origin.y+current.y-drag.start.y};changed();scheduleDragPaint();}
    }else{if(!drag.moved){checkpoint();drag.moved=true;}b().viewport={...drag.origin,x:drag.origin.x+event.clientX-drag.start.x,y:drag.origin.y+event.clientY-drag.start.y};transform();changed();}
  });
  document.addEventListener('pointerup',event=>{
    if(connecting&&active()){
      const from=connecting.from;connecting=null;const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-network-node]');
      if(target&&target.dataset.networkNode!==from)edgeEditor(from,target.dataset.networkNode);else if(!target)nodeEditor(null,from,point(event));paintWorld();
    }
    if(drag){
      const completed=drag;drag=null;ignoreClick=true;setTimeout(()=>{ignoreClick=false;},0);
      if(completed.mode==='node'&&!completed.moved){
        if(event.shiftKey){selection.has(completed.id)?selection.delete(completed.id):selection.add(completed.id);paintWorld();}
        else{
          selection=new Set([completed.id]);inspectNode(completed.id);
          if(lastClick?.id===completed.id&&Date.now()-lastClick.at<450){expandNode(completed.id);lastClick=null;}
          else lastClick={id:completed.id,at:Date.now()};
        }
      }
    }
  });
  function expandNode(id) {checkpoint();b().collapsed=b().collapsed.filter(n=>n!==id);const related=allEdges().filter(e=>e.from===id||e.to===id).flatMap(e=>[e.from,e.to]);b().hidden=b().hidden.filter(n=>!related.includes(n));b().expanded=[...new Set([...(b().expanded||[]),...related])];visibleLimit+=40;changed();paintWorld();inspectNode(id);}
  document.addEventListener('pointercancel',()=>{drag=null;connecting=null;});
  document.addEventListener('contextmenu',event=>{
    const card=event.target.closest('[data-network-node]');if(!card||!active())return;event.preventDefault();contextNode=card.dataset.networkNode;document.getElementById('network-context-menu')?.remove();
    const menu=document.createElement('div');menu.id='network-context-menu';menu.className='network-context';menu.style.left=Math.min(event.clientX,innerWidth-215)+'px';menu.style.top=Math.min(event.clientY,innerHeight-290)+'px';
    menu.innerHTML=[['edit-node','Edit / annotate'],['duplicate-node','Duplicate as observation'],['pin','Pin / unpin'],['collapse','Collapse / expand branch'],['hide','Hide from board'],['research','Research further']].map(([action,title])=>`<button data-network-action="${action}" data-id="${e(contextNode)}">${title}</button>`).join('');document.body.append(menu);
  });
  document.addEventListener('keydown',event=>{
    if(!active()||event.target.matches('input,textarea,select'))return;
    if(event.code==='Space'){space=true;if(document.activeElement?.closest('#research-network'))event.preventDefault();}
    if(event.key==='Escape'){document.getElementById('network-context-menu')?.remove();connecting=null;drag=null;}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().catch(e=>feedback(e.message));}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();document.querySelector(`[data-network-action="${event.shiftKey?'redo':'undo'}"]`)?.click();}
    if((event.key==='Enter'||event.key===' ')&&event.target.dataset.networkNode){event.preventDefault();selection=new Set([event.target.dataset.networkNode]);inspectNode(event.target.dataset.networkNode);}
    if(event.key==='Enter'&&event.target.dataset.networkEdge)inspectEdge(event.target.dataset.networkEdge);
  });
  document.addEventListener('keyup',event=>{if(event.code==='Space')space=false;});
  document.addEventListener('click',event=>{
    const map=event.target.closest('#network-minimap');
    if(map&&active()){
      const location=new DOMPoint(event.clientX,event.clientY).matrixTransform(map.getScreenCTM().inverse()),canvas=document.getElementById('network-canvas');
      b().viewport.x=canvas.clientWidth/2-location.x*b().viewport.zoom;b().viewport.y=canvas.clientHeight/2-location.y*b().viewport.zoom;transform();changed();
    }
  });
  async function poll() {
    if(!active()||pending||document.hidden||drag||connecting||!api.connected)return;
    const busy=(detail.tasks||[]).some(task=>['Queued','Researching'].includes(task.status));
    const interval=busy?15000:60000;
    if(Date.now()-lastBoardPoll<interval)return;
    lastBoardPoll=Date.now();pending=true;const boardId=b().id;
    try{const result=await api.request('boards?id='+encodeURIComponent(boardId));if(!active()||b().id!==boardId)return;
      const graphChanged=result.graph.version!==detail.graph.version||result.graph.nodes.length!==detail.graph.nodes.length;
      if(!dirty&&!saving){const view=b().viewport;detail=result;detail.board.viewport=view;}else{detail.graph=result.graph;detail.tasks=result.tasks;}
      const tasks=document.getElementById('network-tasks');if(tasks)tasks.innerHTML=taskList();
      if(graphChanged){paintWorld();changed();feedback('New source-backed findings are available. Your layout and notes are preserved.');}
    }catch(error){feedback(error.message);}finally{pending=false;}
  }
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  window.addEventListener('crawler:server-state',()=>{
    const boardId=new URLSearchParams(location.search).get('board');
    if(api.connected&&boardId&&!detail&&!pending){pending=true;openBoard(boardId).catch(e=>{const target=document.getElementById('start-feedback');if(target)target.textContent=e.message;}).finally(()=>{pending=false;history.replaceState(null,'',location.pathname);});}
  });
  setInterval(poll,10000);
  window.CrawlerNetwork={attach,openBoard,save,renderPanels,get detail(){return detail;},get dirty(){return dirty;}};
})();

