// Runs the <script> of frontends/web/index.html with a stub DOM, fake timers and scripted fetch results,
// one tick per step, and prints one JSON line per step. Used by tests/test_web.py.
//   node tests/web_harness.js frontends/web/index.html
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

const els = {};
const el = id => (els[id] ||= {innerHTML: '', textContent: '', hidden: false, lastElementChild: null});
global.document = {getElementById: el, querySelectorAll: () => []};

const timers = [];  // fake setTimeout: the test fires them by delay
global.setTimeout = (fn, ms) => timers.push({fn, ms});
global.clearTimeout = id => { if (timers[id - 1]) timers[id - 1].fn = null; };
const fire = ms => { const t = timers.find(t => t.fn && t.ms === ms); if (t) { const fn = t.fn; t.fn = null; fn(); } };
let now = 0;
Date.now = () => now;

const SNAP = {platform: 'Linux', model: 'Test', uptime: 60, power_mode: null, system: {os: 'Test OS'},
  cpu: [{id: 0, usage: 1, freq: null}], gpu: null, memory: {total: 8, used: 2, swap_total: 0, swap_used: 0},
  disk: {total: 10, used: 5}, temperature: {}, power: {}, fans: []};
const reply = (status, body) => ({ok: status >= 200 && status < 300, status,
  statusText: status === 503 ? 'Service Unavailable' : 'OK', json: () => Promise.resolve(body)});
const plan = [
  ['ok', () => Promise.resolve(reply(200, SNAP))],
  ['503', () => Promise.resolve(reply(503, {error: 'no current data'}))],
  ['hang', signal => new Promise((_, reject) => signal && signal.addEventListener('abort',
    () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'}))))],
  ['down', () => Promise.reject(new TypeError('Failed to fetch'))],
  ['garbage', () => Promise.resolve({ok: true, status: 200, statusText: 'OK',
    json: () => Promise.reject(new SyntaxError("Unexpected token '<'"))})],
  ['recovered', () => Promise.resolve(reply(200, SNAP))],
];
let step = 0;
global.fetch = (url, opts) => plan[step][1]((opts || {}).signal);
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  eval(code);  // the page script ends with tick(): that is step 0
  for (step = 0; step < plan.length; step++) {
    if (step > 0) { now += 1000; fire(1000); }  // the 1 s refresh timer starts the next tick
    await settle(); await settle();
    if (plan[step][0] === 'hang') { now += 5000; fire(5000); await settle(); await settle(); }  // request timeout
    console.log(JSON.stringify({
      step: plan[step][0], err: el('err').textContent, shows_data: el('cpu').innerHTML.includes('CPU0'),
      refresh_scheduled: timers.filter(t => t.fn && t.ms === 1000).length,
    }));
  }
})();
