// Runs the <script> of frontends/web/index.html with a stub DOM, fake clocks and timers and scripted fetch
// results, and prints one JSON line per step. Used by tests/test_web.py.
//   node tests/web_harness.js frontends/web/index.html
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

const els = {};
const el = id => (els[id] ||= {innerHTML: '', textContent: '', hidden: false, lastElementChild: null});
const listeners = [];
global.document = {getElementById: el, querySelectorAll: () => [], visibilityState: 'visible',
  addEventListener: (type, fn) => type === 'visibilitychange' && listeners.push(fn)};
const tabReturns = () => { document.visibilityState = 'visible'; listeners.forEach(fn => fn()); };

const timers = [];  // fake setTimeout: the test fires them by delay
global.setTimeout = (fn, ms) => timers.push({fn, ms});
global.clearTimeout = id => { if (timers[id - 1]) timers[id - 1].fn = null; };
const fire = ms => { const t = timers.find(t => t.fn && t.ms === ms); if (t) { const fn = t.fn; t.fn = null; fn(); } };
const intervals = [];  // fake setInterval: the age display timer
global.setInterval = (fn, ms) => intervals.push({fn, ms});
const tickAge = () => intervals.forEach(t => t.fn());
let now = 0;  // ms, for both browser clocks
Date.now = () => now;
Object.defineProperty(globalThis, 'performance', {value: {now: () => now}, configurable: true});

const SNAP = {platform: 'Linux', model: 'Test', uptime: 60, power_mode: null, system: {os: 'Test OS'},
  cpu: [{id: 0, usage: 1, freq: null}], gpu: null, memory: {total: 8, used: 2, swap_total: 0, swap_used: 0},
  disk: {total: 10, used: 5}, temperature: {}, power: {}, fans: []};
const meta = (id, sequence, data_age_ms) => ({...SNAP, schema_version: 1, collectors: {core: {state: 'ok', reason: null}},
  sample: {instance_id: id, sequence, data_age_ms, age_ms: data_age_ms - 250, duration_ms: 250}});
const reply = (status, body) => ({ok: status >= 200 && status < 300, status,
  statusText: status === 503 ? 'Service Unavailable' : 'OK', json: () => Promise.resolve(body)});
const ok = body => () => Promise.resolve(reply(200, body));
const hang = signal => new Promise((_, reject) => signal && signal.addEventListener('abort',
  () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'}))));
let release;  // answers a held request when the test says so
const held = body => () => new Promise(resolve => { release = () => resolve(reply(200, body)); });

const answers = [];  // what the next requests get, in order
let fetches = 0;
global.fetch = (url, opts) => { fetches++; return answers.shift()((opts || {}).signal); };
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
const report = step => console.log(JSON.stringify({
  step, err: el('err').textContent, age: el('age').textContent, shows_data: el('cpu').innerHTML.includes('CPU0'),
  refresh_scheduled: timers.filter(t => t.fn && t.ms === 1000).length, age_timers: intervals.length, fetches,
}));
const next = async (answer, step) => { answers.push(answer); now += 1000; fire(1000); await settle(); if (step) report(step); };

(async () => {
  // an older server without sample metadata, through every kind of failure
  answers.push(ok(SNAP));
  eval(code);  // the page script ends with tick()
  await settle(); report('ok');
  await next(() => Promise.resolve(reply(503, {error: 'no current data'})), '503');
  await next(hang);
  now += 5000; fire(5000); await settle(); report('hang');  // request timeout
  await next(() => Promise.reject(new TypeError('Failed to fetch')), 'down');
  await next(() => Promise.resolve({ok: true, status: 200, statusText: 'OK',
    json: () => Promise.reject(new SyntaxError("Unexpected token '<'"))}), 'garbage');
  await next(ok(SNAP), 'recovered');

  // a server with sample metadata: the age is the sample's, not the time since the last answer
  await next(ok(meta('a', 5, 2000)), 'sample');
  await next(ok(meta('a', 5, 3000)), 'same_sample');  // polled again, same sample: no reset to 0
  await next(() => Promise.resolve(reply(503, {error: 'no current data', sample: {sequence: 5}})), 'sample_503');
  await next(hang);
  now += 2000; tickAge(); report('sample_hang_waiting');  // the age moves while the request hangs
  now += 3000; fire(5000); await settle(); report('sample_hang');
  await next(ok({...SNAP, schema_version: 1, sample: {instance_id: 'a', sequence: 'x', data_age_ms: null}}), 'bad_metadata');
  await next(ok(meta('b', 1, 100)), 'new_instance');  // restarted server: new instance, sequence 1
  await next(ok(meta('b', 2, 1400)), 'new_sequence');

  // back to the tab: no answer is trusted until a new one arrives, and never two requests at once
  now += 600000;  // browser asleep for 10 min, the refresh timer did not run
  answers.push(held(meta('b', 600, 300)));
  tabReturns(); report('tab_return_checking');
  release(); await settle(); report('tab_return_verified');
  await next(held(meta('b', 601, 300)));
  tabReturns(); report('tab_return_while_requesting');  // the running request is the check
  release(); await settle(); report('tab_return_while_requesting_done');
})();
