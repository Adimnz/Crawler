/* Regression coverage for loading feedback and slow provider connections. */
const { spawn } = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const KEY = 'sk-test-fixture-connection-secret';
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

(async () => {
  const child = spawn('python', [path.join(__dirname, 'search_fixture.py')], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let logs = '', browser;
  child.stderr.on('data', chunk => { logs += chunk; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  try {
    const fixture = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Loading fixture did not start: ' + logs)), 60000);
      child.stdout.on('data', chunk => {
        output += chunk;
        if (output.includes('\n')) {
          clearTimeout(timer);
          try { resolve(JSON.parse(output.split('\n')[0])); } catch (error) { reject(error); }
        }
      });
      child.once('exit', code => { clearTimeout(timer); reject(new Error('Loading fixture exited: ' + code + ' ' + logs)); });
      child.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const base = 'http://127.0.0.1:' + fixture.port;
    browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-proxy-server'] });
    const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const requests = [], errors = [], expensive = new Set(['/api/health', '/api/workspace', '/api/documents', '/api/operations', '/api/metrics', '/api/events', '/api/investment']);
    await context.route('**/*', async route => {
      const url = route.request().url();
      if (!url.startsWith(base + '/')) return route.abort();
      if (expensive.has(new URL(url).pathname)) await pause(8000);
      return route.continue().catch(() => {});
    });
    await context.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/api/')) requests.push({ path: url.pathname, method: request.method() }); });
    const initialAISettings = page.waitForResponse(base + '/api/ai/settings');
    const started = Date.now();
    await page.goto(base + '/CRAWLER/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.CrawlerServer?.connected);
    assert.ok(Date.now() - started < 5000, 'The search screen must connect without waiting for delayed archive or health requests');
    assert.ok(await page.locator('#start-query').isEnabled(), 'Search must be usable immediately after connection');
    await initialAISettings;
    await pause(300);
    assert.ok(requests.some(request => request.path === '/api/ready'), 'Startup must use the lightweight readiness endpoint');
    assert.deepEqual(requests.filter(request => expensive.has(request.path)), [], 'The default search screen must not hydrate the archive or dashboard');
    const initialSettings = requests.filter(request => request.path === '/api/ai/settings').length;
    assert.equal(initialSettings, 1, 'Startup must load AI settings once');
    // Crossing both browser polling intervals catches background request loops.
    await pause(11000);
    assert.equal(requests.filter(request => request.path === '/api/ai/settings').length, initialSettings, 'An idle landing screen must not repeatedly reload AI settings');
    assert.deepEqual(requests.filter(request => expensive.has(request.path)), [], 'An idle landing screen must keep archive synchronization paused');

    await page.locator('[data-openai-connect]:visible').first().click();
    await page.locator('#openai-connection-form [name=apiKey]').fill(KEY);
    await page.waitForSelector('#openai-connection-form [name=model] option[value="fixture-delayed-model"]', { state: 'attached' });
    await page.locator('#openai-connection-form [name=model]').selectOption('fixture-delayed-model');
    await page.locator('#openai-connection-form [name=automaticAnalysis]').uncheck();
    const connecting = page.waitForRequest(request => request.url() === base + '/api/ai/connect' && request.method() === 'POST');
    await page.locator('#openai-connection-form button[type=submit]').click();
    await connecting;
    await pause(150);
    assert.match(await page.locator('#openai-connection-feedback').innerText(), /verifying/i);
    const statusStarted = Date.now();
    const [settings, ready] = await Promise.all([
      fetch(base + '/api/ai/settings').then(response => response.json()),
      fetch(base + '/api/ready').then(response => response.json()),
    ]);
    assert.ok(Date.now() - statusStarted < 1000, 'Settings and readiness must stay responsive during a slow provider connection check');
    assert.equal(settings.configured, false, 'A pending provider check must not prematurely mark AI connected');
    assert.equal(ready.ready, true);
    await page.waitForSelector('#openai-connection-dialog', { state: 'hidden' });
    const verified = await fetch(base + '/api/ai/settings').then(response => response.json());
    assert.equal(verified.model, 'fixture-delayed-model');
    assert.equal(verified.lastTest?.ok, true);
    assert.equal(verified.automaticAnalysis, false);
    assert.match(await page.locator('.start-ai-button:visible').first().innerText(), /OpenAI connected/);

    // An HTML-only host can render the UI, but must offer the actual Python
    // origin instead of leaving the connection dialog indefinitely loading.
    const staticContext = await browser.newContext();
    await staticContext.route('**/*', route => {
      const url = route.request().url();
      if (!url.startsWith(base + '/')) return route.abort();
      if (new URL(url).pathname.startsWith('/api/')) return route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"No research API at this host"}' });
      return route.continue();
    });
    await staticContext.addInitScript(() => { window.WebSocket = class { close() {} }; });
    const staticPage = await staticContext.newPage();
    staticPage.on('pageerror', error => errors.push(error.message));
    await staticPage.goto(base + '/CRAWLER/', { waitUntil: 'domcontentloaded' });
    await staticPage.locator('[data-openai-connect]:visible').first().click();
    await staticPage.waitForSelector('#openai-connection-dialog[open]');
    assert.ok(await staticPage.locator('#open-server-app').isVisible(), 'An HTML-only host must link directly to the Python application');
    assert.equal(await staticPage.locator('#open-server-app').getAttribute('href'), 'http://127.0.0.1:8765/CRAWLER/');
    assert.ok(await staticPage.locator('#openai-connection-form button[type=submit]').isDisabled(), 'A missing research API cannot accept a provider connection');
    assert.match(await staticPage.locator('#openai-connection-feedback').innerText(), /Python app URL|research API/);
    await staticContext.close();
    assert.deepEqual(errors, []);
    console.log('Loading regression passed: fast readiness, no archive traffic or repeated settings on the idle search screen, responsive status during a delayed verified connection, and direct Python-origin recovery on an HTML-only host.');
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null && !child.killed) {
      child.stdin.end('stop\n');
      const code = await Promise.race([exited, pause(5000).then(() => 'timeout')]);
      if (code === 'timeout') child.kill();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
