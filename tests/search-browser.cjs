/* Offline real-browser coverage for the search-first research experience. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const QUERY = 'Fixture Equity Laboratory';
const KEY = 'sk-test-fixture-connection-secret';
async function until(check, message, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error(message);
}

(async () => {
  const child = spawn('python', [path.join(__dirname, 'search_fixture.py')], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let logs = '', browser;
  child.stderr.on('data', chunk => { logs += chunk; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  try {
    const fixture = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Search fixture did not start: ' + logs)), 60000);
      child.stdout.on('data', chunk => {
        output += chunk;
        if (output.includes('\n')) {
          clearTimeout(timer);
          try { resolve(JSON.parse(output.split('\n')[0])); } catch (error) { reject(error); }
        }
      });
      child.once('exit', code => { clearTimeout(timer); reject(new Error('Search fixture exited: ' + code + ' ' + logs)); });
      child.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const base = 'http://127.0.0.1:' + fixture.port;
    browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-proxy-server'] });
    const context = await browser.newContext({ viewport: { width: 1500, height: 1050 } });
    await context.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
    await context.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const page = await context.newPage(), errors = [], returnedSecrets = [];
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', async response => {
      if (response.url().startsWith(base + '/api/')) {
        const body = await response.text().catch(() => '');
        if (body.includes(KEY)) returnedSecrets.push(response.url());
      }
    });
    await page.goto(base + '/CRAWLER/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.CrawlerServer?.connected);
    assert.equal(await page.locator('body').getAttribute('data-experience'), 'start');
    assert.equal(await page.locator('#start-heading').innerText(), 'Where do I start');
    assert.ok(await page.locator('#start-query').isVisible(), 'Search must be immediately accessible');
    assert.equal(await page.locator('.app-rail').isVisible(), false, 'The default screen must hide dashboard navigation');
    assert.equal(await page.locator('.wrap').isVisible(), false, 'The default screen must hide the dashboard');
    assert.ok(await page.locator('#start-heading').evaluate(element => parseFloat(getComputedStyle(element).fontSize) >= 48 && Number(getComputedStyle(element).fontWeight) >= 650), 'The start question must be large and bold');
    assert.ok(await page.locator('#start-search-form').evaluate(element => Math.abs(element.getBoundingClientRect().left + element.getBoundingClientRect().width / 2 - innerWidth / 2) < 30), 'The search form must be centered');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-search-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'The default start screen must fit mobile width');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-search-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1500, height: 1050 });

    await page.locator('#start-query').fill(QUERY);
    await page.locator('#start-search-form button[type=submit]').click();
    await page.waitForFunction(() => document.body.dataset.experience === 'topic');
    await until(async () => {
      const result = await page.evaluate(() => fetch('/api/topics').then(response => response.json()));
      const rows = result.topics || result.portfolios || [];
      return rows.some(topic => topic.query === 'Fixture Equity Laboratory' && topic.lastRunAt);
    }, 'The topic worker did not complete initial research');
    const topic = await page.evaluate(async query => {
      const result = await fetch('/api/topics').then(response => response.json());
      return (result.topics || result.portfolios).find(item => item.query === query);
    }, QUERY);
    const detail = await page.evaluate(async id => fetch('/api/topics?id=' + encodeURIComponent(id)).then(response => response.json()), topic.id);
    const portfolio = detail.portfolio || detail.topic || detail;
    assert.ok(portfolio.entries.some(entry => entry.assetId === fixture.equityId), 'The matching qualified asset must be curated: ' + JSON.stringify({ state: portfolio.state, entries: portfolio.entries, candidates: portfolio.candidates }));
    assert.ok(!portfolio.entries.some(entry => entry.assetId === fixture.cryptoId), 'An unrelated qualified asset must not enter the topic portfolio');
    assert.ok(!portfolio.entries.some(entry => entry.assetId === fixture.staleId), 'Stale market data must withhold monitoring qualification');
    assert.ok((portfolio.candidates || []).some(entry => entry.assetId === fixture.staleId), 'A relevant stale asset must remain an investigation candidate');
    await page.waitForSelector('#topic-workspace [data-asset-profile="' + fixture.equityId + '"]');
    assert.match(await page.locator('#topic-workspace').innerText(), /stale|unavailable|investigation/i);
    assert.ok(await page.locator('#topic-workspace a[href="https://fixture.example/company-report"]').count(), 'Topic conclusions must expose original sources');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-topic-desktop.png'), fullPage: true });

    // A fresh visit starts with the same clean search screen; topic research is
    // kept on the server and can be reopened from its recent-topic shortcut.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.CrawlerServer?.connected);
    assert.equal(await page.locator('body').getAttribute('data-experience'), 'start');
    await page.locator('#recent-topics-button').click();
    await page.locator('[data-open-topic="' + topic.id + '"]').first().click();
    await page.waitForFunction(() => document.body.dataset.experience === 'topic');
    assert.match(await page.locator('#topic-workspace').innerText(), /Fixture Equity Laboratory/);

    // Connecting AI sends the key only to the local server. The fake network
    // verifies the server forwards it to the selected model's connection check.
    await page.locator('[data-openai-connect]:visible').first().click();
    await page.waitForSelector('#openai-connection-dialog[open]');
    assert.equal(await page.locator('#openai-connection-form [name=model]').evaluate(element => element.tagName), 'SELECT', 'Model selection must use a dropdown');
    await page.locator('#openai-connection-form [name=apiKey]').fill('sk-test-invalid-key');
    await page.waitForFunction(() => document.querySelector('#openai-model-status').textContent.includes('could not be loaded'));
    assert.equal((await fetch(base + '/api/ai/settings').then(response => response.json())).configured, false, 'Rejected API keys must not be marked connected');
    await page.locator('#openai-connection-form [name=apiKey]').fill(KEY);
    await page.waitForSelector('#openai-connection-form [name=model] option[value="fixture-research-model"]', { state: 'attached' });
    assert.equal(await page.locator('#openai-connection-form [name=model] option[value="text-embedding-3-small"]').count(), 0, 'Embedding models must not be offered as research models');
    await page.locator('#openai-connection-form [name=model]').selectOption('fixture-unsupported-model');
    await page.locator('#openai-connection-form button[type=submit]').click();
    await page.waitForFunction(() => !document.querySelector('#openai-connection-form button[type=submit]').disabled);
    assert.equal((await fetch(base + '/api/ai/settings').then(response => response.json())).configured, false, 'Unsupported models must not save an unverified connection');
    assert.ok(await page.locator('#openai-connection-dialog[open]').count(), 'A failed connection must keep settings available to correct');
    assert.match(await page.locator('#openai-connection-feedback').innerText(), /model|support|OpenAI/i);
    await page.locator('#openai-connection-form [name=model]').selectOption('fixture-research-model');
    await page.locator('#openai-connection-form [name=automaticAnalysis]').check();
    await page.locator('#openai-connection-form button[type=submit]').click();
    await until(async () => (await page.evaluate(() => fetch('/api/ai/settings').then(response => response.json()))).configured, 'OpenAI settings were not saved');
    const settings = await page.evaluate(() => fetch('/api/ai/settings').then(response => response.json()));
    assert.equal(settings.keyConfigured, true);
    assert.equal(settings.model, 'fixture-research-model');
    assert.equal(settings.automaticAnalysis, true);
    assert.ok(!JSON.stringify(settings).includes(KEY));
    await page.waitForSelector('#openai-connection-dialog', { state: 'hidden' });
    await page.locator('[data-openai-connect]:visible').first().click();
    await page.locator('#openai-connection-form [data-ai-test]').click();
    await until(async () => (await page.evaluate(() => fetch('/api/ai/settings').then(response => response.json()))).lastTest?.ok === true, 'The synthetic OpenAI connection check failed');
    assert.equal(await page.locator('#openai-connection-form [name=apiKey]').inputValue(), '', 'The submitted secret must be cleared');
    assert.equal(await page.evaluate(key => JSON.stringify(localStorage).includes(key) || JSON.stringify(sessionStorage).includes(key), KEY), false, 'Secrets must not enter browser storage');
    assert.deepEqual(returnedSecrets, [], 'No API response may return the provider key');
    await page.locator('#openai-connection-dialog [data-close-ai]').click();

    await page.locator('#new-topic-search').click();
    await page.waitForFunction(() => document.body.dataset.experience === 'start');
    await new Promise(resolve => setTimeout(resolve, 500));
    assert.equal(await page.locator('body').getAttribute('data-experience'), 'start', 'A background refresh must not reopen the topic after navigation');
    await page.locator('#open-workspace').click();
    await page.waitForFunction(() => document.body.dataset.experience === 'workspace');
    assert.ok(await page.locator('.app-rail').isVisible(), 'The full workspace remains directly accessible');
    assert.equal(await page.locator('.rail-link').count(), 3);
    await page.locator('#new-topic-search').click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('.app-rail').isVisible(), false);
    assert.ok(await page.locator('#start-query').isVisible());
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Search must fit a mobile viewport');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-search-mobile.png'), fullPage: true });
    await page.locator('#recent-topics-button').click();
    await page.locator('[data-open-topic="' + topic.id + '"]').first().click();
    await page.waitForFunction(() => document.body.dataset.experience === 'topic');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'The topic portfolio must fit mobile width');
    await page.screenshot({ path: path.join(process.env.TEMP || '.', 'crawler-topic-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Search browser integration passed: centered start, curated topic portfolio, evidence gates, persistent topics, account model dropdown, rejected keys and unsupported models, verified OpenAI connection without browser-stored secrets, workspace access, and mobile layout.');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null && !child.killed) {
      child.stdin.end('stop\n');
      const code = await Promise.race([exited, new Promise(resolve => setTimeout(() => resolve('timeout'), 5000))]);
      if (code === 'timeout') child.kill();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
