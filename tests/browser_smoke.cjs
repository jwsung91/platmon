// Optional real Chromium check. Uses an already installed Playwright, never installs a dependency.
// PLATMON_PLAYWRIGHT=/path/to/playwright node tests/browser_smoke.cjs /path/to/chromium OUTPUT_DIR
const {chromium} = require(process.env.PLATMON_PLAYWRIGHT);
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = process.argv[3]; fs.mkdirSync(output, {recursive: true});
const bad = '<img src=x onerror="globalThis.injected=1">';
const snap = {platform: 'Linux', model: 'Fixture board', uptime: 60, power_mode: null, system: {},
  cpu: [{id: 0, usage: 1, freq: null}], gpu: null, memory: {total: 8e9, used: 2e9, swap_total: 0},
  disk: {total: 10e9, used: 5e9}, temperature: {[bad]: 40}, power: {[bad]: 2}, fans: [{name: bad, rpm: 0, percent: null}],
  network: {interfaces: [{name: bad, rx: {errors: 0, dropped: 0}, tx: {errors: 0, dropped: 0}, window_ms: 1234,
    rates: {rx_bytes_per_s: 1024, tx_bytes_per_s: 0, rx_packets_per_s: 1, tx_packets_per_s: 0}}]},
  disk_io: {disks: [{name: 'sda', in_flight: 0, rates: null, reason: 'warmup'}]},
  pressure: {resources: {cpu: {some: {avg10: 1.5}, full: null}}}};
const obs = {groups: {wifi: {state: 'ok', stale_after_ms: 15000,
  observation: {id: 1, data_age_ms: 14000, stale: false}, data: {interfaces: [
    {name: bad, connected: true, signal_dbm: -64, link_quality: 45}]}},
  storage: {state: 'ok', observation: {id: 1, data_age_ms: 1000, stale: false}, data: {filesystems: [
    {mount_points: [{path: '/long/' + 'mount'.repeat(40), read_only: true}], fstype: 'ext4', device: 'sda1',
      total_bytes: 4e9, used_bytes: 1e9, available_bytes: 3e9}], partitions: []}}}};
(async () => {
  const browser = await chromium.launch({executablePath: process.argv[2], headless: true});
  try {
    const page = await browser.newPage(); const errors = []; const counts = {};
    page.on('pageerror', e => errors.push(e.message));
    let mode = 'ok';
    await page.route('http://platmon.test/**', async route => {
      const url = new URL(route.request().url()); counts[url.pathname] = (counts[url.pathname] || 0) + 1;
      if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: fs.readFileSync('frontends/web/index.html', 'utf8')});
      if (url.pathname.startsWith('/assets/')) return route.fulfill({contentType: 'image/svg+xml', body: fs.readFileSync(path.join('frontends/web', url.pathname))});
      if (url.pathname === '/api/stats') {
        if (mode === 'timeout') return; // held until the browser's AbortController cancels
        return route.fulfill({status: mode === '503' ? 503 : 200, json: snap});
      }
      if (url.pathname === '/api/observations') return route.fulfill({json: obs});
      return route.fulfill({status: 404, json: {}});
    });
    for (const width of [1280, 390]) {
      await page.setViewportSize({width, height: 900}); await page.goto('http://platmon.test/');
      await page.waitForFunction(() => document.querySelector('#wifi').textContent.includes('-64 dBm'));
      await page.waitForTimeout(2200);
      assert((await page.locator('#wifi').innerText()).includes('(not current)'));
      assert((await page.locator('#net').innerText()).includes('window 1.234 s'));
      assert((await page.locator('#dio').innerText()).includes('in flight 0'));
      assert.equal(await page.locator('section img').count(), 0);
      assert(await page.locator('.brand img').evaluate(img => img.complete && img.naturalWidth > 0));
      assert.equal(await page.evaluate(() => !!globalThis.injected), false);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no horizontal overflow');
      await page.screenshot({path: path.join(output, `browser-${width}.png`), fullPage: true});
    }
    const before = await page.locator('*').count();
    for (let n = 0; n < 120; n++) await page.evaluate(() => tick());
    assert.equal(await page.locator('*').count(), before, 'repeated rendering does not append DOM nodes');
    mode = '503'; await page.evaluate(() => tick());
    assert((await page.locator('#err').innerText()).includes('No current data'));
    mode = 'timeout'; await page.evaluate(() => tick());
    assert((await page.locator('#err').innerText()).includes('No answer within 5 s'));
    mode = 'ok'; await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForFunction(() => !document.querySelector('#err').textContent);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'browser.json'), JSON.stringify({browser: await browser.version(),
      fixtures: true, widths: [1280, 390], repeat_renders: 120, dom_nodes: before, errors, requests: counts,
      visibility: 'synthetic visibilitychange in real Chromium', timeout: 'real 5 second deadline'}, null, 2));
    console.log('Chromium desktop/narrow, XSS, stale, repeat DOM, 503, timeout, tab-return event: passed');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
