// Optional endpoint concurrency and tab-return tests with real AbortController and fake time.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = {}, requests = [], timers = new Map(), intervals = [], listeners = [];
let now = 0, next = 0;
const context = vm.createContext({
  AbortController, console, performance: {now: () => now},
  document: {visibilityState: 'visible', getElementById: id => elements[id] ||= {innerHTML: '', textContent: ''},
    querySelectorAll: () => [], addEventListener: (_, fn) => listeners.push(fn)},
  setTimeout: (fn, ms) => { timers.set(++next, {fn, ms}); return next; },
  clearTimeout: id => timers.delete(id), setInterval: fn => intervals.push(fn),
  fetch: (url, options) => new Promise((resolve, reject) => {
    const request = {url, options, resolve, reject}; requests.push(request);
    options?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'})));
  }),
});
const flush = async () => { for (let n = 0; n < 6; n++) await new Promise(setImmediate); };
const count = path => requests.filter(r => r.url.startsWith(path)).length;
(async () => {
  vm.runInContext(code, context);
  await flush();
  now = 11000; intervals.forEach(fn => fn()); await flush();
  assert.equal(count('api/observations'), 1, 'a hanging observation request must not overlap another');
  assert.equal(count('api/history'), 1, 'a hanging history request must not overlap another');
  for (const [id, t] of [...timers]) if (t.ms === 5000) { timers.delete(id); t.fn(); }
  await flush();
  assert(requests.every(r => r.options.signal.aborted), 'all endpoints have a deadline');
  now = 22000; intervals.forEach(fn => fn()); await flush();
  assert.equal(count('api/observations'), 2);
  assert.equal(count('api/history'), 2);
  context.document.visibilityState = 'hidden'; listeners.forEach(fn => fn());
  now += 600000;
  context.document.visibilityState = 'visible'; listeners.forEach(fn => fn()); await flush();
  intervals.forEach(fn => fn()); await flush();
  assert.equal(count('api/observations'), 3, 'tab return refreshes observations');
  assert.equal(count('api/history'), 3, 'tab return refreshes history');
  console.log('optional endpoint concurrency, deadline and tab return: passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
