/* Source-backed topic research must work before an instrument qualifies. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function until(check, message, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await check();
    if (result) return result;
    await pause(150);
  }
  throw new Error(message);
}

(async () => {
  const child = spawn('python', [path.join(__dirname, 'search_fixture.py'), '--market-research'], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let logs = '', browser;
  child.stderr.on('data', chunk => { logs += chunk; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  try {
    const fixture = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Market research fixture did not start: ' + logs)), 60000);
      child.stdout.on('data', chunk => {
        output += chunk;
        if (output.includes('\n')) {
          clearTimeout(timer);
          try { resolve(JSON.parse(output.split('\n')[0])); } catch (error) { reject(error); }
        }
      });
      child.once('exit', code => { clearTimeout(timer); reject(new Error('Market research fixture exited: ' + code + ' ' + logs)); });
      child.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const base = 'http://127.0.0.1:' + fixture.port;
    const get = route => fetch(base + '/api/' + route).then(response => response.json());
    const configuration = await get('ai/settings');
    assert.equal(configuration.configured, true);
    assert.equal(configuration.lastTest?.ok, true);
    assert.equal(configuration.automaticAnalysis, false, 'The fixture must exercise explicit research with background AI disabled');
    browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-proxy-server'] });
    const context = await browser.newContext({ viewport: { width: 1500, height: 1050 } });
    await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
    await context.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const page = await context.newPage(), errors = [];
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/CRAWLER/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.CrawlerServer?.connected);
    await page.locator('#start-query').fill(fixture.marketQuery);
    await page.locator('#start-search-form button[type=submit]').click();
    const topic = await until(async () => {
      const result = await get('topics');
      return result.topics?.find(item => item.query === fixture.marketQuery && item.lastRunAt);
    }, 'A manual source research search did not complete');
    assert.equal(topic.state, 'Monitoring', 'Matching source records must enable monitoring without investment qualification');
    assert.equal(topic.entries.length, 0, 'The fixture must not invent qualified assets for subjects without identities or market data');
    assert.equal(topic.qualifiedCount, 0);
    assert.equal(topic.marketResearch?.method, 'OpenAI source research', 'The saved model must perform manual source research even when background AI is disabled');
    assert.equal(topic.marketResearch.model, 'fixture-research-model');
    assert.ok(topic.marketResearch.summary.length && topic.marketResearch.drivers.length && topic.marketResearch.risks.length, 'Research must include a summary, drivers, and risks');
    const subjects = topic.watchSubjects || topic.marketResearch.subjects;
    assert.deepEqual(new Set(subjects.map(subject => subject.kind)), new Set(['company', 'market', 'financial_institution']));
    for (const subject of subjects) {
      assert.ok(subject.connection && subject.watchFor, 'A subject needs a documented connection and monitoring direction');
      assert.ok(subject.evidence.some(evidence => evidence.documentId === fixture.marketDocumentId && evidence.quote), 'Each subject must cite a retained source and exact quote');
    }
    await page.waitForFunction(() => document.querySelector('#topic-workspace .topic-state')?.textContent.includes('Monitoring'));
    await page.waitForSelector('#topic-watchlist .topic-subject');
    await page.getByRole('heading', { name: 'Market research', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Companies, markets & institutions', exact: true }).waitFor();
    const reportSection = page.locator('#topic-workspace section').filter({ has: page.getByRole('heading', { name: 'Market research', exact: true }) });
    assert.match(await reportSection.innerText(), /funding|financing/i);
    assert.match(await reportSection.innerText(), /driver/i);
    assert.match(await reportSection.innerText(), /risk/i);
    assert.ok(await reportSection.locator('a[href="https://fixture.example/regional-credit-report"]').count(), 'The market research report must link directly to its original evidence');
    const visibleText = await page.locator('#topic-workspace').innerText();
    for (const name of ['Fixture Manufacturers Ltd', 'regional credit markets', 'Fixture Regional Bank']) assert.ok(visibleText.includes(name), name + ' must be visible as a research subject');
    assert.match(await page.locator('.topic-state').innerText(), /monitoring/i);
    assert.ok(!visibleText.includes('No assets qualify for monitoring yet.'), 'Financial qualification must not replace a source-backed research report with a blocking empty state');
    assert.equal(await page.locator('#topic-workspace [data-asset-profile]').count(), 0, 'Research subjects must not masquerade as identified financial profiles');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-market-research-desktop.png'), fullPage: true });

    await page.locator('#refresh-topic').click();
    const refreshed = await until(async () => {
      const result = await get('topics?id=' + encodeURIComponent(topic.id));
      return result.lastRunAt > topic.lastRunAt && result.state === 'Monitoring' ? result : null;
    }, 'Manual refresh did not complete with background AI disabled');
    assert.equal(refreshed.marketResearch.method, 'OpenAI source research');
    assert.equal(refreshed.state, 'Monitoring');
    assert.equal((await get('ai/settings')).automaticAnalysis, false, 'A manual investigation must not silently enable paid background analysis');
    await page.waitForFunction(() => document.querySelector('#topic-workspace .topic-state')?.textContent.includes('Monitoring'));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'The report and source subjects must fit mobile width');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-market-research-mobile.png'), fullPage: true });

    // A rejected provider key must remain actionable when discovery yields no
    // original records and therefore no report can supply its own error banner.
    await page.route('**/api/topics?**', route => {
      if (new URL(route.request().url()).searchParams.get('id') !== topic.id) return route.continue();
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ...refreshed, state: 'Needs evidence', status: 'Needs evidence', marketResearch: null,
        watchSubjects: [], evidence: [], discoveryError: {
          errorCode: 'invalid_key', message: 'OpenAI rejected this API key. Check or replace the API key.',
        },
      }) });
    });
    await page.evaluate(id => window.CrawlerStart.openTopic(id), topic.id);
    const unavailableNotice = page.locator('#topic-workspace .topic-ai-notice');
    assert.ok(await unavailableNotice.isVisible(), 'A provider failure must be shown even when no source report exists');
    assert.match(await unavailableNotice.innerText(), /OpenAI rejected this API key\. Check or replace the API key\./);
    assert.ok(await unavailableNotice.locator('[data-openai-connect]').isVisible(), 'The empty-result error must offer OpenAI settings');
    assert.match(await unavailableNotice.locator('[data-openai-connect]').innerText(), /OpenAI settings/i);
    assert.deepEqual(errors, []);
    console.log('Market research browser passed: manual saved-AI research with background AI disabled, source-backed summary/drivers/risks, cited company/market/institution subjects, monitoring without qualified assets, explicit refresh, mobile layout, and actionable API failure without source records.');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null && !child.killed) {
      child.stdin.end('stop\n');
      const code = await Promise.race([exited, pause(5000).then(() => 'timeout')]);
      if (code === 'timeout') child.kill();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
