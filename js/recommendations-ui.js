/* Figures come from the server calculator. This view never creates a return. */
(() => {
  'use strict';
  const api = window.CrawlerServer;
  let busy=false, lastBoard='', lastAt=0, current=null, nextAttemptAt=0, failures=0, wasConnected=api.connected;
  const e = value => esc(String(value ?? ''));
  const pct = value => typeof value==='number' && Number.isFinite(value) ? value.toFixed(2)+'%' : 'Unavailable';
  const date = value => value ? new Date(value).toLocaleString() : 'Unavailable';
  const evidence = rows => rows.map(r=>`<a href="${e(safeURL(r.url))}" target="_blank" rel="noopener noreferrer">${e(r.documentId)} · v${e(r.version)}</a><blockquote>${e(r.quote)}</blockquote>`).join('');
  function card(row) {
    if(row.expiresAt && Date.now()>=row.expiresAt) row={...row,status:"Expired — refresh required",potentialReturn:null,blockers:[...row.blockers,"The source price exceeded its freshness window."]};
    const analysis=row.analysis, range=row.potentialReturn, validation=analysis.validation;
    const historyRange=analysis.forecast;
    return `<article class="recommendation-card ${range?'eligible':''}" data-recommendation-asset="${e(row.assetId)}">
      <div class="recommendation-card-heading"><div><span class="recommendation-kicker">${e(row.assetClass)}</span><h3>${e(row.ticker || row.name)}</h3><p>${e(row.name)}</p></div><strong class="recommendation-state">${e(row.status)}</strong></div>
      <p>${e(row.timing)}</p>
      <dl class="recommendation-numbers"><div><dt>Latest source price</dt><dd>${row.market?e(row.market.currency)+' '+e(row.market.value):'Unavailable'}</dd></div><div><dt>Holding horizon</dt><dd>${e(row.holdingHorizonSessions)} source sessions</dd></div><div><dt>Conditional median estimate</dt><dd>${pct(range?.medianPercent)}</dd></div><div><dt>Historical 10th–90th percentile</dt><dd>${range?pct(range.p10Percent)+' to '+pct(range.p90Percent):'Withheld'}</dd></div></dl>
      <p class="recommendation-small">Market value observed ${date(row.market?.observedAt)} · daily model session ${date(analysis.latestPrice?.observedAt)} · signal expires ${date(row.expiresAt)}. Refresh before using an entry signal. Estimates are hypothetical; the range is not a guaranteed or calibrated prediction interval.</p>
      ${row.blockers.length?`<details open><summary>What must change before entry?</summary><ul>${row.blockers.map(b=>`<li>${e(b)}</li>`).join('')}</ul></details>`:''}
      <details><summary>Evidence, calculations & validation</summary>
        <p>${e(analysis.method)}</p><p>${e(row.unmodeledContext)}</p>
        <dl class="recommendation-numbers"><div><dt>Comparable history</dt><dd>${e(analysis.usedHistorySessions)} sessions</dd></div><div><dt>Point-in-time samples</dt><dd>${e(analysis.pointInTimeSamples || 0)}</dd></div><div><dt>Validation outcomes</dt><dd>${e(validation?.samples || 0)}</dd></div><div><dt>Validated signal / loss cases</dt><dd>${e(validation?.signalSamples || 0)} / ${e(validation?.signalLosses || 0)}</dd></div><div><dt>Model / baseline error</dt><dd>${pct(validation?.meanAbsoluteErrorPercent)} / ${pct(validation?.baselineMeanAbsoluteErrorPercent)}</dd></div><div><dt>Worst held-out signal return</dt><dd>${pct(validation?.worstSignalReturnPercent)}</dd></div></dl>
        ${historyRange && !range?`<p>Exploratory analogue median: ${pct(historyRange.medianPercent)}; historical range ${pct(historyRange.p10Percent)} to ${pct(historyRange.p90Percent)}. This is withheld as an investment recommendation because the gates above have not cleared.</p>`:''}
        <p>Return basis: ${e(analysis.returnBasis)}. Round-trip cost assumption: ${analysis.roundTripCostBps===null?'not supplied':e(analysis.roundTripCostBps)+' bps'}. Costs are user inputs, not observed facts.</p>
        <p>Momentum: ${pct(analysis.features?.momentumPercent)} · daily log-return volatility: ${pct(analysis.features?.dailyLogReturnVolatilityPercent)}.</p>
        <h4>Reported financial / market context</h4><p>Original measurements below are context; the model does not invent a return coefficient for them.</p>${row.contextObservations?.length?`<div class="recommendation-context"><table><thead><tr><th>Measurement</th><th>Source value</th><th>Period / observed</th></tr></thead><tbody>${row.contextObservations.map(r=>`<tr><td><a href="${e(safeURL(r.sourceUrl))}" target="_blank" rel="noopener noreferrer">${e(r.metric)}</a></td><td>${e(r.value)} ${e(r.unit || r.currency)}</td><td>${e(r.periodEnd || date(r.observedAt))}</td></tr>`).join('')}</tbody></table></div>`:'<p>No further collected measurements for this asset.</p>'}<h4>Topic connection</h4><p>${row.topicEvidenceCount ?? row.topicEvidence.length} source link(s); preview below. The export contains the full evidence.</p>${evidence(row.topicEvidence) || '<p>No current supporting quote.</p>'}
        <h4>Limits</h4><ul>${analysis.limitations.map(v=>`<li>${e(v)}</li>`).join('')}</ul>
        <p>${e(analysis.excludedAvailabilityOrGaps || 0)} candidate windows excluded for availability or gaps. ${e(analysis.excludedOlderSessions || 0)} older sessions outside the declared model window.</p>
      </details></article>`;
  }
  function render(value) {
    const host=document.getElementById('board-recommendations');if(!host)return;
    const open=[...host.querySelectorAll('details[open]')].map(d=>d.dataset.section).filter(Boolean);
    host.innerHTML=`<div class="recommendation-heading"><div><span class="recommendation-kicker">FROM TOPIC TO MARKET</span><h2>Investment research</h2><p>What is supported, when an entry signal qualifies, and the historical outcomes behind it.</p></div><button id="refresh-recommendations">Refresh analysis</button><button id="export-recommendations">Export evidence</button></div>
      <div id="recommendation-progress">${window.CrawlerActivity?.progress(value.progress || {percent:100,stage:"Current research assessment complete"},"Recommendation assessment progress") || ""}</div><p class="recommendation-status" role="status">${e(value.assets.filter(row=>row.status==='Eligible entry signal' && row.expiresAt>Date.now()).length)} eligible entry signal(s) · revision ${e(value.revision)} · assessed ${date(value.asOf)}</p>
      <p class="recommendation-small">${e(value.coverage.storedDocumentsScreened)} stored documents screened · ${e(value.coverage.relevantDocuments)} relevant records · ${e(value.coverage.branchesIncluded)} research branches · ${e(value.coverage.candidateAssets)} resolved candidates. Displaying ${value.assets.length} of ${value.assetCount ?? value.assets.length}; export includes all candidates.</p>
      <div class="recommendation-grid">${value.assets.map(card).join('') || '<div class="recommendation-empty"><h3>No supported asset candidates yet</h3><p>Continue topic research to identify publicly traded stocks or crypto assets with provider-verified identities and source citations. Stock return analysis requires an explicit daily price connector; SEC filings alone do not supply market prices.</p></div>'}</div>
      <details data-section="changes"><summary>What changed?</summary><ul>${value.whatChanged.map(v=>`<li>${e(v)}</li>`).join('')}</ul></details>
      <details data-section="method"><summary>Coverage & method</summary><p>${e(value.method)}</p><p>${e(value.coverage.scope)}</p><ul>${value.limitations.map(v=>`<li>${e(v)}</li>`).join('')}</ul><p>Model ${e(value.modelVersion)}. Source text controls relevance and evidence gates. No unsupported numerical effect is assigned to a news story.</p><p>${value.sourceManifestCount ?? value.sourceManifest.length} source version(s) are included in the evidence export.</p></details>
      ${api.session?.ownerAuthorized?`<details data-section="settings"><summary>Research cost assumptions</summary><form id="recommendation-settings"><label>Estimated total fees + slippage for buying and selling, basis points<input name="roundTripCostBps" type="number" min="0" max="1000" step="0.1" value="${e(value.settings.roundTripCostBps ?? '')}" required></label><p>Applies to every asset in this first model version. The recommendation is withheld until this assumption is explicitly provided. 100 bps = 1%.</p><button type="submit">Save assumptions</button></form></details>`:''}`;
    host.querySelectorAll('details[data-section]').forEach(d=>{d.open=open.includes(d.dataset.section);});
  }
  async function refresh(force=false) {
    const boardId=window.CrawlerNetwork?.detail?.board?.id;
    if(!boardId || !api.connected || document.hidden || document.body.dataset.experience!=='topic' || busy)return;
    if(Date.now()<nextAttemptAt || api.busy)return;
    if(!force && boardId===lastBoard && Date.now()-lastAt<10000)return;
    busy=true;lastBoard=boardId;lastAt=Date.now();
    try {
      const value=await api.request('board-recommendations?boardId='+encodeURIComponent(boardId));
      if(window.CrawlerNetwork?.detail?.board?.id!==boardId)return;
      failures=0;nextAttemptAt=Date.now()+Math.max(10000,value.retryAfterMs || 0);
      if(value.refreshing) {
        current=null;
        if(value.coverage){render(value);const p=document.getElementById('board-recommendations')?.querySelector('.recommendation-status');if(p)p.textContent=value.message;}
        else {const host=document.getElementById('board-recommendations');if(host)host.innerHTML='<div class="recommendation-heading"><div><span class="recommendation-kicker">FROM TOPIC TO MARKET</span><h2>Assessing investment research</h2></div></div><div id="recommendation-progress">'+(window.CrawlerActivity?.progress(value.progress,'Recommendation assessment progress') || '<p>'+e(value.message)+'</p>')+'</div>'; }
        return;
      }
      current=value;render(value);
    } catch(error) {
      current=null;failures++;nextAttemptAt=Date.now()+Math.max(error.retryAfterMs || 0,Math.min(60000,10000*2**Math.min(failures,3)));
      // Clear old entry signals on transport failure so stale advice cannot remain actionable.
      const host=document.getElementById('board-recommendations');if(host){host.replaceChildren();const p=document.createElement('p');p.className='recommendation-status';p.textContent=error.code==='SERVER_BUSY'?'The research server is busy. Recommendation updates will resume automatically.':error.code==='REQUEST_TIMEOUT'?'Recommendation status took too long to respond. Background research may still be running; retrying automatically.':'Recommendation unavailable: '+error.message+'. Retrying automatically.';host.append(p);}
    } finally {busy=false;}
  }
  window.addEventListener('crawler:board-ready',()=>{if(current && current.boardId===window.CrawlerNetwork?.detail?.board?.id)render(current);refresh();});
  window.addEventListener('crawler:server-state',()=>{const reconnected=api.connected&&!wasConnected;wasConnected=api.connected;if(reconnected){nextAttemptAt=0;refresh(true);}else if(!api.connected){current=null;const host=document.getElementById('board-recommendations');if(host)host.textContent='Research connection interrupted. Entry recommendations are unavailable until the server reconnects.';}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(true);});
  document.addEventListener('click',async event=>{
    if(event.target.closest('#refresh-recommendations')){nextAttemptAt=0;refresh(true);}
    if(event.target.closest('#export-recommendations') && current){const detail=await api.request('board-recommendations?boardId='+encodeURIComponent(current.boardId)+'&full=1').catch(()=>null);if(!detail || detail.refreshing)return;const url=URL.createObjectURL(new Blob([JSON.stringify(detail,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='topic-investment-research.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  });
  document.addEventListener('submit',async event=>{
    if(event.target.id!=='recommendation-settings')return;event.preventDefault();
    const button=event.target.querySelector('button');button.disabled=true;
    try {await api.request('recommendations/settings',{roundTripCostBps:Number(event.target.elements.roundTripCostBps.value)});nextAttemptAt=0;await refresh(true);}
    catch(error){alert(error.message);}finally{if(button.isConnected)button.disabled=false;}
  });
  setInterval(()=>refresh(),10000);
})();

