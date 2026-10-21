/* Run with PLAYWRIGHT_MODULE pointing to an existing playwright-core installation. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
(async () => {
  const root = path.resolve(__dirname, '../..');
  const server = http.createServer((request, response) => {
    const filename = path.resolve(root, '.' + new URL(request.url, 'http://localhost').pathname);
    if (!filename.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
    fs.readFile(filename, (error, content) => {
      if (error) { response.writeHead(404).end(); return; }
      response.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[path.extname(filename)] || 'application/octet-stream');
      response.end(content);
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const baseURL = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-proxy-server'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
    await context.route('**/*', route => route.request().url().startsWith(baseURL + '/') ? route.continue() : route.abort());
    await context.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    let localRequests = 0;
    page.on('request', request => { if (request.url().startsWith(baseURL)) localRequests++; });
    await page.goto(baseURL + '/CRAWLER/index.html', { waitUntil: 'domcontentloaded' }).catch(error => { throw new Error(error.message + '\nLocal requests: ' + localRequests + '\nScript errors: ' + JSON.stringify(errors)); });
    console.log('Loaded crawler interface.');
    await page.locator('#open-workspace').click();
    await page.waitForSelector('#signal-list .research-empty');
    assert.equal(await page.locator('.rail-link').count(), 3);
    assert.equal(await page.locator('#tabs').isVisible(), false);
    await page.evaluate(() => {
      const now = Date.now();
      const fixtures = [
        { id: 'qa-one', title: 'Semiconductor export legislation changes manufacturing supply chain compliance requirements today audit impact', source: 'QA Primary Office', tier: 'primary', syms: ['NVDA'] },
        { id: 'qa-two', title: 'Semiconductor export legislation changes manufacturing supply chain compliance requirements today regional implementation', source: 'QA Independent Reporter', tier: 'major', syms: ['NVDA'] },
        { id: 'qa-three', title: 'Central bank publishes inflation employment economic statistics review', source: 'QA Statistical Office', tier: 'primary', syms: [] },
        { id: 'qa-injection', title: '<img src=x onerror="window.injectionExecuted=true"> Cryptocurrency token rumor spreads across social campaign', source: 'QA Community', tier: 'social', syms: ['BTC'] }
      ];
      for (const item of fixtures) addPost({ id: item.id, title: item.title, text: item.title, sub: item.source, tier: item.tier, syms: item.syms, ts: now - 60000, src: 'News', outlet: true, language: 'en', url: 'https://example.test/' + item.id });
      renderAll();
    });
    await page.waitForSelector('.signal-card');
    assert.equal(await page.locator('.signal-card').count(), 3);
    assert.equal(await page.evaluate(() => window.injectionExecuted), undefined);
    await page.getByRole('button', { name: /Semiconductor export legislation changes manufacturing supply chain compliance requirements today audit impact/, exact: true }).first().click();
    await page.locator('#research-detail [data-save]').click();
    await page.locator('[data-detail-kind=notes] > summary').click();
    await page.locator('#note-form textarea').fill('Review the official implementation timetable.');
    await page.locator('#note-form button').click();
    await page.locator('#review-signal').click();
    await page.locator('#claim-form [name=text]').fill('The agency published a semiconductor proposal.');
    await page.locator('#claim-form [name=status]').selectOption('Verified');
    await page.locator('#claim-form [name=rationale]').fill('Direct record reviewed for this specific statement.');
    await page.locator('#claim-form button[type=submit]').click();
    assert.match(await page.locator('#claim-form .form-feedback').innerText(), /supporting record/);
    await page.locator('#claim-form [data-evidence]').first().selectOption('supports');
    await page.locator('#claim-form [name=directEvidence]').check();
    await page.locator('#claim-form button[type=submit]').click();
    await page.waitForSelector('.reviewed-claim .status-verified');
    await page.locator('#research-detail summary').filter({ hasText: /^Record a conditional scenario$/ }).click();
    await page.locator('#forecast-form [name=statement]').fill('An official implementation timetable will be published.');
    await page.locator('#forecast-form [name=assumptions]').fill('The agency proceeds with its review. A withdrawal would invalidate this scenario.');
    await page.locator('#forecast-form [name=dueDate]').fill(new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10));
    await page.locator('#forecast-form button').click();
    assert.match(await page.locator('#forecast-form .form-feedback').innerText(), /Saved/);
    await page.locator('[data-destination=watchlist]').click();
    assert.equal(await page.locator('#workspace-saved .workspace-item').count(), 1);
    assert.match(await page.locator('#workspace-saved').innerText(), /official implementation timetable/);
    await page.locator('#alert-form [name=query]').fill('semiconductor');
    await page.locator('#alert-form [name=minMomentum]').fill('0');
    await page.locator('#alert-form button').click();
    assert.match(await page.locator('#workspace-alerts').innerText(), /1 current match/);
    await page.locator('.outcome-form [name=outcome]').selectOption('Inconclusive');
    await page.locator('.outcome-form [name=resolution]').fill('No implementation record is available in the collection. Reference https://example.test/qa-one.');
    await page.locator('.outcome-form button').click();
    assert.match(await page.locator('#workspace-forecasts').innerText(), /Inconclusive/i);
    const downloadWait = page.waitForEvent('download'); await page.locator('#export-research').click(); const download = await downloadWait;
    assert.match(download.suggestedFilename(), /trend-crawler-research/);
    await page.locator('[data-destination=overview]').click();
    await page.locator('#research-query').fill('What semiconductor developments should I watch?');
    await page.locator('#research-question button[type=submit]').click();
    assert.ok(await page.locator('.chat-result').count() > 0);
    await page.locator('[data-destination=operations]').click();
    assert.ok(await page.locator('#registry-rows tr').count() > 50);
    await page.locator('#browser-source-registration > summary').click();
    await page.locator('#source-form [name=name]').fill('QA Custom Feed');
    await page.locator('#source-form [name=url]').fill('https://example.test/custom-feed.xml');
    await page.locator('#source-form [name=permissions]').fill('Fixture source. Polling remains disabled.');
    await page.locator('#source-form button').click();
    assert.match(await page.locator('#registry-rows').innerText(), /QA Custom Feed/);
    assert.equal(await page.evaluate(() => window.CrawlerIntelligence.state.sources[0].enabled), false);
    await page.locator('[data-destination=overview]').click();
    await page.locator('#i-category').selectOption('Economics');
    assert.equal(await page.locator('.signal-card').count(), 1);
    await page.locator('#i-category').selectOption('');
    const imagePath = path.join(process.env.TEMP || '.', 'crawler-intelligence-desktop.png');
    await page.locator('.signal-title').first().click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: imagePath, fullPage: true });
    await page.reload();
    await page.locator('#open-workspace').click();
    await page.waitForFunction(() => window.CrawlerIntelligence?.archiveLoaded && window.CrawlerIntelligence.documents.size >= 4);
    await page.locator('[data-destination=watchlist]').click();
    assert.equal(await page.locator('#workspace-saved .workspace-item').count(), 1);
    assert.match(await page.locator('#workspace-saved').innerText(), /implementation timetable/);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-destination=overview]').click();
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-intelligence-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile layout must not overflow the viewport');
    await page.evaluate(() => { addPost({ id: 'qa-price', src: 'News', sub: 'QA Market', ts: Date.now(), text: 'NVDA earnings market update', syms: ['NVDA'], url: 'https://example.test/qa-price' }); quotes.set('NVDA', { price: 123.45, chg: 1, t: Date.now() - 3600000 }); lastBuild = 0; renderAll(); });
    assert.match(await page.locator('#rows [data-s=NVDA]').innerText(), /Quote unavailable \/ stale/);
    await page.evaluate(() => { quotes.set('NVDA', { price: 123.45, chg: 1, t: Date.now(), marketAt: Date.now() }); lastBuild = 0; renderAll(); });
    assert.match(await page.locator('#rows [data-s=NVDA]').innerText(), /123\.45/);
    await page.locator('#rows [data-s=NVDA]').click();
    assert.equal(await page.locator('#detail').isVisible(), true);
    assert.equal(await page.locator('#research-detail').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log('Browser smoke passed: evidence gates, notes, watchlist, monitors, scenarios and outcomes, research, filters, custom-source registration, export, persistence, injection escaping, mobile layout, and legacy market view.');
    console.log('Desktop screenshot: ' + imagePath);
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
