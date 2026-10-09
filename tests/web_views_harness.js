// View selection, bounded polling and hidden-page lifecycle with deterministic fixtures.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const code = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
let now = 0, nextTimer = 0, focused = '', failure = false;
const elements = {}, intervals = [], timers = new Map(), listeners = [], requests = [];
const el = id => elements[id] ||= {innerHTML: '', textContent: '', value: '', hidden: false, attrs: {}, handlers: {},
  setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, fn) { this.handlers[k] = fn; }, focus() { focused = id; }};
const stats = {model: 'Fixture', platform: 'Linux', uptime: 12, system: {}, power_mode: null,
  cpu: [{id: 0, usage: 20, freq: null}, {id: 1, usage: 40, freq: null}], gpu: null,
  memory: {used: 2e9, total: 8e9, swap_total: 0}, disk: {used: 5e9, total: 10e9},
  temperature: {'<b>hot</b>': 60, cool: 40}, power: {}, fans: [],
  network: {interfaces: [{name: 'lo', rx: {}, tx: {}, rates: {rx_bytes_per_s: 999999, tx_bytes_per_s: 0, rx_packets_per_s: 0, tx_packets_per_s: 0}},
    {name: 'eth0', rx: {}, tx: {}, rates: {rx_bytes_per_s: 1024, tx_bytes_per_s: 2048, rx_packets_per_s: 1, tx_packets_per_s: 2}}]}};
const history = {retention_s: 600, series: {'cpu/0/usage': [[1, 2000, 20]], 'memory/used_bytes': [[1, 1000, 2e9]],
  'network/ns/1/eth0/rx_bytes_per_s': [[1, 3000, 1024]], 'temperature/name:cool': [[1, 1000, 40]]}};
const context = vm.createContext({AbortController, console, performance: {now: () => now},
  document: {visibilityState: 'visible', getElementById: el, querySelectorAll: () => [],
    addEventListener: (_, fn) => listeners.push(fn)},
  setInterval: fn => intervals.push(fn), setTimeout: (fn, ms) => { timers.set(++nextTimer, {fn, ms}); return nextTimer; },
  clearTimeout: id => timers.delete(id), fetch: async url => {
    requests.push(url);
    if (failure && url === 'api/stats') return {ok: false, status: 503};
    return {ok: true, status: 200, json: async () => url === 'api/stats' ? stats : url.startsWith('api/history') ? history : {groups: {}}};
  }});
const run = text => vm.runInContext(text, context);
const flush = async () => { for (let n = 0; n < 6; n++) await new Promise(setImmediate); };
const count = prefix => requests.filter(url => url.startsWith(prefix)).length;
const switchTo = async tab => { el('tab-' + tab).handlers.click(); await flush(); };
(async () => {
  run(code); await flush();
  assert.equal(count('api/stats'), 1);
  assert.equal(count('api/history'), 0, 'overview does not request graphs');
  assert.equal(count('api/observations'), 0);
  assert(el('overview').innerHTML.includes('30.0%'));
  assert(el('overview').innerHTML.includes('Mean of 2 measured cores'));
  assert(el('overview').innerHTML.includes('60.0 °C') && el('overview').innerHTML.includes('&#60;b&#62;hot'));
  assert(el('overview').innerHTML.includes('eth0') && !el('overview').innerHTML.includes('999999'));
  assert.equal(el('cpu').innerHTML, '', 'inactive resource view is not rendered');
  const overview = el('overview').innerHTML;
  await switchTo('resources');
  assert.equal(el('tab-resources').attrs['aria-selected'], 'true');
  assert.equal(el('panel-overview').hidden, true);
  assert.equal(el('panel-resources').hidden, false);
  assert(el('cpu').innerHTML.includes('CPU0'));
  assert.equal(count('api/history'), 1);
  assert(!el('hist').innerHTML.includes('eth0'));
  el('history-series').value = 'memory/used_bytes'; el('history-series').handlers.change();
  assert(el('hist').innerHTML.includes('RAM used') && !el('hist').innerHTML.includes('CPU0'));
  const graph = el('hist').innerHTML;
  stats.cpu[0].usage = 80; await run('tick()');
  assert.equal(el('overview').innerHTML, overview, 'inactive overview is not rewritten');
  now = 4000; intervals.forEach(fn => fn()); await flush();
  assert.equal(el('hist').innerHTML, graph, 'one-second timer never rebuilds graphs');
  await switchTo('network');
  assert.equal(count('api/observations'), 1);
  assert.equal(count('api/history'), 1, 'tab switch shares the history cache and deadline');
  assert(el('hist').innerHTML.includes('eth0') && !el('hist').innerHTML.includes('CPU0'));
  for (let n = 0; n < 20; n++) { await switchTo('storage'); await switchTo('network'); }
  assert.equal(count('api/observations'), 1);
  assert.equal(count('api/history'), 1);
  assert.equal(intervals.length, 1);
  assert.equal([...timers.values()].filter(t => t.ms === 1000).length, 1);
  const beforeKeys = requests.length;
  el('tab-network').handlers.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(focused, 'tab-storage');
  assert.equal(el('tab-network').attrs['aria-selected'], 'true', 'arrows move focus without fetching');
  assert.equal(requests.length, beforeKeys);
  failure = true; await run('tick()');
  await switchTo('overview');
  assert(el('overview').innerHTML.includes('60.0%'), 'last good snapshot is available in another view');
  assert(el('age').textContent.includes('not current'));
  const beforeHidden = requests.length;
  context.document.visibilityState = 'hidden'; listeners.forEach(fn => fn()); await flush();
  assert.equal(timers.size, 0, 'no pending request or refresh timer while hidden');
  now += 60000; intervals.forEach(fn => fn()); await run('tick()');
  assert.equal(requests.length, beforeHidden);
  failure = false;
  context.document.visibilityState = 'visible'; listeners.forEach(fn => fn()); await flush();
  assert.equal(count('api/stats'), 4, 'return requests one fresh stats snapshot');
  assert.equal(el('err').textContent, '');
  assert.equal(count('api/history'), 1, 'return to overview still does not request history');
  console.log('views, summaries, keyboard, shared polling, cached errors and hidden-page suspension: passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
