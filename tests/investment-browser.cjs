/* Offline real-browser coverage for autonomous asset research and portfolios. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const REQUIRED_SECTIONS = ['Identity', 'Market performance', 'Financial health', 'Growth', 'Valuation', 'Market position', 'Economic exposure', 'Political exposure', 'Recent developments', 'Positive indicators', 'Negative indicators', 'Research conclusion', 'Monitoring criteria', 'Source history'];

(async () => {
  const child = spawn('python', [path.join(__dirname, 'investment_fixture.py')], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let logs = '', browser;
  child.stderr.on('data', chunk => { logs += chunk; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  try {
    const fixture = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Investment fixture did not start: ' + logs)), 60000);
      child.stdout.on('data', chunk => {
        output += chunk;
        if (output.includes('\n')) {
          clearTimeout(timer);
          try { resolve(JSON.parse(output.split('\n')[0])); } catch (error) { reject(error); }
        }
      });
      child.once('exit', code => { clearTimeout(timer); reject(new Error('Investment fixture exited: ' + code + ' ' + logs)); });
      child.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const base = 'http://127.0.0.1:' + fixture.port;
    browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-proxy-server'] });
    const context = await browser.newContext({ viewport: { width: 1500, height: 1050 } });
    await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
    await context.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/CRAWLER/', { waitUntil: 'domcontentloaded' });
    await page.locator('#open-workspace').click();
    await page.waitForFunction(() => window.CrawlerServer?.connected);
    await page.waitForSelector('#asset-research .asset-research-card');
    assert.equal(await page.locator('.rail-link').count(), 3, 'Asset research must retain the three main destinations');
    assert.equal(await page.locator('#asset-research .asset-research-card').count(), 2);
    assert.match(await page.locator('#asset-research').innerText(), /source-backed profiles/);

    // A single overview-card click opens all required profile sections.
    await page.locator('#asset-research [data-asset-profile="' + fixture.equityId + '"]').click();
    await page.waitForSelector('#asset-profile-dialog[open]');
    assert.match(await page.locator('#asset-dialog-title').innerText(), /Fixture Equity Laboratory/);
    const headings = await page.locator('#asset-profile-content > .profile-section > summary').allTextContents();
    for (const name of REQUIRED_SECTIONS) assert.ok(headings.some(text => text === name || text.startsWith(name + ' ·')), 'Missing dossier section: ' + name);
    assert.ok(headings.length >= 15, 'Fourteen dossier sections plus qualification risks must be available');
    assert.match(await page.locator('.profile-summary').innerText(), /monitoring/i);
    const market = page.locator('#asset-profile-content > .profile-section').filter({ has: page.locator('summary', { hasText: /^Market performance$/ }) });
    assert.match(await market.locator('.profile-measure strong').first().innerText(), /150/);
    assert.ok(await page.locator('#profile-revision option').count() >= 3, 'Revision selector must retain both assessments');
    await page.locator('#profile-revision').selectOption(String(fixture.firstRevisionAt));
    await page.waitForFunction(() => document.querySelector('.profile-change').textContent.includes('Initial profile created'));
    assert.match(await market.locator('.profile-measure strong').first().innerText(), /139/);
    await page.locator('#profile-revision').selectOption('');
    await page.waitForFunction(() => document.querySelector('.profile-change').textContent.includes('Underlying evidence'));
    assert.match(await market.locator('.profile-measure strong').first().innerText(), /150/);
    await page.locator('#close-asset-profile').click();

    // Cross-market reports use the same evidence dialog, without another tab.
    await page.locator('.cross-market-reports > summary').click();
    await page.locator('[data-research-report]').first().click();
    await page.waitForSelector('#report-revision');
    assert.match(await page.locator('#asset-profile-content').innerText(), /What happened\?/);
    assert.match(await page.locator('#asset-profile-content').innerText(), /What remains uncertain\?/);
    const reportOptions = await page.locator('#report-revision option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    assert.ok(reportOptions.length >= 2, 'Cross-market report revisions must be retained');
    await page.locator('#report-revision').selectOption(reportOptions[reportOptions.length - 1]);
    await page.waitForFunction(() => document.querySelector('#asset-profile-content').textContent.includes('Cross-market report v1'));
    await page.locator('#report-revision').selectOption('');
    await page.waitForFunction(() => !document.querySelector('#asset-profile-content').textContent.includes('Cross-market report v1'));
    await page.locator('#close-asset-profile').click();

    await page.locator('#open-portfolios').click();
    await page.waitForSelector('#watch-portfolios .portfolio-filters');
    assert.equal(await page.locator('[data-portfolio-theme]').count(), 7, 'All themes and six thematic controls must be visible');
    for (const theme of ['growth', 'policy', 'macro', 'activity', 'digital', 'research']) {
      await page.locator('[data-portfolio-theme="' + theme + '"]').click();
      assert.equal(await page.locator('#watch-portfolios .portfolio-group').count(), 1);
      assert.equal(await page.locator('#watch-portfolios .portfolio-group[open]').count(), 1);
      assert.ok(await page.locator('#watch-portfolios .portfolio-group .asset-research-card').count() > 0, theme + ' must contain its evidence-qualified fixture');
    }
    assert.match(await page.locator('#watch-portfolios').innerText(), /no investment weights, targets, or expected returns/i);
    await page.locator('[data-portfolio-theme="digital"]').click();
    await page.locator('#watch-portfolios [data-asset-profile="' + fixture.cryptoId + '"]').click();
    await page.waitForSelector('#asset-profile-dialog[open]');
    assert.match(await page.locator('#asset-dialog-title').innerText(), /Fixture Digital Token/);
    const rawProvenance = page.locator('#asset-profile-content .profile-measure').filter({ hasText: 'nominal price' }).first();
    await rawProvenance.locator('details > summary').first().click();
    assert.match(await rawProvenance.innerText(), /unadjusted provider crypto|nominal price/i);
    await page.locator('#close-asset-profile').click();

    await page.locator('[data-destination="operations"]').click();
    await page.locator('#autonomous-controls > details').filter({ has: page.locator('summary', { hasText: /^Monitoring rules & thresholds$/ }) }).locator('summary').first().click();
    await page.locator('#investment-rules-form [name=observationDays]').fill('9');
    await page.locator('#investment-rules-form [name=priceAnomalyPercent]').fill('11.5');
    await page.locator('#investment-rules-form button[type=submit], #investment-rules-form button').last().click();
    await page.waitForFunction(async () => (await fetch('/api/investment').then(response => response.json())).rules.observationDays === 9);
    const savedRules = await page.evaluate(async () => (await fetch('/api/investment').then(response => response.json())).rules);
    assert.equal(savedRules.priceAnomalyPercent, 11.5);

    await page.locator('#configure-connector').click();
    const kinds = await page.locator('#connector-tool-form [name=kind] option').allTextContents();
    for (const kind of ['sec', 'coingecko_asset', 'fred_vintages']) assert.ok(kinds.includes(kind), 'Missing financial connector type: ' + kind);
    await page.locator('#close-tools').click();
    const providers = page.locator('#autonomous-controls > details').filter({ has: page.locator('summary', { hasText: /^Financial providers$/ }) });
    await providers.locator('summary').first().click();
    for (const [kind, id] of [['sec', 'sec-discovery'], ['crypto', 'coingecko'], ['fred', 'fred']]) {
      await page.locator('[data-enable-provider="' + kind + '"]').click();
      await page.waitForFunction(sourceId => window.CrawlerServer.sources.some(source => source.id === sourceId && source.enabled), id);
    }
    assert.equal((await page.evaluate(() => window.CrawlerServer.sources.filter(source => ['sec', 'coingecko', 'fred_vintages'].includes(source.kind)))).length, 3);

    // Exercise the mobile page and dialog independently of desktop screenshots.
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'System controls must fit mobile width');
    await page.locator('[data-destination="overview"]').click();
    await page.locator('#asset-research [data-asset-profile="' + fixture.equityId + '"]').click();
    await page.waitForSelector('#asset-profile-dialog[open]');
    assert.ok(await page.evaluate(() => { const dialog = document.querySelector('#asset-profile-dialog'); return dialog.getBoundingClientRect().width <= innerWidth && dialog.scrollWidth <= dialog.clientWidth + 1; }), 'Asset profile must fit mobile width');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-investment-mobile.png'), fullPage: true });
    await page.locator('#close-asset-profile').click();
    await page.locator('[data-destination="watchlist"]').click();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Portfolio controls must fit mobile width');
    await page.setViewportSize({ width: 1500, height: 1050 });
    await page.locator('[data-destination="overview"]').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-investment-desktop.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Investment browser integration passed: asset cards, fourteen-section profiles, historical revisions, cross-market reports, six portfolio themes, rule persistence, provider controls, connector types, and mobile layout.');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null && !child.killed) {
      child.stdin.end('stop\n');
      const code = await Promise.race([exited, new Promise(resolve => setTimeout(() => resolve('timeout'), 5000))]);
      if (code === 'timeout') child.kill();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
